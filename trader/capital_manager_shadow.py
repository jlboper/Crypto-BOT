"""Unintegrated phase-3 protocol simulation, never an execution/capital adapter.

Every wallet/account/order/actor identity is explicitly SIM_*. Only a newly named
simulation SQLite file is accepted. No financial DB, broker, exchange or AI import
exists. Approved numbers below come from the caller's dated simulation policy;
there are no default financial budgets and no claim of real available balances.

Money is integer micro-USDT (1 USDT = 1_000_000 units). Book equity is not market
equity. Confirmed simulated fees/PnL are booked exactly; an overrun may create a
signed cash shortfall and RECOVERY_REQUIRED, never an optimistic zero-loss cap.
Committed units mean occupied principal/capital, not gross notional exposure or
verified exchange margin. Fee buffers cover the full entry/exit lifecycle. This
protocol has no prices, market-risk model, daily/weekly halt or real executor.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict,dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

APP="CAPITAL_MANAGER_SHADOW_SIMULATION_V1"
UNITS_PER_USDT=1_000_000
MAX_INTEGER=9_000_000_000_000_000
# This isolated SIM protocol may contend on Windows hosts. Waiting for SQLite's
# lock is bounded and precedes the transaction; it is never an order retry or an
# extension of the caller's balance/expiry checks inside the acquired lock.
SIMULATION_BUSY_SECONDS=5
ENVIRONMENTS=frozenset(("SHADOW","PAPER","SPOT_TESTNET","FUTURES_DEMO"))
TERMINAL=frozenset(("CANCELLED","CLOSED"))
ORDER_STATES=frozenset(("RESERVED","SUBMITTING","PARTIAL","FILLED","UNKNOWN","CANCEL_PENDING","CANCELLED","CLOSED","RECOVERY_REQUIRED"))
_ID=re.compile(r"^SIM_[A-Za-z0-9_-]{1,80}$")
_SYMBOL=re.compile(r"^[A-Z0-9]{2,24}USDT$")


class SimulationError(ValueError):
    pass


def _id(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):
        raise SimulationError("EXPLICIT_SIMULATION_ID_REQUIRED")
    return value


def _money(value,*,signed=False,positive=False):
    if type(value) is not int or not -MAX_INTEGER<=value<=MAX_INTEGER or not signed and value<0 or positive and value<=0:
        raise SimulationError("INTEGER_ATOMIC_MONEY_REQUIRED")
    return value


def _at(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<253402300799:
        raise SimulationError("INVALID_SIMULATION_TIME")
    return float(value)


def _json(value):
    encoded=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False,ensure_ascii=True)
    if len(encoded)>32768:
        raise SimulationError("SIMULATION_EVENT_SIZE_LIMIT")
    return encoded


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class AccountScope:
    environment:str
    account_id:str
    currency:str
    def __post_init__(self):
        if self.environment not in ENVIRONMENTS or self.currency!="USDT":
            raise SimulationError("UNSUPPORTED_SIMULATION_SCOPE")
        _id(self.account_id)


@dataclass(frozen=True)
class SimulationLimits:
    policy_id:str
    approved_actor:str
    approved_at:float
    funding_source:str
    initial_balance_units:int
    total_allocated_limit_units:int
    reserved_limit_units:int
    committed_limit_units:int
    stop_risk_limit_units:int
    # Explicit scenario participants: (strategy_id, allocated_cap, stop_risk_cap).
    strategy_limits:tuple[tuple[str,int,int],...]
    balance_max_age_seconds:int
    max_active_requests:int
    def __post_init__(self):
        _id(self.policy_id);_id(self.approved_actor);_at(self.approved_at)
        if self.funding_source!="EXPLICIT_NEW_SIMULATION_COHORT":
            raise SimulationError("EXPLICIT_SIMULATION_FUNDING_REQUIRED")
        for key in ("initial_balance_units","total_allocated_limit_units","reserved_limit_units","committed_limit_units","stop_risk_limit_units"):
            _money(getattr(self,key),positive=True)
        if max(self.total_allocated_limit_units,self.reserved_limit_units,self.committed_limit_units,self.stop_risk_limit_units)>self.initial_balance_units:
            raise SimulationError("SIMULATION_LIMIT_ABOVE_FUNDED_BALANCE")
        if (not isinstance(self.strategy_limits,tuple) or not 1<=len(self.strategy_limits)<=16
                or type(self.balance_max_age_seconds) is not int or not 1<=self.balance_max_age_seconds<=86400
                or type(self.max_active_requests) is not int or not 1<=self.max_active_requests<=100):
            raise SimulationError("BOUNDED_EXPLICIT_POLICY_REQUIRED")
        names=set()
        for row in self.strategy_limits:
            if not isinstance(row,tuple) or len(row)!=3:raise SimulationError("IMMUTABLE_STRATEGY_POLICY_REQUIRED")
            name,allocated,risk=row
            _id(name);_money(allocated,positive=True);_money(risk,positive=True)
            if name in names or allocated>self.total_allocated_limit_units or risk>self.stop_risk_limit_units:
                raise SimulationError("INVALID_STRATEGY_SIMULATION_BUDGET")
            names.add(name)


@dataclass(frozen=True)
class LegRequest:
    leg_id:str
    symbol:str
    direction:str
    venue:str
    principal_units:int
    fee_buffer_units:int
    stop_risk_units:int
    def __post_init__(self):
        _id(self.leg_id)
        if not isinstance(self.symbol,str) or not _SYMBOL.fullmatch(self.symbol) or self.direction not in {"LONG","SHORT"} or self.venue not in {"SPOT_REFERENCE","FUTURES_REFERENCE"}:
            raise SimulationError("INVALID_SIMULATED_LEG")
        _money(self.principal_units,positive=True);_money(self.fee_buffer_units);_money(self.stop_risk_units,positive=True)


@dataclass(frozen=True)
class ReservationRequest:
    request_id:str
    scope:AccountScope
    strategy_id:str
    policy_id:str
    legs:tuple[LegRequest,...]
    expires_at:float
    def __post_init__(self):
        _id(self.request_id);_id(self.strategy_id);_id(self.policy_id);_at(self.expires_at)
        if (not isinstance(self.scope,AccountScope) or not isinstance(self.legs,tuple) or not 1<=len(self.legs)<=4
                or any(not isinstance(v,LegRequest) for v in self.legs) or len({v.leg_id for v in self.legs})!=len(self.legs)):
            raise SimulationError("COMPLETE_ATOMIC_LEGS_REQUIRED")


@dataclass(frozen=True)
class ReconciliationEvent:
    event_id:str
    scope:AccountScope
    request_id:str
    leg_id:str
    actor:str
    order_state:str
    cumulative_filled_units:int
    cumulative_entry_fees_units:int
    cumulative_exit_fees_units:int
    cumulative_realized_pnl_units:int
    position_closed:bool
    observed_at:float
    complete:bool
    def __post_init__(self):
        for value in (self.event_id,self.request_id,self.leg_id,self.actor):_id(value)
        if not isinstance(self.scope,AccountScope) or self.order_state not in {"PARTIAL","FILLED","UNKNOWN","CANCELLED","CLOSED"}:
            raise SimulationError("INVALID_RECONCILIATION_STATE")
        for value in (self.cumulative_filled_units,self.cumulative_entry_fees_units,self.cumulative_exit_fees_units):_money(value)
        _money(self.cumulative_realized_pnl_units,signed=True);_at(self.observed_at)
        if type(self.position_closed) is not bool or type(self.complete) is not bool:
            raise SimulationError("EXPLICIT_SIMULATION_FACT_REQUIRED")


@contextmanager
def _connection(path,readonly=False):
    if readonly:
        if not Path(path).is_file():raise SimulationError("SIMULATION_WALLET_NOT_INITIALIZED")
        with Path(path).open("rb") as handle:header=handle.read(100)
        if not header.startswith(b"SQLite format 3\0") or header[18:20]!=b"\x01\x01":
            raise SimulationError("FOREIGN_OR_UNSUPPORTED_SIMULATION_FILE")
        db=sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True,timeout=SIMULATION_BUSY_SECONDS)
        db.execute("PRAGMA query_only=ON")
    else:
        db=sqlite3.connect(path,timeout=SIMULATION_BUSY_SECONDS)
    try:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
        yield db
        if not readonly:db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:db.close()


class CapitalManagerShadow:
    def __init__(self,path,*,wallet_name,scope,limits,clock=time.time,fault_hook=None):
        _id(wallet_name)
        if not isinstance(scope,AccountScope) or not isinstance(limits,SimulationLimits):
            raise SimulationError("EXPLICIT_SCOPE_AND_SIMULATION_POLICY_REQUIRED")
        self.path=Path(path)
        if self.path.name!=wallet_name+".simulation.sqlite3" or self.path.is_symlink():
            raise SimulationError("SEPARATE_NAMED_SIMULATION_WALLET_REQUIRED")
        self.wallet_name,self.scope,self.limits,self.clock=wallet_name,scope,limits,clock
        self._initialized=False
        self.fault_hook=fault_hook  # Synthetic crash injection, never an executor.
        self.identity={"app":APP,"wallet_name":wallet_name,"scope":asdict(scope),"policy":asdict(limits)}
        self._frozen_identity_json=_json(self.identity)

    def initialize(self):
        if self.limits.approved_at>self.clock():raise SimulationError("FUTURE_POLICY_NOT_APPROVED")
        if self.path.exists():
            with _connection(self.path,True) as db:self._identity(db)
            self._initialized=True
            return self.snapshot()
        if not self.path.parent.is_dir():raise SimulationError("SIMULATION_DIRECTORY_MUST_EXIST")
        # Exclusive empty-file creation never opens or migrates another wallet.
        with self.path.open("xb"):pass
        with _connection(self.path) as db:
            db.execute("CREATE TABLE identity(singleton INTEGER PRIMARY KEY CHECK(singleton=1),data TEXT NOT NULL)")
            db.execute("INSERT INTO identity VALUES(1,?)",(self._frozen_identity_json,))
            db.execute("CREATE TABLE account(singleton INTEGER PRIMARY KEY,fees INTEGER NOT NULL,pnl INTEGER NOT NULL,epoch INTEGER NOT NULL,balance_epoch INTEGER NOT NULL,balance_units INTEGER NOT NULL,balance_at REAL NOT NULL,balance_known INTEGER NOT NULL,pending_complete INTEGER NOT NULL,epoch_at REAL NOT NULL)")
            db.execute("INSERT INTO account VALUES(1,0,0,0,0,?,?,1,1,?)",(self.limits.initial_balance_units,self.limits.approved_at,self.limits.approved_at))
            db.execute("CREATE TABLE requests(id TEXT PRIMARY KEY,strategy TEXT NOT NULL,state TEXT NOT NULL,risk INTEGER NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL)")
            db.execute("CREATE TABLE legs(request_id TEXT NOT NULL,id TEXT NOT NULL,symbol TEXT NOT NULL,principal INTEGER NOT NULL,fee_buffer INTEGER NOT NULL,reserved INTEGER NOT NULL,committed INTEGER NOT NULL,filled INTEGER NOT NULL,entry_fees INTEGER NOT NULL,exit_fees INTEGER NOT NULL,pnl INTEGER NOT NULL,closed INTEGER NOT NULL,order_state TEXT NOT NULL,client_id TEXT UNIQUE,submitted_at REAL,terminal_state TEXT,terminal_filled INTEGER,PRIMARY KEY(request_id,id))")
            db.execute("CREATE TABLE asset_locks(symbol TEXT PRIMARY KEY,request_id TEXT NOT NULL)")
            db.execute("CREATE INDEX active_requests ON requests(state,strategy) WHERE state NOT IN ('CANCELLED','CLOSED')")
            db.execute("CREATE INDEX active_legs ON legs(request_id) WHERE reserved<>0 OR committed<>0")
            db.execute("CREATE INDEX leg_order_state ON legs(order_state)")
            db.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,payload_digest TEXT NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL,at REAL NOT NULL)")
            db.execute("CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'simulation journal is append-only'); END")
            db.execute("CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'simulation journal is append-only'); END")
            funding={"kind":"INITIAL_SIMULATION_FUNDING","identity":json.loads(self._frozen_identity_json),"units":self.limits.initial_balance_units}
            db.execute("INSERT INTO events(id,payload_digest,payload,result,at) VALUES(?,?,?,?,?)",("SIM_INITIAL_FUNDING",_digest(funding),_json(funding),_json({"simulation_only":True,"funding_source":self.limits.funding_source}),self.limits.approved_at))
        self._initialized=True
        return self.snapshot()

    def _identity(self,db):
        current={"app":APP,"wallet_name":self.wallet_name,"scope":asdict(self.scope),"policy":asdict(self.limits)}
        if _json(current)!=self._frozen_identity_json:raise SimulationError("SIMULATION_POLICY_MUTATED")
        try:row=db.execute("SELECT data FROM identity WHERE singleton=1").fetchone()
        except sqlite3.Error:raise SimulationError("FOREIGN_SIMULATION_WALLET") from None
        if row is None or row[0]!=self._frozen_identity_json:raise SimulationError("SIMULATION_IDENTITY_OR_POLICY_MISMATCH")

    def _totals(self,db):
        row=db.execute("SELECT * FROM account WHERE singleton=1").fetchone()
        values=db.execute("SELECT COALESCE(SUM(reserved),0),COALESCE(SUM(committed),0) FROM legs WHERE reserved<>0 OR committed<>0").fetchone()
        equity=_money(self.limits.initial_balance_units+row["pnl"]-row["fees"],signed=True)
        free=_money(equity-values[0]-values[1],signed=True)
        return {"book_equity_units":equity,"reserved_units":values[0],"committed_units":values[1],"free_units_signed":free,
                "available_units":max(0,free),"shortfall_units":max(0,-free),"fees_paid_units":row["fees"],"realized_pnl_units":row["pnl"]}

    def _apply(self,event_id,payload,mutation):
        if not self._initialized:raise SimulationError("EXPLICIT_INITIALIZE_REQUIRED")
        _id(event_id)
        event={"scope":asdict(self.scope),"wallet_name":self.wallet_name,**payload}
        encoded,digest=_json(event),_digest(event)
        result=None
        with _connection(self.path) as db:
            self._identity(db)
            prior=db.execute("SELECT payload_digest,result FROM events WHERE id=?",(event_id,)).fetchone()
            if prior:
                if prior[0]!=digest:raise SimulationError("IDEMPOTENCY_CONFLICT")
                return json.loads(prior[1])
            result=mutation(db)
            self._totals(db)  # Exact integer conservation; overflows abort atomically.
            db.execute("INSERT INTO events(id,payload_digest,payload,result,at) VALUES(?,?,?,?,?)",(event_id,digest,encoded,_json(result),self.clock()))
            if self.fault_hook:self.fault_hook("BEFORE_COMMIT")
        if self.fault_hook:self.fault_hook("AFTER_COMMIT")
        return result

    def _request(self,db,request_id):
        row=db.execute("SELECT * FROM requests WHERE id=?",(request_id,)).fetchone()
        if row is None:raise SimulationError("SIMULATION_REQUEST_NOT_FOUND")
        return row

    def _uncertain(self,db):
        return bool(db.execute("SELECT 1 FROM legs WHERE order_state IN ('SUBMITTING','PARTIAL','UNKNOWN','CANCEL_PENDING','RECOVERY_REQUIRED') LIMIT 1").fetchone()
                    or db.execute("SELECT 1 FROM requests WHERE state IN ('SUBMITTING','PARTIAL','UNKNOWN','CANCEL_PENDING','RECOVERY_REQUIRED') LIMIT 1").fetchone())

    def _gate(self,db):
        account=db.execute("SELECT * FROM account WHERE singleton=1").fetchone()
        age=self.clock()-account["balance_at"]
        if not account["balance_known"] or account["balance_epoch"]!=account["epoch"] or account["balance_at"]<account["epoch_at"]:return "BALANCE_UNKNOWN_OR_CHANGED"
        if not 0<=age<=self.limits.balance_max_age_seconds:return "BALANCE_STALE_OR_FUTURE"
        if not account["pending_complete"] or self._uncertain(db):return "PENDING_ORDER_RECONCILIATION_REQUIRED"
        if self._totals(db)["free_units_signed"]<0:return "SIMULATED_CASH_SHORTFALL"
        return None

    def observe_balance(self,event_id,*,actor,balance_units,observed_at,known,pending_orders_complete):
        _id(actor);_money(balance_units,signed=True);_at(observed_at)
        if type(known) is not bool or type(pending_orders_complete) is not bool:raise SimulationError("EXPLICIT_BALANCE_FACT_REQUIRED")
        def mutation(db):
            account=db.execute("SELECT epoch,epoch_at FROM account WHERE singleton=1").fetchone()
            matches=known and balance_units==self._totals(db)["book_equity_units"] and account["epoch_at"]<=observed_at<=self.clock()
            db.execute("UPDATE account SET balance_units=?,balance_at=?,balance_known=?,pending_complete=?,balance_epoch=? WHERE singleton=1",
                (balance_units,observed_at,int(matches),int(pending_orders_complete),account[0]))
            return {"accepted":matches,"state":"KNOWN" if matches else "UNKNOWN","simulation_only":True}
        return self._apply(event_id,{"kind":"BALANCE_OBSERVATION","actor":actor,"balance_units":balance_units,"observed_at":observed_at,"known":known,"pending_orders_complete":pending_orders_complete},mutation)

    def reserve(self,request):
        if not isinstance(request,ReservationRequest) or request.scope!=self.scope or request.policy_id!=self.limits.policy_id:
            raise SimulationError("REQUEST_SCOPE_OR_POLICY_MISMATCH")
        def mutation(db):
            if db.execute("SELECT 1 FROM requests WHERE id=?",(request.request_id,)).fetchone():raise SimulationError("REQUEST_ID_ALREADY_USED")
            reason=self._gate(db)
            if reason:return {"accepted":False,"reason":reason,"simulation_only":True}
            if request.expires_at<=self.clock():return {"accepted":False,"reason":"PROPOSAL_EXPIRED","simulation_only":True}
            budgets={row[0]:row[1:] for row in self.limits.strategy_limits}
            if request.strategy_id not in budgets:return {"accepted":False,"reason":"STRATEGY_NOT_SCENARIO_PARTICIPANT","simulation_only":True}
            amount=_money(sum(leg.principal_units+leg.fee_buffer_units for leg in request.legs),positive=True)
            principal=sum(leg.principal_units for leg in request.legs)
            risk=_money(sum(leg.stop_risk_units for leg in request.legs),positive=True)
            total=self._totals(db)
            active=db.execute("SELECT COUNT(*),COALESCE(SUM(risk),0) FROM requests WHERE state NOT IN ('CANCELLED','CLOSED')").fetchone()
            strategy=db.execute("SELECT COALESCE(SUM(l.reserved+l.committed),0) FROM legs l JOIN requests r ON r.id=l.request_id WHERE r.strategy=? AND (l.reserved<>0 OR l.committed<>0)",(request.strategy_id,)).fetchone()[0]
            strategy_risk=db.execute("SELECT COALESCE(SUM(risk),0) FROM requests WHERE strategy=? AND state NOT IN ('CANCELLED','CLOSED')",(request.strategy_id,)).fetchone()[0]
            future_committed=db.execute("SELECT COALESCE(SUM(CASE WHEN closed=1 OR order_state IN ('FILLED','CANCELLED','CLOSED') THEN committed ELSE principal END),0) FROM legs WHERE reserved<>0 OR committed<>0").fetchone()[0]
            if (amount>total["available_units"] or total["reserved_units"]+amount>self.limits.reserved_limit_units
                    or total["reserved_units"]+total["committed_units"]+amount>self.limits.total_allocated_limit_units
                    or future_committed+principal>self.limits.committed_limit_units or active[1]+risk>self.limits.stop_risk_limit_units
                    or strategy+amount>budgets[request.strategy_id][0] or strategy_risk+risk>budgets[request.strategy_id][1]
                    or active[0]>=self.limits.max_active_requests):
                return {"accepted":False,"reason":"EXPLICIT_SIMULATION_BUDGET_EXCEEDED","simulation_only":True}
            symbols={leg.symbol for leg in request.legs}
            if any(db.execute("SELECT 1 FROM asset_locks WHERE symbol=?",(symbol,)).fetchone() for symbol in symbols):
                return {"accepted":False,"reason":"ACCOUNT_ASSET_ALREADY_RESERVED","simulation_only":True}
            db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?,?)",(request.request_id,request.strategy_id,"RESERVED",risk,_json(asdict(request)),self.clock(),request.expires_at))
            for leg in request.legs:
                db.execute("INSERT INTO legs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(request.request_id,leg.leg_id,leg.symbol,leg.principal_units,leg.fee_buffer_units,leg.principal_units+leg.fee_buffer_units,0,0,0,0,0,0,"RESERVED",None,None,None,None))
            db.executemany("INSERT INTO asset_locks VALUES(?,?)",[(symbol,request.request_id) for symbol in symbols])
            return {"accepted":True,"state":"RESERVED","request_id":request.request_id,"reserved_units":amount,"simulation_only":True}
        return self._apply(request.request_id,{"kind":"RESERVE","request":asdict(request)},mutation)

    def mark_submitting(self,event_id,request_id,*,actor,client_order_ids):
        _id(actor);_id(request_id)
        if not isinstance(client_order_ids,dict) or not 1<=len(client_order_ids)<=4:raise SimulationError("COMPLETE_SIMULATED_ORDER_IDS_REQUIRED")
        for key,value in client_order_ids.items():_id(key);_id(value)
        if len(set(client_order_ids.values()))!=len(client_order_ids):raise SimulationError("DUPLICATE_SIMULATED_ORDER_ID")
        def mutation(db):
            request=self._request(db,request_id)
            legs=db.execute("SELECT id,order_state FROM legs WHERE request_id=?",(request_id,)).fetchall()
            if request["state"]!="RESERVED" or {row[0] for row in legs}!=set(client_order_ids):raise SimulationError("INVALID_SUBMISSION_TRANSITION")
            reason=self._gate(db)
            if request["expires"]<=self.clock():reason="PROPOSAL_EXPIRED"
            if reason:return {"accepted":False,"state":"RESERVED","reason":reason,"simulation_only":True,"execution_enabled":False}
            submitted_at=self.clock()
            for leg in legs:db.execute("UPDATE legs SET order_state='SUBMITTING',client_id=?,submitted_at=? WHERE request_id=? AND id=?",(client_order_ids[leg[0]],submitted_at,request_id,leg[0]))
            db.execute("UPDATE requests SET state='SUBMITTING' WHERE id=?",(request_id,))
            return {"accepted":True,"state":"SUBMITTING","simulation_only":True,"execution_enabled":False}
        return self._apply(event_id,{"kind":"MARK_SUBMITTING","request_id":request_id,"actor":actor,"client_order_ids":client_order_ids},mutation)

    def request_cancel(self,event_id,request_id,*,actor):
        _id(actor);_id(request_id)
        def mutation(db):
            self._request(db,request_id)
            count=db.execute("UPDATE legs SET order_state='CANCEL_PENDING' WHERE request_id=? AND order_state NOT IN ('FILLED','CANCELLED','CLOSED')",(request_id,)).rowcount
            if count==0:raise SimulationError("NO_PENDING_ORDER_TO_CANCEL")
            db.execute("UPDATE requests SET state='CANCEL_PENDING' WHERE id=?",(request_id,))
            return {"state":"CANCEL_PENDING","released_units":0,"simulation_only":True}
        return self._apply(event_id,{"kind":"CANCEL_REQUEST","request_id":request_id,"actor":actor},mutation)

    def recover(self,event_id,*,actor):
        _id(actor)
        def mutation(db):
            rows=db.execute("SELECT DISTINCT request_id FROM legs WHERE order_state IN ('SUBMITTING','PARTIAL','CANCEL_PENDING')").fetchall()
            for row in rows:
                db.execute("UPDATE legs SET order_state='UNKNOWN' WHERE request_id=? AND order_state IN ('SUBMITTING','PARTIAL','CANCEL_PENDING')",(row[0],))
                db.execute("UPDATE requests SET state='UNKNOWN' WHERE id=?",(row[0],))
            return {"state":"RECOVERY_REQUIRED" if rows else "NO_UNCERTAIN_ORDERS","requests":len(rows),"released_units":0,"simulation_only":True}
        return self._apply(event_id,{"kind":"RESTART_RECONCILIATION","actor":actor},mutation)

    def _derive(self,db,request_id):
        legs=[dict(row) for row in db.execute("SELECT * FROM legs WHERE request_id=?",(request_id,))]
        states={row["order_state"] for row in legs}
        if "RECOVERY_REQUIRED" in states:state="RECOVERY_REQUIRED"
        elif "UNKNOWN" in states:state="UNKNOWN"
        elif "CANCEL_PENDING" in states:state="CANCEL_PENDING"
        elif all(row["closed"] or row["filled"]==0 and row["order_state"]=="CANCELLED" for row in legs):state="CLOSED" if any(row["filled"] for row in legs) else "CANCELLED"
        elif "CANCELLED" in states and any(row["committed"] for row in legs):state="RECOVERY_REQUIRED"
        elif states=={"FILLED"}:state="FILLED"
        elif any(row["filled"] for row in legs):state="PARTIAL"
        elif "SUBMITTING" in states:state="SUBMITTING"
        else:state="RESERVED"
        db.execute("UPDATE requests SET state=? WHERE id=?",(state,request_id))
        if state in TERMINAL:db.execute("DELETE FROM asset_locks WHERE request_id=?",(request_id,))
        return state

    def reconcile(self,event):
        if not isinstance(event,ReconciliationEvent) or event.scope!=self.scope:raise SimulationError("RECONCILIATION_SCOPE_MISMATCH")
        def mutation(db):
            request=self._request(db,event.request_id)
            row=db.execute("SELECT * FROM legs WHERE request_id=? AND id=?",(event.request_id,event.leg_id)).fetchone()
            if row is None:raise SimulationError("SIMULATED_LEG_NOT_FOUND")
            # Runtime UNKNOWN/recovery states never erase a final entry quantity.
            # Otherwise CANCELLED->UNKNOWN->FILLED could revive released funds and
            # bypass both account budgets and the asset lock owned by a successor.
            final=row["terminal_state"]
            if final is not None and (not event.complete or event.order_state=="UNKNOWN"
                    or event.cumulative_filled_units!=row["terminal_filled"]
                    or event.order_state not in {final,"CLOSED"}):
                db.execute("UPDATE legs SET order_state='RECOVERY_REQUIRED' WHERE request_id=? AND id=?",(event.request_id,event.leg_id))
                db.execute("UPDATE account SET balance_known=0 WHERE singleton=1")
                return {"accepted":False,"state":self._derive(db,event.request_id),"reason":"TERMINAL_SIMULATION_FACT_DIVERGENCE","released_units":0,"simulation_only":True}
            if not event.complete or event.order_state=="UNKNOWN" or not 0<=self.clock()-event.observed_at<=self.limits.balance_max_age_seconds:
                db.execute("UPDATE legs SET order_state='UNKNOWN' WHERE request_id=? AND id=?",(event.request_id,event.leg_id))
                return {"state":self._derive(db,event.request_id),"released_units":0,"simulation_only":True}
            if (event.cumulative_filled_units<row["filled"] or event.cumulative_filled_units>row["principal"]
                    or event.cumulative_entry_fees_units<row["entry_fees"] or event.cumulative_exit_fees_units<row["exit_fees"]
                    or row["closed"] and event.cumulative_realized_pnl_units!=row["pnl"]
                    or event.cumulative_filled_units>0 and (row["client_id"] is None or row["submitted_at"] is None or event.observed_at<row["submitted_at"])
                    or row["closed"] and not event.position_closed
                    or row["order_state"] in {"FILLED","CANCELLED","CLOSED"} and event.cumulative_filled_units!=row["filled"]
                    or row["order_state"] in {"FILLED","CANCELLED","CLOSED"} and event.order_state not in {row["order_state"],"CLOSED"}
                    or event.order_state=="FILLED" and event.cumulative_filled_units==0
                    or event.order_state=="PARTIAL" and event.position_closed
                    or event.order_state=="CLOSED" and not event.position_closed
                    or event.cumulative_filled_units==0 and event.cumulative_realized_pnl_units!=0
                    or event.cumulative_realized_pnl_units!=0 and not event.position_closed):
                db.execute("UPDATE legs SET order_state='RECOVERY_REQUIRED' WHERE request_id=? AND id=?",(event.request_id,event.leg_id))
                db.execute("UPDATE account SET balance_known=0 WHERE singleton=1")
                return {"accepted":False,"state":self._derive(db,event.request_id),"reason":"CONTRADICTORY_SIMULATED_RECONCILIATION","released_units":0,"simulation_only":True}
            filled=event.cumulative_filled_units
            fees_delta=event.cumulative_entry_fees_units+event.cumulative_exit_fees_units-row["entry_fees"]-row["exit_fees"]
            pnl_delta=event.cumulative_realized_pnl_units-row["pnl"]
            committed=0 if event.position_closed else filled
            total_fees=event.cumulative_entry_fees_units+event.cumulative_exit_fees_units
            terminal_order=event.order_state in {"FILLED","CANCELLED","CLOSED"}
            # Keep unspent lifetime exit costs while any filled capital is held.
            # Terminal entry orders release unused principal, not exit buffers.
            if event.position_closed or terminal_order and filled==0:reserved=0
            else:reserved=(0 if terminal_order else row["principal"]-filled)+max(0,row["fee_buffer"]-total_fees)
            released=max(0,row["reserved"]-(filled-row["filled"])-fees_delta-reserved)
            db.execute("UPDATE legs SET reserved=?,committed=?,filled=?,entry_fees=?,exit_fees=?,pnl=?,closed=?,order_state=?,terminal_state=?,terminal_filled=? WHERE request_id=? AND id=?",
                (reserved,committed,filled,event.cumulative_entry_fees_units,event.cumulative_exit_fees_units,event.cumulative_realized_pnl_units,int(event.position_closed),event.order_state,event.order_state if terminal_order else final,filled if terminal_order else row["terminal_filled"],event.request_id,event.leg_id))
            if fees_delta or pnl_delta or committed!=row["committed"]:
                db.execute("UPDATE account SET fees=fees+?,pnl=pnl+?,epoch=epoch+1,balance_known=0,epoch_at=? WHERE singleton=1",(fees_delta,pnl_delta,self.clock()))
            state=self._derive(db,event.request_id)
            if total_fees>row["fee_buffer"] or self._totals(db)["free_units_signed"]<0:
                db.execute("UPDATE legs SET order_state='RECOVERY_REQUIRED' WHERE request_id=? AND id=?",(event.request_id,event.leg_id))
                state=self._derive(db,event.request_id)
            return {"state":state,"leg_order_state":event.order_state,"released_units":released,"fees_delta_units":fees_delta,"pnl_delta_units":pnl_delta,
                    "simulation_only":True,"execution_enabled":False,"atomic_hedge_claimed":False}
        return self._apply(event.event_id,{"kind":"SIMULATED_RECONCILIATION","event":asdict(event)},mutation)

    def snapshot(self):
        with _connection(self.path,True) as db:
            self._identity(db)
            totals=self._totals(db)
            account=db.execute("SELECT balance_at,balance_known,epoch,balance_epoch,pending_complete,epoch_at FROM account WHERE singleton=1").fetchone()
            recent=[]
            total_requests=db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
            for row in db.execute("SELECT id,strategy,state,created,expires FROM requests ORDER BY CASE WHEN state IN ('CLOSED','CANCELLED') THEN 1 ELSE 0 END,created DESC,id LIMIT 20"):
                item=dict(row)
                item["expired_diagnostic_only"]=item["expires"]<self.clock()
                item["legs"]=[dict(leg) for leg in db.execute("SELECT id,symbol,reserved,committed,filled,entry_fees,exit_fees,pnl,closed,order_state,client_id FROM legs WHERE request_id=? LIMIT 4",(item["id"],))]
                recent.append(item)
            return {"app":APP,"wallet_name":self.wallet_name,"scope":asdict(self.scope),"policy_id":self.limits.policy_id,
                    "simulation_only":True,"execution_enabled":False,"real_account_adapter":False,"atomic_hedge_claimed":False,
                    "unit":"MICRO_USDT","units_per_usdt":UNITS_PER_USDT,**totals,"entry_gate":self._gate(db),
                    "balance_evidence":dict(account),"requests":recent,
                    "request_count":total_requests,"requests_omitted":max(0,total_requests-len(recent)),"inventory_complete":total_requests==len(recent),
                    "event_count":db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    "limitations":["EXPLICIT_VIRTUAL_SCENARIO_ONLY","NO_EXISTING_WALLET_OR_EXCHANGE_READ","NO_REAL_SHARED_ACCOUNT_PROTOCOL","BOOK_VALUE_NOT_MARKET_EQUITY","COMMITTED_CAPITAL_NOT_GROSS_NOTIONAL","NO_MARKET_RISK_OR_DAILY_WEEKLY_HALT","NO_TTL_RELEASE_OF_UNCERTAIN_ORDERS"]}
