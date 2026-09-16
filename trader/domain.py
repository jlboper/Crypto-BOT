from __future__ import annotations

from dataclasses import asdict, dataclass
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

