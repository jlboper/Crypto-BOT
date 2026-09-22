"""Read-only forward PAPER evidence; no strategy selection or trading action."""
from __future__ import annotations

import math
from datetime import UTC, datetime


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (AttributeError, ValueError):
        return None


def paper_scorecard(connection):
    """Summarize all recorded equity points and closed PAPER trades.

    Existing accounting stores no external cash flows or historical benchmark
    prices, so this report cannot claim a risk-adjusted edge or LIVE readiness.
    """
    start = end = None
    first_equity = last_equity = peak = 0.0
    max_drawdown = 0.0
    points = invalid = 0
    for row in connection.execute('SELECT equity,created_at FROM equity ORDER BY id'):
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
    return {
        'mode': 'PAPER', 'status': 'REVIEW_REQUIRED' if observed_days >= 30 and closed >= 30 and invalid == 0 else 'INSUFFICIENT_EVIDENCE',
        'started_at': start.isoformat() if start else None,
        'last_at': end.isoformat() if end else None,
        'observed_days': round(observed_days, 2), 'equity_points': points,
        'invalid_points': invalid, 'closed_trades': closed,
        'net_realized_pnl_usdt': round(float(trades[1]), 4),
        'fees_usdt': round(fees, 4),
        'win_rate_pct': round(100*int(trades[2])/closed, 2) if closed else None,
        'profit_factor': round(float(trades[3])/float(trades[4]), 3) if trades[4] else None,
        'equity_change_pct': round(100*(last_equity/first_equity-1), 3) if points else None,
        'sampled_max_drawdown_pct': round(100*max_drawdown, 3) if points else None,
        'observation_gate': {'days': 30, 'closed_trades': 30},
        'limitations': ['no_cashflow_ledger', 'no_historical_benchmark', 'sampled_equity_drawdown'],
    }
