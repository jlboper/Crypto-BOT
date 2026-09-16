from __future__ import annotations

from datetime import UTC, datetime

from .config import RiskSettings, StrategySettings
from .domain import Candle, Signal
from .indicators import atr, ema_series, rsi, sma


class SwingStrategy:
    def __init__(self, settings: StrategySettings, risk: RiskSettings) -> None:
        self.settings = settings
        self.risk = risk

    @property
    def minimum_history(self) -> int:
        return max(
            self.settings.ema_slow + 5,
            self.settings.breakout_period + 2,
            self.settings.atr_period + 2,
            self.settings.volume_period + 2,
        )

    def evaluate(self, symbol: str, candles: list[Candle], btc_bullish: bool = True) -> Signal:
        required = max(self.settings.ema_slow + 5, self.settings.breakout_period + 2, self.settings.atr_period + 2)
        if len(candles) < required:
            raise ValueError(f"{symbol}: at least {required} closed candles required")

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]
        price = closes[-1]
        fast_series = ema_series(closes, self.settings.ema_fast)
        slow_series = ema_series(closes, self.settings.ema_slow)
        fast = fast_series[-1]
        slow = slow_series[-1]
        current_rsi = rsi(closes, self.settings.rsi_period)
        current_atr = atr(highs, lows, closes, self.settings.atr_period)
        average_volume = sma(volumes[:-1], self.settings.volume_period)
        volume_ratio = volumes[-1] / average_volume if average_volume > 0 else 0.0
        prior_high = max(highs[-self.settings.breakout_period - 1 : -1])
        breakout = price > prior_high
        momentum_5 = (price / closes[-6]) - 1.0

        score = 0
        reasons: list[str] = []
        if price > fast > slow:
            score += 25
            reasons.append("trend aligned")
        if len(fast_series) >= 4 and fast_series[-1] > fast_series[-4]:
            score += 10
            reasons.append("fast trend rising")
        if 52 <= current_rsi <= 72:
            score += 15
            reasons.append("RSI constructive")
        elif 48 <= current_rsi < 52:
            score += 7
        if volume_ratio >= 1.2:
            score += 15
            reasons.append("volume confirmation")
        elif volume_ratio >= 1.0:
            score += 8
        if breakout:
            score += 20
            reasons.append("20-bar breakout")
        if momentum_5 >= 0.01:
            score += 15
            reasons.append("positive momentum")
        if not btc_bullish:
            score -= 20
            reasons.append("BTC regime penalty")
        if current_atr / price > 0.12:
            score -= 15
            reasons.append("extreme volatility penalty")

        action = "BUY" if score >= self.settings.minimum_score else "HOLD"
        stop_distance = max(self.risk.stop_atr_multiple * current_atr, self.risk.minimum_stop_pct * price)
        stop_price = price - stop_distance if action == "BUY" else None
        take_profit = price + self.risk.reward_to_risk * stop_distance if action == "BUY" else None
        return Signal(
            symbol=symbol,
            action=action,
            score=max(0, min(100, score)),
            price=price,
            stop_price=stop_price,
            take_profit=take_profit,
            atr=current_atr,
            rsi=current_rsi,
            ema_fast=fast,
            ema_slow=slow,
            volume_ratio=volume_ratio,
            reason=", ".join(reasons) or "conditions not met",
            created_at=datetime.now(UTC).isoformat(),
        )

    def should_exit(self, candles: list[Candle]) -> tuple[bool, str]:
        closes = [c.close for c in candles]
        fast = ema_series(closes, self.settings.ema_fast)[-1]
        current_rsi = rsi(closes, self.settings.rsi_period)
        if closes[-1] < fast and current_rsi < 48:
            return True, "trend exit: close below fast EMA and RSI below 48"
        return False, "position remains valid"

    def btc_regime(self, candles: list[Candle]) -> bool:
        closes = [c.close for c in candles]
        slow = ema_series(closes, self.settings.ema_slow)
        return closes[-1] > slow[-1] and slow[-1] >= slow[-4]
