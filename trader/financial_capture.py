"""Resumable encrypted financial sources; no trading or account certification."""
from __future__ import annotations
import base64
import ctypes
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import time
from .financial_evidence import AUTHORITY, canonical
from .financial_evidence_io import _atomic_anchor, _path, _writer_lock
from .live_account import dpapi_protect
from .live_transport import LiveError, LiveHTTPError, LiveReadOnlyTransport, SYMBOL, SPOT_TRANSFER_TYPES, SIMPLE_EARN_READ

MAX_STATE=16*1024*1024
MAX_RECORDS=50000
# Source rows remain segregated from operational ledgers and admission facts.
DAY=86400000
# Account inventories now include exchange-listed CJK asset names. Preserve
# their exact spelling in read-only arithmetic; this never expands symbols or
# permits an order. Controls, separators, lowercase/confusables stay rejected.
ASSET=re.compile(r'[A-Z0-9\u3400-\u9fff]{1,24}\Z')


def dpapi_unprotect(raw):
    if os.name!='nt':raise LiveError('WINDOWS_DPAPI_REQUIRED_FOR_RAW_RETENTION')
    class Blob(ctypes.Structure):
        _fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    source,target=Blob(len(raw),buffer),Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    crypt.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype=ctypes.c_int
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not crypt.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise LiveError('LIVE_RAW_DECRYPTION_FAILED')
    try:
        if not 1<=target.size<=MAX_STATE:raise LiveError('BOUNDED_CAPTURE_RECORD_REQUIRED')
        return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)


def _number(value):
    if type(value) not in {str,int} or len(str(value))>64:raise LiveError('INVALID_CAPTURE_AMOUNT')
    try:
        result=Decimal(value)
        if not result.is_finite() or abs(result)>Decimal('1e24') or result.as_tuple().exponent < -18:raise ValueError()
        return result
    except (ValueError,InvalidOperation):raise LiveError('INVALID_CAPTURE_AMOUNT') from None


def _asset(value):
    if type(value) is not str or not ASSET.fullmatch(value):raise LiveError('UNRECOGNIZED_CAPTURE_ASSET')
    return value


def _stamp(value):
    if type(value) is not int or not 0<value<253402300799000:raise LiveError('INVALID_CAPTURE_TIMESTAMP')
    return value


def _identity(value):
    if type(value) not in {int,str} or not 1<=len(str(value))<=128 or type(value) is int and value<0:raise LiveError('INVALID_CAPTURE_IDENTITY')
    return str(value)


def _balances(scope,raw):
    if type(raw) is not dict or 'code' in raw or 'msg' in raw:raise LiveError('INVALID_CAPTURE_ACCOUNT')
    rows=raw.get('balances' if scope=='SPOT_LIVE' else 'assets')
    if type(rows) is not list or len(rows)>10000:raise LiveError('INVALID_CAPTURE_ACCOUNT')
    result={}
    with localcontext() as context:
        context.prec=80
        for row in rows:
            asset=_asset(row['asset'])
            if asset in result:raise LiveError('DUPLICATE_CAPTURE_BALANCE')
            result[asset]=_number(row['free'])+_number(row['locked']) if scope=='SPOT_LIVE' else _number(row['walletBalance'])
    return result


def _directory(directory):
    supplied=Path(directory).absolute()
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (supplied,*supplied.parents)):
        raise LiveError('REGULAR_LOCAL_CAPTURE_DIRECTORY_REQUIRED')
    target=supplied.resolve()
    if any((p/'.git').exists() for p in (target,*target.parents)):raise LiveError('LIVE_EVIDENCE_MUST_BE_OUTSIDE_GIT')
    target.mkdir(parents=True,exist_ok=True)
    return target


def _save_cipher(path,value,protect):
    raw=canonical(value).encode('ascii')
    if len(raw)>MAX_STATE:raise LiveError('CAPTURE_STORAGE_BUDGET_EXHAUSTED')
    cipher=protect(raw)
    if type(cipher) is not bytes or not cipher or cipher==raw or len(cipher)>MAX_STATE+65536:raise LiveError('LIVE_RAW_ENCRYPTION_REQUIRED')
    _atomic_anchor(_path(path),{'cipher':base64.b64encode(cipher).decode('ascii')})


def _load_cipher(path,unprotect):
    path=_path(path,existing=True)
    if path.stat().st_size>(MAX_STATE+65536)*2:raise LiveError('BOUNDED_CAPTURE_RECORD_REQUIRED')
    envelope=json.loads(path.read_bytes())
    if type(envelope) is not dict or set(envelope)!={'cipher'}:raise LiveError('INVALID_CAPTURE_CHECKPOINT')
    raw=unprotect(base64.b64decode(envelope['cipher'],validate=True))
    if type(raw) is not bytes or not 1<=len(raw)<=MAX_STATE:raise LiveError('INVALID_CAPTURE_CHECKPOINT')
    return json.loads(raw)


