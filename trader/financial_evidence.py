"""Canonical financial-window reconciliation, never trading authority.

This validates supplied, retained account cuts. A digest detects content changes;
it does not prove that an exchange returned the data. Producers must retain the
original sources and establish ALL_ACCOUNT pagination/stream coverage themselves.
Current balance snapshots and the old three-kind income scorecard cannot do that.

Financial outcomes can arrive after an operational decision. They are appended
with their actual receipt time and may qualify an already captured window only
as of that later time. They never replace the original receipt or become data
that was available to the strategy at its earlier decision.
"""
from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import stat
from pathlib import Path
import re
import sqlite3
import time

from .migration_evidence import evaluate_forward_cohort, register_forward_cohort

MAX_BYTES = 262144
MAX_ROWS = 1024
MAX_UNITS = 10**24
FLAGS = ('source_complete', 'reconciled', 'costs_complete', 'cashflows_complete', 'protections_complete')
AUTHORITY = {'execution_enabled': False, 'financial_authorization': False,
             'automatic_activation': False, 'ready_for_live': False}
_HASH = re.compile(r'[a-f0-9]{64}\Z', re.ASCII)
_SYMBOL = re.compile(r'[A-Z0-9]{2,24}USDT\Z', re.ASCII)
_ASSET = re.compile(r'[A-Z0-9]{1,24}\Z', re.ASCII)
_KINDS = {'COMMISSION', 'FUNDING_FEE', 'REALIZED_PNL', 'DEPOSIT', 'WITHDRAWAL',
          'TRANSFER_IN', 'TRANSFER_OUT', 'REBATE', 'OTHER'}
_FLOWS = {'DEPOSIT', 'WITHDRAWAL', 'TRANSFER_IN', 'TRANSFER_OUT', 'REBATE'}
_BUNDLE = {'schema', 'account_ref', 'environment', 'currency', 'unit_scale', 'window_start',
           'window_end', 'ledger', 'exchange', 'exposures', 'protections', 'protection_coverage'}
_CUT = {'account_ref', 'environment', 'currency', 'balance_start_units', 'balance_end_units',
        'opening_positions', 'positions', 'fills', 'settlements', 'coverage', 'digest'}
