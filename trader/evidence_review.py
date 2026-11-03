"""Read-only aggregate review; never resets history or grants LIVE authority."""
from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from .operational_cohort import AUTHORITY, FLAGS, OperationalCohortStore, digest, epoch, iso
from .migration_evidence import evaluate_forward_cohort, register_forward_cohort, _receipt_slot
from .preproduction_observer import SourceSpec, audit_legacy_source
from .financial_evidence import AUTHORITY as FINANCIAL_AUTHORITY, _check_deadline
from .financial_evidence_io import read_financial_overlay, read_retained_json

MAX_ROWS = 100_000


def _validate_cohort_metadata(store, *, deadline=None):
    with closing(store.connect(True)) as db:
        registrations = db.execute('SELECT digest,engine,environment,registered,registration FROM cohorts LIMIT 65').fetchall()
        if len(registrations) > 64:
            raise ValueError('COHORT_METADATA_BUDGET')
        for raw in registrations:
            _check_deadline(deadline)
            if len(raw['registration']) > 32768:
                raise ValueError('COHORT_REGISTRATION_INVALID')
            cohort = register_forward_cohort(json.loads(raw['registration']))
            if (raw['digest'] != cohort.digest or raw['engine'] != cohort.engine
                    or raw['environment'] != cohort.environment
                    or iso(epoch(raw['registered'])) != iso(cohort.registered_at.timestamp())):
                raise ValueError('COHORT_METADATA_MISMATCH')
            events = db.execute("SELECT id,at,payload FROM observations WHERE cohort=? AND kind='REGISTERED' LIMIT 2", (cohort.digest,)).fetchall()
            if (len(events) != 1 or events[0]['id'] != 'register:'+cohort.digest
                    or epoch(events[0]['at']) != epoch(raw['registered'])
                    or len(events[0]['payload']) > 8192
                    or json.loads(events[0]['payload']) != {'registration_digest':cohort.digest}):
                raise ValueError('COHORT_REGISTERED_EVENT_MISMATCH')


