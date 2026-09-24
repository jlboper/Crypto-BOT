from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .backtest import BacktestResult, run_backtest
from .config import AppConfig, StrategySettings
from .domain import Candle, Signal
from .indicators import atr, ema_series, max_drawdown, rsi, sma
from .strategy import SwingStrategy


RESEARCH_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


@dataclass(frozen=True)
class ResearchProfile:
    name: str
    family: str
    settings: StrategySettings


class ProfileStrategy:
    """Research-only strategy family. It is never promoted into the live engine automatically."""

    def __init__(self, profile: ResearchProfile, config: AppConfig) -> None:
        self.profile = profile
        self.settings = profile.settings
        self.risk = config.risk
        self.trend = SwingStrategy(self.settings, self.risk)

    @property
    def minimum_history(self) -> int:
        return max(self.trend.minimum_history, 105 if self.profile.family == "mean_reversion" else 0)

    def btc_regime(self, candles: list[Candle]) -> bool:
        return self.trend.btc_regime(candles)

    def evaluate(self, symbol: str, candles: list[Candle], btc_bullish: bool = True) -> Signal:
        if self.profile.family in {"trend_breakout", "fast_momentum", "conservative_trend"}:
            return self.trend.evaluate(symbol, candles, btc_bullish)
        if self.profile.family == "trend_pullback":
            return self._pullback(symbol, candles, btc_bullish)
        if self.profile.family == "mean_reversion":
            return self._mean_reversion(symbol, candles, btc_bullish)
        raise ValueError(f"unknown research family: {self.profile.family}")

    def should_exit(self, candles: list[Candle]) -> tuple[bool, str]:
        closes = [c.close for c in candles]
        current_rsi = rsi(closes, self.settings.rsi_period)
        if self.profile.family == "mean_reversion":
            middle = sma(closes, 20)
            if closes[-1] >= middle or current_rsi >= 60:
                return True, "mean_reversion_recovered"
            return False, "mean_reversion_open"
        if self.profile.family == "trend_pullback":
            slow = ema_series(closes, self.settings.ema_slow)[-1]
            if closes[-1] < slow or current_rsi >= 74:
                return True, "pullback_thesis_complete"
            return False, "pullback_open"
        return self.trend.should_exit(candles)

    def _base_values(self, candles: list[Candle]) -> tuple[list[float], float, float, float, float, float]:
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        price = closes[-1]
        fast = ema_series(closes, self.settings.ema_fast)[-1]
        slow = ema_series(closes, self.settings.ema_slow)[-1]
        current_rsi = rsi(closes, self.settings.rsi_period)
        current_atr = atr(highs, lows, closes, self.settings.atr_period)
        return closes, price, fast, slow, current_rsi, current_atr

    def _signal(
        self,
        symbol: str,
        score: int,
        price: float,
        current_atr: float,
        current_rsi: float,
        fast: float,
        slow: float,
        volume_ratio: float,
        reasons: list[str],
    ) -> Signal:
        action = "BUY" if score >= self.settings.minimum_score else "HOLD"
        distance = max(self.risk.stop_atr_multiple * current_atr, self.risk.minimum_stop_pct * price)
        return Signal(
            symbol=symbol,
            action=action,
            score=max(0, min(100, score)),
            price=price,
            stop_price=price - distance if action == "BUY" else None,
            take_profit=price + self.risk.reward_to_risk * distance if action == "BUY" else None,
            atr=current_atr,
            rsi=current_rsi,
            ema_fast=fast,
            ema_slow=slow,
            volume_ratio=volume_ratio,
            reason=", ".join(reasons) or "conditions not met",
            created_at=datetime.now(UTC).isoformat(),
        )

    def _pullback(self, symbol: str, candles: list[Candle], btc_bullish: bool) -> Signal:
        closes, price, fast, slow, current_rsi, current_atr = self._base_values(candles)
        volumes = [c.volume for c in candles]
        average_volume = sma(volumes[:-1], self.settings.volume_period)
        volume_ratio = volumes[-1] / average_volume if average_volume else 0.0
        score = 0
        reasons: list[str] = []
        if fast > slow and price > slow:
            score += 30
            reasons.append("primary trend positive")
        distance_to_fast = abs(price / fast - 1.0)
        if distance_to_fast <= 0.02:
            score += 20
            reasons.append("controlled pullback to EMA")
        if 42 <= current_rsi <= 60:
            score += 20
            reasons.append("RSI reset")
        if candles[-1].close > candles[-1].open:
            score += 12
            reasons.append("bullish recovery candle")
        if volume_ratio >= 0.8:
            score += 8
        if closes[-1] > closes[-3]:
            score += 10
        if not btc_bullish:
            score -= 20
            reasons.append("BTC regime penalty")
        return self._signal(symbol, score, price, current_atr, current_rsi, fast, slow, volume_ratio, reasons)

    def _mean_reversion(self, symbol: str, candles: list[Candle], btc_bullish: bool) -> Signal:
        closes, price, fast, slow, current_rsi, current_atr = self._base_values(candles)
        window = closes[-20:]
        middle = statistics.fmean(window)
        deviation = statistics.pstdev(window)
        z_score = (price - middle) / deviation if deviation else 0.0
        volumes = [c.volume for c in candles]
        average_volume = sma(volumes[:-1], self.settings.volume_period)
        volume_ratio = volumes[-1] / average_volume if average_volume else 0.0
        slow_series = ema_series(closes, self.settings.ema_slow)
        score = 0
        reasons: list[str] = []
        if z_score <= -1.5:
            score += 35
            reasons.append("statistical downside extension")
        if current_rsi <= 38:
            score += 25
            reasons.append("RSI oversold")
        if slow_series[-1] >= slow_series[-4] * 0.99:
            score += 15
            reasons.append("long-term trend not collapsing")
        if candles[-1].close > candles[-1].open:
            score += 10
            reasons.append("reversal candle")
        if volume_ratio >= 1.0:
            score += 5
        if btc_bullish:
            score += 10
        else:
            score -= 25
            reasons.append("BTC regime penalty")
        return self._signal(symbol, score, price, current_atr, current_rsi, fast, slow, volume_ratio, reasons)


