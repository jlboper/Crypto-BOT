"""Preregistered portfolio experiments on separate development and final windows."""
from __future__ import annotations

from bisect import bisect_right
import math

from .research_portfolio import Intent, futures_intents, scenarios, simulate
from .research_runtime import progress


def aligned(data):
    if not data:
        return {}
    common = set.intersection(*(set(c.open_time for c in rows) for rows in data.values()))
    return {s: [c for c in rows if c.open_time in common] for s, rows in data.items()}


def portfolio_runs(data, signals, config, train, test, market, *, marks=None, funding=None):
    if not data:
        return []
    rows = next(iter(data.values()))
    if len(rows) < train+2*test:
        raise ValueError('Insufficient aligned portfolio history')
    development_end = len(rows)-test
    results = []
    for scenario in scenarios(market):
        kwargs = dict(initial_cash=config.paper.initial_cash_usdt, fee=config.paper.fee_rate,
                      slippage=config.paper.slippage_rate, market=market, marks=marks, funding=funding)
        run = simulate(data, signals, scenario, start=rows[train].open_time,
                       end=rows[development_end-1].open_time, **kwargs)
        holdout = simulate(data, signals, scenario, start=rows[development_end].open_time,
                           end=rows[-1].open_time, **kwargs)
        kwargs.update(fee=config.paper.fee_rate*2, slippage=config.paper.slippage_rate*2)
        stress = simulate(data, signals, scenario, start=rows[development_end].open_time,
                          end=rows[-1].open_time, **kwargs)
        run.update(holdout=holdout, double_cost_holdout=stress, selection='INITIAL_TRAINING_ONLY',
                   start_at=rows[train].open_time, end_at=rows[development_end-1].close_time,
                   holdout_start_at=rows[development_end].open_time,
                   discarded_reasons=[name for name, failed in (
                       ('Retorno neto OOS no positivo', run['net_return_pct'] <= 0),
                       ('Menos de 20 cierres OOS', run['closed_trades'] < 20),
                       ('Drawdown OOS superior al 20%', run['max_drawdown_pct'] > 20),
                       ('Ventana final no positiva', holdout['net_return_pct'] <= 0),
                       ('Costos duplicados no positivos', stress['net_return_pct'] <= 0),
                       ('Liquidación en el modelo de estrés', run['liquidations']+holdout['liquidations'] > 0),
                       ('Falta forward test independiente', True),
                   ) if failed], evidence='RESEARCH_ONLY')
        results.append(run)
    return results


def spot_signals(data, assets, config):
    from .research import ProfileStrategy, default_profiles
    btc = data['BTCUSDT']
    btc_times = [c.close_time for c in btc]
    profiles = {p.name: p for p in default_profiles(config)}
    signals = {}
    for asset in assets:
        symbol = asset['symbol']
        progress(config.research.report_path, f'Cartera Spot: señales {symbol}')
        strategy = ProfileStrategy(profiles[asset['champion_candidate']], config)
        rows = data[symbol]
        signals[symbol] = {}
        for index in range(max(105, strategy.minimum_history), len(rows)):
            candle = rows[index]
            btc_index = bisect_right(btc_times, candle.close_time)-1
            bullish = strategy.btc_regime(btc[max(0, btc_index-249):btc_index+1]) if btc_index >= strategy.minimum_history else False
            signal = strategy.evaluate(symbol, rows[max(0, index-249):index+1], bullish)
            if signal.action == 'BUY' and signal.stop_price and signal.take_profit:
                distance = signal.price-signal.stop_price
                if distance > 0:
                    signals[symbol][candle.close_time] = Intent(1, distance,
                        (signal.take_profit-signal.price)/distance, signal.score)
    return signals


def spot_portfolios(data, assets, config, train, test):
    return portfolio_runs(data, spot_signals(data, assets, config), config, train, test, 'SPOT')


def futures_research(data, marks, funding, config, train, test):
    rows = next(iter(data.values())) if data else []
    if len(rows) < train+2*test:
        return [], [], {}
    base = next(s for s in scenarios('FUTURES') if s.name == 'base' and s.leverage == 1)
    assets, chosen, all_models = [], {}, {}
    for symbol, candles in data.items():
        progress(config.research.report_path, f'Futures: cinco modelos {symbol}')
        models = futures_intents(candles)
        all_models[symbol] = models
        training = []
        kwargs = dict(initial_cash=config.paper.initial_cash_usdt, fee=config.paper.fee_rate,
                      slippage=config.paper.slippage_rate, market='FUTURES', marks={symbol: marks[symbol]},
                      funding={symbol: funding[symbol]})
        for name, signals in models.items():
            result = simulate({symbol: candles}, {symbol: signals}, base,
                              start=candles[105].open_time, end=candles[train-1].open_time, **kwargs)
            training.append((result['net_return_pct']-result['max_drawdown_pct'], name))
        winner = max(training)[1]  # Deterministic ties; no OOS/holdout selection.
        chosen[symbol] = models[winner]
        windows = []
        for index in range(train, len(candles)-test, test):
            stop = min(index+test, len(candles)-test)
            result = simulate({symbol: candles}, {symbol: chosen[symbol]}, base,
                              start=candles[index].open_time, end=candles[stop-1].open_time, **kwargs)
            windows.append({k: result[k] for k in ('net_return_pct', 'closed_trades', 'max_drawdown_pct')})
        holdout = simulate({symbol: candles}, {symbol: chosen[symbol]}, base,
                          start=candles[-test].open_time, end=candles[-1].open_time, **kwargs)
        kwargs.update(fee=config.paper.fee_rate*2, slippage=config.paper.slippage_rate*2)
        stress = simulate({symbol: candles}, {symbol: chosen[symbol]}, base,
                         start=candles[-test].open_time, end=candles[-1].open_time, **kwargs)
        for result in (holdout, stress):
            result.pop('trades', None)
            result.pop('curve', None)
        gates = {'positive_oos': sum(w['net_return_pct'] for w in windows) > 0,
                 'minimum_evidence': len(windows) >= 3 and sum(w['closed_trades'] for w in windows) >= 20,
                 'consistent_folds': sum(w['net_return_pct'] > 0 for w in windows)/len(windows) >= .6,
                 'holdout_positive': holdout['net_return_pct'] > 0,
                 'double_costs_positive': stress['net_return_pct'] > 0,
                 'forward_test_independent': False, 'contract_liquidation_calibration': False}
        assets.append({'symbol': symbol, 'market': 'FUTURES', 'champion_candidate': winner,
                       'selection': 'INITIAL_TRAINING_ONLY', 'models': list(models),
                       'folds': windows, 'holdout': holdout, 'double_cost_holdout': stress,
                       'gates': gates, 'discarded_reasons': [k for k, v in gates.items() if not v],
                       'status': 'RESEARCH_ONLY', 'automatic_promotion': False,
                       'oos_return_pct': (math.prod(1+w['net_return_pct']/100 for w in windows)-1)*100})
    return assets, portfolio_runs(data, chosen, config, train, test, 'FUTURES', marks=marks, funding=funding), all_models


