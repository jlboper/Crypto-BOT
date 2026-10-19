"""Closed synthetic protocol recipes. No engine/account/AI/exchange integration.

This lab always creates a unique run directory. Opening its JSON projection
never initializes or mutates a wallet. Digests identify scenario evidence; this
is scenario validation, not runtime observation or a journal replay service.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from . import capital_manager_shadow as protocol

MAX_REPORT_BYTES = 8000
U = 1_000_000
VIRTUAL_AT = datetime(2026, 10, 18, tzinfo=UTC).timestamp()
RECIPE_VERSION = 'capital-protocol-lab-v1'
ID = re.compile(r'^SIM_[A-Za-z0-9_-]{1,80}$')
HASH = re.compile(r'^[a-f0-9]{64}$')
RUN_ID = re.compile(r'^SIM_[a-f0-9]{32}$')
BOOK_KEYS = ('book_equity_units', 'reserved_units', 'committed_units',
             'free_units_signed', 'available_units', 'shortfall_units',
             'fees_paid_units', 'realized_pnl_units')
RECIPES = (
    ('SIM_ATOMIC_PAIR', 'Reserva atómica de dos patas', 'RESERVED'),
    ('SIM_ACCOUNT_CONFLICT', 'Conflicto de activo en una cuenta simulada', 'RESERVED'),
    ('SIM_CONCURRENT_BUDGET', 'Dos participantes compiten por el mismo presupuesto', 'RESERVED'),
    ('SIM_RESTART_UNKNOWN_TTL', 'Reinicio y TTL conservan una intención incierta', 'UNKNOWN'),
    ('SIM_PARTIAL_CANCEL', 'Cancelación parcial conserva principal y costes', 'RECOVERY_REQUIRED'),
    ('SIM_MULTILEG_UNWIND', 'Fallo de una pata exige cierre simulado explícito', 'CLOSED'),
    ('SIM_LOSS_SHORTFALL', 'Fees y pérdida confirmada no ocultan déficit', 'RECOVERY_REQUIRED'),
)
CHECKS = {
    'SIM_ATOMIC_PAIR': (('TWO_LEGS_ATOMIC',204*U),('TWO_LEGS_PRESENT',2)),
    'SIM_ACCOUNT_CONFLICT': (('SAME_ACCOUNT_ASSET_REJECTED','ACCOUNT_ASSET_ALREADY_RESERVED'),('ONE_RESERVATION',102*U)),
    'SIM_CONCURRENT_BUDGET': (('ONE_PARENT_BUDGET_WINNER',1),('NO_DOUBLE_ALLOCATION',402*U)),
    'SIM_RESTART_UNKNOWN_TTL': (('TTL_RELEASES_NOTHING',102*U),('INTENTION_UNKNOWN','UNKNOWN')),
    'SIM_PARTIAL_CANCEL': (('ONLY_UNUSED_PRINCIPAL_RELEASED',60*U),('OPEN_COMMITMENT_PRESERVED',40*U),('EXIT_COST_BUFFER_RETAINED',1600000)),
    'SIM_MULTILEG_UNWIND': (('RESIDUAL_REQUIRES_UNWIND',100*U),('EXPLICIT_CLOSE_RELEASES_CAPITAL',0),('BOTH_COSTS_BOOKED',1500000)),
    'SIM_LOSS_SHORTFALL': (('NEGATIVE_EQUITY_NOT_HIDDEN',-204*U),('SHORTFALL_VISIBLE',204*U)),
}
EXPECTED_BOOKS = dict(zip((row[0] for row in RECIPES), (
    (1000*U,204*U,0,796*U,796*U,0,0,0),
    (1000*U,102*U,0,898*U,898*U,0,0,0),
    (1000*U,402*U,0,598*U,598*U,0,0,0),
    (1000*U,102*U,0,898*U,898*U,0,0,0),
    (999600000,1600000,40*U,958*U,958*U,0,400000,0),
    (998*U,0,0,998*U,998*U,0,1500000,-500000),
    (-204*U,0,0,-204*U,0,204*U,4*U,-1200*U),
)))
LIMITATIONS = [
    'SYNTHETIC_PROTOCOL_SCENARIOS_ONLY', 'NO_EXISTING_FUNDS_OR_ACCOUNT_READ',
    'NO_ENGINE_CANDIDATE_OR_ORDER_HOOK', 'NOT_OWNER_FINANCIAL_AUTHORIZATION',
    'BOOK_CAPITAL_NOT_MARKET_EQUITY_OR_GROSS_NOTIONAL',
    'SCENARIO_VALIDATION_NOT_JOURNAL_REPLAY', 'NO_STATISTICAL_EDGE_OR_PROMOTION',
]


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(',', ':')).encode('ascii')


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def _policy():
    # Dated example recipe funding, not an owner budget or risk recommendation.
    return protocol.SimulationLimits('SIM_CAPITAL_LAB_POLICY_V1', 'SIM_RECIPE_AUTHOR',
        VIRTUAL_AT, 'EXPLICIT_NEW_SIMULATION_COHORT', 1000*U, 600*U, 600*U,
        600*U, 20*U, (('SIM_SPOT', 600*U, 20*U), ('SIM_PULSE', 600*U, 20*U)), 120, 10)


def _source_version():
    return {'protocol': protocol.APP,
        'protocol_sha256': hashlib.sha256(Path(protocol.__file__).read_bytes()).hexdigest(),
        'lab_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'recipe_version': RECIPE_VERSION,
        'recipe_sha256': _digest({'recipes': RECIPES, 'checks': CHECKS,
                                 'expected_books': EXPECTED_BOOKS, 'policy': asdict(_policy())})}


class _Clock:
    def __init__(self):
        self.value = VIRTUAL_AT
    def __call__(self):
        return self.value


def _book(snapshot):
    return {key: snapshot[key] for key in BOOK_KEYS}


def _conserved(book):
    if not isinstance(book, dict) or set(book) != set(BOOK_KEYS):
        return False
    if any(type(v) is not int or abs(v) > protocol.MAX_INTEGER for v in book.values()):
        return False
    if any(book[k] < 0 for k in ('reserved_units', 'committed_units', 'available_units',
                                'shortfall_units', 'fees_paid_units')):
        return False
    return (book['book_equity_units'] == 1000*U + book['realized_pnl_units'] - book['fees_paid_units']
        and book['book_equity_units'] == book['free_units_signed'] + book['reserved_units'] + book['committed_units']
        and book['available_units'] == max(0, book['free_units_signed'])
        and book['shortfall_units'] == max(0, -book['free_units_signed']))


def _audit(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT id,payload_digest,payload FROM events ORDER BY sequence DESC LIMIT 1').fetchone()
    if not row or _digest(json.loads(row[2])) != row[1]:
        raise ValueError('SCENARIO_EVENT_DIGEST_MISMATCH')
    return row[0], row[1]


def _scenario(directory, recipe):
    case_id, label, expected = recipe
    clock = _Clock()
    scope = protocol.AccountScope('SHADOW', case_id, 'USDT')
    public_scope = {'scenario_environment':'SHADOW', 'simulated_account_id':case_id, 'currency':'USDT'}
    wallet = case_id + '.simulation.sqlite3'
    path = directory/wallet
    def manager():
        return protocol.CapitalManagerShadow(path, wallet_name=case_id, scope=scope,
                                             limits=_policy(), clock=clock)
    current = manager()
    current.initialize()
    # Every recipe always publishes its complete, closed check roster. An
    # interrupted scenario retains NOT_EVALUATED instead of omitting evidence.
    checks = [{'code':code, 'actual':'NOT_EVALUATED', 'expected':target, 'matches':False}
              for code,target in CHECKS[case_id]]
    def check(code, actual, target):
        index = next(i for i,(expected_code,_) in enumerate(CHECKS[case_id]) if code == expected_code)
        if type(target) is not type(CHECKS[case_id][index][1]) or target != CHECKS[case_id][index][1]:
            raise ValueError('RECIPE_CHECK_DEFINITION_MISMATCH')
        checks[index] = {'code': code, 'actual': actual, 'expected': target,
                         'matches': type(actual) is type(target) and actual == target}
    def leg(identifier='SIM_LEG_1', symbol='BTCUSDT', principal=100*U):
        return protocol.LegRequest(identifier, symbol, 'LONG', 'SPOT_REFERENCE', principal, 2*U, 5*U)
    def request(identifier='SIM_REQUEST_1', strategy='SIM_SPOT', legs=None):
        return protocol.ReservationRequest(identifier, scope, strategy, _policy().policy_id,
                                            legs or (leg(),), clock()+60)
    def submit(req='SIM_REQUEST_1', legs=('SIM_LEG_1',)):
        return current.mark_submitting('SIM_SUBMIT_'+req, req, actor='SIM_EXECUTOR',
            client_order_ids={name: 'SIM_ORDER_'+name for name in legs})
    def event(identifier, *, state='FILLED', filled=100*U, entry=U,
              exit_fee=0, pnl=0, closed=False, leg_id='SIM_LEG_1'):
        return protocol.ReconciliationEvent(identifier, scope, 'SIM_REQUEST_1', leg_id,
            'SIM_RECONCILER', state, filled, entry, exit_fee, pnl, closed, clock(), True)
    try:
        if case_id == 'SIM_ATOMIC_PAIR':
            result = current.reserve(request(legs=(leg(), leg('SIM_LEG_2', 'ETHUSDT'))))
            check('TWO_LEGS_ATOMIC', result['reserved_units'], 204*U)
            check('TWO_LEGS_PRESENT', len(current.snapshot()['requests'][0]['legs']), 2)
        elif case_id == 'SIM_ACCOUNT_CONFLICT':
            current.reserve(request())
            result = current.reserve(request('SIM_REQUEST_2', 'SIM_PULSE'))
            check('SAME_ACCOUNT_ASSET_REJECTED', result['reason'], 'ACCOUNT_ASSET_ALREADY_RESERVED')
            check('ONE_RESERVATION', current.snapshot()['reserved_units'], 102*U)
        elif case_id == 'SIM_CONCURRENT_BUDGET':
            barrier = threading.Barrier(2)
            requests = (request('SIM_RACE_1', legs=(leg(principal=400*U),)),
                        request('SIM_RACE_2', 'SIM_PULSE', (leg(symbol='ETHUSDT', principal=400*U),)))
            def compete(req):
                peer = manager()
                peer.initialize()  # Only the new wallet from this run, never a prior run.
                barrier.wait(timeout=5)
                return peer.reserve(req)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(compete, requests))
            check('ONE_PARENT_BUDGET_WINNER', sum(r['accepted'] for r in results), 1)
            check('NO_DOUBLE_ALLOCATION', current.snapshot()['reserved_units'], 402*U)
        elif case_id == 'SIM_RESTART_UNKNOWN_TTL':
            current.reserve(request()); submit()
            before = current.snapshot()['reserved_units']
            clock.value += 121
            current = manager(); current.initialize()
            current.recover('SIM_RESTART', actor='SIM_RECOVERY')
            clock.value += 3600
            check('TTL_RELEASES_NOTHING', current.snapshot()['reserved_units'], before)
            check('INTENTION_UNKNOWN', current.snapshot()['requests'][0]['state'], 'UNKNOWN')
        elif case_id == 'SIM_PARTIAL_CANCEL':
            current.reserve(request()); submit()
            current.reconcile(event('SIM_PARTIAL', state='PARTIAL', filled=40*U, entry=400000))
            result = current.reconcile(event('SIM_CANCELLED', state='CANCELLED', filled=40*U, entry=400000))
            check('ONLY_UNUSED_PRINCIPAL_RELEASED', result['released_units'], 60*U)
            check('OPEN_COMMITMENT_PRESERVED', current.snapshot()['committed_units'], 40*U)
            check('EXIT_COST_BUFFER_RETAINED', current.snapshot()['reserved_units'], 1600000)
        elif case_id == 'SIM_MULTILEG_UNWIND':
            current.reserve(request(legs=(leg(), leg('SIM_LEG_2', 'ETHUSDT'))))
            submit(legs=('SIM_LEG_1', 'SIM_LEG_2'))
            current.reconcile(event('SIM_FIRST_LEG'))
            current.reconcile(event('SIM_FAILED_LEG', state='CANCELLED', filled=0, entry=0, leg_id='SIM_LEG_2'))
            check('RESIDUAL_REQUIRES_UNWIND', current.snapshot()['committed_units'], 100*U)
            current.reconcile(event('SIM_UNWIND', state='CLOSED', exit_fee=500000, pnl=-500000, closed=True))
            check('EXPLICIT_CLOSE_RELEASES_CAPITAL', current.snapshot()['committed_units'], 0)
            check('BOTH_COSTS_BOOKED', current.snapshot()['fees_paid_units'], 1500000)
        elif case_id == 'SIM_LOSS_SHORTFALL':
            current.reserve(request()); submit()
            current.reconcile(event('SIM_FEE_OVERRUN', entry=3*U))
            current.reconcile(event('SIM_GAP_LOSS', state='CLOSED', entry=3*U, exit_fee=U, pnl=-1200*U, closed=True))
            check('NEGATIVE_EQUITY_NOT_HIDDEN', current.snapshot()['book_equity_units'], -204*U)
            check('SHORTFALL_VISIBLE', current.snapshot()['shortfall_units'], 204*U)
        snapshot = current.snapshot()
        actual = snapshot['requests'][0]['state']
        book = _book(snapshot)
        record_id, record_digest = _audit(path)
        conserved = _conserved(book)
        matched = (actual == expected and len(checks) == len(CHECKS[case_id])
                   and all(row['matches'] for row in checks)
                   and tuple(book[key] for key in BOOK_KEYS) == EXPECTED_BOOKS[case_id])
        return {'id': case_id, 'label': label, 'scope':public_scope, 'state': 'PASSED' if matched and conserved else 'FAILED',
            'actual_state': actual, 'expected_state': expected, 'matches': matched,
            'conservation_matches': conserved, 'book': book, 'checks': checks,
            'record_id': record_id, 'record_digest': record_digest}
    except Exception:
        # Bounded evidence of a failed scenario; no private exception text/paths.
        return {'id': case_id, 'label': label, 'scope':public_scope, 'state': 'FAILED', 'actual_state': 'SCENARIO_ERROR',
            'expected_state': expected, 'matches': False, 'conservation_matches': False,
            'book': None, 'checks': checks[:3], 'record_id': None, 'record_digest': None}


def _base(state):
    return {'schema': 1, 'engine': 'CAPITAL_PROTOCOL_LAB', 'mode': 'RESEARCH_ONLY',
        'synthetic': True, 'execution_enabled': False, 'autonomy_level': 0,
        'real_account_adapter': False, 'state': state, 'at': _iso(time.time()),
        'report_id': None, 'report_digest': None, 'source_version': None,
        'policy_id': _policy().policy_id, 'policy': None,
        'unit': 'MICRO_USDT', 'units_per_usdt': U, 'scenarios': [], 'limitations': LIMITATIONS.copy()}


def _root(path):
    value = Path(path).absolute()
    for node in (value, *value.parents):
        if node.is_symlink() or getattr(node, 'is_junction', lambda: False)():
            raise ValueError('SYMLINKED_LAB_PATH_REFUSED')
    return value


def run_capital_protocol_lab(output_dir):
    """Run seven closed recipes in new wallets, never an existing run/wallet."""
    root = _root(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    run_id = 'SIM_'+uuid.uuid4().hex
    run = root/run_id
    run.mkdir(exist_ok=False)
    report = _base('PASSED')
    report.update(report_id=run_id, source_version=_source_version(), policy=asdict(_policy()))
    report['scenarios'] = [_scenario(run, recipe) for recipe in RECIPES]
    if any(row['state'] != 'PASSED' for row in report['scenarios']):
        report['state'] = 'FAILED'
    report['report_digest'] = _digest({k: v for k, v in report.items() if k != 'report_digest'})
    raw = _json(report)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError('CAPITAL_LAB_REPORT_SIZE_LIMIT')
    with (run/'report.json').open('xb') as handle:
        handle.write(raw)
    pointer = {'schema': 1, 'report_id': run_id, 'file_sha256': hashlib.sha256(raw).hexdigest()}
    pending = root/(run_id+'.pointer.tmp')
    with pending.open('xb') as handle:
        handle.write(_json(pointer))
    pending.replace(root/'latest.json')
    return json.loads(raw)  # Return the same JSON types used by the RO projection.


def _valid_report(value):
    if not isinstance(value, dict) or set(value) != set(_base('NOT_RUN')):
        return False
    fixed = _base('NOT_RUN')
    for key in ('schema', 'engine', 'mode', 'synthetic', 'execution_enabled',
                'autonomy_level', 'real_account_adapter', 'unit', 'units_per_usdt', 'policy_id', 'limitations'):
        if type(value[key]) is not type(fixed[key]) or value[key] != fixed[key]:
            return False
    if value['state'] not in ('PASSED', 'FAILED') or not RUN_ID.fullmatch(value.get('report_id') or ''):
        return False
    if not HASH.fullmatch(value.get('report_digest') or '') or value['report_digest'] != _digest({k: v for k, v in value.items() if k != 'report_digest'}):
        return False
    if _json(value['policy']) != _json(asdict(_policy())):
        return False
    source = value['source_version']
    if (not isinstance(source, dict) or set(source) != set(_source_version())
            or source['protocol'] != protocol.APP or source['recipe_version'] != RECIPE_VERSION
            or source['recipe_sha256'] != _source_version()['recipe_sha256']
            or any(not isinstance(source[k], str) or not HASH.fullmatch(source[k])
                   for k in ('protocol_sha256', 'lab_sha256', 'recipe_sha256'))):
        return False
    stamp = datetime.fromisoformat(value['at'])
    if stamp.tzinfo is None:
        return False
    rows = value['scenarios']
    if not isinstance(rows, list) or len(rows) != len(RECIPES):
        return False
    for row, (identifier, label, expected) in zip(rows, RECIPES):
        if (not isinstance(row, dict) or set(row) != {'id','label','scope','state','actual_state','expected_state',
                'matches','conservation_matches','book','checks','record_id','record_digest'}
                or (row['id'], row['label'], row['expected_state']) != (identifier, label, expected)
                or row['scope'] != {'scenario_environment':'SHADOW','simulated_account_id':identifier,'currency':'USDT'}
                or row['state'] not in ('PASSED', 'FAILED')
                or row['actual_state'] not in protocol.ORDER_STATES | {'SCENARIO_ERROR'}
                or type(row['matches']) is not bool or type(row['conservation_matches']) is not bool
                or not isinstance(row['checks'], list) or len(row['checks']) != len(CHECKS[identifier])):
            return False
        for check, (check_code, check_expected) in zip(row['checks'], CHECKS[identifier]):
            if (not isinstance(check, dict) or set(check) != {'code','actual','expected','matches'}
                    or check['code'] != check_code or type(check['expected']) is not type(check_expected) or check['expected'] != check_expected
                    or type(check['actual']) not in (str, int, bool) or type(check['expected']) not in (str, int, bool)
                    or len(str(check['actual'])) > 100 or len(str(check['expected'])) > 100
                    or type(check['matches']) is not bool
                    or check['matches'] != (type(check['actual']) is type(check['expected']) and check['actual'] == check['expected'])):
                return False
        if row['book'] is not None and not _conserved(row['book']):
            return False
        if row['conservation_matches'] != _conserved(row['book']):
            return False
        match = (row['actual_state'] == expected and len(row['checks']) == len(CHECKS[identifier])
                 and all(item['matches'] for item in row['checks']) and row['book'] is not None
                 and tuple(row['book'][key] for key in BOOK_KEYS) == EXPECTED_BOOKS[identifier])
        if row['matches'] != match or (row['state'] == 'PASSED') != (match and row['conservation_matches']):
            return False
        if row['book'] is None:
            if row['actual_state'] != 'SCENARIO_ERROR' or row['record_id'] is not None or row['record_digest'] is not None:
                return False
        elif (not isinstance(row['record_id'], str) or not ID.fullmatch(row['record_id'])
              or not isinstance(row['record_digest'], str) or not HASH.fullmatch(row['record_digest'])):
            return False
    return (value['state'] == 'PASSED') == all(row['state'] == 'PASSED' for row in rows)


def capital_protocol_lab_snapshot(output_dir):
    """Read bounded completed report only; absent is NOT_RUN, corrupt is unknown."""
    try:
        root = _root(output_dir)
        pointer_path = root/'latest.json'
        if not pointer_path.exists():
            return _base('NOT_RUN')
        if pointer_path.is_symlink() or pointer_path.stat().st_size > 512:
            raise ValueError('INVALID_LAB_POINTER')
        with pointer_path.open('rb') as handle:
            pointer_raw = handle.read(513)
        if len(pointer_raw) > 512:
            raise ValueError('INVALID_LAB_POINTER')
        pointer = json.loads(pointer_raw)
        if (not isinstance(pointer, dict) or set(pointer) != {'schema','report_id','file_sha256'}
                or type(pointer['schema']) is not int or pointer['schema'] != 1
                or not isinstance(pointer['report_id'], str) or not RUN_ID.fullmatch(pointer['report_id'])
                or not isinstance(pointer['file_sha256'], str) or not HASH.fullmatch(pointer['file_sha256'])):
            raise ValueError('INVALID_LAB_POINTER')
        run = root/pointer['report_id']
        if run.is_symlink() or getattr(run, 'is_junction', lambda: False)():
            raise ValueError('INVALID_LAB_RUN')
        path = run/'report.json'
        if path.is_symlink() or path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError('INVALID_LAB_REPORT')
        with path.open('rb') as handle:
            raw = handle.read(MAX_REPORT_BYTES+1)
        value = json.loads(raw)
        if (len(raw) > MAX_REPORT_BYTES or hashlib.sha256(raw).hexdigest() != pointer['file_sha256']
                or not isinstance(value, dict) or _json(value) != raw
                or value.get('report_id') != pointer['report_id'] or not _valid_report(value)):
            raise ValueError('INVALID_LAB_REPORT')
        return value
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return _base('UNAVAILABLE')

