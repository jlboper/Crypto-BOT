from __future__ import annotations

from datetime import UTC, datetime
import math
import time

from .config import PaperSettings, RiskSettings
from .database import Database
from .domain import Position, Signal
from .risk_control import profile_multiplier


class PaperBroker:
    def __init__(self, database: Database, settings: PaperSettings, risk: RiskSettings) -> None:
        self.db = database
        self.settings = settings
        self.risk = risk
        self.db.initialize_cash(settings.initial_cash_usdt)

    def equity(self, prices: dict[str, float]) -> tuple[float, float, float]:
        cash = self.db.cash()
        exposure = sum(position.quantity * prices.get(position.symbol, position.entry_price) for position in self.db.positions())
        return cash + exposure, cash, exposure

    def buy(self, signal: Signal, quantity: float, reason: str) -> Position:
        with self.db.transaction():
            return self._buy(signal, quantity, reason)

    def _buy(self, signal: Signal, quantity: float, reason: str) -> Position:
        if signal.action != "BUY" or any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0
            for v in (quantity, signal.price, signal.stop_price, signal.take_profit, signal.atr)
        ):
            raise ValueError("invalid buy values")
        if not signal.stop_price < signal.price < signal.take_profit:
            raise ValueError("invalid protection levels")
        if self.db.position(signal.symbol):
            raise ValueError(f"position already exists for {signal.symbol}")
        if float(self.db.setting("manual_close_until_" + signal.symbol, "0")) > time.time():
            raise ValueError("manual close cooldown active")
        fill_price = signal.price * (1.0 + self.settings.slippage_rate)
        if fill_price >= signal.take_profit:
            raise ValueError("fill exceeds target")
        gross = fill_price * quantity
        fee = gross * self.settings.fee_rate
        cash = self.db.cash()
        prices, _ = self.db.market_snapshot()
        equity, _, exposure = self.equity(prices)
        if len(self.db.positions()) >= self.risk.max_positions:
            raise ValueError("position count limit")
        if gross > equity * self.risk.max_position_pct + 1e-8 or exposure + gross > equity * self.risk.max_total_exposure_pct + 1e-8:
            raise ValueError("exposure limit")
        stop_fill = signal.stop_price * (1 - self.settings.slippage_rate)
        loss = quantity * (fill_price - stop_fill + self.settings.fee_rate * (fill_price + stop_fill))
        risk_factor = profile_multiplier(self.db)
        if risk_factor <= 0 or loss > equity * self.risk.risk_per_trade_pct * risk_factor + 1e-8:
            raise ValueError("per-trade risk limit")
        if gross + fee > cash:
            raise ValueError("insufficient paper cash")
        if signal.stop_price is None or signal.take_profit is None:
            raise ValueError("buy signal has no protection levels")
        position = Position(
            symbol=signal.symbol,
            quantity=quantity,
            entry_price=fill_price,
            stop_price=signal.stop_price,
            take_profit=signal.take_profit,
            high_water=fill_price,
            atr=signal.atr,
            entry_fee=fee,
            opened_at=datetime.now(UTC).isoformat(),
        )
        self.db.set_cash(cash - gross - fee)
        self.db.upsert_position(position)
        self.db.record_trade(signal.symbol, "BUY", quantity, fill_price, fee, 0.0, reason)
        return position

    def sell(self, position: Position, market_price: float, reason: str, *, manual_cooldown_until: float | None = None) -> float:
        with self.db.transaction():
            current = self.db.position(position.symbol)
            if current != position:
                raise ValueError("position absent or stale; duplicate sell blocked")
            if not math.isfinite(market_price) or market_price <= 0:
                raise ValueError("invalid market price")
            pnl = self._sell(position, market_price, reason)
            if manual_cooldown_until is not None:
                if reason != "manual PAPER close" or not math.isfinite(manual_cooldown_until) or manual_cooldown_until <= time.time():
                    raise ValueError("invalid manual close cooldown")
                self.db.set_setting("manual_close_until_" + position.symbol, str(manual_cooldown_until))
            return pnl

    def _sell(self, position: Position, market_price: float, reason: str) -> float:
        fill_price = market_price * (1.0 - self.settings.slippage_rate)
        gross = fill_price * position.quantity
        fee = gross * self.settings.fee_rate
        pnl = (fill_price - position.entry_price) * position.quantity - position.entry_fee - fee
        self.db.set_cash(self.db.cash() + gross - fee)
        self.db.delete_position(position.symbol)
        self.db.record_trade(position.symbol, "SELL", position.quantity, fill_price, fee, pnl, reason)
        return pnl

    def protect(self, position: Position, price: float, atr_value: float) -> tuple[Position | None, str | None]:
        if price <= position.stop_price:
            self.sell(position, price, "protective stop")
            return None, "protective stop"
        if price >= position.take_profit:
            self.sell(position, price, "take profit")
            return None, "take profit"
        high_water = max(position.high_water, price)
        initial_risk = max((position.take_profit - position.entry_price) / self.risk.reward_to_risk, 0.0)
        stop_price = position.stop_price
        if initial_risk > 0 and high_water >= position.entry_price + initial_risk and atr_value > 0:
            stop_price = max(stop_price, position.entry_price, high_water - self.risk.trailing_atr_multiple * atr_value)
        updated = Position(
            symbol=position.symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            stop_price=stop_price,
            take_profit=position.take_profit,
            high_water=high_water,
            atr=atr_value,
            entry_fee=position.entry_fee,
            opened_at=position.opened_at,
        )
        self.db.upsert_position(updated)
        return updated, None
