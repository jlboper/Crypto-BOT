"""Read-only forward PAPER evidence; no strategy selection or trading action."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from .domain import Position
from .monitoring import position_metrics, usable_price


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (AttributeError, ValueError):
        return None


def paper_scorecard(connection, *, prices=None, prices_at=None, cycle_seconds=None, paper=None,
                    research_symbols=(), now=None, mode='paper'):
    """Summarize all recorded equity points and closed PAPER trades.

    Cash flows have no dedicated ledger, so the comparison cannot claim
    a risk-adjusted edge or LIVE readiness.
    """
    start = end = None
    first_equity = last_equity = peak = 0.0
    max_drawdown = 0.0
    points = invalid = 0
    benchmark_first = benchmark_last = None
    benchmark_count = 0
    benchmark_start = benchmark_end = None
    for row in connection.execute('''SELECT e.equity,e.created_at,b.btc_usdt FROM equity e
                                     LEFT JOIN equity_benchmark b ON b.equity_id=e.id ORDER BY e.id'''):
        value, instant = float(row[0]), _time(row[1])
        if not math.isfinite(value) or value <= 0 or instant is None or (end and instant < end):
            invalid += 1
            continue
        if start is None:
            start, first_equity, peak = instant, value, value
        end, last_equity = instant, value
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak-value)/peak)
        points += 1
        quote = row[2]
        if quote is not None and math.isfinite(float(quote)) and float(quote) > 0:
            if benchmark_first is None:
                benchmark_first, benchmark_start = (value, float(quote)), instant
            benchmark_last, benchmark_end = (value, float(quote)), instant
            benchmark_count += 1
    trades = connection.execute('''
        SELECT COUNT(*), COALESCE(SUM(realized_pnl),0),
               COALESCE(SUM(CASE WHEN realized_pnl>0 THEN 1 ELSE 0 END),0),
               COALESCE(SUM(CASE WHEN realized_pnl>0 THEN realized_pnl ELSE 0 END),0),
               COALESCE(SUM(CASE WHEN realized_pnl<0 THEN -realized_pnl ELSE 0 END),0)
        FROM trades WHERE side='SELL'
    ''').fetchone()
    fees = float(connection.execute('SELECT COALESCE(SUM(fee),0) FROM trades').fetchone()[0])
    closed = int(trades[0])
    observed_days = (end-start).total_seconds()/86400 if start and end else 0.0
    asset_rows = connection.execute('''
        SELECT symbol, COUNT(*) AS closed_trades, SUM(realized_pnl) AS net_realized_pnl_usdt,
               SUM(CASE WHEN realized_pnl>0 THEN 1 ELSE 0 END) AS wins
        FROM trades WHERE side='SELL' GROUP BY symbol
    ''').fetchall()
    by_asset = {row[0]: {
        'symbol': row[0], 'closed_trades': int(row[1]),
        'net_realized_pnl_usdt': round(float(row[2]), 4),
        'win_rate_pct': round(100 * int(row[3]) / int(row[1]), 2),
        'open_exposure_usdt': None, 'estimated_open_pnl_usdt': None,
    } for row in asset_rows}
    cursor = connection.execute('SELECT * FROM positions ORDER BY symbol')
    columns = [column[0] for column in cursor.description]
    open_rows = [dict(zip(columns, row)) for row in cursor]
    current = now or datetime.now(UTC)
    quote_time = _time(prices_at)
    open_pnl = open_exposure = 0.0
    missing_quotes = []
    for raw in open_rows:
        position = Position(**raw)
        quote = usable_price((prices or {}).get(position.symbol), prices_at,
                             cycle_seconds, now=current) if cycle_seconds else None
        valid = quote is not None and paper is not None
        asset = by_asset.setdefault(position.symbol, {
            'symbol': position.symbol, 'closed_trades': 0, 'net_realized_pnl_usdt': 0.0,
            'win_rate_pct': None, 'open_exposure_usdt': None, 'estimated_open_pnl_usdt': None,
        })
        if valid:
            metrics = position_metrics(position, quote, paper)
            asset['open_exposure_usdt'] = round(metrics['market_value'], 4)
            asset['estimated_open_pnl_usdt'] = round(metrics['unrealized_pnl'], 4)
            open_pnl += metrics['unrealized_pnl']
            open_exposure += metrics['market_value']
        else:
            missing_quotes.append(position.symbol)
    open_symbols = {row['symbol'] for row in open_rows}
    ordered = sorted(by_asset.values(), key=lambda item:
        (item['symbol'] not in open_symbols, -item['closed_trades'], item['symbol']))
    selected, omitted = ordered[:50], ordered[50:]
    studied = set(research_symbols)
    research_closes = sum(row['closed_trades'] for row in by_asset.values() if row['symbol'] in studied)
    exits = connection.execute('''
        SELECT CASE WHEN reason='protective stop' THEN 'protective_stop'
                    WHEN reason='take profit' THEN 'take_profit'
                    WHEN reason LIKE 'trend exit:%' THEN 'trend_exit'
                    ELSE 'other' END AS exit_type,
               COUNT(*), COALESCE(SUM(realized_pnl),0)
        FROM trades WHERE side='SELL' GROUP BY exit_type ORDER BY exit_type
    ''').fetchall()
    preflight_counts = dict(connection.execute('''
        SELECT status,COUNT(*) FROM order_preflight GROUP BY status
    ''').fetchall())
    preflight_issues = []
    for symbol, status, raw in connection.execute('''
        SELECT symbol,status,reasons FROM order_preflight
        WHERE status!='estimated_compatible' ORDER BY id DESC LIMIT 3
    '''):
        try:
            reasons = json.loads(raw)
        except (TypeError, ValueError):
            reasons = []
        preflight_issues.append({'symbol': str(symbol)[:30], 'status': str(status)[:24],
                                 'reasons': [str(reason)[:40] for reason in reasons[:4]]
                                 if isinstance(reasons, list) else []})
    comparable = benchmark_count >= 2 and benchmark_start < benchmark_end
    paper_return = 100*(benchmark_last[0]/benchmark_first[0]-1) if comparable else None
    btc_return = 100*(benchmark_last[1]/benchmark_first[1]-1) if comparable else None
    # Buy at the first paired quote and sell at the last using the same
    # simulated round-trip costs as PAPER. The 100% BTC allocation remains a
    # reference, not a like-for-like comparison of portfolio risk.
    btc_net_return = (100 * (
        benchmark_last[1] / benchmark_first[1]
        * (1 - paper.slippage_rate) / (1 + paper.slippage_rate)
        * (1 - paper.fee_rate) / (1 + paper.fee_rate) - 1
    )) if comparable and paper is not None else None
    return {
        'mode': str(mode).upper(), 'status': 'REVIEW_REQUIRED' if observed_days >= 30 and closed >= 30 and invalid == 0 else 'INSUFFICIENT_EVIDENCE',
        'started_at': start.isoformat() if start else None,
        'last_at': end.isoformat() if end else None,
        'observed_days': round(observed_days, 2), 'equity_points': points,
        'invalid_points': invalid, 'closed_trades': closed,
        'net_realized_pnl_usdt': round(float(trades[1]), 4),
        'fees_usdt': round(fees, 4),
        'win_rate_pct': round(100*int(trades[2])/closed, 2) if closed else None,
        'profit_factor': round(float(trades[3])/float(trades[4]), 3) if trades[4] else None,
        'estimated_open_pnl_usdt': round(open_pnl, 4) if not missing_quotes else None,
        'open_exposure_usdt': round(open_exposure, 4) if not missing_quotes else None,
        'open_positions': len(open_rows), 'unpriced_positions': len(missing_quotes),
        'price_status': ('not_applicable' if not open_rows else
                         'fresh' if not missing_quotes else 'stale_or_missing'),
        'prices_at': quote_time.isoformat() if quote_time else None,
        'by_asset': selected, 'omitted_assets': len(omitted),
        'attribution': {
            'omitted_closed_trades': sum(row['closed_trades'] for row in omitted),
            'omitted_net_realized_pnl_usdt': round(sum(row['net_realized_pnl_usdt'] for row in omitted), 4),
            'research_closed_trades': research_closes if studied else None,
            'research_symbols': sorted(studied),
            'exit_reasons': [{'reason': row[0], 'closed_trades': int(row[1]),
                              'net_realized_pnl_usdt': round(float(row[2]),4)} for row in exits],
            'market_preflight': {'checked': sum(preflight_counts.values()),
                                 'estimated_compatible': preflight_counts.get('estimated_compatible',0),
                                 'incompatible': preflight_counts.get('incompatible',0),
                                 'unknown': preflight_counts.get('unknown',0),
                                 'recent_issues': preflight_issues},
        },
        'equity_change_pct': round(100*(last_equity/first_equity-1), 3) if points else None,
        'sampled_max_drawdown_pct': round(100*max_drawdown, 3) if points else None,
        'benchmark': {
            'symbol': 'BTCUSDT', 'matched_points': benchmark_count,
            'started_at': benchmark_start.isoformat() if benchmark_start else None,
            'observed_days': round((benchmark_end-benchmark_start).total_seconds()/86400, 2) if comparable else 0,
            'paper_return_pct': round(paper_return, 3) if comparable else None,
            'btc_return_pct': round(btc_return, 3) if comparable else None,
            'difference_pp': round(paper_return-btc_return, 3) if comparable else None,
            'btc_net_return_pct': round(btc_net_return, 3) if btc_net_return is not None else None,
            'net_difference_pp': round(paper_return-btc_net_return, 3) if btc_net_return is not None else None,
        },
        'observation_gate': {'days': 30, 'closed_trades': 30},
        'limitations': ['no_cashflow_ledger', 'benchmark_starts_with_new_samples', 'sampled_equity_drawdown'],
    }
