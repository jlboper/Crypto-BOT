"""Bounded asynchronous evidence only. Never controls an engine or submits orders."""
from contextlib import closing
from datetime import UTC, datetime
from decimal import Context, Decimal, localcontext
import hashlib
import json
from pathlib import Path
import queue
import sqlite3
import threading
import time

from .opportunity_contract import OpportunityEvent, build_intent, build_outcome, canonical, position_digest, FLAGS, ENGINES
from .opportunity_shadow import evaluate_intent

QUEUE_CAPACITY=64
MAX_SNAPSHOT_BYTES=12000
_SERVICE=None
_INGRESS=None
_DROPPED=0
_REGISTRY_LOCK=threading.Lock()
ERROR_CODES=frozenset(('RETENTION_FULL','JOURNAL_FULL','INITIALIZATION_FAILED','OBSERVATION_FAILED','SNAPSHOT_UNAVAILABLE','CLOCK_REGRESSION'))


def _iso(at):return datetime.fromtimestamp(at,UTC).isoformat() if at is not None else None


def register_observer(service):
    global _SERVICE,_INGRESS
    if type(service) is not OpportunityObserverService or not service.enabled:return False
    with _REGISTRY_LOCK:
        if _SERVICE is not None and _SERVICE is not service:return False
        _SERVICE=service;_INGRESS=service._queue
    return True


def unregister_observer(service):
    global _SERVICE,_INGRESS
    with _REGISTRY_LOCK:
        if _SERVICE is service:_INGRESS=None;_SERVICE=None


def _enqueue(event):
    global _DROPPED
    ingress=_INGRESS
    if type(ingress) is not queue.Queue:return False
    try:
        ingress.put_nowait(event)
        try:
            from .preproduction_runtime import enqueue_proposal
            enqueue_proposal(event.payload())
        except Exception:
            pass
        return True
    except queue.Full:_DROPPED+=1;return False


def observe_entry_intent(**fields):
    """Fixed trusted producer route; no SQL, network, model, callback or wait."""
    global _DROPPED
    if _INGRESS is None:return False
    try:return _enqueue(build_intent(**fields))
    except Exception:_DROPPED+=1;return False


def observe_entry_outcome(**fields):
    global _DROPPED
    if _INGRESS is None:return False
    try:return _enqueue(build_outcome(**fields))
    except Exception:_DROPPED+=1;return False


def observe_position_commit(*,engine,environment,position_ref,at,remaining_quantity,quantity=None,proof=None):
    """Only a committed native position identity may resolve an earlier entry."""
    try:
        reference=position_digest(engine,environment,position_ref)
        closed=Decimal(str(remaining_quantity))==0
        return observe_entry_outcome(engine=engine,environment=environment,
            origin_ref='POSITION:'+reference,at=at,stage='LEDGER_COMMIT',
            state='CLOSED' if closed else 'PARTIAL',complete=closed,by_position=True,
            evidence={'position_digest':reference,'remaining_quantity':remaining_quantity,
                      'quantity':quantity,'decision_digest':proof})
    except Exception:
        return False


def _connect(path,readonly=False):
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.25) if readonly else sqlite3.connect(path,timeout=.25)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA trusted_schema=OFF')
    if readonly:db.execute('PRAGMA query_only=ON')
    return db


def _unknown(reason):
    return {'state':'UNKNOWN','reason':reason,'real_admission':'NOT_EVALUABLE','hypothetical_state':'UNKNOWN',
            'gross_notional':None,'committed_capital':None,'estimated_costs':None,
            'nominal_stop_risk':None,'stop_risk':None,'account_identity':'UNKNOWN'}


