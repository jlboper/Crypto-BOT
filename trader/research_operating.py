"""Configured operating signals as a reference, without simulating execution."""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from dataclasses import asdict

from .futures_strategy import evaluate_futures_signal
from .research_runtime import check_cancel
from .strategy import SwingStrategy


HISTORY_BARS = 250  # Both operating engines request this exact closed-bar context.


def operating_signal_rows(market, symbol, candles, btc, config):
    """Use the same pure signal functions and context as the operating engines.

    Quantitative eligibility does not imply an order: AI, existing positions,
    loss gates, executable prices and exchange filters are deliberately absent.
    """
    strategy = SwingStrategy(config.strategy, config.risk)
    btc_times = [c.close_time for c in btc]
    rows = []
    for index in range(HISTORY_BARS-1, len(candles)):
        if index % 64 == 0:
            check_cancel()
        context = candles[index-HISTORY_BARS+1:index+1]
        if market == 'SPOT':
            btc_index = bisect_right(btc_times, candles[index].close_time)-1
            if btc_index < HISTORY_BARS-1:
                continue
            bullish = strategy.btc_regime(btc[btc_index-HISTORY_BARS+1:btc_index+1])
            signal = strategy.evaluate(symbol, context, bullish)
            row = {key: getattr(signal, key) for key in
                   ('score', 'price', 'atr', 'rsi', 'ema_fast', 'ema_slow', 'volume_ratio')}
            row.update(direction='BUY' if signal.action == 'BUY' else None,
                       stop_price=signal.stop_price, take_profit=signal.take_profit,
                       btc_bullish=bullish)
        elif market == 'FUTURES':
            row = evaluate_futures_signal(context, config.strategy, config.futures_testnet)
        else:
            raise ValueError('Unknown operating signal market')
        rows.append(dict(row, symbol=symbol, index=index, candle_close_time=candles[index].close_time))
    return rows


def operating_baselines(spot, futures, config, train, test):
    """Persist reference configuration and signal activity, never a return claim."""
    common_gaps = ['AI_not_replayed', 'position_state_and_order_filters_not_replayed',
        'fills_fees_and_slippage_not_replayed', 'protective_and_signal_exits_not_replayed',
        'daily_weekly_loss_gates_not_replayed', 'native_protection_reconciliation_not_replayed',
        'historical_universe_selection_not_replayed']
    settings = config.futures_testnet
    futures_limits = {key: getattr(settings, key) for key in (
        'forward_max_positions', 'forward_margin_usdt', 'forward_total_notional_usdt',
        'forward_total_stop_loss_usdt', 'forward_cost_buffer_pct', 'forward_leverage',
        'forward_leverage_trials', 'forward_stop_atr_multiple', 'forward_minimum_stop_pct',
        'forward_reward_to_risk', 'margin_type', 'position_mode')}
    futures_limits.update(target_notional_before_filters_usdt=min(settings.forward_margin_usdt,
        settings.forward_total_notional_usdt/settings.forward_max_positions),
        daily_loss_limit_pct=config.risk.daily_loss_limit_pct,
        weekly_loss_limit_pct=config.risk.weekly_loss_limit_pct)
    baselines = []
    for market, data in (('SPOT', spot), ('FUTURES', futures)):
        timeframe = config.bot.timeframe if market == 'SPOT' else settings.forward_timeframe
        limits = asdict(config.risk) if market == 'SPOT' else futures_limits
        configuration = {'strategy': asdict(config.strategy), 'timeframe': timeframe,
            'minimum_score': config.strategy.minimum_score if market == 'SPOT' else settings.forward_min_score,
            'limits': limits, 'ai_review_settings': asdict(config.ai),
            'universe_size': config.bot.universe_size if market == 'SPOT' else len(settings.forward_symbols)}
        if market == 'FUTURES':
            configuration['configured_symbols'] = list(settings.forward_symbols)
        fingerprint = hashlib.sha256(json.dumps({'method': 'configured-operating-signals-v1',
            'market': market, 'configuration': configuration}, sort_keys=True).encode()).hexdigest()
        baseline = {'market': market, 'timeframe': timeframe, 'evidence': 'SIGNAL_PARITY_ONLY',
            'selection': 'CONFIGURED_OPERATING_RULES_NO_SELECTION', 'automatic_promotion': False,
            'profitability_evaluated': False, 'configuration_fingerprint': fingerprint,
            'configuration': configuration, 'history_context_bars': HISTORY_BARS,
            'signal_source': 'trader.strategy.SwingStrategy.evaluate' if market == 'SPOT' else
                             'trader.futures_strategy.evaluate_futures_signal',
            'data_source': 'Public closed market bars; not operating fills',
            'symbols': list(data), 'status': 'AVAILABLE' if data else 'DATA_UNAVAILABLE',
            'execution_gaps': common_gaps + (['trailing_stops_not_replayed'] if market == 'SPOT' else
                ['opposite_signal_exit_not_replayed', 'funding_and_liquidation_not_replayed']),
            'windows': {}, 'latest_signals': []}
        if data:
            candles = next(iter(data.values()))
            development_end = len(candles)-test
            signals = [row for symbol, rows in data.items()
                for row in operating_signal_rows(market, symbol, rows, spot.get('BTCUSDT', []), config)]
            for name, start, end in (('training', 0, train), ('development_oos', train, development_end),
                                     ('final', development_end, len(candles))):
                selected = [row for row in signals if start <= row['index'] < end]
                eligible = sum(row['direction'] is not None for row in selected)
                baseline['windows'][name] = {'start_at': candles[start].open_time,
                    'end_at': candles[end-1].close_time, 'bars_per_symbol': end-start,
                    'evaluated_symbol_bars': len(selected), 'eligible_signals': eligible,
                    'buy_signals': sum(row['direction'] == 'BUY' for row in selected),
                    'long_signals': sum(row['direction'] == 'LONG' for row in selected),
                    'short_signals': sum(row['direction'] == 'SHORT' for row in selected),
                    'hold_signals': len(selected)-eligible,
                    'eligible_rate_pct': round(100*eligible/len(selected), 6) if selected else 0.0,
                    'mean_score': round(sum(row['score'] for row in selected)/len(selected), 6) if selected else 0.0}
            baseline['latest_signals'] = [{key:value for key,value in row.items() if key != 'index'}
                for row in signals if row['index'] == len(candles)-1]
        baselines.append(baseline)
    return baselines
