from __future__ import annotations

from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> float:
    if period <= 0 or len(values) < period:
        raise ValueError("not enough values for SMA")
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    if period <= 0 or len(values) < period:
        raise ValueError("not enough values for EMA")
    seed = sum(values[:period]) / period
    result = [seed]
    multiplier = 2.0 / (period + 1.0)
    current = seed
    for value in values[period:]:
        current = (value - current) * multiplier + current
        result.append(current)
    return result


def ema(values: Sequence[float], period: int) -> float:
    return ema_series(values, period)[-1]


def rsi(values: Sequence[float], period: int = 14) -> float:
    if len(values) < period + 1:
        raise ValueError("not enough values for RSI")
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float:
    if len(closes) < period + 1 or len(highs) != len(closes) or len(lows) != len(closes):
        raise ValueError("not enough aligned values for ATR")
    true_ranges: list[float] = []
    for i in range(1, len(closes)):
        true_ranges.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    value = sum(true_ranges[:period]) / period
    for current in true_ranges[period:]:
        value = ((value * (period - 1)) + current) / period
    return value


def max_drawdown(equity_curve: Sequence[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value / peak) - 1.0)
    return worst

