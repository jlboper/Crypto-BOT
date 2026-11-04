"""Bounded Testnet/Demo outcome sources, separate from LIVE and execution.

The default producer retains encrypted originals and explicit qualification gaps.
Only an explicitly injected, reviewed source materializer can reconstruct exact
cohort boundaries. A successful current GET never becomes a historical cut.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from .account_inventory import TestnetReadOnlyTransport, InventoryError, InventoryHTTPError, HOSTS, SYMBOL
from .financial_capture import _directory, _save_cipher, _load_cipher, dpapi_unprotect
from .financial_evidence import AUTHORITY, build_financial_receipt, canonical, digest
from .financial_evidence_io import _atomic_anchor, _writer_lock, ingest_financial_files
from .live_account import dpapi_protect
from .migration_evidence import register_forward_cohort, evaluate_forward_cohort
from .operational_cohort import OperationalCohortStore, FLAGS, iso, fingerprints_for_config
from .testnet_financial_materializer import reconcile_testnet_sources

ENVIRONMENTS = {'SPOT_TESTNET':'SPOT', 'FUTURES_DEMO':'FUTURES'}
GAPS = ('ALL_ACCOUNT_SOURCE_COVERAGE_UNPROVEN', 'EXACT_BOUNDARY_RECONSTRUCTION_REQUIRED',
        'LEDGER_FILL_IDENTITY_MAPPING_REQUIRED', 'PROTECTION_INTERVALS_UNPROVEN',
        'BOUNDED_CAPTURE_DOES_NOT_BACKFILL_EVERY_OPERATIONAL_RECEIPT')
HISTORY_ENDPOINTS = {'/api/v3/myTrades', '/fapi/v1/userTrades', '/fapi/v1/income'}
MAX_PLAN = 512


def _read_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
    deadline = time.monotonic()+.5
    db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    return db


def read_ledger_cut(path, environment, *, at, since):
    """Retain actual local rows without constructing or migrating a ledger."""
    spot = environment == 'SPOT_TESTNET'
    table, stamp = ('trades','created_at') if spot else ('forward_trades','closed_at')
    position = 'positions' if spot else 'forward_position'
    equity = 'equity' if spot else 'forward_equity'
    protection = 'spot_native_protection' if spot else 'forward_native_protection'
    with closing(_read_db(path)) as db:
        db.execute('BEGIN')
        positions = [dict(r) for r in db.execute(f'SELECT * FROM {position} LIMIT 1025')]
        trades = [dict(r) for r in db.execute(
            f'SELECT * FROM {table} WHERE {stamp}>=? ORDER BY {stamp},id LIMIT 1025',(since,))]
        last = db.execute(f'SELECT * FROM {equity} ORDER BY id DESC LIMIT 1').fetchone()
        native = db.execute('SELECT value FROM settings WHERE key=?',(protection,)).fetchone()
    if max(len(positions),len(trades))>1024:
        raise ValueError('TESTNET_LEDGER_SOURCE_LIMIT')
    # Settings are restricted to the native-protection journal; no arbitrary
    # settings, environment values or credentials enter retained source rows.
    return {'at':iso(at),'environment':environment,'positions':positions,'trades':trades,
            'latest_equity':dict(last) if last else None,
            'native_protection':json.loads(native['value']) if native else None,
            'scope':'LOCAL_LEDGER_ONLY','complete_account_certificate':False}


def read_next_original(cohort_path, environment, *, after, at, latest=False):
    """Read a chained prospective receipt, ignoring cached financial bits.

    The explicit legacy default remains oldest-first. The bounded operating
    producer selects latest-first so its limited GET budget cannot create an
    ever-growing diagnostic queue. Neither selection proves skipped coverage.
    """
    if type(latest) is not bool:
        raise ValueError('EXPLICIT_ORIGINAL_SELECTION_BOOLEAN_REQUIRED')
    store = OperationalCohortStore(cohort_path)
    if not store.path.is_file():
        return None
    chain = store.verify_chain()
    if chain.get('state') != 'VALID_LOCAL_CHAIN':
        raise ValueError('TESTNET_OPERATIONAL_CHAIN_INVALID')
    with closing(_read_db(cohort_path)) as db:
        row = db.execute('SELECT digest,registration FROM cohorts WHERE environment=? '
                         'ORDER BY registered DESC,rowid DESC LIMIT 1',(environment,)).fetchone()
        if row is None:
            return None
        reg = json.loads(row['registration']); cohort = register_forward_cohort(reg)
        order = 'DESC' if latest else 'ASC'
        candidates = db.execute(f'SELECT payload FROM receipts WHERE cohort=? ORDER BY slot {order} LIMIT 50000',
                                (cohort.digest,))
        for candidate in candidates:
            original = json.loads(candidate['payload'])
            if original['interval_start'] < iso(after):
                continue
            temporal = {**original,**{key:True for key in FLAGS}}
            if original.get('source_complete') is not True or evaluate_forward_cohort(
                    reg,[temporal],now=iso(at),expected_digest=cohort.digest)['valid_receipts'] != 1:
                continue
            observation = db.execute('SELECT sequence,at,payload FROM observations WHERE hash=? AND cohort=? '
                                     "AND kind='CAPTURE'",(original['evidence_digest'],cohort.digest)).fetchone()
            if observation is None or original['received_at'] != iso(observation['at']):
                raise ValueError('TESTNET_OPERATIONAL_RECEIPT_NOT_CHAINED')
            prior = db.execute("SELECT at,payload FROM observations WHERE cohort=? AND kind='CAPTURE' "
                               'AND sequence<? ORDER BY sequence DESC LIMIT 1',
                               (cohort.digest,observation['sequence'])).fetchone()
            current_payload = json.loads(observation['payload'])
            start = datetime.fromisoformat(original['interval_start'].replace('Z','+00:00')).timestamp()
            continuous = (prior is not None and prior['at'] <= start+cohort.max_receipt_delay_seconds
                          and observation['at']-prior['at'] <= cohort.cadence_seconds+cohort.max_receipt_delay_seconds)
            prior_payload = json.loads(prior['payload']) if prior else {}
            expected = {key:current_payload.get(key) is True and prior_payload.get(key) is True and continuous for key in FLAGS}
            if any(original.get(key) is not expected[key] for key in FLAGS):
                raise ValueError('TESTNET_OPERATIONAL_RECEIPT_REPLAY_MISMATCH')
            return reg, original
    return None


def read_current_original(cohort_path, environment, *, after, at):
    """Select the latest valid new window; do not replay the historical queue."""
    return read_next_original(cohort_path,environment,after=after,at=at,latest=True)


class TestnetFinancialCaptureService:
    """Cooperative service used by the one existing financial capture thread.

    ``materializer`` is a trusted source adapter, not a user approval flag. It
    receives retained originals and must return an exact canonical bundle or
    None. The installed default has no materializer and claims no qualification.
    """
    def __init__(self, credential_source, data_dir, *, ledger_paths, symbols,
                 clock=time.time, protect=dpapi_protect, unprotect=dpapi_unprotect,
                 materializer=None, transport_factory=TestnetReadOnlyTransport,
                 ledger_reader=read_ledger_cut, original_reader=read_current_original,
                 expected_fingerprints=None):
        if not callable(credential_source) or materializer is not None and not callable(materializer):
            raise ValueError('EXPLICIT_TESTNET_SOURCE_CALLBACK_REQUIRED')
        if set(ledger_paths) != set(symbols) or not set(symbols) <= set(ENVIRONMENTS):
            raise ValueError('EXPLICIT_TESTNET_CAPTURE_SCOPES_REQUIRED')
        if any(type(items) not in (list,tuple) or not 1 <= len(items) <= 100
               or any(type(s) is not str or not SYMBOL.fullmatch(s) for s in items)
               or len(set(items)) != len(items) for items in symbols.values()):
            raise ValueError('EXPLICIT_TESTNET_SYMBOL_UNIVERSE_REQUIRED')
        self.source, self.data = credential_source, Path(data_dir).resolve()
        self.directory = self.data/'testnet-financial-capture'
        self.ledger_paths, self.symbols = {s:Path(p) for s,p in ledger_paths.items()}, {s:sorted(v) for s,v in symbols.items()}
        self.clock, self.protect, self.unprotect = clock, protect, unprotect
        self.materializer, self.transport_factory = materializer, transport_factory
        self.ledger_reader, self.original_reader = ledger_reader, original_reader
        self.expected_fingerprints = expected_fingerprints

    def _save(self, state):
        _save_cipher(self.directory/'controller.dpapi',state,self.protect)

    def _state(self):
        path = self.directory/'controller.dpapi'
        state = _load_cipher(path,self.unprotect) if path.exists() else {
            'schema':1,'symbols':self.symbols,'scopes':{},'sequence':0,'next_scope':0,'not_before_ms':0}
        if state.get('schema') != 1 or state.get('symbols') != self.symbols:
            raise ValueError('TESTNET_CAPTURE_SCOPE_CHANGED')
        return state

    def _fetch(self, state, transport, scope, endpoint, params):
        state['sequence'] += 1; self._save(state)
        started = int(self.clock()*1000)
        original = {'schema':1,'environment':scope,'host':HOSTS[scope], 'endpoint':endpoint,
                    'params':params,'started_ms':started}
        try:
            original['response'] = transport.get(scope,endpoint,params)
        except InventoryError as error:
            code = str(error)
            original['failure'] = code if re.fullmatch('[A-Z0-9_]{1,80}',code) else 'TESTNET_GET_UNKNOWN'
            if isinstance(error, InventoryHTTPError):
                original['http_status'], original['provider_code'] = error.http_status, error.provider_code
        original['received_ms'] = int(self.clock()*1000)
        folder = _directory(self.directory/scope/'responses')
        path = folder/f'{state["sequence"]:012d}.dpapi'
        if path.exists():
            raise ValueError('TESTNET_IMMUTABLE_SOURCE_ALREADY_EXISTS')
        _save_cipher(path,original,self.protect)
        reference = {'file':str(path.relative_to(self.directory/scope)).replace('\\','/'),
                     'sha256':digest(original), 'encrypted_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        if original.get('failure') == 'RATE_LIMITED':
            state['not_before_ms'] = int(self.clock()*1000)+300000; self._save(state)
        return original, reference

    def _open_source(self, scope, ref):
        if type(ref) is not dict or set(ref) != {'file','sha256','encrypted_sha256'} or not re.fullmatch(r'responses/[0-9]{12}\.dpapi',ref['file']):
            raise ValueError('TESTNET_SOURCE_REFERENCE_INVALID')
        path = self.directory/scope/ref['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref['encrypted_sha256']:
            raise ValueError('TESTNET_SOURCE_CIPHER_CHANGED')
        raw = _load_cipher(path,self.unprotect)
        if digest(raw) != ref['sha256'] or raw.get('environment') != scope or raw.get('host') != HOSTS[scope]:
            raise ValueError('TESTNET_SOURCE_SCOPE_OR_CONTENT_CHANGED')
        return raw

    @staticmethod
    def _base_plan(scope):
        return [('/api/v3/account',{}),('/api/v3/openOrders',{}),('/api/v3/openOrderList',{})] if scope == 'SPOT_TESTNET' else [
            ('/fapi/v3/account',{}),('/fapi/v3/balance',{}),('/fapi/v1/openOrders',{}),('/fapi/v1/openAlgoOrders',{})]

    def _identity(self, scope, sources):
        identities=set()
        if scope == 'SPOT_TESTNET':
            for source in sources:
                if source['endpoint'] != '/api/v3/account':continue
                raw=source.get('response')
                uid = raw.get('uid') if type(raw) is dict else None
                if type(uid) in (str,int) and re.fullmatch('[0-9]{1,30}',str(uid)):
                    identities.add(digest({'environment':scope,'reported_uid':str(uid)}))
                else:return None
        else:
            for source in sources:
                if source['endpoint'] != '/fapi/v3/balance':continue
                rows=source.get('response')
                if type(rows) is not list or not rows or not all(type(r) is dict for r in rows):return None
                aliases = {r.get('accountAlias') for r in rows if type(r.get('accountAlias')) is str and 1 <= len(r['accountAlias']) <= 128}
                if len(aliases)!=1 or not all(r.get('accountAlias') in aliases for r in rows):return None
                identities.add(digest({'environment':scope,'reported_account_alias':next(iter(aliases))}))
        if len(identities)>1:raise ValueError('TESTNET_REPORTED_ACCOUNT_CHANGED')
        return next(iter(identities)) if identities else None

    def _extend_ledger_symbols(self, scope, active):
        """Include actual local activity, without claiming a whole account."""
        if active.get('ledger_symbols_added'):
            return
        rows = active['closing_ledger']
        symbols = set(self.symbols[scope])
        for row in rows.get('positions', []) + rows.get('trades', []):
            symbol = row.get('symbol')
            if type(symbol) is not str or not SYMBOL.fullmatch(symbol):
                raise ValueError('TESTNET_LEDGER_SYMBOL_INVALID')
            symbols.add(symbol)
        if len(symbols) > 100:
            raise ValueError('TESTNET_OBSERVED_SYMBOL_LIMIT')
        endpoint = '/api/v3/myTrades' if scope == 'SPOT_TESTNET' else '/fapi/v1/userTrades'
        template = next(params for route, params in active['plan'] if route == endpoint)
        active['plan'] += [(endpoint, {**template, 'symbol': symbol})
                           for symbol in sorted(symbols - set(self.symbols[scope]))]
        active['ledger_symbols_added'] = True

    @staticmethod
    def _split_full_page(active, raw):
        """Retain the full parent and query disjoint inclusive child windows.

        A full page in a single millisecond or a bounded plan limit remains an
        explicit gap. An empty child proves only that requested symbol/time.
        """
        if (raw['endpoint'] not in HISTORY_ENDPOINTS or type(raw.get('response')) is not list
                or len(raw['response']) != 1000):
            return
        params = raw['params']; start, end = params['startTime'], params['endTime']
        entry = {'endpoint': raw['endpoint'], 'params': params, 'children': []}
        active.setdefault('history_partitions', []).append(entry)
        if start >= end or len(active['plan']) + 2 > MAX_PLAN:
            entry['gap'] = 'TESTNET_HISTORY_DENSE_OR_PARTITION_LIMIT'
            return
        middle = (start + end) // 2
        entry['children'] = [{**params, 'endTime': middle}, {**params, 'startTime': middle + 1}]
        active['plan'] += [(raw['endpoint'], child) for child in entry['children']]

    def _retain_window(self, state, scope, item):
        active = item['active']; reg, original = active['registration'], active['original']
        refs = item['baseline']['refs']+active['refs']
        sources = [self._open_source(scope,ref) for ref in refs]
        reasons = set(GAPS)
        if any('failure' in raw for raw in sources): reasons.add('TESTNET_GET_SOURCE_UNAVAILABLE')
        if any(type(raw.get('response')) is list and len(raw['response']) == 1000 for raw in sources):
            reasons.add('TESTNET_HISTORY_PAGE_REQUIRES_SPLIT')
        account_ref = self._identity(scope,sources)
        if account_ref is None: reasons.add('TESTNET_REPORTED_ACCOUNT_IDENTITY_MISSING')
        scope_dir = _directory(self.directory/scope)
        binding = {'schema':1,'environment':scope,'cohort_digest':register_forward_cohort(reg).digest,
            'account_ref':account_ref,'unit_scale':8,'identity_state':'REPORTED' if account_ref else 'UNKNOWN',**AUTHORITY}
        binding_path = scope_dir/'binding.json'
        retained_binding = _directory(scope_dir/'bindings')/(binding['cohort_digest']+'.json')
        # UNKNOWN is an observation gap, not an immutable account assignment.
        # Retain its source window, but allow later consistently reported cuts
        # to establish the first durable binding for this same cohort.
        if account_ref is not None:
            if retained_binding.exists() and json.loads(retained_binding.read_text()) != binding:
                raise ValueError('TESTNET_RETAINED_BINDING_CHANGED')
            if not retained_binding.exists():_atomic_anchor(retained_binding,binding)
        if binding_path.exists():
            old = json.loads(binding_path.read_text())
            if old.get('account_ref') not in (None,account_ref):
                raise ValueError('TESTNET_REPORTED_ACCOUNT_CHANGED')
        _atomic_anchor(binding_path,binding)
        packet = {'schema':1,'environment':scope,'registration':reg,'original':original,
            'baseline':item['baseline'],'closing_ledger':active['closing_ledger'],
            'source_refs':refs,'sources':sources,'symbol_universe':sorted({params['symbol']
                for endpoint,params in active['plan'] if endpoint in HISTORY_ENDPOINTS and 'symbol' in params}),
            'history_partitions':active.get('history_partitions',[]),
            'selection_scope':active.get('selection_scope','RETAINED_IN_FLIGHT_OPERATIONAL_WINDOW'),
            'source_scope':'BOUNDED_SYMBOLS','reason_codes':sorted(reasons),**AUTHORITY}
        folder = _directory(scope_dir/'windows'/digest(original))
        source_path = folder/'sources.dpapi'
        if source_path.exists():
            if _load_cipher(source_path,self.unprotect) != packet:
                raise ValueError('TESTNET_RETAINED_SOURCE_WINDOW_CHANGED')
        else:
            _save_cipher(source_path,packet,self.protect)
        diagnostic = reconcile_testnet_sources(deepcopy(packet))
        # Private normalized quantities and exchange IDs never enter status.json.
        # This independent diagnostic does not confer canonical window coverage.
        diagnostic_path = folder/'reconciliation.dpapi'
        if diagnostic_path.exists():
            if _load_cipher(diagnostic_path,self.unprotect) != diagnostic:
                raise ValueError('TESTNET_RETAINED_SOURCE_DIAGNOSTIC_CHANGED')
        else:
            _save_cipher(diagnostic_path,diagnostic,self.protect)
        outcome = {'state':'RAW_CAPTURED_QUALIFICATION_BLOCKED','reason_codes':sorted(reasons),
                   'packet_received':False,'financial_window_complete':False,**AUTHORITY}
        if self.materializer is not None and account_ref is not None and not any('failure' in r for r in sources):
            bundle = self.materializer(deepcopy(packet))
            if bundle is not None:
                if (type(bundle) is not dict or bundle.get('account_ref') != account_ref
                        or bundle.get('environment') != scope or bundle.get('unit_scale') != 8):
                    raise ValueError('TESTNET_MATERIALIZER_SCOPE_CHANGED')
                if any(bundle.get(name,{}).get('coverage',{}).get('scope') == 'ALL_ACCOUNT'
                       for name in ('ledger','exchange')):
                    # This producer enumerates an explicit symbol universe.
                    # A callback cannot silently promote it to a whole account.
                    raise ValueError('TESTNET_MATERIALIZER_CANNOT_EXPAND_SOURCE_SCOPE')
                checked = build_financial_receipt(reg,original,bundle,now=iso(self.clock()))
                if checked.get('cohort_digest') != binding['cohort_digest']:
                    raise ValueError('TESTNET_MATERIALIZER_PACKET_INVALID')
                # The callback is part of reviewed application code. Retain its
                # full result alongside provider originals, never a UI boolean.
                _save_cipher(folder/'materialized.dpapi',{'bundle':bundle,'checked':checked},self.protect)
                with tempfile.TemporaryDirectory(prefix='materialize-',dir=scope_dir) as temporary:
                    files = []
                    for name,value in (('registration',reg),('original',original),('bundle',bundle)):
                        p=Path(temporary)/(name+'.json');p.write_text(canonical(value),encoding='ascii');files.append(p)
                    outcome = ingest_financial_files(*files,
                        journal_path=scope_dir/'financial-evidence.sqlite3',
                        anchor_path=scope_dir/'financial-evidence.anchor.json',clock=lambda:iso(self.clock()))
                outcome['reason_codes'] = checked['reason_codes']
        outcome['reason_codes'] = sorted(set(outcome.get('reason_codes',())) | reasons)
        _atomic_anchor(scope_dir/'status.json',{'schema':1,'environment':scope,'at':iso(self.clock()),
            'source_window_retained':True,'source_window_ref':digest(original),
            'selection_scope':packet['selection_scope'],
            'source_reconciliation':diagnostic['summary'],**outcome})
        item['retained_windows'] = item.get('retained_windows',0)+1
        item['last'] = outcome
        item['after'] = datetime.fromisoformat(original['interval_end'].replace('Z','+00:00')).timestamp()
        # The previous actual closing observations become the next baseline.
        # They keep their original request/receipt timestamps across restarts.
        item['baseline'] = {'refs':active['refs'][:len(self._base_plan(scope))],
                            'ledger':active['closing_ledger'], 'at':active['closed_at']}
        item['active'] = None
        self._save(state)

    def tick(self, *, max_calls=16, should_stop=None):
        if type(max_calls) is not int or not 1 <= max_calls <= 192 or should_stop is not None and not callable(should_stop):
            raise ValueError('BOUNDED_TESTNET_CAPTURE_TICK_REQUIRED')
        stopping = lambda:should_stop is not None and should_stop()
        public = {'schema':1,'mode':'TESTNET_DEMO_FINANCIAL_SOURCE_CAPTURE','state':'TESTNET_CAPTURE_BLOCKED',
            'automatic_source_producer':True,'financial_window_complete':False,**AUTHORITY}
        if stopping(): return {**public,'state':'CAPTURE_STOP_REQUESTED'}
        try:
            _directory(self.directory)
            with _writer_lock(self.directory/'controller.lock'):
                state = self._state()
                if state['not_before_ms'] > int(self.clock()*1000):
                    return {**public,'state':'TESTNET_RATE_LIMITED','not_before_ms':state['not_before_ms']}
                credentials = self.source()  # Secrets loaded only on this worker.
                credentials = {s:p for s,p in credentials.items() if s in self.symbols}
                if not credentials: return {**public,'reason_codes':['TESTNET_CREDENTIALS_UNAVAILABLE']}
                transport = self.transport_factory(credentials,max_calls=min(80,max_calls+4),clock=self.clock)
                if type(transport) is not TestnetReadOnlyTransport:
                    raise ValueError('GET_ONLY_TESTNET_TRANSPORT_REQUIRED')
                used = 0; scopes = sorted(credentials)
                # Rotate scopes so a low call budget cannot starve Spot behind Futures.
                order = scopes[state['next_scope']%len(scopes):]+scopes[:state['next_scope']%len(scopes)]
                state['next_scope'] = (state['next_scope']+1)%len(scopes)
                for scope in order:
                    if stopping() or used >= max_calls: break
                    key_hash = digest({'environment':scope,'api_key':credentials[scope][0]})
                    item = state['scopes'].setdefault(scope,{'key_hash':key_hash,'baseline':{'refs':[]},'active':None,'retained_windows':0})
                    if item['key_hash'] != key_hash: raise ValueError('TESTNET_CREDENTIAL_SCOPE_CHANGED')
                    base_plan = self._base_plan(scope)
                    baseline = item['baseline']
                    if len(baseline['refs']) < len(base_plan) or 'ledger' not in baseline:
                        for endpoint,params in base_plan[len(baseline['refs']):]:
                            if used >= max_calls or stopping(): break
                            raw,ref = self._fetch(state,transport,scope,endpoint,params);used+=1
                            if 'failure' in raw:
                                item.setdefault('failed_refs',[]).append(ref);self._save(state)
                                return {**public,'reason_codes':[raw['failure']]}
                            baseline['refs'].append(ref);self._save(state)
                        if len(baseline['refs']) == len(base_plan):
                            baseline['at'] = self.clock()
                            baseline['ledger'] = self.ledger_reader(self.ledger_paths[scope],scope,
                                at=baseline['at'],since=iso(baseline['at']))
                            item['after'] = baseline['at'];self._save(state)
                        continue
                    if item['active'] is None:
                        found = self.original_reader(self.data/'operational-cohorts.sqlite3',scope,
                            after=item.get('after',baseline['at']),at=self.clock())
                        if found is None: continue
                        reg,original = found
                        if self.expected_fingerprints is not None and reg['fingerprints'] != self.expected_fingerprints[scope]:
                            raise ValueError('TESTNET_CURRENT_COHORT_FINGERPRINT_MISMATCH')
                        item['active'] = {'registration':reg,'original':original,'refs':[],'plan':base_plan.copy(),
                            'selection_scope':'LATEST_AVAILABLE_OPERATIONAL_WINDOW'
                                if self.original_reader is read_current_original else 'INJECTED_OPERATIONAL_WINDOW'}
                        active = item['active']
                        start = int(datetime.fromisoformat(original['interval_start'].replace('Z','+00:00')).timestamp()*1000)
                        end = int(datetime.fromisoformat(original['interval_end'].replace('Z','+00:00')).timestamp()*1000)-1
                        endpoint = '/api/v3/myTrades' if scope=='SPOT_TESTNET' else '/fapi/v1/userTrades'
                        active['plan'] += [(endpoint,{'symbol':s,'startTime':start,'endTime':end,'limit':1000}) for s in self.symbols[scope]]
                        if scope=='FUTURES_DEMO': active['plan'].append(('/fapi/v1/income',{'startTime':start,'endTime':end,'limit':1000}))
                        self._save(state)
                    active=item['active']
                    if len(active['refs']) >= len(base_plan) and 'closing_ledger' not in active:
                        active['closed_at']=self.clock()
                        active['closing_ledger']=self.ledger_reader(self.ledger_paths[scope],scope,
                            at=active['closed_at'],since=active['original']['interval_start'])
                        self._save(state)
                    if 'closing_ledger' in active:
                        self._extend_ledger_symbols(scope, active); self._save(state)
                    for endpoint,params in active['plan'][len(active['refs']):]:
                        if used >= max_calls or stopping(): break
                        raw,ref=self._fetch(state,transport,scope,endpoint,params);used+=1
                        if 'failure' in raw:
                            item.setdefault('failed_refs',[]).append(ref);self._save(state)
                            return {**public,'reason_codes':[raw['failure']]}
                        # Publish the consumed source and its child plan in the
                        # same controller checkpoint; a restart cannot skip a
                        # durable full parent whose split was not yet saved.
                        active['refs'].append(ref)
                        self._split_full_page(active,raw)
                        self._save(state)
                        if len(active['refs'])==len(base_plan):
                            active['closed_at']=self.clock()
                            active['closing_ledger']=self.ledger_reader(self.ledger_paths[scope],scope,
                                at=active['closed_at'],since=active['original']['interval_start'])
                            self._extend_ledger_symbols(scope,active)
                            self._save(state)
                    if len(active['refs'])==len(active['plan']) and not stopping():
                        self._retain_window(state,scope,item)
                self._save(state)
                return {**public,'state':'RAW_CAPTURED_QUALIFICATION_BLOCKED' if any(x.get('retained_windows') for x in state['scopes'].values()) else 'PROSPECTIVE_BASELINE_OR_WINDOW_PENDING',
                    'calls_this_run':used,'retained_windows':sum(x.get('retained_windows',0) for x in state['scopes'].values()),
                    'reason_codes':list(GAPS),'history_reset':False}
        except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as error:
            code=str(error)
            return {**public,'reason_codes':[code if re.fullmatch('[A-Z0-9_]{1,80}',code) else 'TESTNET_CAPTURE_SOURCE_UNKNOWN']}


def create_testnet_capture_service(config):
    """No environment, credential read, source directory or network at factory."""
    if getattr(config.bot,'mode',None) != 'testnet': return None
    data=Path(config.bot.database_path).parent
    def credentials():
        result={}
        for scope,key,secret in (
                ('SPOT_TESTNET','BINANCE_API_KEY','BINANCE_API_SECRET'),
                ('FUTURES_DEMO','BINANCE_FUTURES_TESTNET_API_KEY','BINANCE_FUTURES_TESTNET_API_SECRET')):
            a,b=os.getenv(key,''),os.getenv(secret,'')
            if a and b: result[scope]=(a,b)
        return result
    futures=getattr(config,'futures_testnet',None)
    universe=tuple(sorted(set(getattr(futures,'forward_symbols',()))|{'BTCUSDT','ETHUSDT'}))
    paths={'SPOT_TESTNET':Path(config.bot.database_path)}
    if futures is not None and getattr(futures,'enabled',False):
        paths['FUTURES_DEMO']=Path(futures.database_path)
    expected={}
    for scope in paths:
        value=fingerprints_for_config(config,ENVIRONMENTS[scope])
        value['configuration']=digest({'supplied_configuration':value['configuration'],
            'source_max_age_seconds':900,'local_capture_schema':1})
        expected[scope]=value
    return TestnetFinancialCaptureService(credentials,data,
        ledger_paths=paths,symbols={scope:universe for scope in paths},expected_fingerprints=expected)
