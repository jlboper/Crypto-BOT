"""Conservative BTCUSDT USDⓈ-M Futures Demo forward-test engine.

Runs beside Spot Testnet but keeps a separate ledger, position, kill switch and
order journal. Automatic leverage is fixed at 1x. LIVE is not implemented.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from .domain import Candle
from .futures_testnet import FuturesTestnetLab, FuturesTestnetExecutionError, _decimal
from .indicators import atr, ema_series, rsi, sma


class FuturesForwardEngine:
    def __init__(self, config, exchange):
        self.config = config
        self.settings = config.futures_testnet
        self.exchange = exchange
        self.lab = FuturesTestnetLab(self.settings)
        self.ledger = self.lab.ledger

    def killed(self) -> bool:
        return self.settings.kill_switch_path.exists()

    def _halt(self, reason: str) -> None:
        self.settings.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.kill_switch_path.write_text(str(reason)[:200] + "\n", encoding="utf-8")
        self.ledger.set_setting("forward_last_error", {
            "message": str(reason)[:200],
            "at": datetime.now(UTC).isoformat(),
        })

    def _signal(self, candles: list[Candle]) -> dict:
        s = self.config.strategy
        required = max(s.ema_slow + 5, s.breakout_period + 2, s.atr_period + 2, s.volume_period + 2)
        if len(candles) < required:
            raise ValueError("BTCUSDT Futures forward history unavailable")
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]
        price = closes[-1]
        fast_series = ema_series(closes, s.ema_fast)
        slow_series = ema_series(closes, s.ema_slow)
        fast = fast_series[-1]
        slow = slow_series[-1]
        current_rsi = rsi(closes, s.rsi_period)
        current_atr = atr(highs, lows, closes, s.atr_period)
        average_volume = sma(volumes[:-1], s.volume_period)
        volume_ratio = volumes[-1] / average_volume if average_volume > 0 else 0.0
        prior_high = max(highs[-s.breakout_period - 1 : -1])
        prior_low = min(lows[-s.breakout_period - 1 : -1])
        momentum = (price / closes[-6]) - 1.0

        long_score = 0
        short_score = 0
        if price > fast > slow:
            long_score += 25
        if price < fast < slow:
            short_score += 25
        if len(fast_series) >= 4 and fast_series[-1] > fast_series[-4]:
            long_score += 10
        if len(fast_series) >= 4 and fast_series[-1] < fast_series[-4]:
            short_score += 10
        if 52 <= current_rsi <= 72:
            long_score += 15
        elif 48 <= current_rsi < 52:
            long_score += 7
        if 28 <= current_rsi <= 48:
            short_score += 15
        elif 48 < current_rsi <= 52:
            short_score += 7
        if volume_ratio >= 1.2:
            long_score += 15
            short_score += 15
        elif volume_ratio >= 1.0:
            long_score += 8
            short_score += 8
        if price > prior_high:
            long_score += 20
        if price < prior_low:
            short_score += 20
        if momentum >= 0.01:
            long_score += 15
        if momentum <= -0.01:
            short_score += 15
        if current_atr / price > 0.12:
            long_score -= 15
            short_score -= 15

        long_score = max(0, min(100, long_score))
        short_score = max(0, min(100, short_score))
        score = max(long_score, short_score)
        direction = None
        if score >= self.settings.forward_min_score and abs(long_score - short_score) >= 10:
            direction = "LONG" if long_score > short_score else "SHORT"
        return {
            "direction": direction,
            "score": score,
            "long_score": long_score,
            "short_score": short_score,
            "price": price,
            "atr": current_atr,
            "rsi": current_rsi,
            "ema_fast": fast,
            "ema_slow": slow,
            "volume_ratio": volume_ratio,
        }

    def _actual_rows(self) -> list[dict]:
        return self.lab._position_rows(self.settings.forward_symbol)

    def _record_account(self) -> dict:
        account = self.lab._account()
        wallet = float(_decimal(account.get("totalWalletBalance", "0")))
        available = float(_decimal(account.get("availableBalance", "0")))
        rows = self._actual_rows()
        unrealized = sum(float(_decimal(row.get("unRealizedProfit", "0"))) for row in rows)
        self.ledger.record_forward_equity(wallet, available, unrealized)
        return {
            "wallet_balance": wallet,
            "available_balance": available,
            "unrealized_pnl": unrealized,
        }

    def _assert_consistent(self, local: dict | None, rows: list[dict]) -> None:
        if local is None and rows:
            raise FuturesTestnetExecutionError("Untracked Futures Demo position; forward test halted")
        if local is None:
            return
        if len(rows) != 1:
            raise FuturesTestnetExecutionError("Tracked Futures position missing or ambiguous")
        amount = _decimal(rows[0].get("positionAmt", "0"))
        expected_sign = 1 if local["direction"] == "LONG" else -1
        actual_sign = 1 if amount > 0 else -1
        if actual_sign != expected_sign or abs(float(abs(amount)) - float(local["quantity"])) > 1e-12:
            raise FuturesTestnetExecutionError("Futures forward position identity mismatch")
        if int(float(rows[0].get("leverage", 0) or 0)) != 1:
            raise FuturesTestnetExecutionError("Automatic Futures leverage changed from 1x")
        if str(rows[0].get("marginType", "")).lower() != "isolated":
            raise FuturesTestnetExecutionError("Automatic Futures margin is not isolated")

    def _close(self, local: dict, reason: str) -> dict:
        rows = self._actual_rows()
        self._assert_consistent(local, rows)
        amount = _decimal(rows[0]["positionAmt"])
        side = "SELL" if amount > 0 else "BUY"
        order = self.lab.forward_submit(
            symbol=local["symbol"], side=side, quantity=abs(amount), reduce_only=True
        )
        if self._actual_rows():
            raise FuturesTestnetExecutionError("Futures forward close left an open position")
        exit_price = self.lab._execution_price(order, local["symbol"])
        entry = _decimal(local["entry_price"])
        qty = _decimal(local["quantity"])
        pnl = ((exit_price - entry) * qty if local["direction"] == "LONG"
               else (entry - exit_price) * qty)
        return self.ledger.close_forward_position(
            exit_price=float(exit_price), gross_pnl=float(pnl), exit_reason=reason
        )

    def protection_tick(self) -> dict:
        if not self.settings.forward_enabled:
            return {"enabled": False}
        local = self.ledger.forward_position()
        pending = self.lab.reconcile_forward_pending()
        if pending and not pending.get("resolved"):
            return {"enabled": True, "status": "PENDING_RECONCILIATION"}
        rows = self._actual_rows()
        try:
            self._assert_consistent(local, rows)
        except Exception as exc:
            self._halt(str(exc))
            raise
        if not local:
            return {"enabled": True, "status": "FLAT"}
        mark = _decimal(rows[0].get("markPrice", rows[0].get("entryPrice", "0")))
        if mark <= 0:
            raise FuturesTestnetExecutionError("Futures mark price unavailable")
        if local["direction"] == "LONG":
            if mark <= _decimal(local["stop_price"]):
                return {"enabled": True, "closed": self._close(local, "STOP")}
            if mark >= _decimal(local["take_profit"]):
                return {"enabled": True, "closed": self._close(local, "TAKE_PROFIT")}
        else:
            if mark >= _decimal(local["stop_price"]):
                return {"enabled": True, "closed": self._close(local, "STOP")}
            if mark <= _decimal(local["take_profit"]):
                return {"enabled": True, "closed": self._close(local, "TAKE_PROFIT")}
        return {"enabled": True, "status": "OPEN", "mark_price": float(mark)}

    def cycle(self, candles: list[Candle]) -> dict:
        if not self.settings.forward_enabled:
            return {"enabled": False, "status": "OFF"}
        if self.killed():
            return {"enabled": True, "status": "KILLED"}
        pending = self.lab.reconcile_forward_pending()
        if pending and not pending.get("resolved"):
            return {"enabled": True, "status": "PENDING_RECONCILIATION"}

        account = self._record_account()
        local = self.ledger.forward_position()
        rows = self._actual_rows()
        try:
            self._assert_consistent(local, rows)
        except Exception as exc:
            self._halt(str(exc))
            raise

        signal = self._signal(candles)
        self.ledger.set_setting("forward_last_signal", {
            **signal,
            "at": datetime.now(UTC).isoformat(),
        })

        if local:
            if local["direction"] == "LONG" and signal["short_score"] >= self.settings.forward_min_score:
                closed = self._close(local, "OPPOSITE_SIGNAL")
                return {"enabled": True, "status": "CLOSED", "trade": closed, "signal": signal, **account}
            if local["direction"] == "SHORT" and signal["long_score"] >= self.settings.forward_min_score:
                closed = self._close(local, "OPPOSITE_SIGNAL")
                return {"enabled": True, "status": "CLOSED", "trade": closed, "signal": signal, **account}
            return {"enabled": True, "status": "OPEN", "position": local, "signal": signal, **account}

        if signal["direction"] is None:
            return {"enabled": True, "status": "FLAT", "signal": signal, **account}

        quantity = self.lab._validate_smoke_quantity(
            self.settings.forward_symbol, signal["direction"]
        )
        estimated_notional = _decimal(signal["price"]) * quantity
        budget = Decimal(str(self.settings.forward_margin_usdt))
        if estimated_notional > budget * Decimal("1.25"):
            raise FuturesTestnetExecutionError("BTCUSDT minimum quantity exceeds Futures forward budget")
        minimum_headroom = max(budget, estimated_notional) * Decimal("1.25")
        if _decimal(account["available_balance"]) < minimum_headroom:
            raise FuturesTestnetExecutionError("Insufficient Futures Demo margin for forward test")

        self.lab._configure(self.settings.forward_symbol, 1)
        side = "BUY" if signal["direction"] == "LONG" else "SELL"
        order = self.lab.forward_submit(
            symbol=self.settings.forward_symbol,
            side=side,
            quantity=quantity,
            reduce_only=False,
        )
        rows = self._actual_rows()
        if len(rows) != 1:
            raise FuturesTestnetExecutionError("Futures forward open position not found")
        amount = _decimal(rows[0]["positionAmt"])
        actual_qty = abs(amount)
        entry = _decimal(rows[0].get("entryPrice", order.get("avgPrice", "0")))
        if entry <= 0:
            entry = self.lab._execution_price(order, self.settings.forward_symbol)

        distance = max(
            Decimal(str(self.settings.forward_stop_atr_multiple * signal["atr"])),
            Decimal(str(self.settings.forward_minimum_stop_pct)) * entry,
        )
        if signal["direction"] == "LONG":
            stop = entry - distance
            take = entry + Decimal(str(self.settings.forward_reward_to_risk)) * distance
        else:
            stop = entry + distance
            take = entry - Decimal(str(self.settings.forward_reward_to_risk)) * distance

        liquidation = _decimal(rows[0].get("liquidationPrice", "0"))
        position = {
            "symbol": self.settings.forward_symbol,
            "direction": signal["direction"],
            "leverage": 1,
            "quantity": float(actual_qty),
            "entry_price": float(entry),
            "stop_price": float(stop),
            "take_profit": float(take),
            "liquidation_price": float(liquidation) if liquidation > 0 else None,
            "signal_score": int(signal["score"]),
            "opened_at": datetime.now(UTC).isoformat(),
        }
        self.ledger.set_forward_position(position)
        return {"enabled": True, "status": "OPENED", "position": position, "signal": signal, **account}

    def snapshot(self) -> dict:
        data = self.ledger.forward_snapshot()
        return {
            "enabled": self.settings.forward_enabled,
            "killed": self.killed(),
            "symbol": self.settings.forward_symbol,
            "automatic_leverage": 1,
            "latest_signal": self.ledger.setting("forward_last_signal"),
            "last_error": self.ledger.setting("forward_last_error"),
            **data,
        }