_COVERAGE = {'start', 'end', 'received_at', 'scope', 'position_count', 'fill_count',
             'settlement_count', 'fills_exhausted', 'settlements_exhausted',
             'unknown_orders', 'unrecognized_positions'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('CLOSED_FINANCIAL_EVIDENCE_REQUIRED')


def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError('RETAINED_EVIDENCE_DIGEST_REQUIRED')


def _time(value):
    if type(value) is not str or len(value) > 40 or not value.endswith('Z'):
        raise ValueError('EXPLICIT_UTC_REQUIRED')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
            raise ValueError()
        return result.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError('EXPLICIT_UTC_REQUIRED') from None


def _iso(value):
    return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _units(value, *, positive=False, signed=False):
    if (type(value) is not int or abs(value) > MAX_UNITS
            or not signed and value < 0 or positive and value <= 0):
        raise ValueError('EXACT_INTEGER_FINANCIAL_UNITS_REQUIRED')
    return value


def seal_cut(value):
    """Content addressing helper; not an external attestation of completeness."""
    value = dict(value)
    value.pop('digest', None)
    return {**value, 'digest': digest(value)}


def _rows(value, keys, identity):
    if type(value) is not list or len(value) > MAX_ROWS:
        raise ValueError('BOUNDED_FINANCIAL_ROWS_REQUIRED')
    result = {}
    for row in value:
        _keys(row, keys)
        _hash(row[identity])
        if row[identity] in result:
            raise ValueError('DUPLICATE_FINANCIAL_RECORD')
        result[row[identity]] = row
    return result


def _position(row):
    if (type(row['symbol']) is not str or not _SYMBOL.fullmatch(row['symbol'])
            or row['direction'] not in {'LONG', 'SHORT'}):
        raise ValueError('FINANCIAL_POSITION_SCOPE_REQUIRED')
    _units(row['quantity_units'], positive=True)


def _cut(value, bundle, start, end, now, *, spot):
    _keys(value, _CUT)
    if (value['account_ref'] != bundle['account_ref'] or value['environment'] != bundle['environment']
            or value['currency'] != 'USDT'):
        raise ValueError('FINANCIAL_ACCOUNT_SCOPE_CHANGED')
    _hash(value['digest'])
    if value['digest'] != digest({k: v for k, v in value.items() if k != 'digest'}):
        raise ValueError('FINANCIAL_CUT_DIGEST_MISMATCH')
    for name in ('balance_start_units', 'balance_end_units'):
        _units(value[name], signed=True)
    coverage = value['coverage']
    _keys(coverage, _COVERAGE)
    if (_time(coverage['start']) != start or _time(coverage['end']) != end
            or not end <= _time(coverage['received_at']) <= now
            or coverage['scope'] not in {'ALL_ACCOUNT', 'BOUNDED_SYMBOLS', 'UNKNOWN'}):
        raise ValueError('FINANCIAL_WINDOW_SCOPE_REQUIRED')
    for name in ('position_count', 'fill_count', 'settlement_count', 'unknown_orders', 'unrecognized_positions'):
        _units(coverage[name])
    for name in ('fills_exhausted', 'settlements_exhausted'):
        if type(coverage[name]) is not bool:
            raise ValueError('EXPLICIT_COVERAGE_REQUIRED')
    positions = _rows(value['positions'], {'ref', 'symbol', 'direction', 'quantity_units'}, 'ref')
    opening = _rows(value['opening_positions'], {'ref', 'symbol', 'direction', 'quantity_units'}, 'ref')
    fills = _rows(value['fills'], {'ref', 'position_ref', 'symbol', 'direction', 'effect', 'at',
        'sequence', 'quantity_units', 'quote_units', 'fee_asset', 'fee_units', 'fee_quote_units'}, 'ref')
    settlements = _rows(value['settlements'], {'ref', 'kind', 'asset', 'amount_units', 'at'}, 'ref')
    costs = True
    for row in list(opening.values())+list(positions.values()):
        _position(row)
        if spot and row['direction'] != 'LONG':
            raise ValueError('SPOT_SHORT_EVIDENCE_BLOCKED')
    for row in fills.values():
        _position(row)
        _hash(row['position_ref'])
        _units(row['sequence'])
        if row['effect'] not in {'OPEN', 'REDUCE', 'CLOSE'} or not start <= _time(row['at']) < end:
            raise ValueError('FINANCIAL_FILL_WINDOW_REQUIRED')
        if spot and row['direction'] != 'LONG':
            raise ValueError('SPOT_SHORT_EVIDENCE_BLOCKED')
        _units(row['quote_units'], positive=True)
        _units(row['fee_units'])
        if row['fee_quote_units'] is not None:
            _units(row['fee_quote_units'])
        asset = row['fee_asset']
        if asset is not None and (type(asset) is not str or not _ASSET.fullmatch(asset)):
            raise ValueError('FINANCIAL_FEE_ASSET_REQUIRED')
        # Base-asset fee quantity has the same units as the fill quantity. Its
        # quote valuation is rounded up to an integer quote unit, never guessed.
        if asset == 'USDT':
            expected = row['fee_units']
        elif asset == row['symbol'][:-4]:
            expected = (row['fee_units'] * row['quote_units'] + row['quantity_units'] - 1) // row['quantity_units']
        else:
            expected = None
        costs = costs and expected is not None and row['fee_quote_units'] == expected
    known_flows = True
    for row in settlements.values():
        if row['kind'] not in _KINDS or type(row['asset']) is not str or not _ASSET.fullmatch(row['asset']):
            raise ValueError('FINANCIAL_SETTLEMENT_REQUIRED')
        if not start <= _time(row['at']) < end:
            raise ValueError('FINANCIAL_SETTLEMENT_WINDOW_REQUIRED')
        _units(row['amount_units'], signed=True)
        if (row['kind'] in {'DEPOSIT', 'TRANSFER_IN', 'REBATE'} and row['amount_units'] < 0
                or row['kind'] in {'WITHDRAWAL', 'TRANSFER_OUT', 'COMMISSION'} and row['amount_units'] > 0):
            raise ValueError('FINANCIAL_SETTLEMENT_SIGN_CONTRADICTION')
        known_flows = known_flows and row['asset'] == 'USDT' and row['kind'] != 'OTHER'
    counts = (len(positions), len(fills), len(settlements))
    reported = tuple(coverage[k] for k in ('position_count', 'fill_count', 'settlement_count'))
    complete = (counts == reported and coverage['scope'] == 'ALL_ACCOUNT'
                and coverage['fills_exhausted'] and coverage['settlements_exhausted']
                and coverage['unknown_orders'] == coverage['unrecognized_positions'] == 0)
    if spot:
        known_flows = known_flows and all(r['kind'] in _FLOWS for r in settlements.values())
        trading = sum((1 if r['effect'] in {'REDUCE', 'CLOSE'} else -1) * r['quote_units']
                      - (r['fee_units'] if r['fee_asset'] == 'USDT' else 0) for r in fills.values())
    else:
        trading = 0  # Futures quote notional is not a settled-wallet cashflow.
        costs = (costs and all(r['fee_asset'] == 'USDT' for r in fills.values())
                 and sum(r['amount_units'] for r in settlements.values() if r['kind'] == 'COMMISSION')
                     == -sum(r['fee_units'] for r in fills.values()))
    cash = sum(r['amount_units'] for r in settlements.values())
    balanced = known_flows and value['balance_end_units'] - value['balance_start_units'] == trading + cash
    return positions, fills, settlements, complete, costs, known_flows, balanced, opening


def _exposure_timeline(opening, closing, fills, start, end, *, spot):
    """Reconstruct held quantities rather than trusting supplied no-gap flags."""
    refs = set(opening) | set(closing) | {r['position_ref'] for r in fills.values()}
    expected, ending = [], {}
    for ref in sorted(refs):
        changes = sorted((r for r in fills.values() if r['position_ref'] == ref),
                         key=lambda r: (_time(r['at']), r['sequence']))
        metadata = [r for r in (opening.get(ref), closing.get(ref)) if r is not None]+changes
        shapes = {(r['symbol'], r['direction']) for r in metadata}
        if len(shapes) != 1:
            raise ValueError('POSITION_IDENTITY_CHANGED_WITHIN_WINDOW')
        symbol, direction = next(iter(shapes))
        quantity, previous, sequence = opening.get(ref, {}).get('quantity_units', 0), start, -1
        for row in changes:
            at = _time(row['at'])
            if row['sequence'] <= sequence:
                raise ValueError('AMBIGUOUS_FILL_ORDER')
            sequence = row['sequence']
            if previous < at and quantity:
                expected.append({'position_ref':ref,'symbol':symbol,'direction':direction,
                    'start':_iso(previous),'end':_iso(at),'quantity_units':quantity})
            fee = row['fee_units'] if spot and row['fee_asset'] == symbol[:-4] else 0
            quantity += row['quantity_units']-fee if row['effect'] == 'OPEN' else -row['quantity_units']-fee
            if quantity < 0 or row['effect'] == 'CLOSE' and quantity != 0 or row['effect'] == 'REDUCE' and quantity <= 0:
                raise ValueError('POSITION_QUANTITY_CONTRADICTION')
            previous = at
        if previous < end and quantity:
            expected.append({'position_ref':ref,'symbol':symbol,'direction':direction,
                'start':_iso(previous),'end':_iso(end),'quantity_units':quantity})
        if quantity:
            ending[ref] = {'ref':ref,'symbol':symbol,'direction':direction,'quantity_units':quantity}
    return expected, ending == closing


def _protections(bundle, positions, expected_exposures, start, end, now):
    coverage = bundle['protection_coverage']
    _keys(coverage, {'start', 'end', 'received_at', 'complete', 'source_digest'})
    _hash(coverage['source_digest'])
    if (type(coverage['complete']) is not bool or _time(coverage['start']) != start
            or _time(coverage['end']) != end or not end <= _time(coverage['received_at']) <= now):
        raise ValueError('PROTECTION_HISTORY_WINDOW_REQUIRED')
    exposures = bundle['exposures']
    protections = bundle['protections']
    if type(exposures) is not list or type(protections) is not list or max(len(exposures), len(protections)) > MAX_ROWS:
        raise ValueError('BOUNDED_PROTECTION_HISTORY_REQUIRED')
    if coverage['source_digest'] != digest({'start':coverage['start'],'end':coverage['end'],
                                           'exposures':exposures,'protections':protections}):
        raise ValueError('PROTECTION_SOURCE_DIGEST_MISMATCH')
    by_position = {}
    for row in exposures:
        _keys(row, {'position_ref', 'symbol', 'direction', 'start', 'end', 'quantity_units'})
        _hash(row['position_ref']); _position(row)
        a, b = _time(row['start']), _time(row['end'])
        if not start <= a < b <= end:
            raise ValueError('EXPOSURE_WINDOW_REQUIRED')
        by_position.setdefault(row['position_ref'], []).append((a, b, row))
    for entries in by_position.values():
        entries.sort(key=lambda x: x[0])
        if any(right[0] < left[1] for left, right in zip(entries, entries[1:])):
            raise ValueError('OVERLAPPING_EXPOSURE_HISTORY')
    arms, unknown = {}, {}
    for row in protections:
        _keys(row, {'position_ref', 'start', 'end', 'quantity_units', 'order_ref',
                    'confirmed_at', 'received_at', 'status', 'kind'})
        _hash(row['position_ref'])
        a, b = _time(row['start']), _time(row['end'])
        received = _time(row['received_at'])
        _units(row['quantity_units'])
        if (not start <= a < b <= end or not b <= received <= now
                or row['status'] not in {'ARMED', 'UNKNOWN', 'MISSING'}
                or row['kind'] not in {'STOP_LOSS', 'TAKE_PROFIT'}
                or row['position_ref'] not in by_position):
            raise ValueError('PROTECTION_HISTORY_REQUIRED')
        if row['status'] == 'ARMED':
            _hash(row['order_ref'])
            confirmed = _time(row['confirmed_at'])
            if confirmed > a:
                raise ValueError('PROTECTION_NOT_CONFIRMED_AT_SEGMENT_START')
            if row['kind'] == 'STOP_LOSS':
                arms.setdefault(row['position_ref'], []).append((a, b, row['quantity_units']))
        elif row['order_ref'] is not None or row['confirmed_at'] is not None:
            raise ValueError('UNKNOWN_PROTECTION_CANNOT_CLAIM_CONFIRMATION')
        elif row['kind'] == 'STOP_LOSS':
            unknown.setdefault(row['position_ref'], []).append((a, b))
    complete = coverage['complete'] and sorted(exposures,key=canonical) == sorted(expected_exposures,key=canonical)
    for position in positions.values():
        complete = complete and any(b == end and r['symbol'] == position['symbol']
            and r['direction'] == position['direction'] and r['quantity_units'] == position['quantity_units']
            for a, b, r in by_position.get(position['ref'], []))
    # Exact comparison with the mechanically reconstructed timeline above also
    # covers fills. Do not require a base-commission amount to be protected as
    # if it were still held: the net post-fill position excludes that fee.
    for ref, entries in by_position.items():
        for a, b, row in entries:
            if any(left < b and right > a for left, right in unknown.get(ref, [])):
                complete = False
            cursor = a
            for left, right, quantity in sorted(arms.get(ref, [])):
                if quantity >= row['quantity_units'] and left <= cursor < right:
                    cursor = max(cursor, right)
            complete = complete and cursor >= b
    return complete


def build_financial_receipt(registration, original, bundle, *, now):
    """Validate one frozen operational receipt plus its later financial facts.

    Invalid input yields closed diagnostics and no completeness flags. Complete
    flags attest only the supplied window, never all history or strategy edge.
    """
    value = {'schema': 1, 'method': 'FINANCIAL_WINDOW_V1', 'state': 'UNKNOWN',
        'available_at': None, 'cohort_digest': None, 'engine': None, 'environment': None,
        'original_receipt_digest': None, 'bundle_digest': None, 'account_ref': None,
        'interval_start': None, 'interval_end': None, 'unit_scale': None,
        'outcome_digest': None, 'opening_state_digest': None, 'closing_state_digest': None,
        'contemporaneous': False,
        'usable_at_original_decision': False, 'financial_window_complete': False,
        'reason_codes': ['FINANCIAL_EVIDENCE_INVALID'], **{k: False for k in FLAGS}, **AUTHORITY}
    try:
        instant = _time(now)
        cohort = register_forward_cohort(registration)
        if cohort.engine not in {'SPOT', 'FUTURES'}:
            raise ValueError('FINANCIAL_ENGINE_SCOPE_REQUIRED')
        # Reuse only the existing receipt's prospective time/fingerprint rules.
        # Its original financial flags remain untouched and are not trusted.
        if type(original) is not dict or original.get('source_complete') is not True:
            raise ValueError('ORIGINAL_OPERATIONAL_RECEIPT_REQUIRED')
        temporal = {**original, **{k: True for k in FLAGS}}
        if evaluate_forward_cohort(registration, [temporal], now=now,
                expected_digest=cohort.digest)['valid_receipts'] != 1:
            raise ValueError('ORIGINAL_OPERATIONAL_RECEIPT_INVALID')
        _keys(bundle, _BUNDLE)
        if type(bundle['schema']) is not int or bundle['schema'] != 1 or len(canonical(bundle)) > MAX_BYTES:
            raise ValueError('BOUNDED_FINANCIAL_BUNDLE_REQUIRED')
        _hash(bundle['account_ref'])
        if bundle['environment'] != cohort.environment or bundle['currency'] != 'USDT':
            raise ValueError('FINANCIAL_ACCOUNT_SCOPE_CHANGED')
        if type(bundle['unit_scale']) is not int or not 0 <= bundle['unit_scale'] <= 12:
            raise ValueError('EXPLICIT_QUOTE_UNIT_SCALE_REQUIRED')
        start, end = _time(bundle['window_start']), _time(bundle['window_end'])
        if start != _time(original['interval_start']) or end != _time(original['interval_end']):
            raise ValueError('ORIGINAL_WINDOW_MISMATCH')
        ledger = _cut(bundle['ledger'], bundle, start, end, instant, spot=cohort.engine == 'SPOT')
        exchange = _cut(bundle['exchange'], bundle, start, end, instant, spot=cohort.engine == 'SPOT')
        exposures, position_balanced = _exposure_timeline(exchange[7], exchange[0], exchange[1],
            start, end, spot=cohort.engine == 'SPOT')
        protections = _protections(bundle, exchange[0], exposures, start, end, instant)
        source = ledger[3] and exchange[3]
        rows_match = ledger[:3] == exchange[:3] and ledger[7] == exchange[7]
        balances_match = all(bundle['ledger'][k] == bundle['exchange'][k] for k in ('balance_start_units', 'balance_end_units'))
        flags = {'source_complete': source,
            'costs_complete': source and rows_match and ledger[4] and exchange[4],
            'cashflows_complete': source and rows_match and ledger[5] and exchange[5],
            'reconciled': source and rows_match and balances_match and ledger[6] and exchange[6] and position_balanced,
            'protections_complete': source and rows_match and protections}
        complete = all(flags.values())
        timely = instant <= end + timedelta(seconds=cohort.max_receipt_delay_seconds)
        outcome = {'account_ref': bundle['account_ref'], 'environment': bundle['environment'],
            'currency': 'USDT', 'unit_scale': bundle['unit_scale'], 'start': _iso(start), 'end': _iso(end),
            'ledger': {k: bundle['ledger'][k] for k in ('balance_start_units', 'balance_end_units')},
            'ledger_rows': ledger[:3], 'exchange_rows': exchange[:3], 'opening_positions': exchange[7],
            'exchange': {k: bundle['exchange'][k] for k in ('balance_start_units', 'balance_end_units')},
            'exposures': sorted(bundle['exposures'], key=canonical),
            'protections': sorted([{k: v for k, v in p.items() if k != 'received_at'}
                                   for p in bundle['protections']], key=canonical)}
        def state_digest(at, balance, positions):
            # Boundary equality concerns the complete segregated wallet state,
            # before events belonging to the next half-open window. Digests are
            # rebuilt from retained packets, never accepted as source assertions.
            return digest({'account_ref':bundle['account_ref'], 'environment':bundle['environment'],
                'currency':'USDT', 'unit_scale':bundle['unit_scale'], 'at':_iso(at),
                'balance_units':balance, 'positions':sorted(positions.values(),key=canonical)})
        value.update(state='RECONCILED_WINDOW' if complete else 'INCOMPLETE_WINDOW',
            available_at=_iso(instant), cohort_digest=cohort.digest, engine=cohort.engine,
            environment=cohort.environment, original_receipt_digest=digest(original),
            bundle_digest=digest(bundle), account_ref=bundle['account_ref'],
            interval_start=_iso(start), interval_end=_iso(end), contemporaneous=timely,
            unit_scale=bundle['unit_scale'], outcome_digest=digest(outcome),
            opening_state_digest=state_digest(start,bundle['exchange']['balance_start_units'],exchange[7]),
            closing_state_digest=state_digest(end,bundle['exchange']['balance_end_units'],exchange[0]),
            usable_at_original_decision=False, financial_window_complete=complete,
            reason_codes=[k.upper()+'_UNPROVEN' for k in FLAGS if not flags[k]] or ['SUPPLIED_WINDOW_ONLY'], **flags)
        if complete and not timely:
            value['state'] = 'LATE_RECONCILED_WINDOW'
        # Even timely reconciliation was produced after that original decision.
        # Do not claim it was decision input. The source producer can separately
        # retain any predecision information; this journal is outcome evidence.
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        pass
    return value


class FinancialEvidenceStore:
    """Append-only financial receipts, in a separate non-authoritative SQLite."""
    def __init__(self, path, *, clock=time.time, max_records=100000, max_bytes=256*1024*1024):
        if type(max_records) is not int or not 1 <= max_records <= 200000:
            raise ValueError('FINANCIAL_RECORD_LIMIT_REQUIRED')
        if type(max_bytes) is not int or not 65536 <= max_bytes <= 512*1024*1024:
            raise ValueError('FINANCIAL_BYTE_LIMIT_REQUIRED')
        self.path, self.clock, self.max_records, self.max_bytes = Path(path), clock, max_records, max_bytes

    def _safe(self, *, existing=True):
        if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (self.path, *self.path.parents)):
            raise ValueError('LINKED_FINANCIAL_EVIDENCE_BLOCKED')
        try:
            info = self.path.stat(follow_symlinks=False)
        except FileNotFoundError:
            if existing:
                raise ValueError('EXISTING_FINANCIAL_JOURNAL_REQUIRED') from None
            return None
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('REGULAR_SINGLE_LINK_FINANCIAL_JOURNAL_REQUIRED')
        return info

    @staticmethod
    def _schema(db, *, readonly, new=False):
        expected = {'financial_receipts':'table', 'sqlite_sequence':'table',
            'financial_cohort':'index', 'sqlite_autoindex_financial_receipts_1':'index',
            'sqlite_autoindex_financial_receipts_2':'index',
            'financial_no_update':'trigger', 'financial_no_delete':'trigger'}
        entries = list(db.execute('SELECT name,type,tbl_name,sql FROM sqlite_master LIMIT 9'))
        if not entries and new:
            return
        found = {row[0]:row for row in entries}
        required = {'financial_receipts'} if readonly else set(expected)
        if (not required <= set(found) or set(found) - set(expected)
                or any(row[1] != expected[row[0]] for row in entries)
                or any(row[2] != ('sqlite_sequence' if row[0] == 'sqlite_sequence' else 'financial_receipts') for row in entries)):
            raise ValueError('DEDICATED_FINANCIAL_JOURNAL_REQUIRED')
        columns = list(db.execute('PRAGMA table_info(financial_receipts)'))
        names = ('sequence','id','cohort','original','at','receipt','bundle','previous','hash')
        if (len(columns) != len(names) or any(tuple(row[1:]) !=
                (name,'INTEGER' if index == 0 else 'TEXT',0 if index == 0 else 1,None,1 if index == 0 else 0)
                for index,(row,name) in enumerate(zip(columns,names)))):
            raise ValueError('DEDICATED_FINANCIAL_TABLES_REQUIRED')
        for name,operation in (('financial_no_update','UPDATE'),('financial_no_delete','DELETE')):
            if name in found:
                sql = found[name][3]
                target = "CREATE TRIGGER "+name+" BEFORE "+operation+" ON financial_receipts BEGIN SELECT RAISE(ABORT,'immutable financial receipt'); END"
                if type(sql) is not str or ''.join(sql.split()).lower() != ''.join(target.split()).lower():
                    raise ValueError('IMMUTABLE_FINANCIAL_TRIGGERS_REQUIRED')
        if not readonly:
            for name,fields in (('financial_cohort',('cohort','sequence')),
                    ('sqlite_autoindex_financial_receipts_1',('id',)),
                    ('sqlite_autoindex_financial_receipts_2',('hash',))):
                if tuple(row[2] for row in db.execute('PRAGMA index_info('+name+')')) != fields:
                    raise ValueError('DEDICATED_FINANCIAL_INDEXES_REQUIRED')

    def _connect(self, readonly=False, *, _new_identity=None):
        before = self._safe()
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        guard = os.open(self.path, flags)
        db = None
        try:
            opened = os.fstat(guard)
            identity = (opened.st_dev,opened.st_ino)
            def unchanged():
                named, held = self._safe(), os.fstat(guard)
                if (identity != (before.st_dev,before.st_ino)
                        or identity != (named.st_dev,named.st_ino)
                        or identity != (held.st_dev,held.st_ino)
                        or not stat.S_ISREG(held.st_mode) or held.st_nlink != 1):
                    raise ValueError('FINANCIAL_JOURNAL_IDENTITY_CHANGED')
            unchanged()
            if _new_identity is not None and (readonly or identity != _new_identity or opened.st_size != 0):
                raise ValueError('EXPLICIT_NEW_FINANCIAL_JOURNAL_REQUIRED')
            # Neither public record() nor readonly verification can create a DB.
            # Hold the checked descriptor while SQLite resolves the named file.
            mode = 'ro' if readonly else 'rw'
            db = sqlite3.connect(self.path.resolve().as_uri()+'?mode='+mode,uri=True,timeout=.1)
            unchanged()
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA trusted_schema=OFF')  # connection-local, no header write
            if readonly:
                db.execute('PRAGMA query_only=ON')
            self._schema(db,readonly=readonly,new=_new_identity is not None)
            unchanged()
            if not readonly:
                # This potentially persistent PRAGMA follows file/schema checks.
                pagesize = db.execute('PRAGMA page_size').fetchone()[0]
                db.execute('PRAGMA max_page_count='+str(max(16,self.max_bytes//pagesize)))
            unchanged()
            result, db = db, None
            return result
        finally:
            if db is not None:
                db.close()
            os.close(guard)

    def initialize(self):
        self._safe(existing=False); self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_BINARY',0)
        try:
            created = os.open(self.path,flags,0o600)
        except FileExistsError:
            # Idempotence accepts only a dedicated, already initialized journal.
            # A pre-existing empty file is not an implicit initialization grant.
            with closing(self._connect()):
                return
        try:
            info = os.fstat(created)
            identity = (info.st_dev,info.st_ino)
            with closing(self._connect(_new_identity=identity)) as db, db:
                db.executescript('''CREATE TABLE financial_receipts(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
                    cohort TEXT NOT NULL,original TEXT NOT NULL,at TEXT NOT NULL,
                    receipt TEXT NOT NULL,bundle TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT UNIQUE NOT NULL);
                    CREATE INDEX financial_cohort ON financial_receipts(cohort,sequence);
                    CREATE TRIGGER financial_no_update BEFORE UPDATE ON financial_receipts
                    BEGIN SELECT RAISE(ABORT,'immutable financial receipt'); END;
                    CREATE TRIGGER financial_no_delete BEFORE DELETE ON financial_receipts
                    BEGIN SELECT RAISE(ABORT,'immutable financial receipt'); END;''')
                self._schema(db,readonly=False)
                named = self._safe()
                if identity != (named.st_dev,named.st_ino):
                    raise ValueError('FINANCIAL_JOURNAL_IDENTITY_CHANGED')
        finally:
            os.close(created)

    def record(self, registration, original, bundle, *, now=None):
        at = _iso(datetime.fromtimestamp(self.clock(), UTC)) if now is None else now
        receipt = build_financial_receipt(registration, original, bundle, now=at)
        if receipt['cohort_digest'] is None:
            raise ValueError('VALID_FINANCIAL_INPUT_REQUIRED')
        identity = digest({'method': receipt['method'], 'original': receipt['original_receipt_digest'], 'bundle': receipt['bundle_digest']})
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT receipt,hash FROM financial_receipts WHERE id=?', (identity,)).fetchone()
            if old:
                return {'receipt': json.loads(old['receipt']), 'hash': old['hash'], 'duplicate': True}
            if db.execute('SELECT COUNT(*) FROM financial_receipts').fetchone()[0] >= self.max_records:
                raise ValueError('FINANCIAL_RETENTION_FULL')
            tail = db.execute('SELECT hash,at FROM financial_receipts ORDER BY sequence DESC LIMIT 1').fetchone()
            if tail and _time(tail['at']) > _time(receipt['available_at']):
                raise ValueError('FINANCIAL_CLOCK_REGRESSION')
            previous = tail['hash'] if tail else '0'*64
            frame = {'id': identity, 'receipt': receipt, 'bundle': bundle, 'previous': previous}
            value_hash = digest(frame)
            db.execute('INSERT INTO financial_receipts(id,cohort,original,at,receipt,bundle,previous,hash) VALUES(?,?,?,?,?,?,?,?)',
                (identity, receipt['cohort_digest'], receipt['original_receipt_digest'], receipt['available_at'],
                 canonical(receipt), canonical(bundle), previous, value_hash))
        return {'receipt': receipt, 'hash': value_hash, 'duplicate': False}

    def receipts(self, *, cohort_digest, now):
        _hash(cohort_digest); instant = _time(now)
        if not self.path.exists():
            return []
        with closing(self._connect(True)) as db:
            rows = db.execute('SELECT receipt FROM financial_receipts WHERE cohort=? ORDER BY sequence LIMIT ?', (cohort_digest, self.max_records+1)).fetchall()
        if len(rows) > self.max_records:
            raise ValueError('FINANCIAL_RETENTION_FULL')
        return [row for raw in rows if _time((row := json.loads(raw['receipt']))['available_at']) <= instant]

    def verify_chain(self, *, expected_anchor=None):
        if expected_anchor is not None:
            _hash(expected_anchor)
        previous, count, found = '0'*64, 0, expected_anchor is None
        with closing(self._connect(True)) as db:
            for row in db.execute('SELECT * FROM financial_receipts ORDER BY sequence LIMIT ?', (self.max_records+1,)):
                frame = {'id': row['id'], 'receipt': json.loads(row['receipt']), 'bundle': json.loads(row['bundle']), 'previous': previous}
                if row['previous'] != previous or digest(frame) != row['hash']:
                    return {'state': 'INVALID', 'records': count, 'reason': 'FINANCIAL_CHAIN_MISMATCH'}
                previous, count = row['hash'], count+1
                found = found or expected_anchor == previous
        return {'state': 'VALID_LOCAL_CHAIN' if found and count <= self.max_records else 'INVALID',
                'records': count, 'anchor': previous, 'external_attestation': False}

    def coverage(self, registration, originals, *, now, expected_cohort_digest,
                 expected_account_ref, expected_unit_scale, expected_anchor):
        """Rebuild stored outcomes from their packets in one anchored snapshot.

        Use this for integration, rather than accepting completeness booleans
        from imported JSON. The caller retains the latest append hash outside
        this file; an absent or outdated anchor does not qualify any windows.
        This verifies consistency of supplied retained sources, not an exchange
        signature or a substitute for a producer's documented full pagination.
        """
        receipts, error = [], None
        try:
            _hash(expected_anchor)
            cohort = register_forward_cohort(registration)
            if (cohort.digest != expected_cohort_digest or type(originals) is not list
                    or len(originals) > 50000):
                raise ValueError('RETAINED_COHORT_ANCHOR_REQUIRED')
            by_digest = {digest(row): row for row in originals}
            previous, count = '0'*64, 0
            with closing(self._connect(True)) as db, db:
                db.execute('BEGIN')
                for row in db.execute('SELECT * FROM financial_receipts ORDER BY sequence LIMIT ?', (self.max_records+1,)):
                    receipt, bundle = json.loads(row['receipt']), json.loads(row['bundle'])
                    frame = {'id':row['id'],'receipt':receipt,'bundle':bundle,'previous':previous}
                    if row['previous'] != previous or digest(frame) != row['hash']:
                        raise ValueError('FINANCIAL_CHAIN_MISMATCH')
                    previous, count = row['hash'], count+1
                    if row['cohort'] != expected_cohort_digest or _time(receipt['available_at']) > _time(now):
                        continue
                    original = by_digest.get(receipt['original_receipt_digest'])
                    if original is None:
                        continue
                    rebuilt = build_financial_receipt(registration, original, bundle, now=receipt['available_at'])
                    identity = digest({'method':rebuilt['method'],'original':rebuilt['original_receipt_digest'],
                                       'bundle':rebuilt['bundle_digest']})
                    if row['id'] != identity or rebuilt != receipt or (row['at'],row['cohort'],row['original']) != (
                            receipt['available_at'],receipt['cohort_digest'],receipt['original_receipt_digest']):
                        raise ValueError('FINANCIAL_STORED_OUTCOME_MISMATCH')
                    receipts.append(rebuilt)
            if count > self.max_records or previous != expected_anchor:
                raise ValueError('RETAINED_LATEST_FINANCIAL_ANCHOR_REQUIRED')
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError, sqlite3.Error, OSError):
            receipts, error = [], 'FINANCIAL_JOURNAL_VERIFICATION_REQUIRED'
        result = evaluate_financial_coverage(registration, originals, receipts, now=now,
            expected_cohort_digest=expected_cohort_digest, expected_account_ref=expected_account_ref,
            expected_unit_scale=expected_unit_scale)
        result['journal_verified'] = error is None
        if error:
            result['reason_codes'] = [error]
        else:
            result['reason_codes'] = [r for r in result['reason_codes'] if r != 'VERIFY_RETAINED_FINANCIAL_JOURNAL_ANCHOR']
            result['reason_codes'].append('VERIFIED_RETAINED_FINANCIAL_JOURNAL_SNAPSHOT')
        return result


def evaluate_financial_coverage(registration, originals, reconciliations, *, now, expected_cohort_digest,
                                expected_account_ref, expected_unit_scale):
    """Join new financial receipts to retained original windows, as of now.

    This is a separate outcome-quality measure, not the old decision-receipt
    validator with fabricated earlier timestamps. No late row becomes available
    in historical strategy replay. Caller must also verify the durable journal's
    retained chain anchor before trusting supplied reconciliation rows.
    """
    result = {'schema': 1, 'mode': 'OBSERVED_FINANCIAL_COVERAGE', 'state': 'UNKNOWN',
        'at': now, 'valid_windows': 0, 'covered_seconds': 0, 'qualified_days': None,
        'continuous_qualified_days': None, 'late_reconciled_windows': 0, 'missing_windows': None,
        'conflicting_windows': 0, 'external_attestation': False, 'reason_codes': [], **AUTHORITY}
    try:
        cohort = register_forward_cohort(registration); instant = _time(now)
        _hash(expected_account_ref)
        if type(expected_unit_scale) is not int or not 0 <= expected_unit_scale <= 12:
            raise ValueError('RETAINED_ACCOUNT_UNITS_REQUIRED')
        if cohort.digest != expected_cohort_digest:
            raise ValueError('RETAINED_COHORT_ANCHOR_REQUIRED')
        if type(originals) is not list or type(reconciliations) is not list or max(len(originals), len(reconciliations)) > 50000:
            raise ValueError('BOUNDED_FINANCIAL_RECEIPTS_REQUIRED')
        by_digest, slots, conflicts = {}, {}, set()
        for original in originals:
            temporal = {**original, **{k: True for k in FLAGS}}
            if original.get('source_complete') is not True or evaluate_forward_cohort(
                    registration, [temporal], now=now, expected_digest=cohort.digest)['valid_receipts'] != 1:
                continue
            slot = int((_time(original['interval_start'])-cohort.starts_at).total_seconds())//cohort.cadence_seconds
            key = digest(original)
            if slot in slots and slots[slot] != key:
                conflicts.add(slot)
            slots[slot] = key; by_digest[key] = (slot, original)
        valid = {}
        for row in reconciliations:
            key = row.get('original_receipt_digest') if type(row) is dict else None
            if key not in by_digest or row.get('method') != 'FINANCIAL_WINDOW_V1':
                continue
            slot, original = by_digest[key]
            if (row.get('cohort_digest') != cohort.digest or row.get('environment') != cohort.environment
                    or row.get('engine') != cohort.engine or not all(row.get(k) is True for k in FLAGS)
                    or row.get('financial_window_complete') is not True
                    or row.get('account_ref') != expected_account_ref
                    or row.get('unit_scale') != expected_unit_scale
                    or row.get('interval_start') != _iso(_time(original['interval_start']))
                    or row.get('interval_end') != _iso(_time(original['interval_end']))
                    or row.get('usable_at_original_decision') is not False
                    or not _time(original['received_at']) <= _time(row['available_at']) <= instant
                    or any(row.get(k) is not False for k in AUTHORITY)):
                continue
            _hash(row.get('account_ref')); _hash(row.get('bundle_digest')); _hash(row.get('outcome_digest'))
            _hash(row.get('opening_state_digest')); _hash(row.get('closing_state_digest'))
            late = _time(row['available_at']) > _time(row['interval_end'])+timedelta(seconds=cohort.max_receipt_delay_seconds)
            if row.get('contemporaneous') is not (not late):
                continue
            value = (row['account_ref'], row['outcome_digest'], row['opening_state_digest'], row['closing_state_digest'])
            if slot in valid and valid[slot][0] != value:
                conflicts.add(slot)
            if slot not in valid or _time(row['available_at']) < valid[slot][2]:
                valid[slot] = (value, late, _time(row['available_at']),row['opening_state_digest'],row['closing_state_digest'])
        for slot in conflicts:
            valid.pop(slot, None)
        ordered = sorted(valid); runs = []; length = 0; previous = None; discontinuous = False
        for slot in ordered:
            if previous is not None:
                adjacent = slot == previous+1
                boundary_matches = adjacent and valid[previous][4] == valid[slot][3]
                if not boundary_matches:
                    runs.append(length); length = 0
                    discontinuous = discontinuous or adjacent
            length += 1; previous = slot
        if length:
            runs.append(length)
        matured = max(0, int((instant-cohort.starts_at).total_seconds())-cohort.max_receipt_delay_seconds)//cohort.cadence_seconds
        result.update(state='SUPPLIED_FINANCIAL_WINDOWS_ONLY' if ordered else 'UNKNOWN',
            valid_windows=len(ordered), covered_seconds=len(ordered)*cohort.cadence_seconds,
            qualified_days=sum(n*cohort.cadence_seconds//86400 for n in runs) if runs else None,
            continuous_qualified_days=max(n*cohort.cadence_seconds//86400 for n in runs) if runs else None,
            late_reconciled_windows=sum(v[1] for v in valid.values()),
            missing_windows=matured-sum(slot < matured for slot in ordered), conflicting_windows=len(conflicts),
            reason_codes=['NO_AUTOMATIC_AUTHORITY', 'VERIFY_RETAINED_FINANCIAL_JOURNAL_ANCHOR', 'FINANCIAL_DATA_AVAILABLE_ONLY_AT_RECORDED_RECEIPT_TIME'])
        if discontinuous:
            result['reason_codes'].append('FINANCIAL_BOUNDARY_CONTINUITY_UNPROVEN')
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        result['reason_codes'] = ['FINANCIAL_COVERAGE_INPUT_INVALID']
    return result
