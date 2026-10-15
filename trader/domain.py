from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: str
    score: int
    price: float
    stop_price: float | None
    take_profit: float | None
    atr: float
    rsi: float
    ema_fast: float
    ema_slow: float
    volume_ratio: float
    reason: str
    created_at: str
    observed_price: float | None = None
    observed_stop_price: float | None = None
    observed_take_profit: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in ('observed_price', 'observed_stop_price', 'observed_take_profit'):
            if payload[name] is None:
                payload.pop(name)
        return payload

    def at_entry_price(self, price: float) -> Signal:
        """Move an entry plan without changing its percentage risk or reward/risk.

        EMA/RSI/volume describe the observed closed candle. Protection and ATR
        are amounts in the entry price scale, as in next-open backtesting.
        Callers must still check the original signal range before rebasing.
        """
        values = (self.price, price, self.atr, self.stop_price, self.take_profit)
        if (self.action != 'BUY' or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values)
                or not self.stop_price < self.price < self.take_profit):
            raise ValueError('invalid entry price plan')
        scale = price / self.price
        origin = (self.observed_price, self.observed_stop_price, self.observed_take_profit)
        if all(v is None for v in origin):
            origin = (self.price, self.stop_price, self.take_profit)
        if (any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in origin)
                or not origin[1] < origin[0] < origin[2]):
            raise ValueError('invalid observed entry plan')
        updated = replace(self, price=price, stop_price=self.stop_price*scale,
                          take_profit=self.take_profit*scale, atr=self.atr*scale,
                          observed_price=origin[0], observed_stop_price=origin[1],
                          observed_take_profit=origin[2])
        if any(not math.isfinite(v) or v <= 0 for v in (updated.stop_price, updated.take_profit, updated.atr)):
            raise ValueError('invalid entry price plan')
        return updated


@dataclass(frozen=True)
class AIReview:
    verdict: str
    confidence: float
    risk_multiplier: float
    reason: str


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    entry_price: float
    stop_price: float
    take_profit: float
    high_water: float
    atr: float
    entry_fee: float
    opened_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