def _replay_cohort(store, row, at, *, deadline=None, return_sources=False):
    """Rebuild derived receipts from chained captures, distrust cached bits."""
    with closing(store.connect(True)) as db:
        if deadline is not None:
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        db.execute('BEGIN')
        raw = db.execute('SELECT registration FROM cohorts WHERE digest=?', (row['registration_digest'],)).fetchone()
        if raw is None or len(raw[0]) > 32768:
            raise ValueError('COHORT_REGISTRATION_INVALID')
        registration = json.loads(raw[0])
        cohort = register_forward_cohort(registration)
        if cohort.digest != row['registration_digest']:
            raise ValueError('COHORT_REGISTRATION_INVALID')
        expected, previous, count = {}, None, 0
        for capture in db.execute("SELECT at,payload,hash FROM observations WHERE cohort=? AND kind='CAPTURE' ORDER BY sequence LIMIT ?",
                                  (cohort.digest, store.max_records+1)):
            _check_deadline(deadline)
            count += 1
            if count > store.max_records or len(capture['payload']) > 8192:
                raise ValueError('BOUNDED_COHORT_CAPTURE_REQUIRED')
            captured = epoch(capture['at'])
            evidence = json.loads(capture['payload'])
            if type(evidence) is not dict or any(type(evidence.get(key)) is not bool for key in FLAGS):
                raise ValueError('COHORT_CAPTURE_FLAGS_INVALID')
            completed = int((captured-cohort.starts_at.timestamp())//cohort.cadence_seconds)
            if completed > 0:
                slot = completed-1
                start = cohort.starts_at.timestamp()+slot*cohort.cadence_seconds
                end = start+cohort.cadence_seconds
                continuous = (previous is not None and previous[0] <= start+cohort.max_receipt_delay_seconds
                              and captured-previous[0] <= cohort.cadence_seconds+cohort.max_receipt_delay_seconds)
                if captured <= end+cohort.max_receipt_delay_seconds:
                    flags = {key: evidence[key] and previous is not None and previous[1].get(key) is True and continuous for key in FLAGS}
                    receipt = {'receipt_id': 'receipt:'+digest({'cohort': cohort.digest, 'slot': slot}),
                        'cohort_digest': cohort.digest, 'environment': cohort.environment,
                        'fingerprints': dict(cohort.fingerprints), 'interval_start': iso(start), 'interval_end': iso(end),
                        'available_at': iso(captured), 'decided_at': iso(captured), 'received_at': iso(captured),
                        'evidence_kind': 'OBSERVED_FORWARD', 'evidence_digest': capture['hash'], **flags}
                    expected.setdefault(slot, receipt)
            previous = captured, evidence
        receipts = []
        for retained in db.execute('SELECT slot,payload,operational,financial FROM receipts WHERE cohort=? ORDER BY slot LIMIT 50001', (cohort.digest,)):
            _check_deadline(deadline)
            if len(receipts) >= 50000 or len(retained['payload']) > 32768:
                raise ValueError('BOUNDED_COHORT_RECEIPTS_REQUIRED')
            receipt = json.loads(retained['payload'])
            if receipt != expected.pop(retained['slot'], None):
                raise ValueError('COHORT_RECEIPT_CAPTURE_MISMATCH')
            try:
                # Use the same strict receipt validator with the already parsed
                # registration. Re-parsing/hashing a registration twice for
                # every five-minute receipt made routine RO status exceed its
                # budget as genuine history accumulated.
                temporal = {**receipt, **{flag: True for flag in FLAGS}}
                temporal_valid = _receipt_slot(temporal, cohort, datetime.fromtimestamp(at, UTC)) == retained['slot']
            except (ValueError, TypeError, KeyError, OverflowError):
                temporal_valid = False
            operational = receipt['source_complete'] and temporal_valid
            financial = all(receipt[flag] is True for flag in FLAGS) and temporal_valid
            if retained['operational'] != int(operational) or retained['financial'] != int(financial):
                raise ValueError('COHORT_CACHED_QUALIFICATION_MISMATCH')
            receipts.append(receipt)
        if expected:
            raise ValueError('COHORT_RECEIPTS_MISSING')
    financial_receipts = [receipt for receipt in receipts if all(receipt[flag] is True for flag in FLAGS)]
    replay = evaluate_forward_cohort(registration, financial_receipts, now=iso(at), expected_digest=cohort.digest)
    replay['invalid_receipts'] += len(receipts)-len(financial_receipts)
    _check_deadline(deadline)
    result = {**row, **{key: replay[key] for key in ('qualified_days', 'valid_receipts', 'invalid_receipts', 'missing_windows')},
            'receipt_complete_days': replay['qualified_days'], 'receipt_replay_verified': True}
    return (result, registration, receipts) if return_sources else result


def _bounded_cohort_chain(store, deadline):
    """Verify actual observations rather than a cached receipt/day counter."""
    previous, count = '0'*64, 0
    if store.path.stat().st_size > store.max_bytes:
        raise ValueError('BOUNDED_COHORT_JOURNAL_REQUIRED')
    with closing(store.connect(True)) as db:
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        for row in db.execute('SELECT * FROM observations ORDER BY sequence LIMIT ?', (store.max_records+1,)):
            _check_deadline(deadline)
            if len(row['payload']) > 8192:
                raise ValueError('BOUNDED_COHORT_CAPTURE_REQUIRED')
            value = {'id': row['id'], 'cohort': row['cohort'], 'at': row['at'], 'kind': row['kind'],
                     'payload': json.loads(row['payload']), 'previous': previous}
            if row['previous'] != previous or digest(value) != row['hash']:
                return {'state': 'INVALID', 'reason': 'CHAIN_CONTENT_MISMATCH', 'records': count}
            previous, count = row['hash'], count+1
    _check_deadline(deadline)
    if count > store.max_records:
        raise ValueError('BOUNDED_COHORT_JOURNAL_REQUIRED')
    return {'state': 'VALID_LOCAL_CHAIN', 'records': count, 'anchor': previous, 'external_attestation': False}


def _financial_overlay(data, row, registration, originals, at, deadline):
    """Join only this scope's independently retained account binding/outcomes."""
    if (row['engine'], row['environment']) not in {('SPOT', 'SPOT_TESTNET'), ('FUTURES', 'FUTURES_DEMO')}:
        return None
    directory = data/'testnet-financial-capture'/row['environment']
    try:
        _check_deadline(deadline)
        binding = read_retained_json(directory/'binding.json', max_bytes=4096)
        names = {'schema', 'environment', 'cohort_digest', 'account_ref', 'unit_scale', 'identity_state'} | set(FINANCIAL_AUTHORITY)
        if (type(binding) is not dict or set(binding) != names or type(binding['schema']) is not int or binding['schema'] != 1
                or binding['environment'] != row['environment'] or binding['cohort_digest'] != row['registration_digest']
                or binding['identity_state'] != 'REPORTED' or any(binding[key] is not False for key in FINANCIAL_AUTHORITY)
                or type(binding['account_ref']) is not str or not re.fullmatch('[0-9a-f]{64}', binding['account_ref'])
                or type(binding['unit_scale']) is not int or binding['unit_scale'] != 8):
            return None
        overlay = read_financial_overlay(directory/'financial-evidence.sqlite3', directory/'financial-evidence.anchor.json',
            registration, originals, now=iso(at), expected_cohort_digest=row['registration_digest'],
            expected_account_ref=binding['account_ref'], expected_unit_scale=binding['unit_scale'], deadline=deadline)
        # Account/cohort bindings are not refreshed by a status read. A concurrent
        # rebinding invalidates this outcome, even when the old chain was valid.
        if read_retained_json(directory/'binding.json', max_bytes=4096) != binding:
            return None
        _check_deadline(deadline)
        return overlay
    except (OSError, ValueError, TypeError, KeyError, RecursionError, sqlite3.Error):
        _check_deadline(deadline)
        return None


def read_verified_cohort_snapshot(data_dir, *, now=None, budget_seconds=3):
    """Bounded RO replay for status; financial outcomes stay separate from inputs.

    The current registration, chained original captures, receipt derivation,
    financial packet chain, external retained anchor and independent scope/account
    binding must all agree. A supplied/cached day count never substitutes for
    replay. No read initializes a source or obtains exchange/provider data.
    """
    at = epoch(time.time() if now is None else now)
    if type(budget_seconds) not in (int, float) or not 0 < budget_seconds <= 10:
        raise ValueError('BOUNDED_COHORT_READ_BUDGET_REQUIRED')
    deadline = time.monotonic()+budget_seconds
    data = Path(data_dir).resolve()
    result = {'state': 'UNAVAILABLE', 'cohort_chain': {'state': 'UNAVAILABLE'}, 'scopes': [], 'reason_codes': []}
    store = OperationalCohortStore(data/'operational-cohorts.sqlite3', max_records=100_000)
    if not store.path.is_file():
        result['state'] = 'NOT_REGISTERED'
        return result
    try:
        chain = _bounded_cohort_chain(store, deadline)
        result['cohort_chain'] = chain
        if chain['state'] != 'VALID_LOCAL_CHAIN':
            result['reason_codes'] = ['COHORT_CHAIN_INVALID']
            return result
        _validate_cohort_metadata(store, deadline=deadline)
        snapshot = store.snapshot(now=at)
        _check_deadline(deadline)
        if snapshot['state'] not in {'OBSERVING', 'NOT_REGISTERED'}:
            raise ValueError('COHORT_SNAPSHOT_UNAVAILABLE')
        rows = []
        for row in snapshot['scopes']:
            if row['engine'] not in {'SPOT', 'FUTURES'}:
                continue
            _check_deadline(deadline)
            replay, registration, originals = _replay_cohort(store, row, at, deadline=deadline, return_sources=True)
            overlay = _financial_overlay(data, replay, registration, originals, at, deadline)
            verified = overlay is not None and overlay['coverage_verified'] is True
            replay.update(financial_overlay=overlay,
                financial_qualified_days=overlay['qualified_days'] if verified else None,
                financial_continuous_qualified_days=overlay['continuous_qualified_days'] if verified else None)
            for key in ('financial_qualified_days', 'financial_continuous_qualified_days'):
                days = replay[key]
                if days is not None and (type(days) is not int or days < 0
                        or replay['operational_coverage_days'] is None or days > replay['operational_coverage_days']):
                    raise ValueError('FINANCIAL_COVERAGE_EXCEEDS_ORIGINAL_OPERATIONS')
            rows.append(replay)
        final_chain = _bounded_cohort_chain(store, deadline)
        if final_chain != chain:
            raise ValueError('COHORT_CHAIN_CHANGED_DURING_REVIEW')
        result.update(state=snapshot['state'], scopes=rows)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, RecursionError):
        result.update(state='UNAVAILABLE', scopes=[], reason_codes=['COHORT_AUDIT_UNAVAILABLE'])
    return result