def forward_observation(report, spot, futures, marks, funding, models, config):
    """Freeze a small cohort once; subsequent closed bars were unseen at registration.

    Replaying the frozen rules on incoming public bars is PAPER observation, not
    Demo fills. No ranking, retuning, automatic promotion or capital movement.
    """
    import hashlib
    import json
    from dataclasses import asdict
    from datetime import UTC, datetime
    from .research_runtime import atomic, read
    path = config.research.report_path.parent/'forward-baseline.json'
    fingerprint = hashlib.sha256(json.dumps({'strategy': asdict(config.strategy),
        'risk': asdict(config.risk), 'paper': asdict(config.paper), 'timeframe': config.bot.timeframe,
        'method': '0.10.20-frozen-forward'}, sort_keys=True).encode()).hexdigest()
    baseline = read(path)
    previous = baseline
    if baseline.get('fingerprint') != fingerprint:
        baseline = {'fingerprint': fingerprint, 'registered_at': datetime.now(UTC).isoformat(),
            'spot': {a['symbol']: a['champion_candidate'] for a in report['assets'][:5]},
            'futures': {a['symbol']: a['champion_candidate'] for a in report['futures_assets']},
            'start_after': {'SPOT': int(datetime.now(UTC).timestamp()*1000), 'FUTURES': int(datetime.now(UTC).timestamp()*1000)}}
        # Retain old registrations instead of silently replacing their evidence.
        if path.is_file():
            atomic(path.parent/'forward-cohorts'/f"{previous['fingerprint']}-{previous['start_after']['SPOT']}.json", previous)
        atomic(path, baseline)
    result = []
    for market, data in (('SPOT', spot), ('FUTURES', futures)):
        frozen = baseline['spot' if market == 'SPOT' else 'futures']
        if not frozen and data:
            frozen = {a['symbol']: a['champion_candidate'] for a in (report['assets'][:5] if market == 'SPOT' else report['futures_assets'])}
            baseline['spot' if market == 'SPOT' else 'futures'] = frozen
            baseline['start_after'][market] = int(datetime.now(UTC).timestamp()*1000)
            atomic(path, baseline)
        missing = [s for s in frozen if s not in data]
        item = {'market': market, 'stage': 'OBSERVATION_ONLY', 'registered_at': baseline['registered_at'],
                'model_fingerprint': fingerprint, 'symbols': list(frozen), 'automatic_promotion': False,
                'minimum_days': 30, 'minimum_closes': 30, 'observed_days': 0,
                'status': 'WAITING_NEW_DATA', 'missing_symbols': missing}
        subset = {s: data[s] for s in frozen if s in data}
        if not frozen or missing:
            item['status'] = 'DATA_UNAVAILABLE'
        elif subset:
            rows = next(iter(subset.values()))
            new = [c for c in rows if c.open_time > baseline['start_after'][market]]
            if new and rows[0].open_time > baseline['start_after'][market]+1:
                item['status'] = 'HISTORY_GAP'
            elif len(new) >= 2:
                signals = spot_signals(spot, [{'symbol':s,'champion_candidate':p} for s,p in frozen.items()], config) if market == 'SPOT' else {
                    s: models[s][p] for s,p in frozen.items()}
                scenario = next(s for s in scenarios(market) if s.name == 'base' and s.leverage == 1)
                simulation = simulate(subset, signals, scenario, initial_cash=config.paper.initial_cash_usdt,
                    fee=config.paper.fee_rate, slippage=config.paper.slippage_rate,
                    start=new[0].open_time, end=new[-1].open_time, market=market,
                    marks=marks if market == 'FUTURES' else None, funding=funding if market == 'FUTURES' else None)
                simulation['closed_trades'] = sum(t['reason'] != 'END_WINDOW' for t in simulation['trades'])
                simulation['terminal_valuation'] = 'net of hypothetical final exit; forced exit excluded from close count'
                simulation.pop('trades', None)
                item.update(status='OBSERVING', observed_days=(new[-1].close_time-new[0].open_time)/86400000,
                            simulation=simulation, last_closed_at=new[-1].close_time)
        result.append(item)
    return result
