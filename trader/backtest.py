from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass
from typing import Protocol

from .config import AppConfig
from .domain import Candle, Signal
from .indicators import atr, max_drawdown
from .strategy import SwingStrategy


class BacktestStrategy(Protocol):
    @property
    def minimum_history(self) -> int: ...

    def evaluate(self, symbol: str, candles: list[Candle], btc_bullish: bool = True) -> Signal: ...

    def should_exit(self, candles: list[Candle]) -> tuple[bool, str]: ...

    def btc_regime(self, candles: list[Candle]) -> bool: ...


@dataclass(frozen=True)
class TradeRecord:
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    net_pnl: float
    return_pct: float
    bars_held: int
    exit_reason: str


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    strategy: str
    start_cash: float
    end_equity: float
    return_pct: float
    benchmark_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    trades: int
    win_rate_pct: float
    profit_factor: float
    expectancy_usdt: float
    average_trade_pct: float
    exposure_pct: float
    turnover_multiple: float
    evaluated_bars: int
    trade_records: tuple[TradeRecord, ...]


def _bars_per_year(interval: str) -> float:
    mapping = {
        "1m": 365.0 * 24 * 60,
        "5m": 365.0 * 24 * 12,
        "15m": 365.0 * 24 * 4,
        "30m": 365.0 * 24 * 2,
        "1h": 365.0 * 24,
        "2h": 365.0 * 12,
        "4h": 365.0 * 6,
        "6h": 365.0 * 4,
        "8h": 365.0 * 3,
        "12h": 365.0 * 2,
        "1d": 365.0,
    }
    return mapping.get(interval, 365.0)


def _regime_lookup(candles: list[Candle], strategy: BacktestStrategy) -> tuple[list[int], list[bool]]:
    minimum = max(4, strategy.minimum_history)
    settings = getattr(strategy, "settings", None)
    slow_period = getattr(settings, "ema_slow", None)
    if slow_period:
        from .indicators import ema_series

        closes = [candle.close for candle in candles]
        slow = ema_series(closes, int(slow_period))
        times = [candles[index].close_time for index in range(minimum - 1, len(candles))]
        regimes = []
        for index in range(minimum - 1, len(candles)):
            aligned = index - int(slow_period) + 1
            regimes.append(closes[index] > slow[aligned] and slow[aligned] >= slow[aligned - 3])
        return times, regimes
    times: list[int] = []
    regimes: list[bool] = []
    for index in range(minimum - 1, len(candles)):
        # The live engine evaluates at most 250 candles each cycle. Keeping the
        # same bounded history also prevents distant data from changing signals
        # that the operational strategy could not have seen.
        window = candles[max(0, index - 249) : index + 1]
        times.append(candles[index].close_time)
        regimes.append(strategy.btc_regime(window))
    return times, regimes


def _benchmark_return(candles: list[Candle], start_index: int, config: AppConfig) -> float:
    if start_index >= len(candles):
        return 0.0
    entry = candles[start_index].open * (1.0 + config.paper.slippage_rate)
    exit_price = candles[-1].close * (1.0 - config.paper.slippage_rate)
    quantity = config.paper.initial_cash_usdt / (entry * (1.0 + config.paper.fee_rate))
    ending = quantity * exit_price * (1.0 - config.paper.fee_rate)
    return (ending / config.paper.initial_cash_usdt - 1.0) * 100.0