def default_profiles(config: AppConfig) -> tuple[ResearchProfile, ...]:
    base = config.strategy
    return (
        ResearchProfile("baseline_trend", "trend_breakout", base),
        ResearchProfile(
            "fast_momentum",
            "fast_momentum",
            replace(base, ema_fast=12, ema_slow=36, breakout_period=12, volume_period=12, minimum_score=68),
        ),
        ResearchProfile(
            "conservative_trend",
            "conservative_trend",
            replace(base, ema_fast=30, ema_slow=100, breakout_period=55, volume_period=30, minimum_score=75),
        ),
        ResearchProfile("trend_pullback", "trend_pullback", replace(base, minimum_score=70)),
        ResearchProfile("mean_reversion", "mean_reversion", replace(base, minimum_score=65)),
    )


def _finite(value: float, fallback: float = 0.0) -> float:
    return value if math.isfinite(value) else fallback


def _research_score(result: BacktestResult) -> float:
    if result.trades < 3:
        return -1_000.0 + result.trades
    excess = result.return_pct - result.benchmark_return_pct
    return (
        24.0 * max(-3.0, min(3.0, result.sharpe_ratio))
        + 10.0 * max(-5.0, min(5.0, result.calmar_ratio))
        + 0.30 * excess
        - 0.45 * result.max_drawdown_pct
        - 0.20 * result.turnover_multiple
        + min(result.trades, 20) * 0.30
    )