class FinancialCapture:
    def __init__(self,transport,directory,*,symbols,start_utc_ms,end_utc_ms,clock=time.time,page_size=1000,protect=dpapi_protect,unprotect=dpapi_unprotect,capture_current=True):
        if type(transport) is not LiveReadOnlyTransport:raise LiveError('LIVE_GET_ONLY_TRANSPORT_REQUIRED')
        universes = symbols if type(symbols) is dict else {scope: symbols for scope in transport._credentials}
        if (set(universes) != set(transport._credentials) or any(
                type(items) not in {list, tuple} or not 1 <= len(items) <= 100
                or any(type(s) is not str or not SYMBOL.fullmatch(s) for s in items)
                or len(set(items)) != len(items) for items in universes.values())):
            raise LiveError('EXPLICIT_CAPTURE_SYMBOLS_REQUIRED')
        if any(type(v) is not int for v in (start_utc_ms,end_utc_ms)) or not 0<start_utc_ms<end_utc_ms<=int(clock()*1000) or end_utc_ms-start_utc_ms>DAY:raise LiveError('CAPTURE_WINDOW_MAX_ONE_DAY')
        if type(page_size) is not int or not 1<=page_size<=1000:raise LiveError('CAPTURE_PAGE_SIZE_REQUIRED')
        if type(capture_current) is not bool:raise LiveError('EXPLICIT_CAPTURE_CURRENT_FLAG_REQUIRED')
        self.directory=_directory(directory)
        self.path=_path(self.directory/'capture.dpapi');self.lock=_path(self.directory/'capture.lock')
        self.transport,self.clock=transport,clock
        self.protect,self.unprotect=protect,unprotect
        normalized = {scope: sorted(items) for scope, items in universes.items()} if type(symbols) is dict else sorted(symbols)
        self.spec={'schema':1,'start':start_utc_ms,'end':end_utc_ms,'symbols':normalized,'page_size':page_size,'keys':{s:p.fingerprint() for s,p in transport._credentials.items()},'capture_current':capture_current}

    def _new(self):
        streams=[]
        for scope in sorted(self.spec['keys']):
            for symbol in (self.spec['symbols'][scope] if type(self.spec['symbols']) is dict else self.spec['symbols']):
                streams.append({'scope':scope,'kind':'trades','params':{'symbol':symbol},'endpoint':'/api/v3/myTrades' if scope=='SPOT_LIVE' else '/fapi/v1/userTrades'})
            if scope=='SPOT_LIVE':
                streams.extend({'scope':scope,'kind':k,'params':{},'endpoint':e} for k,e in [('deposits','/sapi/v1/capital/deposit/hisrec'),('withdrawals','/sapi/v1/capital/withdraw/history')])
                streams.extend({'scope':scope,'kind':'transfers','params':{'type':d},'endpoint':'/sapi/v1/asset/transfer'} for d in sorted(SPOT_TRANSFER_TYPES))
            else:streams.append({'scope':scope,'kind':'income','params':{},'endpoint':'/fapi/v1/income'})
        for s in streams:s.update(pending=[[self.spec['start'],self.spec['end']-1]],records={},done=False,cursor=1 if s['kind']=='transfers' else 0,total=None,reason=None,
            coverage_start_ms=self.spec['start'],coverage_end_ms=self.spec['end'])
        return {'spec':self.spec,'streams':streams,'originals':[],'snapshots':{},'finished':False,'next_stream':0}

    def _save(self,state):
        _save_cipher(self.path,state,self.protect)

    def _load(self):
        if not self.path.exists():return self._new()
        state=_load_cipher(self.path,self.unprotect)
        if type(state) is not dict or state.get('spec')!=self.spec:raise LiveError('CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED')
        return state

    def _get(self,state,scope,endpoint,params):
        started=int(self.clock()*1000)
        try:
            value=self.transport.get(scope,endpoint,params)
        except LiveHTTPError as error:
            state['originals'].append({'scope':scope,'endpoint':endpoint,'params':params,'started':started,
                'received':int(self.clock()*1000),'failure':{'code':str(error),**error.diagnostics()}})
            self._save(state)
            raise
        received=int(self.clock()*1000)
        original={'scope':scope,'endpoint':endpoint,'params':params,'started':started,'received':received,'response':value}
        state['originals'].append(original)
        if len(state['originals'])>10000:raise LiveError('CAPTURE_STORAGE_BUDGET_EXHAUSTED')
        self._save(state)
        return value,original

    @staticmethod
    def _parse_row(stream,row,start,end):
        kind=stream['kind']
        if kind=='trades':
            stamp=_stamp(row.get('time'));identity=_identity(row.get('id'))
            if row.get('symbol')!=stream['params']['symbol'] or type(row.get('isBuyer',row.get('buyer'))) is not bool:raise LiveError('INVALID_CAPTURE_TRADE')
            for key in ('qty','quoteQty','commission'):
                if _number(row[key])<0:raise LiveError('INVALID_CAPTURE_TRADE')
            _asset(row['commissionAsset'])
            if stream['scope']=='FUTURES_LIVE':
                _number(row['realizedPnl'])
                if row.get('marginAsset') is not None:_asset(row['marginAsset'])
        elif kind=='income':
            stamp=_stamp(row.get('time'))
            if type(row.get('incomeType')) is not str or not 1<=len(row['incomeType'])<=64:raise LiveError('INVALID_CAPTURE_INCOME')
            identity=row['incomeType']+':'+_identity(row.get('tranId'))
            _number(row['income']);_asset(row['asset'])
        elif kind=='transfers':
            stamp=_stamp(row.get('timestamp'));identity=_identity(row.get('tranId'))
            if row.get('type')!=stream['params']['type'] or row.get('status') not in {'CONFIRMED','FAILED','PENDING'}:raise LiveError('INVALID_CAPTURE_TRANSFER')
            if _number(row['amount'])<0:raise LiveError('INVALID_CAPTURE_TRANSFER')
            _asset(row['asset'])
        elif kind=='deposits':
            stamp=_stamp(row.get('insertTime'));identity=_identity(row.get('id'))
            if _number(row['amount'])<0:raise LiveError('INVALID_CAPTURE_DEPOSIT')
            _asset(row['coin'])
            if type(row.get('status')) is not int:raise LiveError('INVALID_CAPTURE_DEPOSIT')
        else:
            try:stamp=int(datetime.strptime(row.get('applyTime'),'%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC).timestamp()*1000)
            except (ValueError,TypeError):raise LiveError('WITHDRAWAL_TIMESTAMP_UNKNOWN') from None
            identity=_identity(row.get('id'))
            if _number(row['amount'])<0 or _number(row['transactionFee'])<0:raise LiveError('INVALID_CAPTURE_WITHDRAWAL')
            _asset(row['coin'])
            if type(row.get('status')) is not int:raise LiveError('INVALID_CAPTURE_WITHDRAWAL')
        if not start<=stamp<=end:raise LiveError('CAPTURE_HISTORY_WINDOW_CONTRADICTION')
        return identity

    def _page(self,state,stream):
        start,end=stream['pending'][0];kind=stream['kind']
        limit=min(self.spec['page_size'],100) if kind=='transfers' else self.spec['page_size']
        params=dict(stream['params'],startTime=start,endTime=end)
        params['size' if kind=='transfers' else 'limit']=limit
        if kind=='transfers':params['current']=stream['cursor']
        elif kind in {'deposits','withdrawals'}:params['offset']=stream['cursor']
        value,_=self._get(state,stream['scope'],stream['endpoint'],params)
        total=stream['total']
        if kind=='transfers':
            if type(value) is not dict or type(value.get('total')) is not int or value['total']<0:raise LiveError('INVALID_CAPTURE_TRANSFER_ENVELOPE')
            rows=value.get('rows',[] if value['total']==0 else None)
            if total is not None and value['total']!=total:raise LiveError('CAPTURE_TRANSFER_TOTAL_CHANGED')
            total=value['total']
        else:rows=value
        if type(rows) is not list or len(rows)>limit or any(type(r) is not dict for r in rows):raise LiveError('INVALID_CAPTURE_HISTORY_ROWS')
        parsed={}
        for row in rows:
            identity=self._parse_row(stream,row,start,end)
            if identity in parsed:raise LiveError('DUPLICATE_CAPTURE_HISTORY_ROW')
            parsed[identity]=row
        if kind in {'trades','income'} and len(rows)==limit:
            if start==end:raise LiveError('CAPTURE_TIMESTAMP_SATURATED')
            middle=(start+end)//2;stream['pending'][:1]=[[start,middle],[middle+1,end]]
        else:
            if set(parsed)&set(stream['records']):raise LiveError('CAPTURE_DUPLICATE_OR_CHANGED_HISTORY')
            merged={**stream['records'],**parsed}
            if len(merged)>MAX_RECORDS:raise LiveError('CAPTURE_STORAGE_BUDGET_EXHAUSTED')
            if kind=='transfers':
                count=len(merged)
                if count>total or len(rows)<limit and count!=total:raise LiveError('CAPTURE_TRANSFER_TOTAL_CONTRADICTION')
                done=count==total
            else:done=len(rows)<limit if kind in {'deposits','withdrawals'} else True
            # Validate the whole page before committing normalized rows/cursor.
            stream['records'],stream['total']=merged,total
            if not done:stream['cursor']+=1 if kind=='transfers' else len(rows)
            if done:stream['pending'].pop(0)
        stream['done']=not stream['pending']

    def run(self,*,max_calls=20,should_stop=None):
        if type(max_calls) is not int or not 1<=max_calls<=200:raise LiveError('CAPTURE_CALL_BUDGET_REQUIRED')
        if should_stop is not None and not callable(should_stop):raise LiveError('CAPTURE_STOP_CALLBACK_REQUIRED')
        stopping = lambda: should_stop is not None and should_stop()
        with _writer_lock(self.lock):
            state=self._load()
            if state['finished']:return self._public(state,0)
            if state.get('not_before_ms',0)>int(self.clock()*1000):return self._public(state,0)
            used, failed = 0, set()
            count = len(state['streams'])
            while used < max_calls and not stopping():
                cursor = state.get('next_stream', 0)
                eligible = [i for n in range(count) if not state['streams'][i := (cursor+n) % count]['done'] and i not in failed]
                if not eligible:
                    break
                index = eligible[0]
                stream = state['streams'][index]
                state['next_stream'] = (index+1) % count
                used += 1
                try:
                    self._page(state, stream)
                    stream['reason'] = None
                except (LiveError, KeyError, TypeError, ValueError) as error:
                    code = str(error)
                    stream['reason'] = code if re.fullmatch('[A-Z0-9_]{1,80}', code) else 'CAPTURE_RESPONSE_UNKNOWN'
                    failed.add(index)  # At most one failed attempt per stream/run.
                    if isinstance(error,LiveHTTPError) and error.http_status in {418,429}:
                        state['not_before_ms']=int(self.clock()*1000)+300000
                        self._save(state)
                        return self._public(state,used)
                self._save(state)
            if all(s['done'] for s in state['streams']) and not stopping():
                for scope in sorted(self.spec['keys']) if self.spec['capture_current'] else []:
                    if stopping():return self._public(state,used)
                    if scope not in state['snapshots'] and used<max_calls:
                        used+=1;endpoint='/api/v3/account' if scope=='SPOT_LIVE' else '/fapi/v3/account'
                        try:
                            raw,original=self._get(state,scope,endpoint,{})
                            _balances(scope,raw);state['snapshots'][scope]=original
                        except (LiveError,KeyError,TypeError,ValueError) as error:
                            if isinstance(error,LiveHTTPError) and error.http_status in {418,429}:
                                state['not_before_ms']=int(self.clock()*1000)+300000
                            self._save(state);return self._public(state,used)
                        self._save(state)
                state['finished']=not self.spec['capture_current'] or set(state['snapshots'])==set(self.spec['keys']);self._save(state)
            return self._public(state,used)

    def _public(self,state,calls):
        reasons={'SOURCE_SCOPE_BOUNDED','OPENING_SNAPSHOT_NOT_RETAINED','HISTORICAL_PROTECTIONS_NOT_CAPTURED',
                 'SUBACCOUNT_AND_OTHER_PRODUCT_FLOWS_NOT_CERTIFIED','CURRENT_SNAPSHOT_IS_NOT_HISTORICAL_CUT'}
        reasons.update(s['reason'] for s in state['streams'] if s['reason'])
        if 'FUTURES_LIVE' in self.spec['keys'] and self.spec['start']<int(self.clock()*1000)-89*DAY:reasons.add('FUTURES_RETENTION_HORIZON_EXCEEDED')
        limited=state.get('not_before_ms',0)>int(self.clock()*1000)
        return {'schema':1,'mode':'AUTOMATIC_GET_CAPTURE','state':'CAPTURED_BOUNDED_WINDOW' if state['finished'] else 'CAPTURE_RATE_LIMITED' if limited else 'CAPTURE_PENDING',
            'window_start_ms':self.spec['start'],'window_end_ms':self.spec['end'],'calls_this_run':calls,
            'streams':len(state['streams']),'streams_exhausted':sum(s['done'] for s in state['streams']),
            'retained_responses':sum('response' in row for row in state['originals']),'retained_attempts':len(state['originals']),
            'retained_records':sum(len(s['records']) for s in state['streams']), 'not_before_ms':state.get('not_before_ms',0),
            'raw_encrypted_retention':any('response' in row for row in state['originals']),'automatic_source_producer':True,
            'account_history_complete':False,'ledger_reconciled':False,'financial_window_complete':False,'reason_codes':sorted(reasons),**AUTHORITY}

    def retained(self):
        with _writer_lock(self.lock):return self._load()


def record_time(kind, row):
    if kind == 'withdrawals':
        try:
            return int(datetime.strptime(row['applyTime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC).timestamp()*1000)
        except (ValueError, TypeError, KeyError):
            raise LiveError('WITHDRAWAL_TIMESTAMP_UNKNOWN') from None
    return _stamp(row.get('time', row.get('timestamp', row.get('insertTime'))))


def reconcile_sources(scope, opening, closing, streams):
    """Private asset equations over supplied cuts; this is not a LIVE ledger.

    Exact decimals preserve fees in their original asset. Futures wallet movement
    comes from income; quote notional and commissions are never counted twice.
    A matching supplied equation does not establish complete account coverage.
    """
    if scope not in {'SPOT_LIVE', 'FUTURES_LIVE'}:
        raise LiveError('LIVE_SCOPE_REQUIRED')
    if opening is None or closing is None:
        return {'state': 'UNKNOWN', 'reconciled': False,
                'reason_codes': ['OPENING_OR_CLOSING_CUT_MISSING'], **AUTHORITY}
    relevant = [s for s in streams if s['scope'] == scope]
    required = {'trades', 'income'} if scope == 'FUTURES_LIVE' else {'trades', 'deposits', 'withdrawals', 'transfers'}
    unknown = [] if required <= {s['kind'] for s in relevant} else ['REQUIRED_SOURCE_STREAM_MISSING']
    if scope == 'SPOT_LIVE' and {s.get('params', {}).get('type') for s in relevant if s['kind'] == 'transfers'} != SPOT_TRANSFER_TYPES:
        unknown.append('REQUIRED_TRANSFER_DIRECTION_MISSING')
    with localcontext() as context:
        context.prec = 80
        first, last = _balances(scope, opening), _balances(scope, closing)
        movements, fees, funding, transfers = {}, {}, {}, {}
        trade_fees, trade_pnl, income_fees, income_pnl = {}, {}, {}, {}
        def add(values, asset, amount):
            values[asset] = values.get(asset, Decimal(0)) + amount
        seen = set()
        for stream in relevant:
            if stream['done'] is not True:
                unknown.append('HISTORY_PAGINATION_PENDING')
            for identity, row in stream['records'].items():
                kind = stream['kind']
                key = (kind, stream.get('params', {}).get('symbol'), stream.get('params', {}).get('type'), identity)
                if key in seen:
                    raise LiveError('DUPLICATE_RECONCILIATION_RECORD')
                seen.add(key)
                if kind == 'trades':
                    symbol, asset = row['symbol'], _asset(row['commissionAsset'])
                    fee = _number(row['commission'])
                    add(fees, asset, fee)
                    if scope == 'SPOT_LIVE':
                        direction = 1 if row.get('isBuyer', row.get('buyer')) else -1
                        add(movements, symbol[:-4], direction*_number(row['qty']))
                        add(movements, 'USDT', -direction*_number(row['quoteQty']))
                        add(movements, asset, -fee)
                    else:
                        trade_fees[(symbol, str(row['id']), asset)] = fee
                        # Legacy USDT symbols have USDT margin. Other margin
                        # assets require the provider's explicit marginAsset.
                        margin = row.get('marginAsset', 'USDT')
                        trade_pnl[(symbol, str(row['id']), margin)] = _number(row['realizedPnl'])
                elif kind == 'income':
                    asset, amount, income = _asset(row['asset']), _number(row['income']), row['incomeType']
                    add(movements, asset, amount)
                    if income == 'FUNDING_FEE':
                        add(funding, asset, amount)
                    elif income == 'TRANSFER':
                        add(transfers, asset, amount)
                    elif income in {'COMMISSION', 'REALIZED_PNL'}:
                        key = (row.get('symbol'), str(row.get('tradeId')), asset)
                        add(income_fees if income == 'COMMISSION' else income_pnl, key,
                            -amount if income == 'COMMISSION' else amount)
                    else:
                        unknown.append('UNCLASSIFIED_INCOME_RETAINED')
                elif kind == 'transfers':
                    if row['status'] == 'PENDING':
                        unknown.append('PENDING_TRANSFER')
                    elif row['status'] == 'CONFIRMED':
                        if row['type'] not in SPOT_TRANSFER_TYPES:
                            raise LiveError('UNRECOGNIZED_SPOT_TRANSFER_TYPE')
                        amount = _number(row['amount'])*(1 if row['type'].endswith('_MAIN') else -1)
                        add(movements, row['asset'], amount)
                        add(transfers, row['asset'], amount)
                elif kind in {'deposits', 'withdrawals'}:
                    wallet = row.get('walletType')
                    if type(wallet) is not int or wallet not in {0, 1}:
                        unknown.append('CASHFLOW_WALLET_UNKNOWN')
                        continue
                    if wallet == 1:
                        continue  # Funding-wallet rows are retained, not Spot.
                    if kind == 'deposits':
                        if row['status'] in {1, 6}:
                            add(movements, row['coin'], _number(row['amount']))
                        else:
                            unknown.append('UNSETTLED_DEPOSIT')
                    elif row['status'] == 6:
                        fee = _number(row['transactionFee'])
                        add(movements, row['coin'], -_number(row['amount'])-fee)
                        add(fees, row['coin'], fee)
                        if fee:
                            # The REST schema does not establish whether amount
                            # includes the fee; do not certify this convention.
                            unknown.append('WITHDRAWAL_DEBIT_SEMANTICS_UNKNOWN')
                    elif row['status'] not in {1, 3, 5}:
                        unknown.append('UNSETTLED_WITHDRAWAL')
        differences = {a: last.get(a, Decimal(0))-first.get(a, Decimal(0))-movements.get(a, Decimal(0))
                       for a in set(first) | set(last) | set(movements)}
        if scope == 'FUTURES_LIVE':
            if any(trade_fees.get(k, 0) != income_fees.get(k, 0) for k in set(trade_fees) | set(income_fees)):
                unknown.append('TRADE_COMMISSION_INCOME_MISMATCH')
            if any(trade_pnl.get(k, 0) != income_pnl.get(k, 0) for k in set(trade_pnl) | set(income_pnl)):
                unknown.append('TRADE_REALIZED_PNL_INCOME_MISMATCH')
        different = any(differences.values())
        return {'state': 'DIFFERENCE' if different else 'UNKNOWN' if unknown else 'MATCHED_SUPPLIED_CUTS',
                'reconciled': not different and not unknown,
                'asset_differences': {k: format(v, 'f') for k, v in sorted(differences.items())},
                'fees_by_asset': {k: format(v, 'f') for k, v in sorted(fees.items())},
                'funding_by_asset': {k: format(v, 'f') for k, v in sorted(funding.items())},
                'transfers_by_asset': {k: format(v, 'f') for k, v in sorted(transfers.items())},
                'reason_codes': sorted(set(unknown)), 'account_history_complete': False,
                'ledger_reconciled': False, 'historical_protections_complete': False, **AUTHORITY}


def normalize_daily_snapshots(scope, response, *, start_utc_ms, end_utc_ms):
    if scope not in {'SPOT_LIVE', 'FUTURES_LIVE'}:
        raise LiveError('LIVE_SCOPE_REQUIRED')
    if (type(response) is not dict or type(response.get('code')) is not int or response['code'] != 200
            or type(response.get('snapshotVos')) is not list or len(response['snapshotVos']) > 30):
        raise LiveError('DAILY_SNAPSHOT_RESPONSE_UNKNOWN')
    expected = 'spot' if scope == 'SPOT_LIVE' else 'futures'
    result, seen = [], set()
    for row in response['snapshotVos']:
        stamp = _stamp(row.get('updateTime'))
        if (type(row.get('type')) is not str or row['type'].lower() != expected
                or not start_utc_ms <= stamp <= end_utc_ms or stamp in seen):
            raise LiveError('DAILY_SNAPSHOT_SCOPE_OR_TIME_CHANGED')
        seen.add(stamp)
        raw = row.get('data')
        _balances(scope, raw)
        result.append({'at_ms': stamp, 'account': raw,
                       'source_digest': hashlib.sha256(canonical(row).encode('ascii')).hexdigest()})
    return sorted(result, key=lambda r: r['at_ms'])


class DailySnapshotCapture:
    """Explicit, resumable high-weight baseline capture; never background polling."""
    def __init__(self, transport, directory, *, start_utc_ms, end_utc_ms,
                 clock=time.time, protect=dpapi_protect, unprotect=dpapi_unprotect):
        if type(transport) is not LiveReadOnlyTransport:
            raise LiveError('LIVE_GET_ONLY_TRANSPORT_REQUIRED')
        if (any(type(v) is not int for v in (start_utc_ms, end_utc_ms))
                or not 0 < start_utc_ms < end_utc_ms <= int(clock()*1000)
                or end_utc_ms-start_utc_ms >= 30*DAY):
            raise LiveError('DAILY_SNAPSHOT_WINDOW_REQUIRED')
        self.directory = _directory(directory)
        self.path, self.lock = _path(self.directory/'daily-snapshots.dpapi'), _path(self.directory/'daily-snapshots.lock')
        self.transport, self.clock, self.protect, self.unprotect = transport, clock, protect, unprotect
        self.spec = {'schema': 1, 'start': start_utc_ms, 'end': end_utc_ms,
                     'keys': {s: p.fingerprint() for s, p in transport._credentials.items()}}

    def _load(self):
        state = _load_cipher(self.path, self.unprotect) if self.path.exists() else {
            'spec': self.spec, 'originals': [], 'snapshots': {}, 'errors': {}}
        if type(state) is not dict or state.get('spec') != self.spec:
            raise LiveError('CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED')
        return state

    def run(self, *, max_scopes=1):
        if type(max_scopes) is not int or not 1 <= max_scopes <= 2:
            raise LiveError('SNAPSHOT_SCOPE_BUDGET_REQUIRED')
        with _writer_lock(self.lock):
            state = self._load()
            used = 0
            if state.get('not_before_ms',0)>int(self.clock()*1000):
                return {'schema':1,'state':'DAILY_SNAPSHOTS_RATE_LIMITED','snapshot_calls_this_run':0,
                    'documented_ip_weight_this_run':0,'not_before_ms':state['not_before_ms'],
                    'reason_codes':['LIVE_RATE_LIMITED'],'raw_encrypted_retention':any('response' in row for row in state['originals']),**AUTHORITY}
            for scope in sorted(self.spec['keys']):
                if scope in state['snapshots'] or used >= max_scopes:
                    continue
                used += 1
                try:
                    started = int(self.clock()*1000)
                    response = self.transport.get_account_snapshots(scope,
                        start_utc_ms=self.spec['start'], end_utc_ms=self.spec['end'])
                    state['originals'].append({'scope': scope, 'endpoint': '/sapi/v1/accountSnapshot',
                        'started': started, 'received': int(self.clock()*1000), 'response': response})
                    _save_cipher(self.path, state, self.protect)
                    state['snapshots'][scope] = normalize_daily_snapshots(scope, response,
                        start_utc_ms=self.spec['start'], end_utc_ms=self.spec['end'])
                    state['errors'].pop(scope, None)
                except (ValueError, TypeError, KeyError) as error:
                    code = str(error)
                    state['errors'][scope] = code if re.fullmatch('[A-Z0-9_]{1,80}', code) else 'DAILY_SNAPSHOT_RESPONSE_UNKNOWN'
                    if isinstance(error,LiveHTTPError):
                        state['originals'].append({'scope':scope,'endpoint':'/sapi/v1/accountSnapshot',
                            'started':started,'received':int(self.clock()*1000),
                            'failure':{'code':str(error),**error.diagnostics()}})
                        if error.http_status in {418,429}:
                            state['not_before_ms']=int(self.clock()*1000)+300000
                            _save_cipher(self.path,state,self.protect)
                            break
                _save_cipher(self.path, state, self.protect)
            limited=state.get('not_before_ms',0)>int(self.clock()*1000)
            return {'schema': 1, 'state': 'DAILY_SNAPSHOTS_RETAINED' if set(state['snapshots']) == set(self.spec['keys']) else 'DAILY_SNAPSHOTS_RATE_LIMITED' if limited else 'DAILY_SNAPSHOTS_PENDING',
                'snapshot_calls_this_run': used, 'documented_ip_weight_this_run': used*2400,
                'not_before_ms':state.get('not_before_ms',0),
                'raw_encrypted_retention': any('response' in row for row in state['originals']),
                'snapshots_by_scope': {s: len(rows) for s, rows in state['snapshots'].items()},
                'reason_codes': sorted(set(state['errors'].values())), 'account_history_complete': False,
                'ledger_reconciled': False, **AUTHORITY}

    def retained(self):
        with _writer_lock(self.lock):
            return self._load()


def reconcile_daily_pairs(scope, snapshots, streams):
    """Reconcile only fully captured intervals between original reported cuts."""
    results = []
    for opening, closing in zip(snapshots, snapshots[1:]):
        start, end = opening['at_ms'], closing['at_ms']
        if not start < end:
            raise LiveError('DAILY_SNAPSHOT_ORDER_REQUIRED')
        selected, boundary = [], False
        for stream in streams:
            if stream['scope'] != scope:
                continue
            a, b = stream.get('coverage_start_ms'), stream.get('coverage_end_ms')
            # Jobs are half open. A cut pair needs each component of the union
            # of jobs, including empty jobs, not just rows inside the interval.
            if type(a) is not int or type(b) is not int or not a < end or b <= start:
                continue
            rows = {}
            for identity, row in stream['records'].items():
                stamp = record_time(stream['kind'], row)
                boundary = boundary or stamp in {start, end}
                if start < stamp < end:
                    rows[identity] = row
            selected.append({**stream, 'records': rows})
        result = reconcile_sources(scope, opening['account'], closing['account'], selected)
        groups = {}
        for stream in selected:
            key = (stream['kind'], canonical(stream.get('params', {})))
            groups.setdefault(key, []).append(stream)
        for parts in groups.values():
            cursor = start
            for part in sorted(parts, key=lambda p: p['coverage_start_ms']):
                if part['done'] and part['coverage_start_ms'] <= cursor:
                    cursor = max(cursor, part['coverage_end_ms'])
            if cursor < end:
                result['reason_codes'].append('DAILY_PAIR_SOURCE_WINDOW_GAP')
                result['reconciled'] = False
        if boundary:
            result['reason_codes'].append('DAILY_SNAPSHOT_BOUNDARY_EVENT_UNCERTAIN')
            result['reconciled'] = False
        if result['state'] == 'MATCHED_SUPPLIED_CUTS' and not result['reconciled']:
            result['state'] = 'UNKNOWN'
        result.update(window_start_ms=start, window_end_ms=end,
            opening_source_digest=opening['source_digest'], closing_source_digest=closing['source_digest'])
        result['reason_codes'] = sorted(set(result['reason_codes']))
        results.append(result)
    return results


def reconciliation_summary(result):
    """Public projection: no balances, assets, provider IDs, paths or source rows."""
    return {'state': result['state'], 'matched_supplied_cuts': result['reconciled'],
        'differing_assets': sum(Decimal(v) != 0 for v in result.get('asset_differences', {}).values()),
        'fee_assets_observed': len(result.get('fees_by_asset', {})),
        'funding_assets_observed': len(result.get('funding_by_asset', {})),
        'transfer_assets_observed': len(result.get('transfers_by_asset', {})),
        'reason_codes': list(result['reason_codes']), 'financial_window_complete': False,
        'ledger_reconciled': False, 'account_history_complete': False, **AUTHORITY}


class EarnSourceCapture:
    """Explicit, resumable supplemental Earn GETs with encrypted originals.

    An Earn asset is never relabelled as a Spot/LD asset or operating cash. A
    position response is a contemporaneous cut, not a historical baseline.
    These potentially high-weight endpoints are never called by the worker.
    """
    def __init__(self, transport, directory, *, start_utc_ms, end_utc_ms,
                 clock=time.time, protect=dpapi_protect, unprotect=dpapi_unprotect,
                 page_size=100):
        if type(transport) is not LiveReadOnlyTransport or set(transport._credentials) != {'SPOT_LIVE'}:
            raise LiveError('EXPLICIT_SPOT_GET_ONLY_TRANSPORT_REQUIRED')
        if (any(type(v) is not int for v in (start_utc_ms, end_utc_ms))
                or not 0 < start_utc_ms < end_utc_ms <= int(clock()*1000)
                or end_utc_ms-start_utc_ms > 30*DAY):
            raise LiveError('EARN_FIXED_WINDOW_MAX_THIRTY_DAYS')
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise LiveError('EARN_PAGE_SIZE_REQUIRED')
        self.directory = _directory(directory)
        self.path, self.lock = _path(self.directory/'earn-sources.dpapi'), _path(self.directory/'earn-sources.lock')
        self.transport, self.clock, self.protect, self.unprotect = transport, clock, protect, unprotect
        self.spec = {'schema':1, 'start':start_utc_ms, 'end':end_utc_ms, 'page_size':page_size,
                     'key':transport._credentials['SPOT_LIVE'].fingerprint()}

    def _load(self):
        if self.path.exists():
            state = _load_cipher(self.path, self.unprotect)
            if type(state) is not dict or state.get('spec') != self.spec:
                raise LiveError('CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED')
            return state
        return {'spec':self.spec, 'originals':[], 'not_before_ms':0,
                'streams':{e:{'page':1,'total':None,'records':{},'done':False,'reason':None}
                           for e in sorted(SIMPLE_EARN_READ)}}

    def _save(self, state):
        _save_cipher(self.path, state, self.protect)

    def _parse(self, endpoint, row):
        if type(row) is not dict:
            raise LiveError('EARN_ROW_INVALID')
        asset = _asset(row.get('asset'))
        product = _identity(row.get('productId'))
        if endpoint.endswith('/position'):
            if _number(row.get('totalAmount')) < 0:
                raise LiveError('EARN_ROW_INVALID')
            return canonical([asset, product])
        stamp = _stamp(row.get('time'))
        if not self.spec['start'] <= stamp <= self.spec['end']:
            raise LiveError('EARN_HISTORY_WINDOW_CONTRADICTION')
        if endpoint.endswith('/rewardsRecord'):
            if row.get('type') not in {'BONUS','REALTIME','REWARDS'} or _number(row.get('rewards')) < 0:
                raise LiveError('EARN_ROW_INVALID')
            return canonical([asset, product, row['type'], stamp])
        if _number(row.get('amount')) < 0 or type(row.get('status')) is not str or not 1 <= len(row['status']) <= 40:
            raise LiveError('EARN_ROW_INVALID')
        kind = 'purchaseId' if endpoint.endswith('/subscriptionRecord') else 'redeemId'
        return canonical([asset, product, _identity(row.get(kind))])

    def _page(self, state, endpoint):
        stream = state['streams'][endpoint]
        params = {'current':stream['page'], 'size':self.spec['page_size']}
        if not endpoint.endswith('/position'):
            params.update(startTime=self.spec['start'], endTime=self.spec['end'])
        if endpoint.endswith('/rewardsRecord'):
            params['type'] = 'ALL'
        started = int(self.clock()*1000)
        try:
            raw = self.transport.get_simple_earn(endpoint, params)
        except LiveHTTPError as error:
            state['originals'].append({'scope':'SPOT_LIVE','endpoint':endpoint,'params':params,
                'started':started,'received':int(self.clock()*1000),'failure':{'code':str(error),**error.diagnostics()}})
            self._save(state)
            raise
        state['originals'].append({'scope':'SPOT_LIVE','endpoint':endpoint,'params':params,
            'started':started,'received':int(self.clock()*1000),'response':raw})
        if len(state['originals']) > 10000:
            raise LiveError('CAPTURE_STORAGE_BUDGET_EXHAUSTED')
        self._save(state)  # Retain malformed replies before normalization.
        if (type(raw) is not dict or type(raw.get('total')) is not int or not 0 <= raw['total'] <= MAX_RECORDS
                or type(raw.get('rows')) is not list or len(raw['rows']) > self.spec['page_size']):
            raise LiveError('EARN_ENVELOPE_INVALID')
        if stream['total'] is not None and raw['total'] != stream['total']:
            raise LiveError('EARN_TOTAL_CHANGED')
        parsed = {}
        for row in raw['rows']:
            identity = self._parse(endpoint, row)
            if identity in parsed or identity in stream['records']:
                raise LiveError('EARN_DUPLICATE_OR_CHANGED_ROW')
            parsed[identity] = row
        count = len(stream['records'])+len(parsed)
        if count > raw['total'] or len(raw['rows']) < self.spec['page_size'] and count != raw['total']:
            raise LiveError('EARN_TOTAL_CONTRADICTION')
        stream['records'].update(parsed)
        stream.update(total=raw['total'], done=count == raw['total'], reason=None)
        if not stream['done']:
            stream['page'] += 1

    def run(self, *, max_calls=4):
        if type(max_calls) is not int or not 1 <= max_calls <= 4:
            raise LiveError('EARN_CALL_BUDGET_REQUIRED')
        with _writer_lock(self.lock):
            state, used, failed = self._load(), 0, set()
            while used < max_calls and state.get('not_before_ms',0) <= int(self.clock()*1000):
                available = [e for e,s in state['streams'].items() if not s['done'] and e not in failed]
                if not available:
                    break
                endpoint = available[0]
                used += 1
                try:
                    self._page(state, endpoint)
                except (LiveError, KeyError, TypeError, ValueError) as error:
                    code = str(error)
                    state['streams'][endpoint]['reason'] = code if re.fullmatch('[A-Z0-9_]{1,80}',code) else 'EARN_SOURCE_UNKNOWN'
                    failed.add(endpoint)
                    if isinstance(error, LiveHTTPError) and error.http_status in {418,429}:
                        state['not_before_ms'] = int(self.clock()*1000)+300000
                self._save(state)
            limited = state.get('not_before_ms',0) > int(self.clock()*1000)
            complete = all(s['done'] for s in state['streams'].values())
            return {'schema':1,'mode':'EXPLICIT_SUPPLEMENTAL_EARN_GET',
                'state':'EARN_SOURCES_CAPTURED' if complete else 'EARN_RATE_LIMITED' if limited else 'EARN_CAPTURE_PENDING',
                'calls_this_run':used,'not_before_ms':state.get('not_before_ms',0),
                'documented_endpoint_ip_weight_this_run':150*used,
                'window_start_ms':self.spec['start'],'window_end_ms':self.spec['end'],
                'streams_exhausted':sum(s['done'] for s in state['streams'].values()),
                'rows_by_source':{e.rsplit('/',1)[-1]:len(s['records']) for e,s in state['streams'].items()},
                'raw_encrypted_retention':any('response' in o for o in state['originals']),
                'reason_codes':sorted({'EARN_TO_WRAPPER_IDENTITY_NOT_CERTIFIED','CURRENT_EARN_POSITION_IS_NOT_HISTORICAL_CUT'}
                    | {s['reason'] for s in state['streams'].values() if s['reason']}),
                'account_history_complete':False,'ledger_reconciled':False,'financial_window_complete':False,**AUTHORITY}

    def retained(self):
        with _writer_lock(self.lock):
            return self._load()


class FinancialCaptureService:
    """Prospective cut -> original capture -> normalization -> reconciliation.

    The supervisor runs tick in a background worker with a bounded GET budget.
    A restart resumes the exact retained closing cut, not a new current balance.
    The controller and detailed results remain encrypted outside Git. There is
    no Daily Account Snapshot call here and no trading permission is produced.
    """
    def __init__(self, credential_source, directory, *, symbols, clock=time.time,
                 protect=dpapi_protect, unprotect=dpapi_unprotect, interval_seconds=300):
        if not callable(credential_source):
            raise LiveError('CAPTURE_CREDENTIAL_SOURCE_REQUIRED')
        if type(interval_seconds) is not int or not 60 <= interval_seconds <= 86400:
            raise LiveError('CAPTURE_INTERVAL_REQUIRED')
        if type(symbols) is dict:
            normalized = {scope: sorted(items) for scope, items in symbols.items()}
        elif type(symbols) in {list, tuple}:
            normalized = sorted(symbols)
        else:
            raise LiveError('EXPLICIT_CAPTURE_SYMBOLS_REQUIRED')
        self.source, self.clock, self.symbols = credential_source, clock, normalized
        self.directory = _directory(directory)
        self.path, self.lock = _path(self.directory/'controller.dpapi'), _path(self.directory/'controller.lock')
        self.protect, self.unprotect, self.interval = protect, unprotect, interval_seconds*1000

    def _read(self):
        state = _load_cipher(self.path, self.unprotect) if self.path.exists() else {
            'schema': 1, 'binding': None, 'symbols': self.symbols, 'opening': {}, 'closing': {},
            'active': None, 'next_due': 0, 'completed': 0, 'last': None, 'snapshot_attempts': []}
        if (type(state) is not dict or state.get('schema') != 1 or state.get('symbols') != self.symbols
                or type(state.get('completed')) is not int or state['completed'] < 0):
            raise LiveError('INVALID_CAPTURE_CONTROLLER')
        return state

    def _write(self, state):
        _save_cipher(self.path, state, self.protect)

    def _job(self, transport, active, part):
        return FinancialCapture(transport,
            self.directory/f'window-{active["start"]}-{active["end"]}'/f'part-{part["start"]}',
            symbols=self.symbols, start_utc_ms=part['start'], end_utc_ms=part['end'],
            clock=self.clock, protect=self.protect, unprotect=self.unprotect, capture_current=False)

    def _cut(self, state, target, scope, transport):
        endpoint = '/api/v3/account' if scope == 'SPOT_LIVE' else '/fapi/v3/account'
        started = int(self.clock()*1000)
        try:
            raw = transport.get(scope, endpoint)
        except LiveHTTPError as error:
            state['snapshot_attempts'].append({'scope':scope,'endpoint':endpoint,'params':{},'started':started,
                'received':int(self.clock()*1000),'failure':{'code':str(error),**error.diagnostics()}})
            if error.http_status in {418,429}:state['next_due']=int(self.clock()*1000)+300000
            self._write(state)
            raise
        original = {'scope': scope, 'endpoint': endpoint, 'params': {}, 'started': started,
                    'received': int(self.clock()*1000), 'response': raw}
        if len(state['snapshot_attempts']) >= 1000:
            raise LiveError('CAPTURE_STORAGE_BUDGET_EXHAUSTED')
        state['snapshot_attempts'].append(original)
        self._write(state)  # Preserve even a response rejected by the parser.
        _balances(scope, raw)
        target[scope] = original
        self._write(state)

    def _finish(self, state, transport):
        active = state['active']
        streams = []
        for part in active['parts']:
            streams.extend(self._job(transport, active, part).retained()['streams'])
        private, summary = {}, {}
        for scope in sorted(state['binding']):
            opening, closing = state['opening'][scope], state['closing'][scope]
            lo, hi = opening['received'], closing['started']
            selected, ambiguous = [], False
            for stream in streams:
                if stream['scope'] != scope:
                    continue
                rows = {}
                for identity, row in stream['records'].items():
                    stamp = record_time(stream['kind'], row)
                    if stamp <= lo or stamp >= hi:
                        ambiguous = True
                    else:
                        rows[identity] = row
                selected.append({**stream, 'records': rows})
            result = reconcile_sources(scope, opening['response'], closing['response'], selected)
            result['reason_codes'] = sorted(set(result['reason_codes']) | {'NONATOMIC_ACCOUNT_CUTS', 'SOURCE_SCOPE_BOUNDED'})
            if ambiguous or hi <= lo:
                result['reason_codes'].append('ACCOUNT_CUT_BOUNDARY_ACTIVITY_UNCERTAIN')
                result['reconciled'] = False
                if result['state'] == 'MATCHED_SUPPLIED_CUTS':
                    result['state'] = 'UNKNOWN'
            result['financial_window_complete'] = False
            private[scope], summary[scope] = result, reconciliation_summary(result)
        archive = self.directory/f'window-{active["start"]}-{active["end"]}'/'reconciliation.dpapi'
        _save_cipher(archive, {'opening': state['opening'], 'closing': state['closing'],
            'snapshot_attempts': state['snapshot_attempts'], 'results': private}, self.protect)
        if not all(result['reconciled'] for result in private.values()):
            state['unmatched_windows'] = state.get('unmatched_windows', 0)+1
            state['last_unmatched_window'] = {'start': active['start'], 'end': active['end']}
        state.update(opening=state['closing'], closing={}, active=None,
            next_due=int(self.clock()*1000)+self.interval, completed=state['completed']+1,
            last=summary, snapshot_attempts=[])
        self._write(state)
        return summary

    def tick(self, *, max_calls=12, should_stop=None):
        if type(max_calls) is not int or not 1 <= max_calls <= 192:
            raise LiveError('CAPTURE_CALL_BUDGET_REQUIRED')
        if should_stop is not None and not callable(should_stop):
            raise LiveError('CAPTURE_STOP_CALLBACK_REQUIRED')
        stopping = lambda: should_stop is not None and should_stop()
        public = {'schema': 1, 'mode': 'AUTOMATIC_GET_CAPTURE', 'state': 'CAPTURE_BLOCKED',
            'automatic_source_producer': True, 'raw_encrypted_retention': False, 'completed_windows': 0,
            'unmatched_closed_windows': 0,
            'account_history_complete': False, 'ledger_reconciled': False, 'financial_window_complete': False, **AUTHORITY}
        if stopping():
            return {**public,'state':'CAPTURE_STOP_REQUESTED','reason_codes':['COOPERATIVE_CAPTURE_STOP']}
        try:
            with _writer_lock(self.lock):
                state = self._read()
                now = int(self.clock()*1000)
                public['completed_windows'] = state['completed']
                public['unmatched_closed_windows'] = state.get('unmatched_windows', 0)
                if now < state['next_due']:
                    return {**public, 'state': 'WAITING_NEXT_CAPTURE', 'raw_encrypted_retention': bool(state['opening']),
                            'next_due_ms': state['next_due'], 'last_reconciliation': state['last']}
                credentials = self.source()
                transport = LiveReadOnlyTransport(credentials, max_calls=max_calls+8, clock=self.clock)
                binding = {s: p.fingerprint() for s, p in credentials.items()}
                if state['binding'] is not None and state['binding'] != binding:
                    raise LiveError('CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED')
                state['binding'] = binding
                used = 0
                initial = set(state['opening']) != set(binding)
                target = state['opening'] if initial else state['closing']
                for scope in sorted(binding):
                    if stopping():
                        return {**public,'state':'CAPTURE_STOP_REQUESTED','raw_encrypted_retention':bool(state['snapshot_attempts'])}
                    if scope not in target and used < max_calls:
                        used += 1
                        self._cut(state, target, scope, transport)
                if initial:
                    if set(state['opening']) == set(binding):
                        state['next_due'] = now+self.interval
                        self._write(state)
                    return {**public, 'state': 'OPENING_CUTS_RETAINED' if set(state['opening']) == set(binding) else 'OPENING_CUTS_PENDING',
                        'raw_encrypted_retention': bool(state['snapshot_attempts']), 'next_due_ms': state['next_due'],
                        'reason_codes': ['PROSPECTIVE_BASELINE_ONLY_NO_CLOSED_WINDOW']}
                if set(state['closing']) != set(binding):
                    return {**public, 'state': 'CLOSING_CUTS_PENDING', 'raw_encrypted_retention': True}
                if state['active'] is None:
                    start = min(v['started'] for v in state['opening'].values())
                    end = max(v['received'] for v in state['closing'].values())
                    if start >= end:
                        raise LiveError('CAPTURE_CLOCK_REGRESSION')
                    state['active'] = {'start': start, 'end': end, 'cursor': start, 'parts': []}
                    self._write(state)
                active = state['active']
                if active['cursor'] < active['end']:
                    if used >= max_calls:
                        return {**public, 'state': 'HISTORY_CAPTURE_PENDING', 'raw_encrypted_retention': True}
                    part = {'start': active['cursor'], 'end': min(active['end'], active['cursor']+DAY)}
                    report = self._job(transport, active, part).run(max_calls=max_calls-used, should_stop=should_stop)
                    if report['state'] != 'CAPTURED_BOUNDED_WINDOW':
                        return {**report, 'completed_windows': state['completed']}
                    active['parts'].append(part)
                    active['cursor'] = part['end']
                    self._write(state)
                if active['cursor'] < active['end']:
                    return {**public, 'state': 'HISTORY_CAPTURE_PENDING', 'raw_encrypted_retention': True}
                if stopping():
                    return {**public,'state':'CAPTURE_STOP_REQUESTED','raw_encrypted_retention':True}
                summary = self._finish(state, transport)
                return {**public, 'state': 'PROSPECTIVE_WINDOW_RECONCILED', 'raw_encrypted_retention': True,
                    'completed_windows': state['completed'], 'unmatched_closed_windows': state.get('unmatched_windows', 0),
                    'last_reconciliation': summary}
        except (ValueError, OSError, KeyError, TypeError) as error:
            code = str(error)
            public['reason_codes'] = [code if re.fullmatch('[A-Z0-9_]{1,80}', code) else 'CAPTURE_SERVICE_UNKNOWN']
            if isinstance(error,LiveHTTPError) and error.http_status in {418,429}:
                public['state']='CAPTURE_RATE_LIMITED'
                public['not_before_ms']=int(self.clock()*1000)+300000
            return public


class FinancialHistoryCapture:
    """Bounded backfill driver with original daily-cut reconciliation.

    Each one-day job is encrypted and idempotent. The controller commits only
    completed job references, never a cursor that outruns retained source rows.
    Explicit daily snapshots are captured once per scope; background services
    never invoke this high-weight path. The caller supplies the fixed window.
    """
    def __init__(self, transport, directory, *, symbols, start_utc_ms, end_utc_ms,
                 clock=time.time, protect=dpapi_protect, unprotect=dpapi_unprotect):
        if type(transport) is not LiveReadOnlyTransport:
            raise LiveError('LIVE_GET_ONLY_TRANSPORT_REQUIRED')
        if (any(type(v) is not int for v in (start_utc_ms, end_utc_ms))
                or not 0 < start_utc_ms < end_utc_ms <= int(clock()*1000)
                or end_utc_ms-start_utc_ms > 366*DAY):
            raise LiveError('BOUNDED_HISTORY_CAPTURE_WINDOW_REQUIRED')
        universes = symbols if type(symbols) is dict else {scope: symbols for scope in transport._credentials}
        if (set(universes) != set(transport._credentials) or any(
                type(items) not in {list, tuple} or not 1 <= len(items) <= 100
                or any(type(s) is not str or not SYMBOL.fullmatch(s) for s in items)
                or len(set(items)) != len(items) for items in universes.values())):
            raise LiveError('EXPLICIT_CAPTURE_SYMBOLS_REQUIRED')
        self.symbols = {scope: sorted(items) for scope, items in universes.items()}
        self.directory = _directory(directory)
        self.path, self.lock = _path(self.directory/'history-controller.dpapi'), _path(self.directory/'history-controller.lock')
        self.transport, self.clock, self.protect, self.unprotect = transport, clock, protect, unprotect
        self.spec = {'schema': 1, 'start': start_utc_ms, 'end': end_utc_ms, 'symbols': self.symbols,
                     'keys': {s: p.fingerprint() for s, p in transport._credentials.items()}}

    def _read(self):
        state = _load_cipher(self.path, self.unprotect) if self.path.exists() else {
            'spec': self.spec, 'cursor': self.spec['start'], 'parts': [], 'daily': None,
            'reconciliation': None, 'last_job': None}
        if type(state) is not dict or state.get('spec') != self.spec:
            raise LiveError('CAPTURE_SCOPE_OR_KEY_BINDING_CHANGED')
        return state

    def _write(self, state):
        _save_cipher(self.path, state, self.protect)

    def _job(self, part):
        return FinancialCapture(self.transport, self.directory/f'part-{part["start"]}',
            symbols=self.symbols, start_utc_ms=part['start'], end_utc_ms=part['end'], clock=self.clock,
            protect=self.protect, unprotect=self.unprotect, capture_current=False)

    def _daily(self):
        # Binance documents a strict sub-30-day query and the last month only.
        # Preserve the requested history span separately; do not invent an
        # opening cut for the earliest portion outside this snapshot range.
        start = max(self.spec['start'], self.spec['end']-29*DAY)
        return DailySnapshotCapture(self.transport, self.directory/'daily',
            start_utc_ms=start, end_utc_ms=self.spec['end'], clock=self.clock,
            protect=self.protect, unprotect=self.unprotect)

    def _reconcile(self, state):
        daily = self._daily().retained()
        streams = []
        for part in state['parts']:
            streams.extend(self._job(part).retained()['streams'])
        private, public = {}, {}
        for scope in sorted(self.spec['keys']):
            snapshots = daily['snapshots'].get(scope, [])
            results = reconcile_daily_pairs(scope, snapshots, streams)
            private[scope] = results
            public[scope] = {'original_daily_cuts': len(snapshots),
                'first_cut_utc_ms': snapshots[0]['at_ms'] if snapshots else None,
                'last_cut_utc_ms': snapshots[-1]['at_ms'] if snapshots else None,
                'cut_pairs_evaluated': len(results),
                'cut_pairs_matched': sum(r['reconciled'] for r in results),
                'cut_pairs_with_differences': sum(r['state'] == 'DIFFERENCE' for r in results),
                'cut_pairs_unknown': sum(r['state'] == 'UNKNOWN' for r in results),
                'matched_supplied_cut_seconds': sum((r['window_end_ms']-r['window_start_ms'])/1000 for r in results if r['reconciled']),
                'periods': [{'start_utc_ms': r['window_start_ms'], 'end_utc_ms': r['window_end_ms'],
                             **reconciliation_summary(r)} for r in results],
                'reason_codes': [] if results else ['ORIGINAL_DAILY_CUT_PAIR_UNAVAILABLE']}
        _save_cipher(self.directory/'historical-reconciliation.dpapi',
            {'spec': self.spec, 'daily_originals': daily['originals'], 'results': private}, self.protect)
        state['reconciliation'] = public
        self._write(state)

    def run(self, *, max_calls=80, daily_snapshot_scopes=0):
        if type(max_calls) is not int or not 4 <= max_calls <= 200:
            raise LiveError('CAPTURE_CALL_BUDGET_REQUIRED')
        if type(daily_snapshot_scopes) is not int or not 0 <= daily_snapshot_scopes <= 2:
            raise LiveError('SNAPSHOT_SCOPE_BUDGET_REQUIRED')
        before = self.transport.calls
        with _writer_lock(self.lock):
            state = self._read()
            if (state['daily'] or {}).get('not_before_ms',0)>int(self.clock()*1000):
                return {'schema':1,'state':'CAPTURE_RATE_LIMITED','daily_baselines':state['daily'],
                    'calls_this_run':0,'account_history_complete':False,'ledger_reconciled':False,**AUTHORITY}
            if daily_snapshot_scopes:
                state['daily'] = self._daily().run(max_scopes=daily_snapshot_scopes)
                self._write(state)
                if state['daily']['state']=='DAILY_SNAPSHOTS_RATE_LIMITED':
                    return {'schema':1,'state':'CAPTURE_RATE_LIMITED','daily_baselines':state['daily'],
                        'calls_this_run':self.transport.calls-before,'account_history_complete':False,
                        'ledger_reconciled':False,**AUTHORITY}
            while state['cursor'] < self.spec['end']:
                remaining = max_calls-(self.transport.calls-before)-2  # Allow signed-clock GETs.
                if remaining <= 0:
                    break
                part = {'start': state['cursor'], 'end': min(self.spec['end'], state['cursor']+DAY)}
                report = self._job(part).run(max_calls=min(remaining, 200))
                state['last_job'] = report
                if report['state'] != 'CAPTURED_BOUNDED_WINDOW':
                    self._write(state)
                    break
                state['parts'].append(part)
                state['cursor'] = part['end']
                self._write(state)
            complete = state['cursor'] == self.spec['end']
            if complete and state['daily'] is not None:
                self._reconcile(state)
            return {'schema': 1, 'mode': 'AUTOMATIC_GET_BACKFILL',
                'state': 'BOUNDED_HISTORY_CAPTURED' if complete else 'HISTORY_CAPTURE_PENDING',
                'window_start_ms': self.spec['start'], 'window_end_ms': self.spec['end'],
                'captured_through_ms': state['cursor'], 'completed_day_parts': len(state['parts']),
                'calls_this_run': self.transport.calls-before, 'daily_baselines': state['daily'],
                'reconciliation': state['reconciliation'], 'last_job': state['last_job'],
                'bounded_history_sources_exhausted': complete, 'raw_encrypted_retention': bool(state['parts']) or bool((state['last_job'] or {}).get('raw_encrypted_retention')) or bool((state['daily'] or {}).get('raw_encrypted_retention')),
                'account_history_complete': False, 'ledger_reconciled': False,
                'reason_codes': ['BOUNDED_TRADE_SYMBOL_UNIVERSE', 'SUBACCOUNT_AND_OTHER_PRODUCT_FLOWS_NOT_CERTIFIED',
                                 'HISTORICAL_PROTECTIONS_NOT_CAPTURED'], **AUTHORITY}