def run_backtest(
    symbol: str,
    candles: list[Candle],
    config: AppConfig,
    *,
    strategy: BacktestStrategy | None = None,
    strategy_name: str = "baseline_trend",
    btc_candles: list[Candle] | None = None,
    trade_start_index: int | None = None,
) -> BacktestResult:
    """Conservative event-driven, long-only simulation.

    Signals created at bar close execute at the next bar open. Protective orders use
    intrabar OHLC data. If a stop and target are both touched, the stop wins so the
    simulator never assumes an optimistic event order that the candle cannot prove.
    """

    selected = strategy or SwingStrategy(config.strategy, config.risk)
    minimum_history = max(
        getattr(selected, "minimum_history", 0),
        config.strategy.atr_period + 2,
    )
    start_index = max(minimum_history, trade_start_index or minimum_history)
    if len(candles) <= start_index + 1:
        raise ValueError(f"{symbol}: at least {start_index + 2} closed candles required")

    regime_source = btc_candles or (candles if symbol == "BTCUSDT" else None)
    regime_times: list[int] = []
    regimes: list[bool] = []
    if regime_source:
        regime_times, regimes = _regime_lookup(regime_source, selected)

    def btc_bullish_at(close_time: int) -> bool:
        if not regime_times:
            return True
        index = bisect_right(regime_times, close_time) - 1
        return regimes[index] if index >= 0 else True

    cash = config.paper.initial_cash_usdt
    position: dict[str, float | int] | None = None
    pending_entry: Signal | None = None
    pending_exit: str | None = None
    records: list[TradeRecord] = []
    equity_curve: list[float] = [cash]
    exposure_bars = 0
    turnover = 0.0

    def close_position(fill_price: float, exit_time: int, reason: str, held_bars: int) -> None:
        nonlocal cash, position, turnover
        if position is None:
            return
        quantity = float(position["quantity"])
        exit_fee = fill_price * quantity * config.paper.fee_rate
        proceeds = fill_price * quantity - exit_fee
        entry_price = float(position["entry_price"])
        entry_fee = float(position["entry_fee"])
        net_pnl = (fill_price - entry_price) * quantity - entry_fee - exit_fee
        invested = entry_price * quantity + entry_fee
        cash += proceeds
        turnover += fill_price * quantity
        records.append(
            TradeRecord(
                entry_time=int(position["entry_time"]),
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=fill_price,
                quantity=quantity,
                net_pnl=net_pnl,
                return_pct=(net_pnl / invested * 100.0) if invested else 0.0,
                bars_held=held_bars,
                exit_reason=reason,
            )
        )
        position = None

    for index in range(start_index, len(candles)):
        bar = candles[index]

        if position is not None and pending_exit:
            fill = bar.open * (1.0 - config.paper.slippage_rate)
            held = index - int(position["entry_index"])
            close_position(fill, bar.open_time, pending_exit, held)
            pending_exit = None

        if position is None and pending_entry is not None:
            entry_fill = bar.open * (1.0 + config.paper.slippage_rate)
            signal_distance = max(
                pending_entry.price - float(pending_entry.stop_price or pending_entry.price),
                config.risk.minimum_stop_pct * pending_entry.price,
            )
            distance = signal_distance * (entry_fill / pending_entry.price)
            stop = entry_fill - distance
            target = entry_fill + config.risk.reward_to_risk * distance
            equity = cash
            stop_fill = stop * (1 - config.paper.slippage_rate)
            loss_per_unit = entry_fill - stop_fill + config.paper.fee_rate * (entry_fill + stop_fill)
            by_risk = (equity * config.risk.risk_per_trade_pct) / loss_per_unit
            by_position = (equity * config.risk.max_position_pct) / entry_fill
            by_cash = cash / (entry_fill * (1.0 + config.paper.fee_rate))
            quantity = math.floor(min(by_risk, by_position, by_cash) * 1_000_000) / 1_000_000
            if quantity > 0:
                entry_fee = entry_fill * quantity * config.paper.fee_rate
                cash -= entry_fill * quantity + entry_fee
                turnover += entry_fill * quantity
                position = {
                    "quantity": quantity,
                    "entry_price": entry_fill,
                    "entry_fee": entry_fee,
                    "entry_time": bar.open_time,
                    "entry_index": index,
                    "stop": stop,
                    "target": target,
                    "high_water": entry_fill,
                    "initial_risk": distance,
                }
            pending_entry = None

        if position is not None:
            exposure_bars += 1
            stop = float(position["stop"])
            target = float(position["target"])
            reason: str | None = None
            trigger: float | None = None
            if bar.open <= stop:
                trigger = bar.open
                reason = "gap_stop"
            elif bar.low <= stop and bar.high >= target:
                trigger = stop
                reason = "stop_before_target_conservative"
            elif bar.low <= stop:
                trigger = stop
                reason = "protective_stop"
            elif bar.high >= target:
                trigger = target
                reason = "take_profit"
            if trigger is not None and reason is not None:
                fill = trigger * (1.0 - config.paper.slippage_rate)
                held = index - int(position["entry_index"]) + 1
                close_position(fill, bar.close_time, reason, held)

        window = candles[max(0, index - 249): index + 1]
        if position is not None:
            current_atr = atr(
                [c.high for c in window],
                [c.low for c in window],
                [c.close for c in window],
                config.strategy.atr_period,
            )
            position["high_water"] = max(float(position["high_water"]), bar.high)
            trailing_stop = float(position["high_water"]) - config.risk.trailing_atr_multiple * current_atr
            if float(position["high_water"]) >= float(position["entry_price"]) + float(position["initial_risk"]):
                position["stop"] = max(float(position["stop"]), float(position["entry_price"]), trailing_stop)
            should_exit, reason = selected.should_exit(window)
            if should_exit:
                pending_exit = reason
        elif index + 1 < len(candles):
            signal = selected.evaluate(symbol, window, btc_bullish_at(bar.close_time))
            if signal.action == "BUY":
                pending_entry = signal

        marked_equity = cash
        if position is not None:
            marked_equity += float(position["quantity"]) * bar.close * (1.0 - config.paper.fee_rate)
        equity_curve.append(marked_equity)

    if position is not None:
        last = candles[-1]
        fill = last.close * (1.0 - config.paper.slippage_rate)
        held = len(candles) - int(position["entry_index"])
        close_position(fill, last.close_time, "end_of_test", held)
        equity_curve[-1] = cash

    periodic_returns = [
        equity_curve[i] / equity_curve[i - 1] - 1.0
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    bars_year = _bars_per_year(config.bot.timeframe)
    mean_return = statistics.fmean(periodic_returns) if periodic_returns else 0.0
    volatility = statistics.stdev(periodic_returns) if len(periodic_returns) > 1 else 0.0
    downside = [min(0.0, value) for value in periodic_returns]
    downside_deviation = math.sqrt(statistics.fmean(value * value for value in downside)) if downside else 0.0
    sharpe = (mean_return / volatility * math.sqrt(bars_year)) if volatility > 0 else 0.0
    sortino = (mean_return / downside_deviation * math.sqrt(bars_year)) if downside_deviation > 0 else 0.0
    drawdown_pct = -max_drawdown(equity_curve) * 100.0
    years = max((candles[-1].close_time - candles[start_index].open_time) / (365.0 * 24 * 3600 * 1000), 1 / bars_year)
    annualized = ((cash / config.paper.initial_cash_usdt) ** (1.0 / years) - 1.0) * 100.0 if cash > 0 else -100.0
    calmar = annualized / drawdown_pct if drawdown_pct > 0 else 0.0
    pnls = [trade.net_pnl for trade in records]
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    evaluated_bars = len(candles) - start_index

    return BacktestResult(
        symbol=symbol,
        strategy=strategy_name,
        start_cash=config.paper.initial_cash_usdt,
        end_equity=cash,
        return_pct=(cash / config.paper.initial_cash_usdt - 1.0) * 100.0,
        benchmark_return_pct=_benchmark_return(candles, start_index, config),
        annualized_return_pct=annualized,
        max_drawdown_pct=drawdown_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        trades=len(records),
        win_rate_pct=(sum(trade.net_pnl > 0 for trade in records) / len(records) * 100.0) if records else 0.0,
        profit_factor=(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0),
        expectancy_usdt=statistics.fmean(pnls) if pnls else 0.0,
        average_trade_pct=statistics.fmean(trade.return_pct for trade in records) if records else 0.0,
        exposure_pct=(exposure_bars / evaluated_bars * 100.0) if evaluated_bars else 0.0,
        turnover_multiple=turnover / config.paper.initial_cash_usdt,
        evaluated_bars=evaluated_bars,
        trade_records=tuple(records),
    )