class OpportunityObserverService:
    def __init__(self,data_dir,*,enabled=True,clock=time.time,max_records=100000,max_bytes=16*1024*1024):
        if type(enabled) is not bool or type(max_records) is not int or not 1<=max_records<=100000 or type(max_bytes) is not int or not 65536<=max_bytes<=16*1024*1024:raise ValueError('INVALID_OBSERVER_SETTINGS')
        self.path=Path(data_dir)/'opportunity-shadow.db';self.enabled=enabled;self.clock=clock
        self.max_records,self.max_bytes=max_records,max_bytes
        self._queue=queue.Queue(maxsize=QUEUE_CAPACITY);self._stop=threading.Event();self._thread=None
        self._errors=0;self._last_error=None;self._initialized=False;self._last_heartbeat=0.
        self._lifecycle_lock=threading.Lock();self._heartbeat_monotonic=0.

    def initialize(self):
        global _DROPPED
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(_connect(self.path)) as db,db:
            db.executescript('''CREATE TABLE IF NOT EXISTS opportunity_records(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,origin TEXT NOT NULL,
              revision INTEGER NOT NULL,kind TEXT NOT NULL,engine TEXT NOT NULL,environment TEXT NOT NULL,
              at REAL NOT NULL,recorded REAL NOT NULL,state TEXT NOT NULL,stage TEXT NOT NULL,data TEXT NOT NULL,assessment TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS opportunity_origin ON opportunity_records(origin,sequence);
              CREATE TABLE IF NOT EXISTS opportunity_origins(origin TEXT PRIMARY KEY,engine TEXT,environment TEXT,
              intent_id TEXT,revision INTEGER,at REAL,state TEXT,metrics TEXT,symbols TEXT,closed INTEGER NOT NULL,terminal TEXT);
              CREATE TABLE IF NOT EXISTS opportunity_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS opportunity_positions(position_digest TEXT PRIMARY KEY,origin TEXT UNIQUE NOT NULL,
                engine TEXT NOT NULL,environment TEXT NOT NULL,proof_digest TEXT);
              CREATE TABLE IF NOT EXISTS opportunity_terminal_proofs(origin TEXT PRIMARY KEY,position_digest TEXT NOT NULL,
                proof_digest TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS opportunity_no_update BEFORE UPDATE ON opportunity_records BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;
              CREATE TRIGGER IF NOT EXISTS opportunity_no_delete BEFORE DELETE ON opportunity_records BEGIN SELECT RAISE(ABORT,'immutable evidence'); END;''')
            page=db.execute('PRAGMA page_size').fetchone()[0]
            db.execute('PRAGMA max_page_count='+str(max(16,self.max_bytes//page)))
            saved=dict(db.execute('SELECT key,value FROM opportunity_meta'))
            self._errors=int(saved.get('errors','0'));self._last_error=saved.get('last_error') or None
            _DROPPED=max(_DROPPED,int(saved.get('dropped','0')))
        self._initialized=True

    def _consume(self,event):
        if type(event) is not OpportunityEvent or len(event.encoded)>4096 or hashlib.sha256(event.encoded).hexdigest()!=event.id:raise ValueError('INVALID_EVENT')
        payload=event.payload();now=self.clock()
        if canonical(payload)!=event.encoded or payload.get('account_identity')!='UNKNOWN' or payload['at']>now:raise ValueError('CAUSALITY_ERROR')
        with closing(_connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM opportunity_records WHERE id=?',(event.id,)).fetchone():return 'IDEMPOTENT'
            count=db.execute('SELECT COUNT(*) FROM opportunity_records').fetchone()[0]
            if count>=self.max_records or self.path.stat().st_size>=self.max_bytes:
                self._last_error='RETENTION_FULL';return 'RETENTION_FULL'
            reference=payload.get('position_digest')
            resolved_origin=payload['origin_digest']
            link=None
            if payload.get('position_reference') is True:
                link=db.execute('SELECT origin FROM opportunity_positions WHERE position_digest=? AND engine=? AND environment=?',
                    (reference,payload['engine'],payload['environment'])).fetchone()
                if link:resolved_origin=link['origin']
            origin=(None if payload.get('position_reference') is True and not link else
                db.execute('SELECT * FROM opportunity_origins WHERE origin=?',(resolved_origin,)).fetchone())
            revision=origin['revision'] if origin else 1
            assessment=_unknown('MISSING_INTENT');state='UNKNOWN';stage=payload.get('stage','HYPOTHETICAL_ENTRY_INTENT' if payload['environment']=='SHADOW' else 'FINAL_ENTRY_INTENT')
            if payload['kind']=='ENTRY_INTENT':
                if origin:
                    revision+=1;assessment=_unknown('ORIGIN_REVISION_CONFLICT');state='ORIGIN_CONFLICT'
                    db.execute("UPDATE opportunity_origins SET revision=?,state='ORIGIN_CONFLICT' WHERE origin=?",(revision,payload['origin_digest']))
                else:
                    previous=[]
                    for held in db.execute("SELECT origin,metrics,symbols,state FROM opportunity_origins WHERE engine=? AND environment=? AND (closed=0 OR state IN ('ORIGIN_CONFLICT','TERMINAL_CONFLICT')) LIMIT 257",(payload['engine'],payload['environment'])):
                        metrics=json.loads(held['metrics']);previous.append({'origin_digest':held['origin'],'capital':metrics.get('committed_capital'),
                            'gross':metrics.get('gross_notional'),'stop_risk':metrics.get('stop_risk'),'costs':metrics.get('estimated_costs'),
                            'symbols':json.loads(held['symbols'])})
                        if held['state'] in ('ORIGIN_CONFLICT','UNCERTAIN','TERMINAL_CONFLICT'):previous[-1]['capital']=None
                    assessment=evaluate_intent(payload,previous)
                    state='UNCERTAIN' if assessment['hypothetical_state']=='UNKNOWN' else 'INTENT_OBSERVED'
                    hypothetical_rejected=assessment['hypothetical_state']=='REJECTED_UNVERIFIED'
                    db.execute('INSERT INTO opportunity_origins VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (payload['origin_digest'],payload['engine'],payload['environment'],event.id,revision,payload['at'],state,
                         canonical(assessment).decode(),canonical([leg['symbol'] for leg in payload['legs']]).decode(),int(hypothetical_rejected),None))
            elif payload['kind']=='ENTRY_OUTCOME' and origin:
                assessment=json.loads(origin['metrics']);state='UNCERTAIN'
                if payload['at']<origin['at']:
                    assessment=_unknown('OUTCOME_BEFORE_INTENT')
                elif origin['state']=='ORIGIN_CONFLICT':
                    assessment=_unknown('ORIGIN_REVISION_CONFLICT');state='ORIGIN_CONFLICT'
                elif (origin['terminal']=='CLOSED' and payload.get('position_reference') is True
                        and payload['state']=='CLOSED' and payload['complete']
                        and db.execute('SELECT 1 FROM opportunity_terminal_proofs WHERE origin=? AND position_digest=? AND proof_digest=?',
                            (resolved_origin,reference,payload['evidence'].get('decision_digest'))).fetchone()
                        and origin['state']!='TERMINAL_CONFLICT'):
                    state='CLOSED_OBSERVED'
                elif (origin['terminal']=='CLOSED' and payload['stage']=='LEDGER_COMMIT'
                        and payload['state']=='OPENED' and payload['complete']
                        and payload['evidence'].get('decision_digest') is not None
                        and db.execute('SELECT 1 FROM opportunity_positions WHERE origin=? AND position_digest=? AND proof_digest=?',
                            (resolved_origin,reference,payload['evidence']['decision_digest'])).fetchone()
                        and origin['state']!='TERMINAL_CONFLICT'):
                    # An exact durable receipt replay does not revive a close.
                    state='CLOSED_OBSERVED'
                elif origin['state']=='TERMINAL_CONFLICT' or origin['terminal'] in ('CLOSED','CANCELLED','REJECTED'):
                    state='TERMINAL_CONFLICT';assessment=_unknown('LATE_TERMINAL_DIVERGENCE')
                elif payload['stage']=='LEDGER_COMMIT' and payload['complete'] and payload['state']=='CLOSED':
                    state='CLOSED_OBSERVED'
                    db.execute("UPDATE opportunity_origins SET closed=1,state=?,terminal='CLOSED' WHERE origin=?",(state,resolved_origin))
                    if payload.get('position_reference') is True:
                        db.execute('INSERT INTO opportunity_terminal_proofs VALUES(?,?,?)',
                            (resolved_origin,reference,payload['evidence']['decision_digest']))
                elif payload['complete'] and payload['state'] in ('CANCELLED','REJECTED') and payload['evidence']['quantity']=='0' and origin['terminal'] not in ('FILLED','OPENED'):
                    state='CANCELLED_OBSERVED'
                    db.execute('UPDATE opportunity_origins SET closed=1,state=?,terminal=? WHERE origin=?',(state,payload['state'],payload['origin_digest']))
                elif payload['complete'] and payload['state']=='FILLED' and payload['stage']=='EXCHANGE_RESPONSE':
                    state='EXCHANGE_FILLED_UNCOMMITTED'
                    db.execute("UPDATE opportunity_origins SET terminal='FILLED' WHERE origin=?",(payload['origin_digest'],))
                elif payload['complete'] and payload['state']=='OPENED' and payload['stage']=='LEDGER_COMMIT':
                    state='COMMITTED_PROTECTION_UNVERIFIED'
                    if reference:
                        links=db.execute('SELECT origin,position_digest,proof_digest FROM opportunity_positions WHERE origin=? OR position_digest=?',
                            (resolved_origin,reference)).fetchall()
                        if links and any(link['origin']!=resolved_origin or link['position_digest']!=reference
                                or link['proof_digest']!=payload['evidence'].get('decision_digest') for link in links):
                            state='ORIGIN_CONFLICT';assessment=_unknown('ORIGIN_REVISION_CONFLICT')
                            for link in links:
                                db.execute("UPDATE opportunity_origins SET state='ORIGIN_CONFLICT' WHERE origin=?",(link['origin'],))
                        elif not links:
                            db.execute('INSERT INTO opportunity_positions VALUES(?,?,?,?,?)',
                                (reference,resolved_origin,payload['engine'],payload['environment'],payload['evidence'].get('decision_digest')))
                    if state!='ORIGIN_CONFLICT':
                        db.execute("UPDATE opportunity_origins SET terminal='OPENED' WHERE origin=?",(resolved_origin,))
                db.execute('UPDATE opportunity_origins SET state=? WHERE origin=?',(state,resolved_origin))
            db.execute('INSERT INTO opportunity_records(id,origin,revision,kind,engine,environment,at,recorded,state,stage,data,assessment) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (event.id,resolved_origin,revision,payload['kind'],payload['engine'],payload['environment'],payload['at'],now,state,stage,event.encoded.decode(),canonical(assessment).decode()))
        return state

    def _flush_health(self,*,heartbeat=False,stopped=False):
        try:
            with closing(_connect(self.path)) as db,db:
                values=[('errors',str(self._errors)),('dropped',str(_DROPPED)),('last_error',self._last_error or '')]
                if heartbeat:
                    self._last_heartbeat=self.clock()
                    self._heartbeat_monotonic=time.monotonic()
                    values.extend([('heartbeat_at',str(self._last_heartbeat)),('running','0' if stopped else '1')])
                db.executemany('INSERT OR REPLACE INTO opportunity_meta VALUES(?,?)',values)
        except Exception:pass

    def _run(self):
        self._flush_health(heartbeat=True)
        while not self._stop.is_set():
            try:event=self._queue.get(timeout=.25)
            except queue.Empty:
                if time.monotonic()-self._heartbeat_monotonic>=5:self._flush_health(heartbeat=True)
                continue
            try:
                result=self._consume(event)
                if result=='RETENTION_FULL':
                    global _DROPPED
                    _DROPPED+=1
            except Exception as error:
                self._errors+=1;self._last_error='JOURNAL_FULL' if isinstance(error,sqlite3.Error) and getattr(error,'sqlite_errorcode',None)==sqlite3.SQLITE_FULL else 'OBSERVATION_FAILED'
            finally:self._queue.task_done();self._flush_health(heartbeat=time.monotonic()-self._heartbeat_monotonic>=5)
        self._flush_health(heartbeat=True,stopped=True)

    def start(self):
        with self._lifecycle_lock:
            if not self.enabled:return False
            if self._thread is not None and self._thread.is_alive():return True
            if not register_observer(self):return False
            try:self.initialize()
            except Exception:
                unregister_observer(self);self._errors+=1;self._last_error='INITIALIZATION_FAILED';return False
            self._stop.clear();self._thread=threading.Thread(target=self._run,name='opportunity-shadow',daemon=True);self._thread.start();return True

    def stop(self,timeout=2.):
        unregister_observer(self);self._stop.set()
        if self._thread is not None:self._thread.join(max(0,min(2.,timeout)))

    def snapshot(self,*,now=None):return opportunity_snapshot(self.path.parent,now=self.clock() if now is None else now)


def opportunity_snapshot(data_dir,*,now=None):
    instant=time.time() if now is None else now;path=Path(data_dir)/'opportunity-shadow.db'
    clock_regression=False
    value={'schema':1,'engine':'OPPORTUNITY_SHADOW','mode':'SHADOW','autonomy_level':0,**FLAGS,
        'state':'NOT_STARTED','at':_iso(instant),'updated_at':None,'freshness':{'state':'UNAVAILABLE','age_seconds':None},
        'health':{'records':None,'errors':None,'dropped':None,'queue_depth':None,'queue_capacity':QUEUE_CAPACITY,'worker_alive':None,'capacity_state':'UNKNOWN','last_error':None,'heartbeat_at':None},
        'coverage':[{'engine':engine,'environment':('SPOT_TESTNET' if engine=='SPOT' else 'FUTURES_DEMO' if engine=='FUTURES' else 'SHADOW'),
                     'state':'NOT_CAPTURED','intents':0,'outcomes':0,'last_at':None} for engine in ENGINES],
        'scopes':[],'recent_records':[]}
    if not path.is_file():return value
    try:
        with closing(_connect(path,True)) as db:
            db.execute('BEGIN')
            total=db.execute('SELECT COUNT(*) FROM opportunity_records').fetchone()[0]
            metadata=dict(db.execute('SELECT key,value FROM opportunity_meta'))
            latest=db.execute('SELECT MAX(recorded) FROM opportunity_records').fetchone()[0]
            heartbeat=float(metadata['heartbeat_at']) if metadata.get('heartbeat_at') else None
            age=instant-heartbeat if heartbeat is not None else None
            clock_regression=(age is not None and age<0) or (latest is not None and latest>instant)
            running=metadata.get('running')=='1'
            fresh=running and age is not None and 0<=age<=15
            value.update(state=('IDLE' if not total else 'OBSERVING') if fresh else 'STALE',updated_at=_iso(latest),
                freshness={'state':'FRESH' if fresh else 'STALE' if age is not None and age>=0 else 'UNAVAILABLE','age_seconds':age if age is not None and age>=0 else None})
            value['health'].update(records=total,errors=int(metadata.get('errors','0')),dropped=int(metadata.get('dropped','0')),
                worker_alive=running if age is not None and 0<=age<=15 else None,heartbeat_at=_iso(heartbeat),
                last_error=metadata.get('last_error') if metadata.get('last_error') in ERROR_CODES else None,
                capacity_state='FULL' if metadata.get('last_error') in ('RETENTION_FULL','JOURNAL_FULL') else 'AVAILABLE')
            if clock_regression:value['health']['last_error']='CLOCK_REGRESSION'
            if value['health']['errors'] or value['health']['dropped'] or value['health']['last_error']:value['state']='PARTIAL'
            for item in value['coverage']:
                rows=db.execute('SELECT kind,COUNT(*) n,MAX(at) last FROM opportunity_records WHERE engine=? GROUP BY kind',(item['engine'],)).fetchall()
                for row in rows:item['intents' if row['kind']=='ENTRY_INTENT' else 'outcomes']=row['n']
                if rows:
                    environments=[row[0] for row in db.execute('SELECT DISTINCT environment FROM opportunity_records WHERE engine=?',(item['engine'],))]
                    item.update(state='OBSERVED',environment=environments[0] if len(environments)==1 else 'UNKNOWN',last_at=_iso(max(row['last'] for row in rows)))
            for group in db.execute('SELECT engine,environment FROM opportunity_origins GROUP BY engine,environment'):
                held=db.execute("SELECT metrics,state FROM opportunity_origins WHERE engine=? AND environment=? AND (closed=0 OR state IN ('ORIGIN_CONFLICT','TERMINAL_CONFLICT'))",tuple(group)).fetchall()
                def summed(key):
                    if any(row['state'] in ('ORIGIN_CONFLICT','TERMINAL_CONFLICT') for row in held):return None
                    metrics=[json.loads(row['metrics']).get(key) for row in held]
                    with localcontext(Context(prec=256)):
                        return format(sum((Decimal(item) for item in metrics),Decimal(0)),'f') if all(item is not None for item in metrics) else None
                capital,costs=summed('committed_capital'),summed('estimated_costs')
                with localcontext(Context(prec=256)):
                    reserved=format(Decimal(capital)+Decimal(costs),'f') if capital is not None and costs is not None else None
                value['scopes'].append({'engine':group['engine'],'environment':group['environment'],'account_identity':'UNKNOWN',
                    'hypothetical_reserved':reserved,'hypothetical_gross':summed('gross_notional'),
                    'hypothetical_stop_risk':summed('stop_risk'),'uncertain_intents':sum(row['state'] in ('UNCERTAIN','ORIGIN_CONFLICT','TERMINAL_CONFLICT') for row in held)})
            for row in db.execute('SELECT * FROM opportunity_records ORDER BY sequence DESC LIMIT 6'):
                payload=json.loads(row['data']);evidence=payload['evidence']
                if payload['kind']=='ENTRY_OUTCOME':
                    evidence={key:evidence.get(key) for key in ('response_digest','decision_digest','quantity','fees')}
                legs=[{key:leg[key] for key in ('symbol','venue','direction','quantity','reference_price','stop_price','take_profit')} for leg in payload.get('legs',[])]
                value['recent_records'].append({'id':row['id'],'origin_digest':row['origin'],'revision':row['revision'],'kind':row['kind'],
                    'engine':row['engine'],'environment':row['environment'],'at':_iso(row['at']),'recorded_at':_iso(row['recorded']),
                    'state':row['state'],'stage':row['stage'],'legs':legs,'payload_digest':row['id'],
                    'evidence':evidence,'assessment':json.loads(row['assessment'])})
    except (sqlite3.Error,ValueError,KeyError,TypeError,OverflowError):
        value.update(state='UNAVAILABLE',scopes=[],recent_records=[]);value['health']['last_error']='SNAPSHOT_UNAVAILABLE'
    service=_SERVICE
    if type(service) is OpportunityObserverService and service.path==path:
        value['health'].update(errors=service._errors,dropped=_DROPPED,queue_depth=service._queue.qsize(),
            worker_alive=bool(service._thread and service._thread.is_alive()),last_error=service._last_error or value['health']['last_error'],
            capacity_state='FULL' if service._last_error in ('RETENTION_FULL','JOURNAL_FULL') else value['health']['capacity_state'])
        if service._errors or _DROPPED or service._last_error:value['state']='PARTIAL'
    if clock_regression:
        # A later heartbeat cannot make evidence from before a UTC rollback
        # current. Preserve its original dates and expose clock uncertainty.
        value['state']='PARTIAL'
        value['freshness']={'state':'UNAVAILABLE','age_seconds':None}
        value['health']['last_error']='CLOCK_REGRESSION'
    while len(canonical(value))>MAX_SNAPSHOT_BYTES and value['recent_records']:value['recent_records'].pop()
    return value
