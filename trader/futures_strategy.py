"""Pure operating Futures signal shared by forward execution and offline research.

This function proposes only a direction and indicators. It does not construct an
engine, load credentials, submit orders or authorize strategy promotion.
"""
from __future__ import annotations

from .config import FuturesTestnetSettings, StrategySettings
from .domain import Candle
from .indicators import atr, ema_series, rsi, sma


def evaluate_futures_signal(candles: list[Candle], strategy_settings: StrategySettings,
                            futures_settings: FuturesTestnetSettings) -> dict:
    """Preserve the operating score and numerical order exactly in one place."""
    s=strategy_settings
    required=max(s.ema_slow+5,s.breakout_period+2,s.atr_period+2,s.volume_period+2)
    if len(candles)<required: raise ValueError("Futures forward history unavailable")
    closes=[c.close for c in candles]; highs=[c.high for c in candles]; lows=[c.low for c in candles]; volumes=[c.volume for c in candles]
    price=closes[-1]; fast_series=ema_series(closes,s.ema_fast); slow_series=ema_series(closes,s.ema_slow)
    fast=fast_series[-1]; slow=slow_series[-1]; current_rsi=rsi(closes,s.rsi_period)
    current_atr=atr(highs,lows,closes,s.atr_period); avg=sma(volumes[:-1],s.volume_period)
    volume_ratio=volumes[-1]/avg if avg>0 else 0.0
    prior_high=max(highs[-s.breakout_period-1:-1]); prior_low=min(lows[-s.breakout_period-1:-1])
    momentum=(price/closes[-6])-1.0
    long_score=0; short_score=0
    if price>fast>slow: long_score+=25
    if price<fast<slow: short_score+=25
    if len(fast_series)>=4 and fast_series[-1]>fast_series[-4]: long_score+=10
    if len(fast_series)>=4 and fast_series[-1]<fast_series[-4]: short_score+=10
    if 52<=current_rsi<=72: long_score+=15
    elif 48<=current_rsi<52: long_score+=7
    if 28<=current_rsi<=48: short_score+=15
    elif 48<current_rsi<=52: short_score+=7
    if volume_ratio>=1.2: long_score+=15; short_score+=15
    elif volume_ratio>=1.0: long_score+=8; short_score+=8
    if price>prior_high: long_score+=20
    if price<prior_low: short_score+=20
    if momentum>=0.01: long_score+=15
    if momentum<=-0.01: short_score+=15
    if current_atr/price>0.12: long_score-=15; short_score-=15
    long_score=max(0,min(100,long_score)); short_score=max(0,min(100,short_score)); score=max(long_score,short_score)
    direction=None
    if score>=futures_settings.forward_min_score and abs(long_score-short_score)>=10:
        direction="LONG" if long_score>short_score else "SHORT"
    return {"direction":direction,"score":score,"long_score":long_score,"short_score":short_score,
            "price":price,"atr":current_atr,"rsi":current_rsi,"ema_fast":fast,"ema_slow":slow,"volume_ratio":volume_ratio}
