from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from dataclasses import replace

from .ai_advisor import AIAdvisor
from .broker import PaperBroker
from .config import AppConfig
from .database import Database
from .domain import Candle, Signal
from .exchange import BinanceClient
from .indicators import atr
from .strategy import SwingStrategy
from .spot_preflight import market_quantity_preflight


class TradingEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.bot.database_path)
        self.exchange = BinanceClient()
        self.strategy = SwingStrategy(config.strategy, config.risk)
        self.broker = PaperBroker(self.db, config.paper, config.risk)
        self.ai = AIAdvisor(config.ai)
        self._errors = int(self.db.setting("consecutive_errors", "0"))
        self._candle_cache = {}

    def killed(self) -> bool:
        return self.config.bot.kill_switch_path.exists()

    def cycle(self) -> dict:
        try:
            # Protect holdings before universe/regime downloads can fail.
            held_symbols = [position.symbol for position in self.db.positions()]
            if held_symbols:
                protective_prices = self.exchange.latest_prices(set(held_symbols))
                self._require_spot_prices(protective_prices, held_symbols)
                self._manage_positions({}, protective_prices)
            symbols = self.exchange.top_usdt_symbols(self.config.bot.universe_size)
            held_symbols = [position.symbol for position in self.db.positions()]
            monitored_symbols = list(dict.fromkeys([*symbols, *held_symbols, "BTCUSDT"]))
            candle_map = self._fetch_candles(monitored_symbols)
            if "BTCUSDT" not in candle_map:
                raise RuntimeError("BTC regime data unavailable")
            btc_bullish = self.strategy.btc_regime(candle_map["BTCUSDT"])

            try:
                prices = self.exchange.latest_prices(set(monitored_symbols))
                self._require_spot_prices(prices, [*held_symbols, "BTCUSDT"])
            except Exception as exc:
                raise RuntimeError("Fresh prices unavailable; entries blocked") from exc
            self.db.record_market_snapshot(prices)
            self._manage_positions(candle_map, prices)
            positions = self.db.positions()
            equity, cash, exposure = self.broker.equity(prices)
            self._prune_diagnostics_if_due()
            if self.killed():
                self.db.record_equity(equity, cash, exposure, prices["BTCUSDT"])
                self.db.event("WARN", "Kill switch active: protections monitored, new entries blocked")
                self._errors = 0
                self.db.set_setting("consecutive_errors", "0")
                return {"status": "killed", "equity": equity, "cash": cash, "exposure": exposure}
            if self._risk_halt(equity):
                self.db.record_equity(equity, cash, exposure, prices["BTCUSDT"])
                return {"status": "risk_halt", "equity": equity}

            held = {position.symbol for position in positions}
            candidates: list[Signal] = []
            for symbol, candles in candle_map.items():
                if symbol in held:
                    continue
                signal = self.strategy.evaluate(symbol, candles, btc_bullish)
                if signal.action == "BUY" or signal.score >= self.config.strategy.minimum_score - 10:
                    self.db.record_signal(signal)
                if signal.action == "BUY":
                    spot = prices.get(symbol)
                    if (spot is not None and self._valid_spot(spot) and signal.stop_price
                            and signal.take_profit and signal.stop_price < spot < signal.take_profit):
                        candidates.append(replace(signal, price=spot))
            candidates.sort(key=lambda signal: signal.score, reverse=True)

            reviews = 0
            opened: list[str] = []
            for signal in candidates:
                positions = self.db.positions()
                equity, cash, exposure = self.broker.equity(prices)
                if len(positions) >= self.config.risk.max_positions:
                    break
                if equity <= 0 or exposure / equity >= self.config.risk.max_total_exposure_pct:
                    break
                if reviews >= self.config.ai.max_reviews_per_cycle:
                    break
                if self.killed():
                    break
                if not self.db.claim_entry(signal.symbol, candle_map[signal.symbol][-1].close_time):
                    continue
                if not self._claim_ai_budget():
                    break
                context = {
                    "equity_usdt": round(equity, 4),
                    "cash_usdt": round(cash, 4),
                    "exposure_pct": round(exposure / equity if equity else 0.0, 6),
                    "open_positions": float(len(positions)),
                }
                review = self.ai.review(signal, btc_bullish, context)
                reviews += 1
                self.db.record_ai_review(signal.symbol, review)
                if review.verdict == "REJECT" or review.risk_multiplier <= 0:
                    continue
                quantity = self._position_size(signal, equity, cash, exposure, review.risk_multiplier)
                if quantity <= 0:
                    continue
                if self.killed():
                    break
                status, reasons = market_quantity_preflight(
                    self.exchange.cached_symbol_info(signal.symbol), quantity, signal.price)
                self.db.record_order_preflight(signal.symbol, status, reasons)
                self.broker.buy(signal, quantity, f"score={signal.score}; AI={review.verdict}: {review.reason}")
                opened.append(signal.symbol)

            equity, cash, exposure = self.broker.equity(prices)
            self.db.record_equity(equity, cash, exposure, prices["BTCUSDT"])
            self.db.event("INFO", f"Cycle complete: {len(symbols)} symbols, {len(candidates)} buys, opened {len(opened)}")
            self._errors = 0
            self.db.set_setting("consecutive_errors", "0")
            return {
                "status": "ok",
                "symbols": len(symbols),
                "buy_candidates": len(candidates),
                "opened": opened,
                "equity": equity,
                "cash": cash,
                "exposure": exposure,
                "btc_bullish": btc_bullish,
            }
        except Exception as exc:
            self._errors += 1
            self.db.set_setting("consecutive_errors", str(self._errors))
            self.db.event("ERROR", f"Cycle failed: {type(exc).__name__}")
            if self._errors >= self.config.risk.max_consecutive_errors:
                self.config.bot.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
                self.config.bot.kill_switch_path.write_text("automatic halt after consecutive errors\n", encoding="utf-8")
                self.db.event("CRITICAL", "Kill switch activated after consecutive errors")
            raise

    def _prune_diagnostics_if_due(self) -> None:
        """Bound diagnostic rows even during a long PAPER pause or risk halt."""
        now = datetime.now(UTC)
        today = now.date().isoformat()
        if self.db.setting("last_prune") != today:
            self.db.prune_diagnostics((now - timedelta(days=90)).isoformat())
            self.db.set_setting("last_prune", today)

    def _fetch_candles(self, symbols: list[str]) -> dict[str, list[Candle]]:
        result: dict[str, list[Candle]] = {}
        with ThreadPoolExecutor(max_workers=self.config.bot.max_parallel_requests) as pool:
            futures = {
                pool.submit(self._cached_candles, symbol): symbol for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    candles = future.result()
                    if len(candles) >= self.config.strategy.ema_slow + 5:
                        result[symbol] = candles
                except Exception as exc:
                    self.db.event("WARN", f"{symbol} data skipped: {type(exc).__name__}")
        return result

    @staticmethod
    def _valid_spot(price: object) -> bool:
        return type(price) in (int, float) and math.isfinite(price) and price > 0

    @classmethod
    def _require_spot_prices(cls, prices: dict[str, float], held_symbols: list[str]) -> None:
        if any(not cls._valid_spot(price) for price in prices.values()):
            raise RuntimeError("Invalid spot quote")
        if any(symbol not in prices for symbol in held_symbols):
            raise RuntimeError("Held position missing spot quote")

    def _cached_candles(self, symbol):
        now = int(time.time() * 1000)
        cached = self._candle_cache.get(symbol)
        if cached and now < cached[0]:
            return cached[1]
        candles = self.exchange.candles(symbol, self.config.bot.timeframe, 250)
        durations = {"1m":60000,"5m":300000,"15m":900000,"30m":1800000,"1h":3600000,
                     "2h":7200000,"4h":14400000,"6h":21600000,"8h":28800000,"12h":43200000,"1d":86400000}
        duration = durations[self.config.bot.timeframe]
        if not candles or now-candles[-1].close_time > duration+120000:
            raise RuntimeError("Stale candle history")
        if any(b.open_time-a.open_time != duration for a,b in zip(candles,candles[1:])):
            raise RuntimeError("Gapped candle history")
        if len(self._candle_cache) > self.config.bot.universe_size + self.config.risk.max_positions + 5:
            self._candle_cache.clear()
        self._candle_cache[symbol] = (candles[-1].close_time + duration + 2000, candles)
        return candles

    def _claim_ai_budget(self):
        today = datetime.now(UTC).date().isoformat()
        with self.db.transaction():
            date, count = (self.db.setting("ai_budget", today + ":0")).rsplit(":", 1)
            used = int(count) if date == today else 0
            if used >= self.config.ai.max_reviews_per_day:
                return False
            self.db.set_setting("ai_budget", f"{today}:{used+1}")
            return True

    def _manage_positions(self, candle_map: dict[str, list[Candle]], prices: dict[str, float]) -> None:
        for position in self.db.positions():
            # Closed candles are signals, never a substitute for an executable
            # quote when deciding whether to close a held position.
            price = prices.get(position.symbol)
            if not self._valid_spot(price):
                raise RuntimeError("Held position missing valid spot quote")
            candles = candle_map.get(position.symbol)
            if not candles:
                self.broker.protect(position, price, position.atr)
                continue
            current_atr = atr(
                [candle.high for candle in candles],
                [candle.low for candle in candles],
                [candle.close for candle in candles],
                self.config.strategy.atr_period,
            )
            updated, exit_reason = self.broker.protect(position, price, current_atr)
            if updated is None:
                self.db.event("INFO", f"{position.symbol} closed: {exit_reason}")
                continue
            should_exit, reason = self.strategy.should_exit(candles)
            if should_exit:
                self.broker.sell(updated, price, reason)

    def _position_size(self, signal: Signal, equity: float, cash: float, exposure: float, multiplier: float) -> float:
        if signal.stop_price is None or signal.price <= signal.stop_price:
            return 0.0
        if not all(math.isfinite(v) for v in (equity, cash, exposure, multiplier, signal.price, signal.stop_price)) or not 0 < multiplier <= 1:
            return 0.0
        fill = signal.price * (1 + self.config.paper.slippage_rate)
        stop_fill = signal.stop_price * (1 - self.config.paper.slippage_rate)
        loss_per_unit = fill - stop_fill + self.config.paper.fee_rate * (fill + stop_fill)
        risk_budget = equity * self.config.risk.risk_per_trade_pct * multiplier
        by_risk = risk_budget / loss_per_unit
        by_position_cap = (equity * self.config.risk.max_position_pct) / fill
        remaining_exposure = max(0.0, equity * self.config.risk.max_total_exposure_pct - exposure)
        by_exposure = remaining_exposure / fill
        by_cash = cash / (fill * (1 + self.config.paper.fee_rate))
        quantity = min(by_risk, by_position_cap, by_exposure, by_cash)
        return math.floor(quantity * 1_000_000) / 1_000_000

    def _risk_halt(self, equity: float) -> bool:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        day_base = self.db.equity_at_or_before(day_start.isoformat()) or self.db.first_equity_since(day_start.isoformat()) or self.config.paper.initial_cash_usdt
        week_base = self.db.equity_at_or_before(week_start.isoformat()) or self.db.first_equity_since(week_start.isoformat()) or self.config.paper.initial_cash_usdt
        if self.db.setting("daily_halt") == day_start.isoformat() or self.db.setting("weekly_halt") == week_start.isoformat():
            return True
        daily_return = (equity / day_base - 1.0) if day_base else 0.0
        weekly_return = (equity / week_base - 1.0) if week_base else 0.0
        if daily_return <= -self.config.risk.daily_loss_limit_pct:
            self.db.set_setting("daily_halt", day_start.isoformat())
            self.db.event("CRITICAL", f"Daily loss limit reached: {daily_return:.2%}")
            return True
        if weekly_return <= -self.config.risk.weekly_loss_limit_pct:
            self.db.set_setting("weekly_halt", week_start.isoformat())
            self.db.event("CRITICAL", f"Weekly loss limit reached: {weekly_return:.2%}")
            return True
        return False

    def run_forever(self, should_stop=lambda: False) -> None:
        self.db.event("INFO", "Trading engine started in PAPER mode")
        while not should_stop():
            started = time.monotonic()
            try:
                self.cycle()
            except KeyboardInterrupt:
                raise
            except Exception:
                pass
            deadline = started + self.config.bot.cycle_seconds
            while time.monotonic() < deadline:
                protection_deadline = min(deadline, time.monotonic()+self.config.bot.protection_seconds)
                while time.monotonic() < protection_deadline:
                    if should_stop():
                        return
                    time.sleep(max(0.01, min(1.0, protection_deadline-time.monotonic())))
                if should_stop():
                    return
                try:
                    self.protection_tick()
                except Exception as exc:
                    self.db.event("WARN", f"Protection price unavailable: {type(exc).__name__}")

    def protection_tick(self):
        symbols = {position.symbol for position in self.db.positions()}
        if symbols:
            prices = self.exchange.latest_prices(symbols)
            self._require_spot_prices(prices, list(symbols))
            self._manage_positions({}, prices)
            self.db.record_market_snapshot(prices)
