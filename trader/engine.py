from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from dataclasses import replace

from .ai_advisor import AIAdvisor
from .broker import PaperBroker
from .testnet_broker import BinanceTestnetBroker
from .testnet_transport import TestnetExecutionError
from .config import AppConfig
from .database import Database
from .domain import Candle, Signal
from .exchange import BinanceClient, ExchangeError
from .indicators import atr
from .strategy import SwingStrategy
from .spot_preflight import market_quantity_preflight
from .testnet import plan_order, TestnetPlanError
from .risk_control import profile_multiplier
from .futures_forward import FuturesForwardEngine
from .futures_testnet_transport import public_request as futures_public_request


class TradingEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db = Database(config.bot.database_path)
        self.exchange = BinanceClient()
        self.strategy = SwingStrategy(config.strategy, config.risk)
        self.broker = (BinanceTestnetBroker(self.db, config.paper, config.risk)
                       if config.bot.mode == "testnet"
                       else PaperBroker(self.db, config.paper, config.risk))
        self.ai = AIAdvisor(config.ai)
        self.futures_forward = FuturesForwardEngine(config, self.exchange) if config.bot.mode == "testnet" else None
        self._errors = int(self.db.setting("consecutive_errors", "0"))
        self._candle_cache = {}
        self._futures_candle_cache = {}

    def killed(self) -> bool:
        return self.config.bot.kill_switch_path.exists()

    def cycle(self) -> dict:
        try:
            if self.config.bot.mode == "testnet" and not self.broker.reconcile_pending():
                raise RuntimeError("Spot Testnet order awaiting reconciliation")
            # Protect holdings before universe/regime downloads can fail.
            held_symbols = [position.symbol for position in self.db.positions()]
            if held_symbols:
                protective_prices = self._position_execution_prices(held_symbols)
                self._require_spot_prices(protective_prices, held_symbols)
                self._manage_positions({}, protective_prices)
            symbols = self.exchange.top_usdt_symbols(self.config.bot.universe_size)
            held_symbols = [position.symbol for position in self.db.positions()]
            futures_symbols = list(self.config.futures_testnet.forward_symbols) if self.futures_forward is not None else []
            monitored_symbols = list(dict.fromkeys([*symbols, *held_symbols, "BTCUSDT", *futures_symbols]))
            candle_map = self._fetch_candles(monitored_symbols)
            if "BTCUSDT" not in candle_map:
                raise RuntimeError("BTC regime data unavailable")
            btc_bullish = self.strategy.btc_regime(candle_map["BTCUSDT"])
            if self.futures_forward is not None:
                self._run_futures_forward_cycle(candle_map)

            try:
                prices = self.exchange.latest_prices(set(monitored_symbols))
                self._require_spot_prices(prices, [*held_symbols, "BTCUSDT"])
            except Exception as exc:
                raise RuntimeError("Fresh prices unavailable; entries blocked") from exc
            held_symbols = [position.symbol for position in self.db.positions()]
            execution_prices = self._position_execution_prices(held_symbols, prices)
            self.db.record_market_snapshot(execution_prices)
            self._manage_positions(candle_map, execution_prices)
            positions = self.db.positions()
            equity, cash, exposure = self.broker.equity(execution_prices)
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
                held_now = [position.symbol for position in positions]
                valuation_prices = self._position_execution_prices(held_now, prices)
                equity, cash, exposure = self.broker.equity(valuation_prices)
                if len(positions) >= self.config.risk.max_positions:
                    break
                if equity <= 0 or exposure / equity >= self.config.risk.max_total_exposure_pct:
                    break
                if reviews >= self.config.ai.max_reviews_per_cycle:
                    break
                if self.killed():
                    break
                if not self._ai_budget_available():
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
                if self.config.bot.mode == "testnet":
                    try:
                        info = self.exchange.testnet_symbol_info(signal.symbol)
                        plan = plan_order(signal.symbol, "BUY", signal.price, info, quantity=quantity)
                    except (TestnetPlanError, ExchangeError) as exc:
                        # Public symbol eligibility/filter reads do not mutate exposure.
                        self.db.record_order_preflight(signal.symbol, "blocked", ["TESTNET_RULES_UNAVAILABLE"])
                        self.db.event("WARN", f"{signal.symbol} entry filters unavailable: {type(exc).__name__}")
                        continue
                    quantity = float(plan.quantity)
                    status, reasons = market_quantity_preflight(info, quantity, signal.price)
                    if plan.status != "READY_FOR_MANUAL_REVIEW":
                        status, reasons = "incompatible", list(plan.reasons)
                else:
                    status, reasons = market_quantity_preflight(
                        self.exchange.cached_symbol_info(signal.symbol), quantity, signal.price)
                self.db.record_order_preflight(signal.symbol, status, reasons)
                if status == "incompatible":
                    self.db.event("INFO", f"{signal.symbol} entry skipped [EXCHANGE_FILTER_PREFLIGHT]")
                    continue
                if not self._buy_or_skip_guardrail(
                    signal, quantity, f"score={signal.score}; AI={review.verdict}: {review.reason}"
                ):
                    continue
                opened.append(signal.symbol)

            held_final = [position.symbol for position in self.db.positions()]
            final_prices = self._position_execution_prices(held_final, prices)
            equity, cash, exposure = self.broker.equity(final_prices)
            self.db.record_equity(equity, cash, exposure, prices["BTCUSDT"])
            self.db.event("INFO", f"Cycle complete: {len(symbols)} symbols, {len(candidates)} buys, opened {len(opened)}")
            if self._errors:
                self.db.set_setting("spot_last_recovery", json.dumps({
                    "recovered_errors": self._errors,
                    "at": datetime.now(UTC).isoformat(),
                }, separators=(",", ":")))
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
            failure = self._spot_failure_projection(exc)
            failure["at"] = datetime.now(UTC).isoformat()
            failure["consecutive_errors"] = self._errors
            self.db.set_setting("spot_last_error", json.dumps(failure, separators=(",", ":")))
            self.db.event("ERROR", f"Cycle failed [{failure['code']}]: {failure['label']}")
            if self._errors >= self.config.risk.max_consecutive_errors:
                self.config.bot.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
                self.config.bot.kill_switch_path.write_text("automatic halt after consecutive errors\n", encoding="utf-8")
                self.db.event("CRITICAL", "Kill switch activated after consecutive errors")
            raise

    @staticmethod
    def _entry_rejection_code(exc: Exception) -> str | None:
        """Classify only expected pre-write entry guardrails; unknown failures still abort the cycle."""
        if isinstance(exc, ValueError):
            return {
                "position count limit": "POSITION_COUNT_LIMIT",
                "position exposure limit": "POSITION_SIZE_LIMIT",
                "total exposure limit": "TOTAL_EXPOSURE_LIMIT",
                "per-trade risk limit": "PER_TRADE_RISK_LIMIT",
                "insufficient Testnet allocation": "LOCAL_ALLOCATION_LIMIT",
                "insufficient paper cash": "LOCAL_CASH_LIMIT",
            }.get(str(exc))
        if isinstance(exc, TestnetExecutionError):
            return {
                "Spot Testnet price moved outside signal protection range": "PRICE_MOVED_OUTSIDE_SIGNAL_RANGE",
                "Testnet filters reject engine quantity": "EXCHANGE_FILTER_REJECTED",
                "Insufficient Spot Testnet USDT": "TESTNET_BALANCE_LIMIT",
            }.get(str(exc))
        return None

    def _buy_or_skip_guardrail(self, signal: Signal, quantity: float, reason: str) -> bool:
        try:
            self.broker.buy(signal, quantity, reason)
            return True
        except Exception as exc:
            code = self._entry_rejection_code(exc)
            if code is None:
                raise
            self.db.record_order_preflight(signal.symbol, "blocked", [code])
            self.db.event("INFO", f"{signal.symbol} entry skipped [{code}]")
            return False

    @staticmethod
    def _spot_failure_projection(exc: Exception) -> dict[str, str]:
        """Return a bounded, non-secret diagnostic suitable for the portal and persistent event log."""
        known = {
            "Spot Testnet order awaiting reconciliation": ("ORDER_RECONCILIATION_PENDING", "orden Spot pendiente de conciliación"),
            "BTC regime data unavailable": ("BTC_REGIME_UNAVAILABLE", "datos del régimen BTC no disponibles"),
            "Fresh prices unavailable; entries blocked": ("FRESH_PRICES_UNAVAILABLE", "cotizaciones recientes no disponibles"),
            "Invalid spot quote": ("INVALID_SPOT_QUOTE", "cotización Spot inválida"),
            "Held position missing spot quote": ("HELD_QUOTE_MISSING", "falta cotización de una posición abierta"),
            "Held position missing valid spot quote": ("HELD_QUOTE_INVALID", "cotización inválida de una posición abierta"),
        }
        if str(exc) in known:
            code, label = known[str(exc)]
            return {"code": code, "label": label, "type": type(exc).__name__}
        if isinstance(exc, ValueError):
            return {"code": "UNEXPECTED_VALUE_ERROR", "label": "validación interna no clasificada", "type": "ValueError"}
        if isinstance(exc, TestnetExecutionError):
            return {"code": "TESTNET_EXECUTION_ERROR", "label": "fallo de ejecución o conciliación Spot Testnet", "type": type(exc).__name__}
        return {
            "code": "UNEXPECTED_" + type(exc).__name__.upper(),
            "label": "fallo operativo no clasificado",
            "type": type(exc).__name__,
        }

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

    def _position_execution_prices(self, symbols: list[str] | set[str] | tuple[str, ...],
                                   base: dict[str, float] | None = None) -> dict[str, float]:
        prices = dict(base or {})
        if self.config.bot.mode != "testnet":
            if not prices and symbols:
                prices = self.exchange.latest_prices(set(symbols))
            return prices
        for symbol in symbols:
            prices[symbol] = self.broker.execution_price(symbol)
        return prices

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

    def _ai_budget_available(self):
        today = datetime.now(UTC).date().isoformat()
        date, count = self.db.setting("ai_budget", today + ":0").rsplit(":", 1)
        return date != today or int(count) < self.config.ai.max_reviews_per_day

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
        risk_budget = equity * self.config.risk.risk_per_trade_pct * multiplier * profile_multiplier(self.db)
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
        self.db.event("INFO", f"Trading engine started in {self.config.bot.mode.upper()} mode")
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


    def _sync_futures_legacy_error_counter(self) -> None:
        cycle = int(self.futures_forward.ledger.setting("forward_cycle_consecutive_errors") or 0)
        protection = int(self.futures_forward.ledger.setting("forward_protection_consecutive_errors") or 0)
        self.futures_forward.ledger.set_setting("forward_consecutive_errors", max(cycle, protection))

    def _record_futures_incident(self, source: str, exc: Exception) -> dict:
        """Deduplicate one recurring root cause while retaining repetition count."""
        now = datetime.now(UTC).isoformat()
        message = (type(exc).__name__ + ": " + str(exc))[:200]
        fingerprint = source + "|" + message
        active = self.futures_forward.ledger.setting("forward_active_incident")
        new_incident = not (isinstance(active, dict) and active.get("fingerprint") == fingerprint)
        if not new_incident:
            incident = {**active, "repetitions": int(active.get("repetitions", 1)) + 1, "last_at": now}
        else:
            sequence = int(self.futures_forward.ledger.setting("forward_incident_sequence") or 0) + 1
            self.futures_forward.ledger.set_setting("forward_incident_sequence", sequence)
            incident = {
                "id": f"FUT-{sequence:04d}",
                "source": source,
                "fingerprint": fingerprint,
                "message": message,
                "repetitions": 1,
                "first_at": now,
                "last_at": now,
            }
        self.futures_forward.ledger.set_setting("forward_active_incident", incident)
        self.futures_forward.ledger.set_setting("forward_last_incident", incident)
        return {"message": message, "at": now, "incident_id": incident["id"], "new_incident": new_incident}

    def _emit_futures_warning(self, source: str, message: str, *, force: bool = False) -> None:
        key = "forward_last_warning_" + source
        prior = self.futures_forward.ledger.setting(key)
        now = datetime.now(UTC)
        emit = force
        if isinstance(prior, dict) and prior.get("message") == message:
            try:
                then = datetime.fromisoformat(str(prior.get("at","")).replace("Z","+00:00"))
                emit = emit or (now-then).total_seconds() >= 900
            except ValueError:
                emit = True
        else:
            emit = True
        if emit:
            self.db.event("WARN", message)
            self.futures_forward.ledger.set_setting(key, {"message":message,"at":now.isoformat()})

    def _resolve_futures_incident(self, source: str) -> None:
        active = self.futures_forward.ledger.setting("forward_active_incident")
        if isinstance(active, dict) and active.get("source") == source:
            resolved = {**active, "resolved_at": datetime.now(UTC).isoformat()}
            self.futures_forward.ledger.set_setting("forward_last_incident", resolved)
            self.futures_forward.ledger.set_setting("forward_active_incident", None)

    def _run_futures_forward_cycle(self, candle_map: dict[str, list[Candle]]) -> None:
        current_cycles = self.futures_forward.ledger.setting("forward_cycle_total") or 0
        self.futures_forward.ledger.set_setting("forward_cycle_total", int(current_cycles) + 1)
        try:
            # Spot data is not interchangeable with the USD-M contract traded.
            futures_map = {}
            for symbol in self.futures_forward.symbols:
                try:
                    futures_map[symbol] = self._futures_candles(symbol)
                except Exception as exc:
                    self._emit_futures_warning("data_" + symbol,
                        f"Futures Demo {symbol} contract data unavailable: {type(exc).__name__}")
            if not futures_map:
                raise RuntimeError("Futures contract candles unavailable")
            result = self.futures_forward.cycle(futures_map)
            self.futures_forward.ledger.set_setting("forward_cycle_consecutive_errors", 0)
            self._resolve_futures_incident("cycle")
            self._sync_futures_legacy_error_counter()
            events = [row for row in result.get("results", []) if row.get("status") in {"OPENED", "CLOSED"}]
            for row in events:
                self.db.event("INFO", f"Futures Demo {row.get('symbol')}: {row.get('status')}")
        except Exception as exc:
            current = self.futures_forward.ledger.setting("forward_cycle_consecutive_errors") or 0
            count = min(3, int(current) + 1)
            detail = self._record_futures_incident("cycle", exc)
            self.futures_forward.ledger.set_setting("forward_cycle_consecutive_errors", count)
            self.futures_forward.ledger.set_setting("forward_last_cycle_error", detail)
            self.futures_forward.ledger.set_setting("forward_last_error", detail)
            self._sync_futures_legacy_error_counter()
            attempts = self.futures_forward.ledger.setting("forward_failure_attempt_total") or 0
            self.futures_forward.ledger.set_setting("forward_failure_attempt_total", int(attempts) + 1)
            self._emit_futures_warning("cycle", "Futures Demo forward cycle failed: " + type(exc).__name__,
                                       force=bool(detail.get("new_incident")))
            if count >= 3:
                self.futures_forward._halt("three consecutive Futures forward errors", overwrite_last_error=False)

    def _futures_candles(self, symbol: str) -> list[Candle]:
        now = int(time.time() * 1000)
        interval = self.config.bot.timeframe
        duration = {"1m":60000,"5m":300000,"15m":900000,"30m":1800000,"1h":3600000,
                    "2h":7200000,"4h":14400000,"6h":21600000,"8h":28800000,"12h":43200000,"1d":86400000}[interval]
        cached = self._futures_candle_cache.get(symbol)
        if cached and now < cached[0]: return cached[1]
        payload = futures_public_request("GET", "/fapi/v1/klines",
            {"symbol":symbol,"interval":interval,"limit":250}, allow_fallback=False)
        candles = BinanceClient._parse_candles(payload)
        if not candles or now-candles[-1].close_time > duration+120000:
            raise RuntimeError("Stale Futures candle history")
        if any(b.open_time-a.open_time != duration for a,b in zip(candles,candles[1:])):
            raise RuntimeError("Gapped Futures candle history")
        self._futures_candle_cache[symbol] = (candles[-1].close_time+duration+2000,candles)
        return candles

    def _run_futures_forward_protection(self) -> None:
        if self.futures_forward is None or not self.config.futures_testnet.forward_enabled:
            return
        try:
            result = self.futures_forward.protection_tick()
            self.futures_forward.ledger.set_setting("forward_protection_consecutive_errors", 0)
            self._resolve_futures_incident("protection")
            self._sync_futures_legacy_error_counter()
            if result.get("closed"):
                self.db.event("INFO", "Futures Demo forward position closed by protection")
        except Exception as exc:
            current = self.futures_forward.ledger.setting("forward_protection_consecutive_errors") or 0
            count = min(3, int(current) + 1)
            detail = self._record_futures_incident("protection", exc)
            self.futures_forward.ledger.set_setting("forward_protection_consecutive_errors", count)
            self.futures_forward.ledger.set_setting("forward_last_protection_error", detail)
            self.futures_forward.ledger.set_setting("forward_last_error", detail)
            self._sync_futures_legacy_error_counter()
            attempts = self.futures_forward.ledger.setting("forward_failure_attempt_total") or 0
            self.futures_forward.ledger.set_setting("forward_failure_attempt_total", int(attempts) + 1)
            self._emit_futures_warning("protection", "Futures Demo protection failed: " + type(exc).__name__,
                                       force=bool(detail.get("new_incident")))
            if count >= 3:
                self.futures_forward._halt("three consecutive Futures protection errors", overwrite_last_error=False)

    def protection_tick(self):
        self._run_futures_forward_protection()
        if self.config.bot.mode == "testnet" and not self.broker.reconcile_pending():
            return
        symbols = {position.symbol for position in self.db.positions()}
        if symbols:
            prices = self._position_execution_prices(symbols)
            self._require_spot_prices(prices, list(symbols))
            self._manage_positions({}, prices)
            self.db.record_market_snapshot(prices)
