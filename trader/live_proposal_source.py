"""Prepared LIVE-native signal production, never an execution/activation service.

Uses SwingStrategy and the operating pure Futures signal without constructing an
engine or wallet. Public sources are fixed-host, unsigned GET only; Testnet
observations are not accepted. Account facts, venue filters and every capital /
risk cap are mandatory inputs. The existing LIVE commissioning guard still owns
activation. Protective closes never call this module or its injected AIAdvisor.

Public protocol checked against Binance documentation / official connector:
https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
https://github.com/binance/binance-futures-connector-python/blob/main/binance/um_futures/market.py
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .ai_advisor import AIAdvisor
from .central_admission import AdmissionFacts, AdmissionPolicy, Scope
from .config import AISettings, FuturesTestnetSettings, RiskSettings, StrategySettings
from .domain import AIReview, Candle
from .exchange import BinanceClient
from .futures_strategy import evaluate_futures_signal
from .live_strategy_adapter import NativeStrategyDecision, VenueExecutionEvidence, _single_file_identity
from .live_transport import LiveError
from .strategy import SwingStrategy

_SOURCES = {'SPOT_LIVE':('https://api.binance.com','/api/v3/klines','/api/v3/time'),
            'FUTURES_LIVE':('https://fapi.binance.com','/fapi/v1/klines','/fapi/v1/time')}
_DURATIONS = {'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'1h':3600,
              '2h':7200,'4h':14400,'6h':21600,'8h':28800,'12h':43200,'1d':86400}
_SYMBOL = re.compile(r'[A-Z0-9]{2,24}USDT\Z',re.ASCII)
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z',re.ASCII)
_MAX_BYTES = 524288
_MICRO = Decimal(1_000_000)


def _raw(value):
    data=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
    if len(data)>_MAX_BYTES:raise LiveError('BOUNDED_NATIVE_SOURCE_EVIDENCE_REQUIRED')
    return data


def _digest(value):return hashlib.sha256(_raw(value)).hexdigest()


def _at(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<253402300799:
        raise LiveError('NATIVE_SOURCE_UTC_TIME_REQUIRED')
    return float(value)


def _number(value,*,zero=False):
    if type(value) not in (str,int,float) or len(str(value))>64:
        raise LiveError('FINITE_NATIVE_SOURCE_NUMBER_REQUIRED')
    try:
        result=Decimal(str(value))
        if (not result.is_finite() or not (0<=result<Decimal('1e15') if zero else 0<result<Decimal('1e15'))
                or result.as_tuple().exponent < -18):raise ValueError()
        return result
    except (InvalidOperation,ValueError):raise LiveError('FINITE_NATIVE_SOURCE_NUMBER_REQUIRED') from None


def _identifier(value):
    if type(value) is not str or not _ID.fullmatch(value):raise LiveError('NATIVE_SOURCE_IDENTIFIER_REQUIRED')


def _units(value):
    if type(value) is not int or not 0<=value<=10**18:raise LiveError('EXPLICIT_NATIVE_SOURCE_UNITS_REQUIRED')


@dataclass(frozen=True)
class PublicCandleCut:
    environment: str
    host: str
    endpoint: str
    symbol: str
    interval: str
    requested_at: float
    received_at: float
    as_of: float
    rows: tuple[tuple, ...]

    def __post_init__(self):
        if (self.environment not in _SOURCES or (self.host,self.endpoint)!=_SOURCES[self.environment][:2]
                or type(self.symbol) is not str or not _SYMBOL.fullmatch(self.symbol)
                or self.interval not in _DURATIONS):
            raise LiveError('EXPLICIT_FIXED_LIVE_PUBLIC_SOURCE_REQUIRED')
        started,received,as_of=map(_at,(self.requested_at,self.received_at,self.as_of))
        if not started<=received<=started+20 or not started-2<=as_of<=received+2:
            raise LiveError('PUBLIC_LIVE_CLOCK_OR_LATENCY_UNCERTAIN')
        if type(self.rows) is not tuple or not 6<=len(self.rows)<=1000:
            raise LiveError('BOUNDED_CLOSED_PUBLIC_CANDLES_REQUIRED')
        duration=_DURATIONS[self.interval]*1000;previous=None
        for row in self.rows:
            if type(row) is not tuple or len(row)!=12:
                raise LiveError('PUBLIC_LIVE_KLINE_SCHEMA_REQUIRED')
            opened,closed=row[0],row[6]
            if (type(opened) is not int or type(closed) is not int or opened<0 or opened%duration
                    or closed!=opened+duration-1 or closed>=int(as_of*1000)
                    or previous is not None and opened!=previous+duration):
                raise LiveError('CLOSED_CONTIGUOUS_UTC_LIVE_CANDLES_REQUIRED')
            o,h,l,c=map(_number,row[1:5]);_number(row[5],zero=True)
            if not l<=min(o,c)<=max(o,c)<=h:raise LiveError('PUBLIC_LIVE_OHLC_RANGE_REQUIRED')
            for value in (row[7],row[9],row[10],row[11]):_number(value,zero=True)
            if type(row[8]) is not int or not 0<=row[8]<=10**12:raise LiveError('PUBLIC_LIVE_TRADE_COUNT_REQUIRED')
            previous=opened
        _raw(asdict(self))

    @property
    def candles(self):
        return [Candle(row[0],*(float(row[i]) for i in range(1,6)),row[6]) for row in self.rows]

    @property
    def fingerprint(self):return _digest(asdict(self))


class LivePublicCandleReader(BinanceClient):
    """Reuse BinanceClient's candle/time interface without reading env or keys.

    Exactly two GETs per cut (time then klines), no retries, proxies, redirects,
    Testnet fallback, dynamic endpoint or private method. Request budget counts
    failed calls too. The optional last open candle is discarded explicitly.
    """
    def __init__(self,*,timeout_seconds,maximum_requests_per_minute,clock=time.time,monotonic=time.monotonic):
        if type(timeout_seconds) is not int or not 1<=timeout_seconds<=10 or type(maximum_requests_per_minute) is not int or not 2<=maximum_requests_per_minute<=60:
            raise LiveError('EXPLICIT_BOUNDED_PUBLIC_READER_LIMITS_REQUIRED')
        self.timeout=timeout_seconds;self.maximum_requests=maximum_requests_per_minute
        self.clock=clock;self.monotonic=monotonic;self._calls=[];self._lock=threading.Lock();self._phase=None

    def _opener(self):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),
            type('NoPublicRedirect',(urllib.request.HTTPRedirectHandler,),{'redirect_request':lambda *args:None})())

    def _request(self,method,path,params=None,signed=False):
        if self._phase is None or signed or method!='GET':raise LiveError('PUBLIC_LIVE_GET_ONLY')
        host,klines,server_time=_SOURCES[self._market]
        expected=(server_time,{}) if self._phase=='TIME' else (klines,self._params)
        if path!=expected[0] or (params or {})!=expected[1]:raise LiveError('PUBLIC_LIVE_ENDPOINT_OR_FIELDS_BLOCKED')
        self._phase=None
        stamp=self.monotonic()
        if type(stamp) not in (int,float) or not math.isfinite(stamp):raise LiveError('PUBLIC_MONOTONIC_CLOCK_REQUIRED')
        if self._calls and stamp<self._calls[-1]:raise LiveError('PUBLIC_MONOTONIC_CLOCK_MOVED_BACKWARD')
        self._calls=[value for value in self._calls if 0<=stamp-value<60]
        if len(self._calls)>=self.maximum_requests:raise LiveError('PUBLIC_LIVE_REQUEST_BUDGET_EXHAUSTED')
        self._calls.append(stamp)
        query=urllib.parse.urlencode(params or {})
        url=host+path+('?' + query if query else '')
        request=urllib.request.Request(url,method='GET',headers={'User-Agent':'CryptoBOT-NativeSource/1','Accept':'application/json'})
        try:
            with self._opener().open(request,timeout=self.timeout) as response:
                if response.geturl()!=url or getattr(response,'status',None)!=200:
                    raise LiveError('PUBLIC_LIVE_REDIRECT_OR_STATUS_BLOCKED')
                raw=response.read(_MAX_BYTES+1)
            if len(raw)>_MAX_BYTES:raise LiveError('PUBLIC_LIVE_RESPONSE_TOO_LARGE')
            return json.loads(raw)
        except LiveError:raise
        except (urllib.error.URLError,TimeoutError,ValueError,TypeError):
            raise LiveError('PUBLIC_LIVE_SOURCE_UNAVAILABLE') from None

    def _parse_candles(self,payload):
        if type(payload) is not list or not 6<=len(payload)<=self._params['limit']:
            raise LiveError('BOUNDED_CLOSED_PUBLIC_CANDLES_REQUIRED')
        if any(type(row) is not list or len(row)!=12 for row in payload):raise LiveError('PUBLIC_LIVE_KLINE_SCHEMA_REQUIRED')
        rows=tuple(tuple(row) for row in payload)
        if (type(rows[-1][0]) is int and type(rows[-1][6]) is int
                and rows[-1][0]<=int(self._as_of*1000)<=rows[-1][6]):
            rows=rows[:-1]
        return rows

    def candles(self,symbol,interval,limit=250):
        if self._phase!='KLINES':raise LiveError('PUBLIC_LIVE_CUT_CONTEXT_REQUIRED')
        if self._market=='SPOT_LIVE':return super().candles(symbol,interval,limit)
        payload=self._request('GET',_SOURCES['FUTURES_LIVE'][1],{'symbol':symbol,'interval':interval,'limit':limit})
        return self._parse_candles(payload)

    def fetch(self,environment,symbol,interval,*,limit):
        if (environment not in _SOURCES or type(symbol) is not str or not _SYMBOL.fullmatch(symbol)
                or interval not in _DURATIONS or type(limit) is not int or not 7<=limit<=1000):
            raise LiveError('BOUNDED_FIXED_LIVE_KLINE_REQUEST_REQUIRED')
        with self._lock:
            self._market=environment;self._params={'symbol':symbol,'interval':interval,'limit':limit}
            started=_at(self.clock())
            try:
                self._phase='TIME';raw=self._request('GET',_SOURCES[environment][2])
                if type(raw) is not dict or set(raw)!={'serverTime'} or type(raw['serverTime']) is not int:
                    raise LiveError('PUBLIC_LIVE_EXCHANGE_TIME_REQUIRED')
                self._as_of=raw['serverTime']/1000
                self._phase='KLINES';rows=self.candles(symbol,interval,limit)
                return PublicCandleCut(environment,*_SOURCES[environment][:2],symbol,interval,started,
                                       _at(self.clock()),self._as_of,rows)
            finally:self._phase=None


@dataclass(frozen=True)
class NativeVenueSnapshot:
    symbol: str
    evidence: VenueExecutionEvidence

    def __post_init__(self):
        if type(self.symbol) is not str or not _SYMBOL.fullmatch(self.symbol) or type(self.evidence) is not VenueExecutionEvidence:
            raise LiveError('TYPED_SYMBOL_BOUND_NATIVE_VENUE_REQUIRED')


@dataclass(frozen=True)
class NativeEntryBudget:
    capital_units: int
    gross_units: int
    stop_risk_units: int
    leverage_milli: int
    correlation_group: str
    strategy_fingerprint: str
    maximum_entry_deviation_bps: int
    spot_stop_limit_gap_ticks: int

    def __post_init__(self):
        for value in (self.capital_units,self.gross_units,self.stop_risk_units):_units(value)
        for value in (self.correlation_group,self.strategy_fingerprint):_identifier(value)
        if (type(self.leverage_milli) is not int or not 1000<=self.leverage_milli<=125000
                or type(self.maximum_entry_deviation_bps) is not int or not 0<=self.maximum_entry_deviation_bps<=1000
                or type(self.spot_stop_limit_gap_ticks) is not int or not 1<=self.spot_stop_limit_gap_ticks<=100000):
            raise LiveError('EXPLICIT_NATIVE_ENTRY_TERMS_REQUIRED')


@dataclass(frozen=True)
class NativeProposalOutcome:
    record_id: str
    status: str
    evidence_digest: str
    decision: NativeStrategyDecision | None


class LiveProposalSourceJournal:
    """Private explicit journal: immutable source receipts and durable AI claims.

    A crash after claiming a review consumes that claim and leaves UNKNOWN; it
    never silently renews a call. No reservation, wallet or permission is issued.
    """
    def __init__(self,path):
        self.path=Path(path)
        if self.path.suffix!='.sqlite3' or not self.path.name.startswith('live-proposal-source-'):
            raise LiveError('SEPARATE_NATIVE_SOURCE_JOURNAL_REQUIRED')

    def _safe(self):
        if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (self.path,*self.path.parents)):
            raise LiveError('LINKED_NATIVE_SOURCE_JOURNAL_BLOCKED')
        return _single_file_identity(self.path,'NONPRIVATE_NATIVE_SOURCE_JOURNAL_BLOCKED')

    def _same_file(self,identity):
        if identity is None or self._safe()!=identity:raise LiveError('NATIVE_SOURCE_JOURNAL_IDENTITY_CHANGED')

    @staticmethod
    def _identity(db):
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables!={'source_meta','source_receipts'} or db.execute('SELECT schema FROM source_meta').fetchall()!=[(1,)]:
            raise LiveError('FOREIGN_NATIVE_SOURCE_JOURNAL')

    def initialize(self):
        identity=self._safe();self.path.parent.mkdir(parents=True,exist_ok=True)
        if identity is None:
            descriptor=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_BINARY',0),0o600)
            os.close(descriptor);identity=self._safe()
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=5)) as db,db:
            self._same_file(identity)
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA synchronous=FULL')
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables:
                self._identity(db);return
            db.execute('CREATE TABLE source_meta(schema INTEGER NOT NULL)');db.execute('INSERT INTO source_meta VALUES(1)')
            db.execute('CREATE TABLE source_receipts(id TEXT PRIMARY KEY,day TEXT NOT NULL,review_claimed INTEGER NOT NULL,state TEXT NOT NULL,digest TEXT NOT NULL,payload BLOB NOT NULL)')
            db.executescript("CREATE TRIGGER source_receipts_no_delete BEFORE DELETE ON source_receipts BEGIN SELECT RAISE(ABORT,'retained source'); END; CREATE TRIGGER source_receipts_final BEFORE UPDATE ON source_receipts WHEN OLD.state='COMPLETE' OR NEW.id!=OLD.id OR NEW.day!=OLD.day OR NEW.review_claimed!=OLD.review_claimed BEGIN SELECT RAISE(ABORT,'immutable source'); END;")

    def _connect(self):
        identity=self._safe()
        if not self.path.is_file():raise LiveError('NATIVE_SOURCE_JOURNAL_NOT_INITIALIZED')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw',uri=True,timeout=5)
        try:
            self._same_file(identity)
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA synchronous=FULL');self._identity(db)
            return db
        except BaseException:db.close();raise

    def load(self,record_id):
        _identifier(record_id)
        with closing(self._connect()) as db:
            row=db.execute('SELECT state,digest,payload FROM source_receipts WHERE id=?',(record_id,)).fetchone()
        if row is None:return None
        state,digest,raw=row
        if type(raw) is not bytes or len(raw)>_MAX_BYTES or hashlib.sha256(raw).hexdigest()!=digest:
            raise LiveError('NATIVE_SOURCE_RECEIPT_CHANGED')
        if state!='COMPLETE':raise LiveError('NATIVE_SOURCE_REVIEW_OUTCOME_UNKNOWN')
        payload=json.loads(raw)
        if _raw(payload)!=raw:raise LiveError('NATIVE_SOURCE_RECEIPT_CHANGED')
        return payload

    def begin(self,record_id,inputs,*,now,review,maximum_reviews_per_day):
        _identifier(record_id)
        if type(review) is not bool or type(maximum_reviews_per_day) is not int or not 0<=maximum_reviews_per_day<=100:
            raise LiveError('EXPLICIT_NATIVE_REVIEW_BUDGET_REQUIRED')
        day=datetime.fromtimestamp(_at(now),UTC).strftime('%Y-%m-%d');raw=_raw(inputs)
        with closing(self._connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM source_receipts WHERE id=?',(record_id,)).fetchone():
                raise LiveError('NATIVE_SOURCE_DECISION_ALREADY_CLAIMED')
            latest=db.execute('SELECT MAX(day) FROM source_receipts').fetchone()[0]
            if latest is not None and latest>day:raise LiveError('NATIVE_SOURCE_DAY_MOVED_BACKWARD')
            if review and db.execute('SELECT COUNT(*) FROM source_receipts WHERE day=? AND review_claimed=1',(day,)).fetchone()[0]>=maximum_reviews_per_day:
                raise LiveError('NATIVE_SOURCE_AI_DAILY_BUDGET_EXHAUSTED')
            db.execute('INSERT INTO source_receipts VALUES(?,?,?,?,?,?)',
                       (record_id,day,int(review),'PENDING',hashlib.sha256(raw).hexdigest(),raw))

    def finish(self,record_id,payload):
        _identifier(record_id);raw=_raw(payload)
        with closing(self._connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("UPDATE source_receipts SET state='COMPLETE',digest=?,payload=? WHERE id=? AND state='PENDING'",
                          (hashlib.sha256(raw).hexdigest(),raw,record_id)).rowcount!=1:
                raise LiveError('EXACT_PENDING_NATIVE_SOURCE_REQUIRED')


class NativeLiveProposalSource:
    """Entry-only pure strategies + constrained injected individual AI review.

    The journal owns per-candle idempotence and a durable budget shared by both
    native strategies. It returns a prepared decision; it never sends an order,
    claims capital, creates a permission, calls protective exits or activates LIVE.
    """
    def __init__(self,*,strategy_settings,risk_settings,futures_settings,advisor,journal,
                 maximum_reviews_per_day,decision_ttl_ms,clock=time.time):
        if (type(strategy_settings) is not StrategySettings or type(risk_settings) is not RiskSettings
                or type(futures_settings) is not FuturesTestnetSettings or type(advisor) is not AIAdvisor
                or type(journal) is not LiveProposalSourceJournal or type(advisor.settings) is not AISettings
                or advisor.settings.fail_closed is not True or type(advisor.settings.max_reviews_per_day) is not int
                or type(maximum_reviews_per_day) is not int or not 0<=maximum_reviews_per_day<=min(100,advisor.settings.max_reviews_per_day)
                or type(decision_ttl_ms) is not int or not 1<=decision_ttl_ms<=30000):
            raise LiveError('EXPLICIT_NATIVE_SOURCE_AND_FAIL_CLOSED_AI_REQUIRED')
        _identifier(advisor.settings.model)
        for value in asdict(strategy_settings).values():
            if type(value) is not int or not 1<=value<=500:raise LiveError('BOUNDED_NATIVE_STRATEGY_SETTINGS_REQUIRED')
        for value in (risk_settings.stop_atr_multiple,risk_settings.minimum_stop_pct,risk_settings.reward_to_risk,
                      futures_settings.forward_stop_atr_multiple,futures_settings.forward_minimum_stop_pct,futures_settings.forward_reward_to_risk):
            _number(value)
        if (type(risk_settings.max_positions) is not int or not 1<=risk_settings.max_positions<=100
                or any(not 0<_number(value)<=1 for value in (risk_settings.risk_per_trade_pct,
                    risk_settings.max_position_pct,risk_settings.max_total_exposure_pct))):
            raise LiveError('EXPLICIT_NATIVE_RISK_UPPER_BOUNDS_REQUIRED')
        self.swing=SwingStrategy(strategy_settings,risk_settings);self.strategy_settings=strategy_settings
        self.risk_settings=risk_settings;self.futures_settings=futures_settings;self.advisor=advisor
        self.journal=journal;self.maximum_reviews=maximum_reviews_per_day;self.ttl=decision_ttl_ms;self.clock=clock
        self._review_settings=_raw(asdict(advisor.settings))

    def _validate(self,cut,btc_cut,scope,facts,venue,policy,budget,now):
        if _raw(asdict(self.advisor.settings))!=self._review_settings:
            raise LiveError('NATIVE_SOURCE_AI_SETTINGS_CHANGED_REBUILD_REQUIRED')
        if (type(cut) is not PublicCandleCut or type(scope) is not Scope or type(facts) is not AdmissionFacts
                or type(venue) is not NativeVenueSnapshot or type(policy) is not AdmissionPolicy
                or type(budget) is not NativeEntryBudget or cut.environment!=scope.environment
                or facts.scope!=scope or venue.evidence.scope!=scope or venue.symbol!=cut.symbol):
            raise LiveError('EXACT_TYPED_LIVE_NATIVE_SOURCE_INPUTS_REQUIRED')
        cuts=[cut]
        if cut.environment=='SPOT_LIVE':
            if (type(btc_cut) is not PublicCandleCut or btc_cut.environment!='SPOT_LIVE' or btc_cut.symbol!='BTCUSDT'
                    or btc_cut.interval!=cut.interval or btc_cut.rows[-1][6]!=cut.rows[-1][6]
                    or budget.leverage_milli!=1000):raise LiveError('EXACT_LIVE_BTC_REGIME_CUT_REQUIRED')
            cuts.append(btc_cut)
        elif btc_cut is not None:raise LiveError('UNEXPECTED_FUTURES_BTC_CUT')
        for item in cuts:
            if (not item.received_at<=now or now-item.received_at>policy.max_data_age_seconds
                    or now-item.as_of>policy.max_data_age_seconds
                    or now-item.rows[-1][6]/1000>_DURATIONS[item.interval]+policy.max_data_age_seconds
                    or len(item.rows)<max(self.swing.minimum_history,self.strategy_settings.rsi_period+2,6)):
                raise LiveError('STALE_NATIVE_PUBLIC_CANDLE_CUT')
        flags=(facts.identity_verified,facts.inventory_complete,facts.orders_reconciled,facts.cashflows_complete,
               facts.free_is_net_of_exchange_commitments,facts.exchange_ready,facts.correlation_verified)
        if (not all(flags) or not facts.observed_at<=facts.received_at<=now
                or now-facts.observed_at>policy.max_data_age_seconds
                or any(not p.protection_verified for p in facts.positions)):
            raise LiveError('COMPLETE_FRESH_NATIVE_ACCOUNT_FACTS_REQUIRED')
        evidence=venue.evidence
        if (not evidence.filters_complete or not evidence.protection_filters_verified
                or not evidence.observed_at<=evidence.received_at<=now
                or now-evidence.observed_at>policy.max_data_age_seconds
                or budget.leverage_milli!=evidence.configured_leverage_milli
                or budget.leverage_milli>policy.max_leverage_milli
                or evidence.fee_bps>policy.max_fee_bps or evidence.slippage_bps>policy.max_slippage_bps
                or evidence.spread_bps>policy.max_spread_bps
                or cut.environment=='FUTURES_LIVE' and (not evidence.isolated_margin_verified or not evidence.one_way_mode_verified)):
            raise LiveError('COMPLETE_APPROVED_NATIVE_VENUE_TERMS_REQUIRED')

    def _size(self,*,scope,symbol,direction,reference,stop,stop_limit,venue,facts,policy,budget,multiplier):
        engine='SPOT' if scope.environment=='SPOT_LIVE' else 'FUTURES'
        try:
            engine_limit=next(row for row in policy.engine_limits if row[0]==engine)
            asset_limit=next(row for row in policy.asset_limits if row[0]==symbol)
            group_limit=next(row for row in policy.correlation_limits if row[0]==budget.correlation_group)
        except StopIteration:raise LiveError('NATIVE_SOURCE_PARTICIPANT_NOT_APPROVED') from None
        positions=facts.positions
        if len(positions)>=min(policy.max_positions,self.risk_settings.max_positions) or any(p.symbol==symbol for p in positions):
            raise LiveError('NATIVE_SOURCE_EXISTING_ASSET_OR_POSITION_LIMIT')
        def total(field,select):return sum(getattr(row,field) for row in positions if select(row))
        everyone=lambda row:True;motor=lambda row:row.engine_id==engine;asset=lambda row:row.symbol==symbol
        group=lambda row:row.correlation_group==budget.correlation_group
        gross_cap=min(budget.gross_units,venue.available_depth_units,
            policy.gross_limit_units-total('gross_units',everyone),engine_limit[2]-total('gross_units',motor),
            asset_limit[1]-total('gross_units',asset),group_limit[1]-total('gross_units',group))
        if venue.maximum_notional_units is not None:gross_cap=min(gross_cap,venue.maximum_notional_units)
        gross_cap=min(gross_cap,int(Decimal(facts.equity_units)*Decimal(str(self.risk_settings.max_total_exposure_pct)))-total('gross_units',everyone))
        risk_cap=min(budget.stop_risk_units,policy.per_trade_stop_risk_limit_units,
            policy.stop_risk_limit_units-total('inclusive_stop_risk_units',everyone),
            engine_limit[3]-total('inclusive_stop_risk_units',motor),asset_limit[2]-total('inclusive_stop_risk_units',asset),
            group_limit[2]-total('inclusive_stop_risk_units',group))
        risk_cap=min(risk_cap,int(Decimal(facts.equity_units)*Decimal(str(self.risk_settings.risk_per_trade_pct))))
        risk_cap=int((Decimal(max(0,risk_cap))*Decimal(str(multiplier))).to_integral_value(rounding=ROUND_FLOOR))
        capital_cap=min(budget.capital_units,facts.free_units,
            policy.capital_budget_units-sum((p.gross_units*1000+p.leverage_milli-1)//p.leverage_milli for p in positions),
            int(Decimal(facts.equity_units)*Decimal(str(self.risk_settings.max_position_pct))),
            engine_limit[1]-sum((p.gross_units*1000+p.leverage_milli-1)//p.leverage_milli for p in positions if motor(p)))
        if min(gross_cap,risk_cap,capital_cap)<=0:raise LiveError('NATIVE_SOURCE_NO_AVAILABLE_BUDGET')
        step=_number(venue.quantity_step);reference=_number(reference)
        distance=abs(reference-_number(stop_limit if stop_limit is not None else stop))
        with localcontext() as context:
            context.prec=80
            high=int((min(_number(venue.maximum_quantity),Decimal(gross_cap)/(_MICRO*reference))/step).to_integral_value(rounding=ROUND_FLOOR))
            low=0
            def amounts(lots):
                qty=step*lots;gross=int((qty*reference*_MICRO).to_integral_value(rounding=ROUND_CEILING))
                costs=(gross*(2*venue.fee_bps+2*venue.slippage_bps+venue.spread_bps)+9999)//10000
                principal=(gross*1000+budget.leverage_milli-1)//budget.leverage_milli
                risk=int((qty*distance*_MICRO).to_integral_value(rounding=ROUND_CEILING))+costs
                return qty,gross,costs,principal,risk
            while low<high:
                middle=(low+high+1)//2;qty,gross,costs,principal,risk=amounts(middle)
                if gross<=gross_cap and principal+costs<=capital_cap and risk<=risk_cap:low=middle
                else:high=middle-1
            qty,gross,costs,principal,risk=amounts(low)
        if qty<_number(venue.minimum_quantity) or gross<venue.minimum_notional_units:
            raise LiveError('NATIVE_SOURCE_SIZE_BELOW_EXCHANGE_FILTERS')
        return format(qty,'f'),{'gross_units':gross,'cost_buffer_units':costs,'principal_units':principal,
                              'inclusive_stop_risk_units':risk,'risk_cap_units':risk_cap,'capital_cap_units':capital_cap}

    @staticmethod
    def _outcome(record_id,payload):
        evidence=payload['evidence'];digest=_digest(evidence);raw=payload['decision']
        if payload['evidence_digest']!=digest:raise LiveError('NATIVE_SOURCE_RECEIPT_CHANGED')
        decision=None
        if raw is not None:
            raw=dict(raw);raw['scope']=Scope(**raw['scope']);raw['review']=AIReview(**raw['review'])
            decision=NativeStrategyDecision(**raw)
            if decision.source_digest!=digest:raise LiveError('NATIVE_SOURCE_RECEIPT_CHANGED')
        return NativeProposalOutcome(record_id,payload['status'],digest,decision)

    def produce(self,cut,*,btc_cut,scope,facts,venue,policy,budget):
        now=_at(self.clock());self._validate(cut,btc_cut,scope,facts,venue,policy,budget,now)
        engine='SPOT' if scope.environment=='SPOT_LIVE' else 'FUTURES'
        rules={'strategy':asdict(self.strategy_settings),'risk':asdict(self.risk_settings),'futures':{
            key:getattr(self.futures_settings,key) for key in ('forward_min_score','forward_stop_atr_multiple',
                'forward_minimum_stop_pct','forward_reward_to_risk')}}
        key='NATIVE-'+_digest([asdict(scope),engine,cut.symbol,cut.interval,cut.rows[-1][6],rules,
                                policy.fingerprint,budget.strategy_fingerprint])
        inputs={'cut':asdict(cut),'btc_cut':asdict(btc_cut) if btc_cut is not None else None,'scope':asdict(scope),
                'account_facts':asdict(facts),'venue':asdict(venue),'policy':asdict(policy),'budget':asdict(budget),
                'rules':rules,'ai_settings':asdict(self.advisor.settings)}
        existing=self.journal.load(key)
        if existing is not None:
            if _raw(existing['evidence']['inputs'])!=_raw(inputs):
                raise LiveError('NATIVE_SOURCE_CACHED_INPUTS_CHANGED_NO_REVIEW_REISSUED')
            return self._outcome(key,existing)
        candles=cut.candles;native=None;btc=None
        if engine=='SPOT':
            btc=self.swing.btc_regime(btc_cut.candles);native=self.swing.evaluate(cut.symbol,candles,btc)
            native=replace(native,created_at=datetime.fromtimestamp(now,UTC).isoformat())
            signal=native.to_dict();direction='LONG' if native.action=='BUY' else None
        else:
            signal=evaluate_futures_signal(candles,self.strategy_settings,self.futures_settings)
            signal={**signal,'symbol':cut.symbol,'timeframe':cut.interval,'candle_close_time':cut.rows[-1][6]}
            direction=signal['direction']
        evidence={'inputs':inputs,'native_signal':signal,'btc_bullish':btc,'evaluated_at':now}
        if direction is None:
            self.journal.begin(key,evidence,now=now,review=False,maximum_reviews_per_day=self.maximum_reviews)
            payload={'status':'HOLD','decision':None,'evidence':evidence,'evidence_digest':_digest(evidence)}
            self.journal.finish(key,payload);return self._outcome(key,payload)
        reference=_number(venue.evidence.reference_price);anchor=_number(signal['price'])
        if abs(reference-anchor)*10000>anchor*budget.maximum_entry_deviation_bps:
            raise LiveError('NATIVE_SOURCE_ENTRY_PRICE_MOVED_TOO_FAR')
        if engine=='SPOT':
            if not _number(native.stop_price)<reference<_number(native.take_profit):raise LiveError('NATIVE_SOURCE_ORIGINAL_PROTECTION_RANGE_CROSSED')
            native=native.at_entry_price(float(reference));raw_stop=_number(native.stop_price);raw_target=_number(native.take_profit)
        else:
            distance=max(_number(self.futures_settings.forward_stop_atr_multiple)*_number(signal['atr']),
                         _number(self.futures_settings.forward_minimum_stop_pct)*reference)
            original_distance=max(_number(self.futures_settings.forward_stop_atr_multiple)*_number(signal['atr']),
                                  _number(self.futures_settings.forward_minimum_stop_pct)*anchor)
            side=1 if direction=='LONG' else -1;reward=_number(self.futures_settings.forward_reward_to_risk)
            drift=Decimal(side)*(reference-anchor)
            if not -original_distance<drift<reward*original_distance:raise LiveError('NATIVE_SOURCE_ORIGINAL_PROTECTION_RANGE_CROSSED')
            raw_stop=reference-side*distance;raw_target=reference+side*reward*distance
        tick=_number(venue.evidence.price_tick)
        def snap(value,up):return format((value/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*tick,'f')
        # Tighten stop toward the quote and round target inward, then size using
        # these exact prices. Never widen risk or round quantity upward.
        stop=snap(raw_stop,direction=='LONG');target=snap(raw_target,direction=='SHORT')
        stop_limit=format(_number(stop)-budget.spot_stop_limit_gap_ticks*tick,'f') if engine=='SPOT' else None
        if not (_number(stop)<reference<_number(target) if direction=='LONG' else _number(target)<reference<_number(stop)):
            raise LiveError('NATIVE_SOURCE_TICK_ROUNDING_COLLAPSED_RANGE')
        quantity,sizing=self._size(scope=scope,symbol=cut.symbol,direction=direction,reference=str(reference),stop=stop,
            stop_limit=stop_limit,venue=venue.evidence,facts=facts,policy=policy,budget=budget,multiplier=1)
        def exact_execution_filters(quantity):
            with localcontext() as context:
                context.prec=80
                if reference%tick:raise LiveError('NATIVE_SOURCE_REFERENCE_OUTSIDE_PRICE_TICK')
                for price in (stop,target,stop_limit):
                    if price is None:continue
                    notional=_number(quantity)*_number(price)*_MICRO
                    if (notional<venue.evidence.minimum_notional_units or venue.evidence.maximum_notional_units is not None
                            and notional>venue.evidence.maximum_notional_units):
                        raise LiveError('NATIVE_SOURCE_PROTECTION_OUTSIDE_NOTIONAL_FILTERS')
        exact_execution_filters(quantity)
        proposed={**signal,'environment':scope.environment,'proposed_reference_price':float(reference),
            'proposed_quantity':float(quantity),'proposed_notional_usdt':sizing['gross_units']/1e6,
            'proposed_stop_price':float(stop),'proposed_take_profit':float(target),'proposed_leverage':budget.leverage_milli/1000,
            'estimated_stop_loss_usdt':sizing['inclusive_stop_risk_units']/1e6}
        evidence.update(proposed_signal=proposed,initial_sizing=sizing)
        self.journal.begin(key,evidence,now=now,review=True,maximum_reviews_per_day=self.maximum_reviews)
        account={'equity':facts.equity_units/1e6,'free_capital':facts.free_units/1e6,'open_positions':len(facts.positions),
                 'gross_exposure':sum(p.gross_units for p in facts.positions)/1e6,
                 'stop_risk':sum(p.inclusive_stop_risk_units for p in facts.positions)/1e6}
        try:
            if engine=='SPOT':
                reviewed_signal=replace(native,stop_price=float(stop),take_profit=float(target))
                review=self.advisor.review(reviewed_signal,btc,account)
            else:review=self.advisor.review_futures(proposed,account)
        except Exception as exc:
            review=AIReview('REJECT',1.0,0.0,'Native source AI failed safely: '+type(exc).__name__[:64])
        reviewed=_at(self.clock())
        if (type(review) is not AIReview or review.verdict not in {'ALLOW','REDUCE','REJECT'}
                or type(review.reason) is not str or len(review.reason)>240
                or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in (review.confidence,review.risk_multiplier))
                or review.confidence<self.advisor.settings.minimum_confidence
                or review.verdict=='REDUCE' and review.risk_multiplier>0.75
                or engine=='FUTURES' and review.verdict!='REJECT' and (review.verdict!='ALLOW' or review.risk_multiplier!=1)):
            review=AIReview('REJECT',1.0,0.0,'Native source invalid constrained AI response')
        evidence.update(review=asdict(review),reviewed_at=reviewed)
        decision=None;status='AI_REJECTED'
        if review.verdict!='REJECT' and review.risk_multiplier>0:
            try:
                self._validate(cut,btc_cut,scope,facts,venue,policy,budget,reviewed)
                quantity,final_sizing=self._size(scope=scope,symbol=cut.symbol,direction=direction,reference=str(reference),stop=stop,
                    stop_limit=stop_limit,venue=venue.evidence,facts=facts,policy=policy,budget=budget,multiplier=review.risk_multiplier)
                exact_execution_filters(quantity)
                evidence.update(final_sizing=final_sizing,final_quantity=quantity)
                expires=min(reviewed+self.ttl/1000,venue.evidence.observed_at+policy.max_data_age_seconds,
                            facts.observed_at+policy.max_data_age_seconds,cut.received_at+policy.max_data_age_seconds)
                decision=NativeStrategyDecision(key,scope,scope.environment,engine,cut.symbol,direction,quantity,
                    str(reference),stop,target,stop_limit,budget.leverage_milli,budget.correlation_group,
                    min(cut.as_of,cut.received_at,venue.evidence.observed_at,facts.observed_at),reviewed,reviewed,expires,
                    budget.strategy_fingerprint,_digest(evidence),review,self.advisor.settings.model,True)
                status='PREPARED'
            except (LiveError,ValueError) as exc:
                evidence['post_review_block']=str(exc)[:180];status='QUANTITATIVE_REJECTED'
        payload={'status':status,'decision':asdict(decision) if decision is not None else None,
                 'evidence':evidence,'evidence_digest':_digest(evidence)}
        self.journal.finish(key,payload);return self._outcome(key,payload)
