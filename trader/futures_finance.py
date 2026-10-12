"""Read-only exchange income collection and conservative cost attribution.

Income is not an order journal. Missing, stale or ambiguous evidence must never
be turned into zero costs or prevent protective position management.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime

from .futures_testnet_transport import signed_request

DAY = 86400000
KINDS = {'COMMISSION', 'FUNDING_FEE', 'REALIZED_PNL'}


def milliseconds(value):
    instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return int(instant.timestamp() * 1000)


def sync_income(ledger, *, now=None, request=None):
    now = now or datetime.now(UTC)
    end = int(now.timestamp()*1000)
    previous = ledger.setting('forward_income_sync') or {}
    if end - int(previous.get('attempt_ms', 0)) < 900000:
        return previous
    request = request or signed_request
    state = {**previous, 'attempt_ms': end}
    try:
        with ledger._connect() as db:
            first = db.execute('''SELECT MIN(instant) FROM (
                SELECT MIN(created_at) instant FROM forward_equity UNION ALL
                SELECT MIN(opened_at) FROM forward_trades UNION ALL
                SELECT MIN(opened_at) FROM forward_position)''').fetchone()[0]
        if not first:
            return previous
        requested_start = milliseconds(first)
        start = max(requested_start, end-89*DAY)
        coverage_start = int(previous.get('start_ms', start))
        cursor = max(start, int(previous.get('through_ms', start))-DAY)
        receipts = []
        while cursor <= end:
            boundary = min(end, cursor+7*DAY-1)
            for page in range(1, 11):
                rows = request('GET', '/fapi/v1/income', {
                    'startTime': cursor, 'endTime': boundary, 'page': page, 'limit': 1000})
                if not isinstance(rows, list):
                    raise ValueError('invalid income response')
                for row in rows:
                    amount = float(row['income'])
                    timestamp = row['time']
                    if (not math.isfinite(amount) or type(timestamp) is not int
                            or not cursor <= timestamp <= boundary
                            or row.get('tranId') is None or not row.get('asset')
                            or not row.get('incomeType')):
                        raise ValueError('invalid income receipt')
                    receipts.append((str(row['incomeType']), str(row['tranId']),
                                     str(row.get('symbol', '')), str(row['asset']), amount, timestamp))
                if len(rows) < 1000:
                    break
            else:
                raise ValueError('income pagination incomplete')
            cursor = boundary+1
        # Commit the complete window and its cursor together; repeated pages
        # and overlapping refreshes cannot double-count exchange receipts.
        state.update(status='OK', start_ms=coverage_start, through_ms=end,
                     requested_start_ms=requested_start, error_type=None)
        with ledger._connect() as db:
            db.executemany('INSERT OR IGNORE INTO forward_income VALUES(?,?,?,?,?,?)', receipts)
            import json
            db.execute('''INSERT INTO settings(key,value) VALUES('forward_income_sync',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                (json.dumps(state, separators=(',', ':')),))
    except Exception as exc:
        state.update(status='UNAVAILABLE', error_type=type(exc).__name__)
        ledger.set_setting('forward_income_sync', state)
    return state


def financial_scorecard(db, sync, *, now=None):
    now = now or datetime.now(UTC)
    sync = sync or {}
    fresh = (sync.get('status') == 'OK'
             and 0 <= int(now.timestamp()*1000)-int(sync.get('through_ms', 0)) <= 1800000)
    trades = [dict(r) for r in db.execute('SELECT * FROM forward_trades ORDER BY id')]
    positions = [dict(r) for r in db.execute('SELECT * FROM forward_position')]
    owners = [(False, r, milliseconds(r['opened_at']), milliseconds(r['closed_at'])) for r in trades]
    owners += [(True, r, milliseconds(r['opened_at']), int(sync.get('through_ms', 0))) for r in positions]
    allocated = {i: [] for i in range(len(owners))}
    totals = {kind: 0.0 for kind in KINDS}
    unmatched = foreign = 0
    ambiguous = set()
    for raw in db.execute('SELECT * FROM forward_income ORDER BY time_ms'):
        row = dict(raw)
        if row['income_type'] not in KINDS:
            continue
        # Demo income times have second precision. A close receipt can round
        # just past the local fill record. Permit one second, only if there is
        # a unique owner and its realized amount also reconciles below.
        matches = [i for i, (is_open, owner, start, end) in enumerate(owners)
                   if owner['symbol'] == row['symbol'] and start-1000 <= row['time_ms'] <= end+(0 if is_open else 1000)]
        if row['asset'] != 'USDT':
            foreign += 1
            ambiguous.update(matches)
            continue
        totals[row['income_type']] += row['income']
        if len(matches) == 1:
            allocated[matches[0]].append(row)
        else:
            unmatched += 1
            ambiguous.update(matches)
    closed = []
    open_costs = []
    for i, (is_open, owner, start, end) in enumerate(owners):
        rows = allocated[i]
        fees = -sum(r['income'] for r in rows if r['income_type']=='COMMISSION')
        funding = sum(r['income'] for r in rows if r['income_type']=='FUNDING_FEE')
        realized = sum(r['income'] for r in rows if r['income_type']=='REALIZED_PNL')
        complete = (fresh and start >= int(sync.get('start_ms', 0))
                    and end <= int(sync.get('through_ms', 0)) and i not in ambiguous
                    and any(r['income_type']=='COMMISSION' for r in rows))
        if is_open:
            open_costs.append({'symbol': owner['symbol'], 'fees_usdt': fees if complete else None,
                               'funding_pnl_usdt': funding if complete else None})
            continue
        # Check income attribution against the durable fills before describing
        # any gross result as net. Other activity in the account stays separate.
        realized_times = {r['time_ms'] for r in rows if r['income_type']=='REALIZED_PNL'}
        exit_fees = [r for r in rows if r['income_type']=='COMMISSION' and r['time_ms'] in realized_times]
        entry_fees = [r for r in rows if r['income_type']=='COMMISSION' and r['time_ms'] not in realized_times]
        complete = (complete and end+1000 <= int(sync.get('through_ms', 0))
                    and bool(exit_fees) and bool(entry_fees)
                    and abs(realized-owner['gross_pnl']) <= 0.00001)
        closed.append({'id': owner['id'], 'symbol': owner['symbol'],
                       'technical': owner['exit_reason'] in {'CONFIG_REPAIR','RECOVERED_CLOSE'},
                       'fees_usdt': fees if complete else None,
                       'funding_pnl_usdt': funding if complete else None,
                       'net_pnl_usdt': owner['gross_pnl']-fees+funding if complete else None})
    strategy = [r for r in closed if not r['technical']]
    all_known = fresh and all(r['net_pnl_usdt'] is not None for r in closed)
    strategy_known = fresh and all(r['net_pnl_usdt'] is not None for r in strategy)
    net = [r['net_pnl_usdt'] for r in strategy] if strategy_known else []
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v < 0]
    return {'status': 'OK' if fresh else ('STALE' if sync.get('status') == 'OK' else sync.get('status', 'PENDING')),
            'synced_at': datetime.fromtimestamp(sync['through_ms']/1000,UTC).isoformat() if sync.get('through_ms') else None,
            'error_type': sync.get('error_type'), 'unmatched_receipts': unmatched,
            'non_usdt_receipts': foreign, 'closed': closed[-50:], 'open_costs': open_costs,
            'account_cash_pnl_usdt': sum(totals.values()) if fresh and not foreign else None,
            'account_commissions_usdt': -totals['COMMISSION'] if fresh else None,
            'account_funding_pnl_usdt': totals['FUNDING_FEE'] if fresh else None,
            'net_realized_pnl_usdt': sum(r['net_pnl_usdt'] for r in closed) if all_known else None,
            'strategy_net_pnl_usdt': sum(net) if strategy_known and strategy else None,
            'strategy_net_expectancy_usdt': sum(net)/len(net) if net else None,
            'strategy_net_win_rate_pct': 100*len(wins)/len(net) if net else None,
            'strategy_net_profit_factor': sum(wins)/abs(sum(losses)) if losses else None,
            'attributed_closed_trades': sum(r['net_pnl_usdt'] is not None for r in closed),
            'limitations': ['time_window_attribution_checked_against_realized_income',
                            'account_totals_include_unattributed_activity', 'open_pnl_excludes_future_exit_costs',
                            'openai_api_costs_not_recorded']}
