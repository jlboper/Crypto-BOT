"""Pure exploratory Quant Shadow diagnostics; no transport or account execution.

Timestamps are seconds in UTC. Values must have been received by decision time.
Initial thresholds are preregistered conservative hypotheses, not fitted optima.
Statistical diagnostics deliberately cannot authorize even a hypothetical entry
until their calibration and an independent research protocol are reviewed.
"""
from __future__ import annotations

import math
from statistics import fmean, pstdev


SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
HYPOTHESIS_ID = 'QUANT_SHADOW_V1'
MAX_HISTORY = 1440
DEFAULT_ASSUMPTIONS = {
    'notional_usdt': 28.4,
    'spot_fee_rate': .001,
    'futures_fee_rate': .001,
    'slippage_rate': .001,
    'max_quote_age_seconds': 90.0,
    'max_leg_time_skew_seconds': 5.0,
    'max_spread_bps': 20.0,
    'min_depth_multiple': 10.0,
    'funding_horizon_seconds': 86400.0,
    'min_funding_events': 8,
    'min_capture_seconds': 60.0,
    'funding_haircut': .5,
    'max_abs_funding_rate': .02,
    'max_abs_basis_rate': .01,
    'basis_stress_rate': .01,
    'basis_cost_reserve_rate': .001,
    'legging_stress_rate': .02,
    'available_virtual_usdt': None,
    'risk_budget_usdt': None,
    'symbol_a': 'BTCUSDT',
    'symbol_b': 'ETHUSDT',
    'sample_seconds': 60.0,
    'min_pair_observations': 360,
    'pair_entry_z': 2.0,
    'pair_reject_z': 4.0,
    'max_hedge_drift_fraction': .25,
    'max_holdout_mean_sigma': 1.5,
    'max_holdout_sigma_ratio': 2.5,
    'min_holdout_sigma_ratio': .4,
    'min_return_correlation': .4,
    'max_correlation_shift': .4,
    'max_return_volatility': .02,
    'residual_adf_screen': -4.0,
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
        return converted if math.isfinite(converted) else None
    except (OverflowError, ValueError):
        return None


def _rounded(value):
    value = _number(value)
    return round(value, 10) if value is not None else None


def _settings(assumptions):
    if assumptions is not None and not isinstance(assumptions, dict):
        return None
    result = dict(DEFAULT_ASSUMPTIONS)
    result.update({k: v for k, v in (assumptions or {}).items() if k in result})
    for key, default in DEFAULT_ASSUMPTIONS.items():
        if default is None:
            if result[key] is not None and (_number(result[key]) is None or result[key] < 0):
                return None
        elif isinstance(default, str):
            if result[key] not in SYMBOLS:
                return None
        elif _number(result[key]) is None:
            return None
    for key in ('notional_usdt', 'max_quote_age_seconds', 'max_leg_time_skew_seconds',
                'max_spread_bps', 'min_depth_multiple', 'sample_seconds',
                'max_hedge_drift_fraction', 'max_holdout_mean_sigma',
                'max_holdout_sigma_ratio', 'min_holdout_sigma_ratio',
                'max_correlation_shift', 'max_return_volatility'):
        if result[key] <= 0:
            return None
    if (not 0 <= result['spot_fee_rate'] <= .02
            or not 0 <= result['futures_fee_rate'] <= .02
            or not 0 <= result['slippage_rate'] <= .02
            or not 0 < result['funding_haircut'] <= .5
            or not 3600 <= result['funding_horizon_seconds'] <= 86400
            or not 8 <= result['min_funding_events'] <= 64
            or int(result['min_funding_events']) != result['min_funding_events']
            or not 30 <= result['min_capture_seconds'] <= 3600
            or not 0 < result['max_abs_funding_rate'] <= .02
            or not 0 < result['max_abs_basis_rate'] <= .02
            or not .001 <= result['basis_cost_reserve_rate'] <= .05
            or not .005 <= result['basis_stress_rate'] <= .2
            or not .01 <= result['legging_stress_rate'] <= .2
            or not 360 <= result['min_pair_observations'] <= MAX_HISTORY
            or int(result['min_pair_observations']) != result['min_pair_observations']
            or not 1.5 <= result['pair_entry_z'] < result['pair_reject_z'] <= 6
            or not -1 <= result['min_return_correlation'] <= 1
            or not -10 <= result['residual_adf_screen'] <= -4):
        return None
    return result


def _result(strategy, now, decision, reason, *, metrics=None, evidence=None, legs=None, reasons=None):
    return {
        'strategy': strategy, 'decision': decision, 'reason': reason,
        'reasons': list(dict.fromkeys(reasons or [reason]))[:12],
        'at': _rounded(now), 'mode': 'SHADOW', 'execution_enabled': False,
        'metrics': {k: _rounded(v) for k, v in (metrics or {}).items()},
        'legs': (legs or [])[:2],
        'evidence': {
            'cutoff_at': _rounded(now), 'hypothesis_id': HYPOTHESIS_ID,
            'qualification': 'EXPLORATORY_SCREEN_ONLY', **(evidence or {}),
        },
    }


def _quote(row, now, settings):
    if not isinstance(row, dict) or row.get('symbol') not in SYMBOLS:
        return None, 'INVALID_QUOTE'
    fields = {k: _number(row.get(k)) for k in
              ('bid', 'ask', 'bid_depth_usdt', 'ask_depth_usdt', 'at', 'received_at')}
    if any(v is None for v in fields.values()):
        return None, 'INCOMPLETE_QUOTE'
    if (not 1e-12 <= fields['bid'] <= fields['ask'] <= 1e12
            or not 0 <= fields['bid_depth_usdt'] <= 1e15
            or not 0 <= fields['ask_depth_usdt'] <= 1e15):
        return None, 'INVALID_QUOTE'
    # Exchange clocks may lead Windows by the existing bounded five seconds.
    # Actual receipt must precede the decision and expire independently; this
    # tolerance never makes a later API response available to an earlier replay.
    if (not 0 < fields['at'] <= fields['received_at']+5
            or not 0 < fields['received_at'] <= now or fields['at'] > now+5):
        return None, 'QUOTE_NOT_AVAILABLE_AT_DECISION'
    if (now-fields['at'] > settings['max_quote_age_seconds']
            or now-fields['received_at'] > settings['max_quote_age_seconds']):
        return None, 'STALE_QUOTE'
    fields['symbol'] = row['symbol']
    fields['mid'] = (fields['ask']+fields['bid'])/2
    fields['spread_rate'] = (fields['ask']-fields['bid'])/fields['mid']
    if fields['spread_rate']*10000 > settings['max_spread_bps']:
        return None, 'WIDE_SPREAD'
    return fields, None


def funding_signal(spot, futures, funding_history, now, assumptions=None):
    """Conditional positive-funding Spot LONG/Futures SHORT Shadow proposal.

    ``lastFundingRate`` belongs in observed_funding_rate, never settled income.
    Historical records are facts available at received_at; future payment remains
    an explicitly haircutted scenario. A caller's independent ledger alone books
    subsequent authoritative funding events while both legs were already held.
    """
    strategy = 'FUNDING_CARRY'
    settings = _settings(assumptions)
    if _number(now) is None or now <= 0 or settings is None:
        return _result(strategy, now, 'REJECT', 'INVALID_ASSUMPTIONS')
    spot_quote, error = _quote(spot, now, settings)
    if error:
        return _result(strategy, now, 'REJECT', error)
    futures_quote, error = _quote(futures, now, settings)
    if error:
        return _result(strategy, now, 'REJECT', error)
    if spot_quote['symbol'] != futures_quote['symbol']:
        return _result(strategy, now, 'REJECT', 'SYMBOL_MISMATCH')
    if abs(spot_quote['at']-futures_quote['at']) > settings['max_leg_time_skew_seconds']:
        return _result(strategy, now, 'REJECT', 'UNALIGNED_LEG_TIMES')
    values = {key: _number(futures.get(key)) for key in
              ('mark_price', 'observed_funding_rate', 'next_funding_at', 'funding_interval_seconds')}
    if any(value is None for value in values.values()) or values['mark_price'] <= 0:
        return _result(strategy, now, 'WAIT', 'FUNDING_METADATA_UNAVAILABLE')
    interval = values['funding_interval_seconds']
    if interval not in (3600, 7200, 14400, 28800):
        return _result(strategy, now, 'WAIT', 'FUNDING_INTERVAL_UNVERIFIED')
    observed = values['observed_funding_rate']
    metrics = {
        'observed_funding_rate': observed, 'funding_interval_seconds': interval,
        'next_funding_at': values['next_funding_at'], 'spot_mid': spot_quote['mid'],
        'futures_mid': futures_quote['mid'], 'mark_price': values['mark_price'],
        'basis_rate': futures_quote['mid']/spot_quote['mid']-1,
        'spot_spread_bps': spot_quote['spread_rate']*10000,
        'futures_spread_bps': futures_quote['spread_rate']*10000,
        'projected_funding_usdt': None, 'conditional_net_estimate_usdt': None,
        'settled_funding_usdt': None,
    }
    evidence = {'latest_received_at': max(spot_quote['received_at'], futures_quote['received_at']),
                'observation_count': 0, 'funding_income_kind': 'CONDITIONAL_PROJECTION_NOT_SETTLED',
                'hedge_execution': 'NON_ATOMIC_SIMULATION',
                'margin_kind': 'VIRTUAL_FULLY_COLLATERALIZED_1X'}
    def finish(decision, reason, *, legs=None):
        return _result(strategy, now, decision, reason, metrics=metrics, evidence=evidence, legs=legs)
    if not 0 < observed <= settings['max_abs_funding_rate']:
        return finish('REJECT', 'NONPOSITIVE_OR_EXTREME_FUNDING')
    if not settings['min_capture_seconds'] <= values['next_funding_at']-now <= interval:
        return finish('WAIT', 'FUNDING_TIME_NOT_CAPTUREABLE')
    if abs(metrics['basis_rate']) > settings['max_abs_basis_rate']:
        return finish('REJECT', 'EXCESSIVE_BASIS')
    if abs(values['mark_price']/futures_quote['mid']-1) > settings['max_abs_basis_rate']:
        return finish('REJECT', 'MARK_BOOK_DIVERGENCE')
    if not isinstance(funding_history, (list, tuple)) or len(funding_history) > 256:
        return finish('REJECT', 'INVALID_FUNDING_HISTORY')
    history = {}
    for row in funding_history:
        if not isinstance(row, dict):
            return finish('REJECT', 'INVALID_FUNDING_HISTORY')
        record = {key: _number(row.get(key)) for key in ('at', 'received_at', 'rate', 'mark_price')}
        if any(value is None for value in record.values()):
            return finish('REJECT', 'INVALID_FUNDING_HISTORY')
        # Supplied later information is excluded, never silently used in replay.
        if record['at'] > now or record['received_at'] > now:
            continue
        if (not 0 < record['at'] <= record['received_at'] or record['mark_price'] <= 0
                or abs(record['rate']) > settings['max_abs_funding_rate']):
            return finish('REJECT', 'INVALID_FUNDING_HISTORY')
        previous = history.get(record['at'])
        if previous and (previous['rate'], previous['mark_price']) != (record['rate'], record['mark_price']):
            return finish('REJECT', 'CONFLICTING_FUNDING_EVENT')
        if previous is None or record['received_at'] < previous['received_at']:
            history[record['at']] = record
    rows = sorted(history.values(), key=lambda row: row['at'])[-64:]
    evidence['observation_count'] = len(rows)
    evidence['history_last_at'] = rows[-1]['at'] if rows else None
    if len(rows) < settings['min_funding_events']:
        return finish('WAIT', 'COLLECTING_FUNDING_HISTORY')
    rows = rows[-int(settings['min_funding_events']):]
    evidence['latest_received_at'] = max(evidence['latest_received_at'], max(row['received_at'] for row in rows))
    if now-rows[-1]['at'] > 1.5*interval or any(
            not .5*interval <= b['at']-a['at'] <= 1.5*interval for a, b in zip(rows, rows[1:])):
        return finish('WAIT', 'FUNDING_HISTORY_GAPPED_OR_INTERVAL_CHANGED')
    rates = [row['rate'] for row in rows]
    metrics.update({'history_mean_funding_rate': fmean(rates),
                    'history_min_funding_rate': min(rates),
                    'history_funding_std': pstdev(rates)})
    if min(rates) <= 0:
        return finish('REJECT', 'ADVERSE_FUNDING_IN_HISTORY')
    conservative_rate = min(observed, min(rates))*settings['funding_haircut']
    expected_events = min(24, 1+int((now+settings['funding_horizon_seconds']-values['next_funding_at'])//interval))
    if expected_events <= 0:
        return finish('WAIT', 'FUNDING_OUTSIDE_HORIZON')
    notional = settings['notional_usdt']
    quantity = notional/spot_quote['mid']
    futures_notional = quantity*futures_quote['mid']
    for quote, required in ((spot_quote, notional), (futures_quote, futures_notional)):
        if min(quote['bid_depth_usdt'], quote['ask_depth_usdt']) < required*settings['min_depth_multiple']:
            return finish('REJECT', 'INSUFFICIENT_TWO_SIDED_LIQUIDITY')
    # Every leg pays entry and exit fees/slippage and an entire observed spread.
    roundtrip_cost = (
        notional*(2*settings['spot_fee_rate']+2*settings['slippage_rate']+spot_quote['spread_rate'])
        + futures_notional*(2*settings['futures_fee_rate']+2*settings['slippage_rate']+futures_quote['spread_rate']))
    basis_reserve = notional*(settings['basis_cost_reserve_rate']+abs(metrics['basis_rate']))
    projected = quantity*values['mark_price']*conservative_rate*expected_events
    conditional_net = projected-roundtrip_cost-basis_reserve
    adverse_funding = quantity*values['mark_price']*max(observed, max(rates))
    stress_loss = (roundtrip_cost+notional*(settings['basis_stress_rate']+settings['legging_stress_rate'])
                   + adverse_funding)
    required_cash = notional+futures_notional+roundtrip_cost+basis_reserve
    metrics.update({
        'quantity_per_leg': quantity, 'spot_notional_usdt': notional,
        'futures_notional_usdt': futures_notional, 'gross_notional_usdt': notional+futures_notional,
        'conditional_funding_rate': conservative_rate, 'projected_event_count': expected_events,
        'projected_funding_usdt': projected, 'roundtrip_cost_usdt': roundtrip_cost,
        'basis_cost_reserve_usdt': basis_reserve, 'conditional_net_estimate_usdt': conditional_net,
        'adverse_one_event_funding_usdt': -adverse_funding, 'estimated_stress_loss_usdt': stress_loss,
        'required_virtual_cash_usdt': required_cash,
        'virtual_collateral_usdt': futures_notional, 'leverage': 1.0,
    })
    evidence['qualification'] = 'CONSERVATIVE_FORWARD_HYPOTHESIS_NOT_VALIDATED_EDGE'
    if settings['available_virtual_usdt'] is None or settings['risk_budget_usdt'] is None:
        return finish('WAIT', 'VIRTUAL_CAPITAL_OR_RISK_UNKNOWN')
    if required_cash > settings['available_virtual_usdt']:
        return finish('REJECT', 'INSUFFICIENT_VIRTUAL_COLLATERAL')
    if stress_loss > settings['risk_budget_usdt']:
        return finish('REJECT', 'ESTIMATED_STRESS_EXCEEDS_BUDGET')
    if conditional_net <= 0:
        return finish('REJECT', 'PROJECTED_CARRY_BELOW_ALL_COSTS')
    return finish('OPEN_SHADOW', 'CONDITIONAL_CARRY_AFTER_COSTS', legs=[
        {'symbol': spot_quote['symbol'], 'venue': 'SPOT_REFERENCE', 'direction': 'LONG', 'weight': 1.0},
        {'symbol': spot_quote['symbol'], 'venue': 'FUTURES_REFERENCE', 'direction': 'SHORT',
         'weight': _rounded(futures_notional/notional)},
    ])


def _regression(x, y):
    mean_x, mean_y = fmean(x), fmean(y)
    variance = sum((value-mean_x)**2 for value in x)
    if variance <= 1e-16:
        return None
    beta = sum((a-mean_x)*(b-mean_y) for a, b in zip(x, y))/variance
    alpha = mean_y-beta*mean_x
    return alpha, beta


def _correlation(x, y):
    if len(x) < 3 or len(x) != len(y):
        return None
    mean_x, mean_y = fmean(x), fmean(y)
    vx = sum((v-mean_x)**2 for v in x)
    vy = sum((v-mean_y)**2 for v in y)
    if min(vx, vy) <= 1e-20:
        return None
    return max(-1.0, min(1.0, sum((a-mean_x)*(b-mean_y) for a, b in zip(x, y))/math.sqrt(vx*vy)))


def _adf_residual_lag_one(values):
    """OLS delta(e_t) ~ e_(t-1) + delta(e_(t-1)), no constant, fixed lag=1.

    Returns a residual t-statistic only. It has neither an ordinary Student-t
    p-value nor ordinary single-series ADF critical values. The -4 screen is a
    deliberately conservative *heuristic*, not a calibrated cointegration test.
    """
    if len(values) < 20:
        return None
    dy = [values[i]-values[i-1] for i in range(2, len(values))]
    x = [values[i-1] for i in range(2, len(values))]
    z = [values[i-1]-values[i-2] for i in range(2, len(values))]
    # Scale columns before solving the two-dimensional normal equations.
    sx, sz = math.sqrt(sum(v*v for v in x)), math.sqrt(sum(v*v for v in z))
    if min(sx, sz) <= 1e-12:
        return None
    u, v = [a/sx for a in x], [a/sz for a in z]
    cross = sum(a*b for a, b in zip(u, v))
    determinant = 1-cross*cross
    if determinant <= 1e-10:
        return None
    uy, vy = sum(a*b for a, b in zip(u, dy)), sum(a*b for a, b in zip(v, dy))
    bu, bv = (uy-cross*vy)/determinant, (vy-cross*uy)/determinant
    residual = [y-bu*a-bv*b for y, a, b in zip(dy, u, v)]
    error_variance = sum(value*value for value in residual)/(len(dy)-2)
    if error_variance <= 1e-24:
        return None
    standard_error = math.sqrt(error_variance/determinant)
    return bu/standard_error


def statarb_signal(aligned_rows, now, assumptions=None):
    """Aligned received-time pair diagnostics with frozen train/holdout split.

    Rows: {at, received_at, prices:{BTCUSDT:..., ETHUSDT:...}}. No forward
    filling, no look-ahead, no calibration on the holdout. One pair per call.
    Statistical entries are intentionally unavailable in this initial screen.
    """
    strategy = 'STATISTICAL_ARBITRAGE'
    settings = _settings(assumptions)
    if _number(now) is None or now <= 0 or settings is None:
        return _result(strategy, now, 'REJECT', 'INVALID_ASSUMPTIONS')
    a, b = settings['symbol_a'], settings['symbol_b']
    if a == b:
        return _result(strategy, now, 'REJECT', 'IDENTICAL_ASSETS')
    evidence = {'symbol_a': a, 'symbol_b': b, 'observation_count': 0,
                'latest_received_at': None, 'statistical_method': 'LOG_OLS_FIXED_LAG1_RESIDUAL_SCREEN',
                'p_value': None, 'independent_validation': 'NOT_AVAILABLE',
                'entry_authorization': 'BLOCKED_UNTIL_RESEARCH_VALIDATION'}
    metrics = {}
    def finish(decision, reason, *, reasons=None, legs=None):
        return _result(strategy, now, decision, reason, metrics=metrics,
                       evidence=evidence, reasons=reasons, legs=legs)
    if not isinstance(aligned_rows, (list, tuple)) or len(aligned_rows) > MAX_HISTORY:
        return finish('REJECT', 'INVALID_OR_UNBOUNDED_PAIR_HISTORY')
    selected = {}
    for row in aligned_rows:
        if not isinstance(row, dict) or not isinstance(row.get('prices'), dict):
            return finish('REJECT', 'INVALID_PAIR_OBSERVATION')
        at, received = _number(row.get('at')), _number(row.get('received_at'))
        if at is None or received is None:
            return finish('REJECT', 'INVALID_PAIR_OBSERVATION')
        if at > now or received > now:
            continue
        prices = (_number(row['prices'].get(a)), _number(row['prices'].get(b)))
        if not 0 < at <= received or any(v is None or v <= 0 for v in prices):
            return finish('REJECT', 'INVALID_PAIR_OBSERVATION')
        if at in selected and selected[at]['prices'] != prices:
            return finish('REJECT', 'CONFLICTING_PAIR_OBSERVATION')
        if at not in selected or received < selected[at]['received_at']:
            selected[at] = {'at': at, 'received_at': received, 'prices': prices}
    rows = sorted(selected.values(), key=lambda row: row['at'])
    evidence['observation_count'] = len(rows)
    if rows:
        evidence['latest_received_at'] = max(row['received_at'] for row in rows)
        evidence['latest_market_at'] = rows[-1]['at']
    if len(rows) < settings['min_pair_observations']:
        return finish('WAIT', 'COLLECTING_ALIGNED_PAIR_HISTORY')
    if now-rows[-1]['at'] > settings['max_quote_age_seconds']:
        return finish('REJECT', 'STALE_PAIR_HISTORY')
    if any(abs(r2['at']-r1['at']-settings['sample_seconds']) > 1.0
           for r1, r2 in zip(rows, rows[1:])):
        return finish('REJECT', 'GAPPED_OR_IRREGULAR_PAIR_HISTORY')
    logs_a = [math.log(row['prices'][0]) for row in rows]
    logs_b = [math.log(row['prices'][1]) for row in rows]
    split = len(rows)*2//3
    train_a, train_b = logs_a[:split], logs_b[:split]
    fitted = _regression(train_b, train_a)
    if fitted is None:
        return finish('REJECT', 'DEGENERATE_TRAINING_PRICES')
    alpha, beta = fitted
    residuals = [y-alpha-beta*x for x, y in zip(logs_b, logs_a)]
    train, holdout = residuals[:split], residuals[split:]
    sigma = pstdev(train)
    if sigma <= 1e-8:
        return finish('REJECT', 'DEGENERATE_RESIDUAL_SPREAD')
    first = _regression(train_b[:split//2], train_a[:split//2])
    second = _regression(train_b[split//2:], train_a[split//2:])
    if first is None or second is None or abs(beta) <= 1e-12:
        return finish('REJECT', 'UNSTABLE_HEDGE_ESTIMATE')
    beta_drift = abs(second[1]-first[1])/abs(beta)
    z_score = (residuals[-1]-fmean(train))/sigma
    return_a = [y-x for x, y in zip(logs_a, logs_a[1:])]
    return_b = [y-x for x, y in zip(logs_b, logs_b[1:])]
    train_corr = _correlation(return_a[:split-1], return_b[:split-1])
    holdout_corr = _correlation(return_a[split:], return_b[split:])
    recent_corr = _correlation(return_a[-60:], return_b[-60:])
    fitted_ar = _regression(train[:-1], train[1:])
    phi = fitted_ar[1] if fitted_ar is not None else None
    half_life = math.log(.5)/math.log(phi) if phi is not None and 0 < phi < 1 else None
    adf = _adf_residual_lag_one(train)
    holdout_sigma_ratio = pstdev(holdout)/sigma
    drift_sigma = abs(fmean(holdout)-fmean(train))/sigma
    # Weighted gross notional pays each leg's entry+exit once. With common
    # rates the total cost per unit *gross* is two fees plus two slippages.
    fee_cost_rate = 2*(settings['futures_fee_rate']+settings['slippage_rate'])
    # Total gross notional is divided across A and beta*B; this is a scenario,
    # not a predicted return, and excludes future convergence/funding certainty.
    convergence_scenario_rate = abs(z_score)*sigma/(1+abs(beta))
    metrics.update({
        'hedge_ratio': beta, 'hedge_drift_fraction': beta_drift,
        'spread': residuals[-1], 'train_spread_mean': fmean(train),
        'train_spread_sigma': sigma, 'z_score': z_score,
        'residual_adf_lag1_t': adf, 'residual_adf_heuristic_threshold': settings['residual_adf_screen'],
        'ar1_phi': phi, 'approximate_half_life_observations': half_life,
        'holdout_mean_shift_sigma': drift_sigma, 'holdout_sigma_ratio': holdout_sigma_ratio,
        'train_return_correlation': train_corr, 'holdout_return_correlation': holdout_corr,
        'recent_return_correlation': recent_corr, 'return_volatility_a': pstdev(return_a[-120:]),
        'return_volatility_b': pstdev(return_b[-120:]),
        'roundtrip_fee_slippage_rate': fee_cost_rate,
        'convergence_scenario_rate': convergence_scenario_rate,
        'net_convergence_scenario_rate': convergence_scenario_rate-fee_cost_rate,
    })
    evidence.update({'train_observations': split, 'holdout_observations': len(holdout),
                     'train_end_at': rows[split-1]['at'], 'holdout_start_at': rows[split]['at'],
                     'train_start_at': rows[0]['at'], 'holdout_end_at': rows[-1]['at'],
                     'thresholds_kind': 'INITIAL_UNVALIDATED_HYPOTHESES',
                     'cointegration_status': 'NOT_FORMALLY_VALIDATED'})
    rejected = []
    if not .1 <= beta <= 10 or beta_drift > settings['max_hedge_drift_fraction']:
        rejected.append('HEDGE_RELATION_UNSTABLE')
    if (drift_sigma > settings['max_holdout_mean_sigma']
            or not settings['min_holdout_sigma_ratio'] <= holdout_sigma_ratio <= settings['max_holdout_sigma_ratio']):
        rejected.append('HOLDOUT_STRUCTURAL_BREAK')
    if any(c is None for c in (train_corr, holdout_corr, recent_corr)):
        rejected.append('CORRELATION_DIAGNOSTIC_UNAVAILABLE')
    elif (min(holdout_corr, recent_corr) < settings['min_return_correlation']
          or abs(holdout_corr-train_corr) > settings['max_correlation_shift']):
        rejected.append('DYNAMIC_RELATION_DIVERGED')
    if max(metrics['return_volatility_a'], metrics['return_volatility_b']) > settings['max_return_volatility']:
        rejected.append('EXCESSIVE_VOLATILITY')
    if half_life is None or half_life > len(holdout):
        rejected.append('MEAN_REVERSION_NOT_SUPPORTED')
    if adf is None or adf >= settings['residual_adf_screen']:
        rejected.append('RESIDUAL_UNIT_ROOT_SCREEN_FAILED')
    if abs(z_score) > settings['pair_reject_z']:
        rejected.append('SPREAD_DIVERGENCE_TOO_EXTREME')
    if rejected:
        return finish('REJECT', rejected[0], reasons=rejected)
    if abs(z_score) < settings['pair_entry_z']:
        return finish('WAIT', 'NO_PAIR_DISLOCATION')
    if convergence_scenario_rate <= fee_cost_rate:
        return finish('REJECT', 'CONVERGENCE_SCENARIO_BELOW_COSTS')
    return finish('WAIT', 'COINTEGRATION_NOT_INDEPENDENTLY_VALIDATED')