def _result_summary(result: BacktestResult) -> dict:
    return {
        "strategy": result.strategy,
        "return_pct": round(result.return_pct, 4),
        "benchmark_return_pct": round(result.benchmark_return_pct, 4),
        "annualized_return_pct": round(result.annualized_return_pct, 4),
        "max_drawdown_pct": round(result.max_drawdown_pct, 4),
        "sharpe_ratio": round(_finite(result.sharpe_ratio), 4),
        "sortino_ratio": round(_finite(result.sortino_ratio), 4),
        "calmar_ratio": round(_finite(result.calmar_ratio), 4),
        "trades": result.trades,
        "win_rate_pct": round(result.win_rate_pct, 4),
        "profit_factor": round(_finite(result.profit_factor, 99.0), 4),
        "expectancy_usdt": round(result.expectancy_usdt, 4),
        "average_trade_pct": round(result.average_trade_pct, 4),
        "exposure_pct": round(result.exposure_pct, 4),
        "turnover_multiple": round(result.turnover_multiple, 4),
        "research_score": round(_research_score(result), 4),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def monte_carlo(trade_portfolio_returns: list[float], simulations: int = 1_000, seed: int = 606) -> dict:
    if not trade_portfolio_returns:
        return {
            "simulations": simulations,
            "median_return_pct": 0.0,
            "p05_return_pct": 0.0,
            "p95_drawdown_pct": 0.0,
            "loss_probability_pct": 100.0,
        }
    rng = random.Random(seed)
    terminal_returns: list[float] = []
    drawdowns: list[float] = []
    for _ in range(simulations):
        equity = peak = 1.0
        worst = 0.0
        sampled = []
        block = min(5, len(trade_portfolio_returns))
        while len(sampled) < len(trade_portfolio_returns):
            start = rng.randrange(len(trade_portfolio_returns))
            sampled.extend(trade_portfolio_returns[(start+j) % len(trade_portfolio_returns)] for j in range(block))
        for value in sampled[:len(trade_portfolio_returns)]:
            equity *= 1.0 + value
            peak = max(peak, equity)
            worst = max(worst, 1.0 - equity / peak)
        terminal_returns.append((equity - 1.0) * 100.0)
        drawdowns.append(worst * 100.0)
    return {
        "simulations": simulations,
        "method": "circular_block_bootstrap",
        "block_trades": min(5, len(trade_portfolio_returns)),
        "median_return_pct": round(_percentile(terminal_returns, 0.50), 4),
        "p05_return_pct": round(_percentile(terminal_returns, 0.05), 4),
        "p95_drawdown_pct": round(_percentile(drawdowns, 0.95), 4),
        "loss_probability_pct": round(sum(value < 0 for value in terminal_returns) / simulations * 100.0, 4),
    }


def _data_quality(candles: list[Candle]) -> dict:
    timestamps = [c.open_time for c in candles]
    duplicate_count = len(timestamps) - len(set(timestamps))
    gaps = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
    expected = int(statistics.median(gaps)) if gaps else 0
    large_gaps = sum(gap > expected * 1.5 for gap in gaps) if expected else 0
    invalid = sum(
        not all(math.isfinite(v) for v in (c.open, c.high, c.low, c.close, c.volume))
        or not 0 < c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high
        or c.volume < 0 or c.close_time <= c.open_time for c in candles
    )
    return {
        "candles": len(candles),
        "duplicate_timestamps": duplicate_count,
        "large_gaps": large_gaps,
        "expected_interval_ms": expected,
        "invalid_candles": invalid,
        "passed": bool(candles) and invalid == 0 and duplicate_count == 0 and large_gaps == 0 and all(g > 0 for g in gaps),
    }


def _iso_ms(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000.0, UTC).isoformat()


def _market_regime(benchmark_return_pct: float) -> str:
    if benchmark_return_pct >= 5.0:
        return "BULLISH"
    if benchmark_return_pct <= -5.0:
        return "BEARISH"
    return "SIDEWAYS"


def _trade_returns(result, initial):
    equity = initial
    values = []
    for trade in result.trade_records:
        values.append(trade.net_pnl / equity if equity > 0 else 0.0)
        equity += trade.net_pnl
    return values


def _research_development(
    symbol: str,
    candles: list[Candle],
    btc_candles: list[Candle],
    config: AppConfig,
    *,
    train_bars: int = 600,
    test_bars: int = 200,
) -> dict:
    profiles = default_profiles(config)
    if train_bars <= 0 or test_bars <= 1:
        raise ValueError("invalid fold sizes")
    maximum_warmup = max(ProfileStrategy(profile, config).minimum_history for profile in profiles)
    if len(candles) < train_bars + test_bars + maximum_warmup:
        raise ValueError(
            f"{symbol}: {len(candles)} candles are insufficient for {train_bars} train + "
            f"{test_bars} test + {maximum_warmup} warmup"
        )

    adaptive_folds: list[dict] = []
    adaptive_trade_returns: list[float] = []
    fixed_folds: dict[str, list[dict]] = {profile.name: [] for profile in profiles}
    fixed_trade_returns: dict[str, list[float]] = {profile.name: [] for profile in profiles}
    test_scores: dict[str, list[float]] = {profile.name: [] for profile in profiles}
    selection_counts: dict[str, int] = {profile.name: 0 for profile in profiles}
    selection_counts["CASH"] = 0
    overfit_selections = 0
    active_selections = 0
    initial_winner = None

    for test_start in range(train_bars, len(candles) - test_bars + 1, test_bars):
        train = candles[test_start - train_bars : test_start]
        context_start = max(0, test_start - maximum_warmup)
        test_context = candles[context_start : test_start + test_bars]
        trade_start = test_start - context_start
        train_results: dict[str, BacktestResult] = {}
        test_results: dict[str, BacktestResult] = {}
        for profile in profiles:
            strategy = ProfileStrategy(profile, config)
            train_results[profile.name] = run_backtest(
                symbol, train, config, strategy=strategy, strategy_name=profile.name, btc_candles=btc_candles
            )
            test_results[profile.name] = run_backtest(
                symbol,
                test_context,
                config,
                strategy=strategy,
                strategy_name=profile.name,
                btc_candles=btc_candles,
                trade_start_index=trade_start,
            )

        ranked_test = sorted(test_results, key=lambda name: _research_score(test_results[name]), reverse=True)
        if initial_winner is None:
            initial_winner = max(train_results, key=lambda name: _research_score(train_results[name]))
        for profile in profiles:
            result = test_results[profile.name]
            test_scores[profile.name].append(_research_score(result))
            fixed_trade_returns[profile.name].extend(
                _trade_returns(result, config.paper.initial_cash_usdt)
            )
            fixed_folds[profile.name].append({
                "number": len(adaptive_folds) + 1,
                "strategy": profile.name,
                "test_rank": ranked_test.index(profile.name) + 1,
                "test_return_pct": round(result.return_pct, 4),
                "test_benchmark_pct": round(result.benchmark_return_pct, 4),
                "test_sharpe": round(_finite(result.sharpe_ratio), 4),
                "test_drawdown_pct": round(result.max_drawdown_pct, 4),
                "test_trades": result.trades,
                "start_at": _iso_ms(test_context[trade_start].open_time),
                "end_at": _iso_ms(test_context[-1].close_time),
                "market_regime": _market_regime(result.benchmark_return_pct),
            })

        selected_name = max(train_results, key=lambda name: _research_score(train_results[name]))
        training_winner = train_results[selected_name]
        cash_gate = training_winner.return_pct <= 0 or training_winner.sharpe_ratio <= 0 or training_winner.trades < 3
        benchmark_result = test_results[selected_name]
        if cash_gate:
            selection_counts["CASH"] += 1
            adaptive = {
                "selected_strategy": "CASH",
                "test_rank": None,
                "test_return_pct": 0.0,
                "test_sharpe": 0.0,
                "test_drawdown_pct": 0.0,
                "test_trades": 0,
            }
        else:
            selected = test_results[selected_name]
            selection_counts[selected_name] += 1
            active_selections += 1
            test_rank = ranked_test.index(selected_name) + 1
            if test_rank > math.ceil(len(profiles) / 2):
                overfit_selections += 1
            adaptive_trade_returns.extend(
                _trade_returns(selected, config.paper.initial_cash_usdt)
            )
            adaptive = {
                "selected_strategy": selected_name,
                "test_rank": test_rank,
                "test_return_pct": round(selected.return_pct, 4),
                "test_sharpe": round(_finite(selected.sharpe_ratio), 4),
                "test_drawdown_pct": round(selected.max_drawdown_pct, 4),
                "test_trades": selected.trades,
            }
        adaptive_folds.append({
            "number": len(adaptive_folds) + 1,
            **adaptive,
            "cash_gate_used": cash_gate,
            "test_benchmark_pct": round(benchmark_result.benchmark_return_pct, 4),
            "start_at": _iso_ms(test_context[trade_start].open_time),
            "end_at": _iso_ms(test_context[-1].close_time),
            "market_regime": _market_regime(benchmark_result.benchmark_return_pct),
        })

    champion_name = initial_winner
    champion_profile = next(profile for profile in profiles if profile.name == champion_name)

    def aggregate(details: list[dict], trade_returns: list[float], *, overfit_rate: float) -> dict:
        compounded = math.prod(1.0 + fold["test_return_pct"] / 100.0 for fold in details) - 1.0
        benchmark = math.prod(1.0 + fold["test_benchmark_pct"] / 100.0 for fold in details) - 1.0
        return {
            "train_bars": train_bars,
            "test_bars": test_bars,
            "folds": len(details),
            "oos_compounded_return_pct": round(compounded * 100.0, 4),
            "oos_benchmark_return_pct": round(benchmark * 100.0, 4),
            "cash_return_pct": 0.0,
            "positive_folds_pct": round(
                sum(fold["test_return_pct"] > 0 for fold in details) / len(details) * 100.0, 4
            ) if details else 0.0,
            "mean_fold_sharpe": round(statistics.fmean(
                fold["test_sharpe"] for fold in details
            ), 4) if details else 0.0,
            "worst_fold_drawdown_pct": round(max(
                (fold["test_drawdown_pct"] for fold in details), default=0.0
            ), 4),
            "trades": sum(fold["test_trades"] for fold in details),
            "selection_overfit_rate_pct": round(overfit_rate, 4),
            "monte_carlo": monte_carlo(trade_returns, seed=sum(map(ord, symbol)) + 606),
            "details": details,
        }

    fixed_details = fixed_folds[champion_name]
    fixed_overfit_rate = sum(
        fold["test_rank"] > math.ceil(len(profiles) / 2) for fold in fixed_details
    ) / len(fixed_details) * 100.0 if fixed_details else 100.0
    fixed_metrics = aggregate(fixed_details, fixed_trade_returns[champion_name], overfit_rate=fixed_overfit_rate)
    adaptive_overfit_rate = overfit_selections / active_selections * 100.0 if active_selections else 0.0
    adaptive_metrics = aggregate(adaptive_folds, adaptive_trade_returns, overfit_rate=adaptive_overfit_rate)
    adaptive_metrics["cash_folds"] = selection_counts["CASH"]
    adaptive_metrics["strategy_folds"] = active_selections
    adaptive_metrics["selection_counts"] = selection_counts

    candidates = []
    champion_summary: dict | None = None
    for profile in profiles:
        full = run_backtest(
            symbol,
            candles,
            config,
            strategy=ProfileStrategy(profile, config),
            strategy_name=profile.name,
            btc_candles=btc_candles,
        )
        summary = _result_summary(full)
        summary["family"] = profile.family
        summary["mean_oos_score"] = round(statistics.fmean(test_scores[profile.name]), 4)
        development_folds = fixed_folds[profile.name]
        summary["development_oos_return_pct"] = round(
            100.0 * (math.prod(1.0 + fold["test_return_pct"] / 100.0
                               for fold in development_folds) - 1.0), 4)
        summary["development_oos_trades"] = sum(fold["test_trades"] for fold in development_folds)
        summary["development_positive_folds_pct"] = round(
            100.0 * sum(fold["test_return_pct"] > 0 for fold in development_folds)
            / len(development_folds), 2) if development_folds else 0.0
        summary["selected_folds"] = selection_counts[profile.name]
        candidates.append(summary)
        if profile.name == champion_name:
            champion_summary = summary
    candidates.sort(key=lambda row: row["mean_oos_score"], reverse=True)

    sensitivity = []
    for score_delta in (-5, 0, 5):
        adjusted = replace(
            champion_profile,
            name=f"{champion_name}_{score_delta:+d}",
            settings=replace(
                champion_profile.settings,
                minimum_score=max(50, min(90, champion_profile.settings.minimum_score + score_delta)),
            ),
        )
        if score_delta == 0:
            result_summary = champion_summary or {}
        else:
            diagnostic = run_backtest(
                symbol,
                candles,
                config,
                strategy=ProfileStrategy(adjusted, config),
                strategy_name=adjusted.name,
                btc_candles=btc_candles,
            )
            result_summary = _result_summary(diagnostic)
        sensitivity.append({
            "minimum_score": adjusted.settings.minimum_score,
            "return_pct": result_summary.get("return_pct", 0.0),
            "max_drawdown_pct": result_summary.get("max_drawdown_pct", 0.0),
            "sharpe_ratio": result_summary.get("sharpe_ratio", 0.0),
            "trades": result_summary.get("trades", 0),
        })

    regime_summary = []
    for regime in ("BULLISH", "SIDEWAYS", "BEARISH"):
        regime_folds = [fold for fold in fixed_details if fold["market_regime"] == regime]
        regime_summary.append({
            "regime": regime,
            "folds": len(regime_folds),
            "average_return_pct": round(statistics.fmean(
                fold["test_return_pct"] for fold in regime_folds
            ), 4) if regime_folds else 0.0,
            "average_benchmark_pct": round(statistics.fmean(
                fold["test_benchmark_pct"] for fold in regime_folds
            ), 4) if regime_folds else 0.0,
            "positive_folds_pct": round(
                sum(fold["test_return_pct"] > 0 for fold in regime_folds) / len(regime_folds) * 100.0,
                4,
            ) if regime_folds else 0.0,
        })

    years = max(
        (candles[-1].close_time - candles[0].open_time) / (365.0 * 24 * 3600 * 1000),
        0.01,
    )
    trades_per_year = float((champion_summary or {}).get("trades", 0)) / years
    gates = {
        "positive_vs_cash": fixed_metrics["oos_compounded_return_pct"] > 0,
        "beats_asset_hold_oos": fixed_metrics["oos_compounded_return_pct"] > fixed_metrics["oos_benchmark_return_pct"],
        "mean_fold_sharpe": fixed_metrics["mean_fold_sharpe"] >= 0.25,
        "positive_folds": fixed_metrics["positive_folds_pct"] >= 60,
        "selection_stability": fixed_metrics["selection_overfit_rate_pct"] <= 40,
        "monte_carlo_loss": fixed_metrics["monte_carlo"]["loss_probability_pct"] <= 30,
        "full_sample_sharpe": float((champion_summary or {}).get("sharpe_ratio", 0)) >= 0.25,
        "parameter_stability": all(row["return_pct"] > 0 for row in sensitivity),
        "turnover_control": trades_per_year <= 80,
        "data_quality": _data_quality(candles)["passed"],
    }
    status = "PROMISING_RESEARCH_ONLY" if all(gates.values()) else "INSUFFICIENT_EVIDENCE"

    return {
        "symbol": symbol,
        "status": status,
        "champion_candidate": champion_name,
        "champion_family": champion_profile.family,
        "candidate_full_sample": champion_summary or {},
        "fixed_strategy": fixed_metrics,
        "adaptive_selector": adaptive_metrics,
        "walk_forward": fixed_metrics,
        "monte_carlo": fixed_metrics["monte_carlo"],
        "qualification": {"passed": status == "PROMISING_RESEARCH_ONLY", "gates": gates},
        "trades_per_year": round(trades_per_year, 2),
        "regime_analysis": regime_summary,
        "parameter_sensitivity": sensitivity,
        "data_quality": _data_quality(candles),
        "candidates": candidates,
    }


def research_asset(symbol, candles, btc_candles, config, *, train_bars=600, test_bars=200):
    """Reserve the final window before any development comparisons."""
    if test_bars <= 1 or train_bars <= 0:
        raise ValueError("invalid fold sizes")
    if not _data_quality(candles)["passed"] or not _data_quality(btc_candles)["passed"]:
        raise ValueError("invalid, unordered or gapped market history")
    split = len(candles) - test_bars
    development = candles[:split]
    result = _research_development(symbol, development, btc_candles, config,
                                   train_bars=train_bars, test_bars=test_bars)
    profile = next(p for p in default_profiles(config) if p.name == result["champion_candidate"])
    start = max(0, split - 250)
    context = candles[start:]
    metrics = []
    for scale in (1, 2):
        stressed = replace(config, paper=replace(config.paper,
            fee_rate=config.paper.fee_rate * scale, slippage_rate=config.paper.slippage_rate * scale))
        run = run_backtest(symbol, context, stressed, strategy=ProfileStrategy(profile, stressed),
                           strategy_name=profile.name, btc_candles=btc_candles, trade_start_index=split-start)
        metrics.append(_result_summary(run))
    result["holdout"] = {"start_at": _iso_ms(candles[split].open_time),
        "end_at": _iso_ms(candles[-1].close_time), "bars": test_bars,
        "base_costs": metrics[0], "double_costs": metrics[1],
        "warning": "Repeated inspection consumes this holdout; future data is needed after tuning."}
    gates = result["qualification"]["gates"]
    gates["holdout_positive"] = metrics[0]["return_pct"] > 0 and metrics[0]["trades"] >= 3
    gates["holdout_beats_asset_hold"] = metrics[0]["return_pct"] > metrics[0]["benchmark_return_pct"]
    gates["holdout_cost_stress"] = metrics[1]["return_pct"] > 0
    gates["minimum_oos_evidence"] = result["fixed_strategy"]["folds"] >= 3 and result["fixed_strategy"]["trades"] >= 20
    result["qualification"]["passed"] = all(gates.values())
    result["status"] = "PROMISING_RESEARCH_ONLY" if all(gates.values()) else "INSUFFICIENT_EVIDENCE"
    result["selection_method"] = "fixed_candidate_selected_on_initial_training_only"
    return result


def _correlation(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or len(left) != len(right):
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_sum = sum((a - left_mean) ** 2 for a in left)
    right_sum = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_sum * right_sum)
    return numerator / denominator if denominator else 0.0


def _correlation_matrix(market_data: dict[str, list[Candle]]) -> dict:
    return_maps: dict[str, dict[int, float]] = {}
    for symbol, candles in market_data.items():
        return_maps[symbol] = {
            candles[index].close_time: candles[index].close / candles[index - 1].close - 1.0
            for index in range(1, len(candles))
            if candles[index - 1].close > 0
        }
    matrix: dict[str, dict[str, float]] = {}
    for left_symbol, left_returns in return_maps.items():
        matrix[left_symbol] = {}
        for right_symbol, right_returns in return_maps.items():
            common = sorted(set(left_returns) & set(right_returns))
            value = _correlation(
                [left_returns[timestamp] for timestamp in common],
                [right_returns[timestamp] for timestamp in common],
            )
            matrix[left_symbol][right_symbol] = round(value, 4)
    return matrix


def _portfolio_summary(assets: list[dict], test_bars: int, interval: str, section: str) -> dict:
    if not assets:
        return {}
    windows = [{(f["start_at"], f["end_at"]): f for f in a[section]["details"]} for a in assets]
    common = sorted(set.intersection(*(set(w) for w in windows)))
    fold_count = len(common)
    returns: list[float] = []
    benchmarks: list[float] = []
    for key in common:
        returns.append(statistics.fmean(
            window[key]["test_return_pct"] for window in windows
        ))
        benchmarks.append(statistics.fmean(
            window[key]["test_benchmark_pct"] for window in windows
        ))
    equity = [1.0]
    for value in returns:
        equity.append(equity[-1] * (1.0 + value / 100.0))
    compounded = (equity[-1] - 1.0) * 100.0
    benchmark = (math.prod(1.0 + value / 100.0 for value in benchmarks) - 1.0) * 100.0
    volatility = statistics.stdev(value / 100.0 for value in returns) if len(returns) > 1 else 0.0
    mean_return = statistics.fmean(value / 100.0 for value in returns) if returns else 0.0
    interval_hours = {"1h": 1, "2h": 2, "4h": 4, "6h": 6, "8h": 8, "12h": 12, "1d": 24}.get(interval, 24)
    folds_per_year = 365.0 * 24.0 / (test_bars * interval_hours)
    sharpe = mean_return / volatility * math.sqrt(folds_per_year) if volatility else 0.0
    return {
        "method": f"equal_weight_{section}_fold_returns",
        "limitation": "Aligned fold allocation illustration; not a joint execution backtest; drawdown uses fold endpoints only.",
        "assets": len(assets),
        "folds": fold_count,
        "oos_compounded_return_pct": round(compounded, 4),
        "oos_benchmark_return_pct": round(benchmark, 4),
        "cash_return_pct": 0.0,
        "max_drawdown_pct": round(-max_drawdown(equity) * 100.0, 4),
        "fold_sharpe_ratio": round(_finite(sharpe), 4),
        "positive_folds_pct": round(sum(value > 0 for value in returns) / len(returns) * 100.0, 4) if returns else 0.0,
    }


def build_research_report(
    market_data: dict[str, list[Candle]],
    config: AppConfig,
    *,
    train_bars: int = 600,
    test_bars: int = 200,
) -> dict:
    btc = market_data.get("BTCUSDT")
    if not btc:
        raise ValueError("BTCUSDT history is required for regime controls")
    assets = [
        research_asset(symbol, candles, btc, config, train_bars=train_bars, test_bars=test_bars)
        for symbol, candles in market_data.items()
    ]
    portfolio = _portfolio_summary(assets, test_bars, config.bot.timeframe, "fixed_strategy")
    adaptive_portfolio = _portfolio_summary(assets, test_bars, config.bot.timeframe, "adaptive_selector")
    return {
        "version": "0.6.2",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "RESEARCH_ONLY",
        "auto_promotion": False,
        "methodology": {
            "execution": "next_bar_open",
            "intrabar_conflict": "stop_first_conservative",
            "costs": "fees_plus_slippage",
            "validation": "initial_train_fixed_selection_rolling_walk_forward_reserved_final_holdout",
            "overfit_metric": "out_of_sample_selection_rank_heuristic",
            "monte_carlo_simulations": 1_000,
            "cash_hurdle": "zero_percent_usdt",
            "adaptive_cash_gate": "positive_train_return_sharpe_and_minimum_trades",
        },
        "summary": {
            "assets": len(assets),
            "strategies_per_asset": len(default_profiles(config)),
            "promising_assets": sum(asset["status"] == "PROMISING_RESEARCH_ONLY" for asset in assets),
            "total_walk_forward_folds": sum(asset["walk_forward"]["folds"] for asset in assets),
        },
        "portfolio": portfolio,
        "adaptive_portfolio": adaptive_portfolio,
        "correlations": _correlation_matrix(market_data),
        "assets": assets,
    }


def save_research_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def execute_research(
    config: AppConfig,
    *,
    symbols: tuple[str, ...] | list[str] | None = None,
    history_candles: int | None = None,
    train_bars: int | None = None,
    test_bars: int | None = None,
) -> dict:
    """Download closed market history and produce a research-only report."""
    from .exchange import BinanceClient

    selected = tuple(dict.fromkeys(symbol.upper() for symbol in (symbols or config.research.symbols)))
    if "BTCUSDT" not in selected:
        selected = ("BTCUSDT", *selected)
    limit = history_candles or config.research.history_candles
    exchange = BinanceClient()
    market_data = {
        symbol: exchange.historical_candles(symbol, config.bot.timeframe, limit)
        for symbol in selected
    }
    report = build_research_report(
        market_data,
        config,
        train_bars=train_bars or config.research.train_bars,
        test_bars=test_bars or config.research.test_bars,
    )
    save_research_report(report, config.research.report_path)
    return report


def report_without_trades(result: BacktestResult) -> dict:
    payload = asdict(result)
    payload.pop("trade_records", None)
    return payload