def _number(value):
    if type(value) not in (int, float, str) or len(str(value)) > 80:
        raise ValueError('FINITE_NUMBER_REQUIRED')
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('FINITE_NUMBER_REQUIRED') from None
    if not number.is_finite() or abs(number) > Decimal('1e18'):
        raise ValueError('FINITE_NUMBER_REQUIRED')
    return number


def _stamp(value, at):
    if type(value) is not str or len(value) > 40:
        raise ValueError('UTC_TIMESTAMP_REQUIRED')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0 or not 0 < parsed.timestamp() <= at:
        raise ValueError('UTC_TIMESTAMP_REQUIRED')


def _ledger(spec, at):
    spot = spec.engine == 'SPOT'
    result = {'engine': spec.engine, 'environment': spec.environment, 'state': 'UNAVAILABLE',
        'legacy': audit_legacy_source(spec, now=at), 'recorded_exit_rows': None,
        'positive_exit_rows': None, 'negative_exit_rows': None, 'recorded_realized_pnl': None,
        'pnl_basis': 'RECORDED_LOCAL' if spot else 'GROSS', 'recorded_fees': None,
        'fully_reconciled_net_pnl': None, 'sampled_max_drawdown_pct': None,
        'sampled_equity_change': None, 'retained_rows_digest': None, 'truncated': False,
        'use': ['DESCRIPTIVE_ACTIVITY', 'OPERATIONAL_INCIDENT_REVIEW'],
        'unproven': ['ACCOUNT_CASHFLOW_RECONCILIATION', 'ALL_COSTS', 'HISTORICAL_METHOD_CONTINUITY',
                     'INDEPENDENT_OOS_EDGE', 'LIVE_EXECUTION_QUALITY', 'CLOSED_EPISODE_LINKAGE']}
    trades_sql = ('SELECT id,side,realized_pnl,fee,created_at FROM trades ORDER BY id LIMIT ?' if spot else
                  'SELECT id,direction,gross_pnl,closed_at FROM forward_trades ORDER BY id LIMIT ?')
    equity_sql = ('SELECT id,equity,created_at FROM equity ORDER BY created_at,id LIMIT ?' if spot else
                  'SELECT id,wallet_balance,unrealized_pnl,created_at FROM forward_equity ORDER BY created_at,id LIMIT ?')
    try:
        with closing(sqlite3.connect(spec.database_path.as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            deadline = time.monotonic()+5
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            db.execute('BEGIN')
            trades = db.execute(trades_sql, (MAX_ROWS+1,)).fetchall()
            equity = db.execute(equity_sql, (MAX_ROWS+1,)).fetchall()
        if max(len(trades), len(equity)) > MAX_ROWS:
            result.update(state='ROW_LIMIT_REACHED', truncated=True)
            return result
        pnl, fees = [], Decimal(0)
        for row in trades:
            _stamp(row[-1], at)
            amount = _number(row[2])
            if row[1] not in ({'BUY', 'SELL'} if spot else {'LONG', 'SHORT'}):
                raise ValueError('TRADE_SIDE_REQUIRED')
            if spot:
                fee = _number(row[3])
                if fee < 0:
                    raise ValueError('NONNEGATIVE_FEE_REQUIRED')
                fees += fee
            if not spot or row[1] == 'SELL':
                pnl.append(amount)
        values = []
        for row in equity:
            _stamp(row[-1], at)
            value = _number(row[1]) if spot else _number(row[1])+_number(row[2])
            if value <= 0:
                raise ValueError('POSITIVE_EQUITY_REQUIRED')
            values.append(value)
        peak, drawdown = Decimal(0), Decimal(0)
        for value in values:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak-value)/peak*100)
        retained = json.dumps([trades, equity], separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        result.update(state='DESCRIPTIVE_RETAINED_EVIDENCE', recorded_exit_rows=len(pnl),
            positive_exit_rows=sum(value > 0 for value in pnl), negative_exit_rows=sum(value < 0 for value in pnl),
            recorded_realized_pnl=format(sum(pnl, Decimal(0)), 'f'),
            recorded_fees=format(fees, 'f') if spot else None,
            sampled_max_drawdown_pct=format(drawdown, 'f') if values else None,
            sampled_equity_change=format(values[-1]-values[0], 'f') if len(values) >= 2 else None,
            retained_rows_digest=hashlib.sha256(retained.encode('ascii')).hexdigest())
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
        result['state'] = 'INVALID_OR_UNAVAILABLE_SOURCE'
    return result


def review_retained_evidence(data_dir, *, now=None):
    """Private local results, per-ledger transactions; no global/account cut.

    Recorded PnL and fees are not subtracted again: historical accounting methods
    may differ. Missing cashflows, costs and methodology remain explicit gaps.
    """
    at, data = epoch(time.time() if now is None else now), Path(data_dir).resolve()
    result = {'schema': 1, 'at': iso(at), 'state': 'REVIEW_INCOMPLETE', **AUTHORITY,
        'history_reset': False, 'globally_atomic': False,
        'engines': [_ledger(SourceSpec(engine, environment, data/name), at)
                    for engine, environment, name in (
                        ('SPOT', 'SPOT_TESTNET', 'testnet-trader.db'),
                        ('FUTURES', 'FUTURES_DEMO', 'futures-testnet.db'))],
        'cohort_chain': {'state': 'UNAVAILABLE'}, 'cohorts': [],
        'decision': 'RETAIN_INACTIVE_REQUIRES_EVIDENCE_AND_SEPARATE_OWNER_AUTHORIZATION',
        'blockers': ['ACCOUNT_RECONCILIATION_INCOMPLETE', 'INDEPENDENT_OOS_EVIDENCE_UNPROVEN',
                     'LIVE_RECOVERY_COMMISSIONING_REQUIRED', 'OWNER_ACTIVATION_REQUIRED']}
    prospective = read_verified_cohort_snapshot(data, now=at)
    result['cohort_chain'] = prospective['cohort_chain']
    result['cohorts'] = [row for row in prospective['scopes'] if row['engine'] in {'SPOT', 'FUTURES'}]
    result['blockers'].extend(prospective['reason_codes'])
    active = {row['engine']: row for row in result['cohorts'] if row['active']}
    if set(active) != {'SPOT', 'FUTURES'} or any(
            row['financial_continuous_qualified_days'] is None or row['financial_continuous_qualified_days'] < 30 or row['stale']
            for row in active.values()):
        result['blockers'].append('FINANCIALLY_QUALIFIED_FORWARD_INCOMPLETE')
    if all(row['state'] == 'DESCRIPTIVE_RETAINED_EVIDENCE' for row in result['engines']):
        result['state'] = 'REVIEWED_WITH_EXPLICIT_GAPS'
    return result
