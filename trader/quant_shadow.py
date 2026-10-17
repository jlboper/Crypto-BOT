"""Persistent, supervised, two-leg Quant research. SHADOW is the only mode.

There is no exchange execution/account client, AI call, live/Testnet activation or
Guardian veto. Every fill, margin reserve and funding receipt below is hypothetical.
Numerical loss estimates cannot guarantee fills or hedge atomicity during gaps.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .quant_models import funding_signal, statarb_signal
from .quant_public import QuantPublicFeed, SYMBOLS


DB_NAME = "quant-shadow.db"
RULE_VERSION = "quant-shadow-v1"
_OWNERS = {}
_OWNERS_LOCK = threading.Lock()
STRATEGIES = ("FUNDING_CARRY", "STATISTICAL_ARBITRAGE")
LIMITATIONS = ["SHADOW_ONLY_NO_EXCHANGE_EXECUTION", "TWO_LEGS_ARE_NOT_AN_ATOMIC_EXCHANGE_HEDGE",
    "SEPARATE_VIRTUAL_CAPITAL_NO_TESTNET_DEMO_AGGREGATION", "STRESS_RISK_ESTIMATE_IS_NOT_A_MAXIMUM_LOSS_GUARANTEE",
    "FUNDING_PROJECTIONS_ARE_NOT_SETTLED_INCOME", "PUBLIC_REFERENCE_DEPTH_IS_PARTIAL",
    "VIRTUAL_MARGIN_STRESS_PROXY_NOT_EXCHANGE_LIQUIDATION_MODEL",
    "INITIAL_HYPOTHESES_NOT_STATISTICALLY_OPTIMAL", "STATISTICAL_SCREEN_NOT_INDEPENDENT_COINTEGRATION_PROOF",
    "PROSPECTIVE_EVIDENCE_NOT_AUTOMATIC_STRATEGY_PROMOTION", "GUARDIAN_OBSERVER_HAS_NO_VETO"]


@dataclass(frozen=True)
class QuantConfig:
    enabled: bool = True
    mode: str = "SHADOW"
    initial_capital: float = 1000.
    risk_per_trade: float = .0025
    daily_loss_limit: float = .01
    weekly_loss_limit: float = .02
    max_exposure_fraction: float = .15
    max_positions: int = 2
    fee_bps: float = 10.
    slippage_bps: float = 10.
    evaluation_interval: float = 60.
    stale_seconds: float = 90.
    pair_stop_fraction: float = .02
    leg_failure_stress_fraction: float = .02
    virtual_margin_stress_fraction: float = .8
    funding_max_hold_seconds: float = 86400.
    statarb_max_hold_seconds: float = 21600.

    def __post_init__(self):
        if self.mode != "SHADOW":
            raise ValueError("Quant execution is locked to SHADOW")
        if type(self.enabled) is not bool or type(self.max_positions) is not int:
            raise ValueError("Invalid Quant settings")
        numbers = [value for key, value in asdict(self).items() if key not in {"enabled", "mode", "max_positions"}]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in numbers):
            raise ValueError("Quant settings require finite numbers")
        if not (0 < self.initial_capital <= 1_000_000 and 0 < self.risk_per_trade <= .0025
                and 0 < self.daily_loss_limit <= .01 and 0 < self.weekly_loss_limit <= .02
                and 0 < self.max_exposure_fraction <= .15 and 1 <= self.max_positions <= 2
                and 10 <= self.fee_bps <= 100 and 10 <= self.slippage_bps <= 100
                and self.evaluation_interval == 60 and self.stale_seconds == 90
                and self.pair_stop_fraction == .02 and self.leg_failure_stress_fraction == .02
                and 0 < self.virtual_margin_stress_fraction <= .8
                and self.funding_max_hold_seconds == 86400 and self.statarb_max_hold_seconds == 21600):
            raise ValueError("Quant conservative research limits exceeded")


def _json(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True, allow_nan=False)


def _number(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or positive and value <= 0:
        raise ValueError("Invalid Quant number")
    return float(value)


def _iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value is not None else None


def _time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError, TypeError):
        return None


def _id(*values):
    return hashlib.sha256(_json(values).encode()).hexdigest()[:32]


@contextmanager
def _connect(path, readonly=False):
    if readonly:
        db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True, timeout=1)
        db.execute("PRAGMA query_only=ON")
    else:
        db = sqlite3.connect(path, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def _get(db, key, default=""):
    row = db.execute("SELECT value FROM quant_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def _set(db, key, value):
    db.execute("INSERT INTO quant_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def _journal(db, now, kind, data, identity=None):
    db.execute("INSERT OR IGNORE INTO quant_journal(id,at,kind,data) VALUES(?,?,?,?)",
               (identity or uuid.uuid4().hex, now, kind, _json(data)))


def _positions(db):
    return [json.loads(row[0]) for row in db.execute("SELECT data FROM quant_positions ORDER BY opened,id")]


def _mid(book):
    return (_number(book["bid"], positive=True)+_number(book["ask"], positive=True))/2


def _fresh_book(book, now, maximum=90):
    try:
        return (isinstance(book, dict) and book.get("symbol") in SYMBOLS
                and -5 <= now-_number(book["at"], positive=True) <= maximum
                and 0 <= now-_number(book["received_at"], positive=True) <= maximum
                and book["at"] <= book["received_at"]+5
                and 1e-12 <= _number(book["bid"], positive=True) < _number(book["ask"], positive=True) <= 1e12)
    except (KeyError, ValueError, TypeError):
        return False


def _book(markets, leg):
    row = markets.get(leg["symbol"], {})
    return row.get("spot" if leg["venue"] == "SPOT_REFERENCE" else "futures")


def _projection(position, markets, now, config):
    result = dict(position)
    legs, complete, unrealized, gross, signed = [], True, 0., 0., 0.
    close_cost = 0.
    for original in position["legs"]:
        leg = dict(original)
        quote = _book(markets, leg)
        current = _fresh_book(quote, now, config.stale_seconds)
        if current:
            mark = _mid(quote)
            side = 1 if leg["direction"] == "LONG" else -1
            exit_reference = quote["bid"] if side == 1 else quote["ask"]
            exit_fill = exit_reference*(1-side*config.slippage_bps/10000)
            value = leg["quantity"]*mark
            pnl = side*leg["quantity"]*(exit_fill-leg["entry_price"])
            fee = leg["quantity"]*exit_fill*config.fee_bps/10000
            unrealized += pnl-fee
            close_cost += fee + leg["quantity"]*abs(exit_fill-exit_reference)
            gross += value
            signed += side*value
            leg.update(mark_price=mark, notional_usdt=value, unrealized_pnl_usdt=pnl-fee,
                       priced_at=_iso(quote["at"]), received_at=_iso(quote["received_at"]), state="FRESH")
        else:
            complete = False
            leg.update(mark_price=None, notional_usdt=None, unrealized_pnl_usdt=None,
                       priced_at=None, received_at=None, state="STALE")
        legs.append(leg)
    result.update(legs=legs, state="FRESH" if complete else "UNPRICED", mark_complete=complete,
                  gross_exposure_usdt=gross if complete else None, net_exposure_usdt=signed if complete else None,
                  unrealized_pnl_usdt=unrealized if complete else None,
                  net_pnl_usdt=unrealized-position["entry_fees_usdt"]+position["funding_usdt"] if complete else None,
                  estimated_exit_cost_usdt=close_cost if complete else None,
                  opened_at=_iso(position["opened"]))
    return result


def _pending_funding(db, position, now):
    """Scheduled payments stay unknown until authoritative simulation receipts.

    This conservative entry schedule is not silently re-written after an interval
    change. A discontinuity therefore makes the cohort incomplete, never a zero
    funding assumption. Long outages beyond the bounded provider page remain
    explicitly incomplete and need historical research rather than invented cash.
    """
    if position["strategy"] != "FUNDING_CARRY":
        return False
    anchor, interval = position.get("funding_anchor"), position.get("funding_interval_seconds")
    if type(anchor) not in (int,float) or type(interval) not in (int,float) or interval <= 0:
        return True
    end = min(now, position.get("closed", now))
    due = anchor
    for _ in range(25):
        if due > end:
            return False
        if not db.execute("SELECT 1 FROM quant_funding WHERE position_id=? AND ABS(at-?)<=1", (position["id"], due)).fetchone():
            return True
        due += interval
    return due <= end


def _unknown_risk(config, now):
    instant = datetime.fromtimestamp(now,UTC)
    day = instant.replace(hour=0,minute=0,second=0,microsecond=0)
    week = day-timedelta(days=day.weekday())
    result = {"state":"UNKNOWN","at":_iso(now),"method":"FIRST_VALID_LEDGER_EQUITY_WITHIN_UTC_PERIOD"}
    for period,start,duration,limit in (("daily",day,1,config.daily_loss_limit),("weekly",week,7,config.weekly_loss_limit)):
        result[period] = {"period_start":_iso(start.timestamp()),"baseline_at":None,"baseline_equity":None,
                          "return_pct":None,"limit_pct":limit*100,"halted":False,
                          "resets_at":_iso((start+timedelta(days=duration)).timestamp())}
    return result


class QuantShadowService:
    """One daemon thread inside the existing signed, supervised engine process."""
    def __init__(self, data_dir, *, config=None, source=None, clock=time.time,
                 kill_switch_path=None, model_funding=None, model_statarb=None, fill_checker=None):
        self.config, self.clock = config or QuantConfig(), clock
        self.data_dir, self.path = Path(data_dir), Path(data_dir)/DB_NAME
        self.kill_switch_path = Path(kill_switch_path) if kill_switch_path else self.data_dir/"QUANT_ARBITRAGE_KILL"
        self.source = source or QuantPublicFeed(clock=clock)
        self.model_funding, self.model_statarb = model_funding or funding_signal, model_statarb or statarb_signal
        self.fill_checker = fill_checker  # Synthetic fault injection only; production has no exchange fill adapter.
        self._owner = uuid.uuid4().hex
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._initialized = False

    def initialize(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self._lock, _connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quant_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_positions(id TEXT PRIMARY KEY,strategy TEXT NOT NULL,opened REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_trades(id TEXT PRIMARY KEY,strategy TEXT NOT NULL,opened REAL NOT NULL,closed REAL NOT NULL,net_pnl REAL NOT NULL,costs REAL NOT NULL,funding REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_decisions(id TEXT PRIMARY KEY,strategy TEXT NOT NULL,instrument TEXT NOT NULL,at REAL NOT NULL,action TEXT NOT NULL,data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS quant_decisions_at ON quant_decisions(at);
                CREATE TABLE IF NOT EXISTS quant_funding(id TEXT PRIMARY KEY,position_id TEXT NOT NULL,symbol TEXT NOT NULL,at REAL NOT NULL,received REAL NOT NULL,cashflow REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_pending_funding(position_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS quant_source_funding(symbol TEXT NOT NULL,at REAL NOT NULL,received REAL NOT NULL,data TEXT NOT NULL,PRIMARY KEY(symbol,at));
                CREATE TABLE IF NOT EXISTS quant_observations(at INTEGER PRIMARY KEY,received REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_sources(id TEXT PRIMARY KEY,at REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_equity(at INTEGER PRIMARY KEY,equity REAL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quant_journal(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,at REAL NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL);
            """)
            hypotheses = _json({"rule_version": RULE_VERSION, **asdict(self.config)})
            previous = _get(db, "hypotheses")
            if previous and previous != hypotheses:
                raise ValueError("Existing Quant cohort hypotheses cannot silently change or reset")
            if not previous:
                for key, value in {"hypotheses": hypotheses, "started_at": self.clock(),
                    "wallet_balance": self.config.initial_capital, "initial_capital": self.config.initial_capital,
                    "peak_equity": self.config.initial_capital, "drawdown_pct": 0., "fees_usdt": 0.,
                    "slippage_usdt": 0., "stress_costs_usdt": 0., "paused": "", "health": _json({"errors": 0, "last_error": None}),
                    "source": _json({"markets": [], "sources": [], "at": None}), "last_evaluation": ""}.items():
                    _set(db, key, value)
                _journal(db, self.clock(), "COHORT_STARTED", {"hypotheses": json.loads(hypotheses),
                         "environment": "SHADOW", "execution_enabled": False}, "cohort-started")
        self._initialized = True

    def _lease(self, now):
        with self._lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            owner, until = _get(db, "lease_owner"), float(_get(db, "lease_until", "0"))
            if owner and owner != self._owner and until > now:
                return False
            _set(db, "lease_owner", self._owner)
            _set(db, "lease_until", now+120)
            return True

    def _owned(self, db, now):
        return _get(db, "lease_owner") == self._owner and float(_get(db, "lease_until", "0")) > now

    def start(self):
        if not self.config.enabled:
            return False
        key = str(self.path.resolve())
        with _OWNERS_LOCK:
            if self._thread and self._thread.is_alive():
                return True
            if key in _OWNERS and _OWNERS[key] is not self:
                return False
            self.initialize()
            _OWNERS[key] = self
        self._stop.clear()
        if callable(getattr(self.source, "resume", None)):
            self.source.resume()
        self._thread = threading.Thread(target=self._run, name="quant-arbitrage-shadow", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout=3):
        self._stop.set()
        if callable(getattr(self.source, "close", None)):
            self.source.close()
        if self._thread and self._thread.ident is not None and self._thread is not threading.current_thread():
            self._thread.join(max(0, min(3, timeout)))
        if not self._thread or not self._thread.is_alive():
            with _OWNERS_LOCK:
                if _OWNERS.get(str(self.path.resolve())) is self:
                    _OWNERS.pop(str(self.path.resolve()), None)

    def _error(self, exc):
        try:
            with self._lock, _connect(self.path) as db:
                health = json.loads(_get(db, "health", "{}"))
                health.update(errors=int(health.get("errors", 0))+1, last_error=type(exc).__name__, last_error_at=_iso(self.clock()))
                _set(db, "health", _json(health))
        except Exception:
            pass  # Optional diagnostics cannot propagate into another engine.

    def _run(self):
        next_tick = 0.
        try:
            while not self._stop.is_set():
                try:
                    now = self.clock()
                    if now >= next_tick:
                        self.tick()
                        next_tick = self.clock()+self.config.evaluation_interval
                    elif not self._lease(now):
                        next_tick = now
                except Exception as exc:
                    self._error(exc)
                    next_tick = self.clock()+60
                self._stop.wait(min(5, max(.01, next_tick-self.clock())))
        finally:
            try:
                with _connect(self.path) as db:
                    db.execute("BEGIN IMMEDIATE")
                    if _get(db, "lease_owner") == self._owner:
                        _set(db, "lease_until", 0)
            except Exception:
                pass
            with _OWNERS_LOCK:
                if _OWNERS.get(str(self.path.resolve())) is self:
                    _OWNERS.pop(str(self.path.resolve()), None)

    def _store_source(self, db, source, now):
        markets = {}
        if not isinstance(source, dict) or not isinstance(source.get("markets"), list) or len(source["markets"]) > 3:
            raise ValueError("Invalid bounded Quant source")
        for row in source["markets"]:
            symbol = row.get("symbol") if isinstance(row, dict) else None
            if symbol not in SYMBOLS or symbol in markets:
                raise ValueError("Invalid or duplicate Quant market")
            for venue in ("spot", "futures"):
                book = row.get(venue)
                if book is not None and (not isinstance(book, dict) or book.get("symbol") != symbol):
                    raise ValueError("Mismatched Quant quote")
            history = row.get("history", [])
            if not isinstance(history, list) or len(history) > 32:
                raise ValueError("Unbounded funding history")
            checked_history = {}
            for event in history:
                at, received = _number(event["at"], positive=True), _number(event["received_at"], positive=True)
                rate, mark = _number(event["rate"]), _number(event["mark_price"], positive=True)
                if not at <= received <= now or abs(rate) > .1:
                    raise ValueError("Invalid funding chronology or rate")
                prior = checked_history.get(at)
                saved = db.execute("SELECT data FROM quant_source_funding WHERE symbol=? AND at=?", (symbol,at)).fetchone()
                saved = json.loads(saved[0]) if saved else None
                if (prior is not None and prior != (rate,mark)
                        or saved is not None and (saved["rate"],saved["mark_price"]) != (rate,mark)):
                    raise ValueError("Conflicting authoritative funding event")
                checked_history[at] = (rate,mark)
                db.execute("INSERT OR IGNORE INTO quant_source_funding VALUES(?,?,?,?)", (symbol, at, received, _json(event)))
            markets[symbol] = row
        if len(_json(source).encode()) > 65536:
            raise ValueError("Quant source exceeds bounded evidence budget")
        _set(db, "source", _json(source))
        source_evidence = {"at": now, "markets": [{"symbol": symbol, "spot": row.get("spot"), "futures": row.get("futures"),
                            "history": [{"at": event["at"], "received_at": event["received_at"]} for event in row.get("history", [])]}
                           for symbol, row in markets.items()], "sources": source.get("sources", [])[:12]}
        db.execute("INSERT OR IGNORE INTO quant_sources VALUES(?,?,?)", (_id(source), now, _json(source_evidence)))
        successful_quotes = [min(row["spot"]["at"], row["futures"]["at"]) for row in markets.values()
                             if _fresh_book(row.get("spot"), now) and _fresh_book(row.get("futures"), now)]
        if successful_quotes:
            _set(db, "market_updated_at", max(successful_quotes))
        aligned = {symbol: _mid(row["spot"]) for symbol, row in markets.items() if _fresh_book(row.get("spot"), now)}
        if len(aligned) == 3:
            instants = [row["spot"]["at"] for row in markets.values()]
            if max(instants)-min(instants) <= 30:
                observation = {"at": int(min(instants)//60)*60, "received_at": now, "prices": aligned}
                # First contemporaneous minute sample is immutable; never backfill.
                db.execute("INSERT OR IGNORE INTO quant_observations VALUES(?,?,?)",
                           (observation["at"], now, _json(observation)))
        return markets

    def _settle_funding(self, db, markets, now):
        candidates = _positions(db)
        candidates += [json.loads(row[0]) for row in db.execute("SELECT data FROM quant_trades WHERE closed>=? ORDER BY closed DESC LIMIT 100", (now-7*86400,))]
        for position in candidates:
            for leg in position["legs"]:
                if leg["venue"] != "FUTURES_REFERENCE":
                    continue
                history = markets.get(leg["symbol"], {}).get("history", [])
                for event in history:
                    at = event["at"]
                    if not position["opened"] < at <= min(position.get("closed", now), now) or event["received_at"] > now:
                        continue
                    identity = _id(position["id"], leg["symbol"], at)
                    cashflow = (1 if leg["direction"] == "SHORT" else -1)*leg["quantity"]*event["mark_price"]*event["rate"]
                    data = {"id": identity, "position_id": position["id"], "symbol": leg["symbol"],
                            "funding_at": _iso(at), "received_at": _iso(event["received_at"]),
                            "rate": event["rate"], "mark_price": event["mark_price"],
                            "quantity": leg["quantity"], "simulated_cashflow_usdt": cashflow,
                            "environment": "SHADOW", "state": "SETTLED_SIMULATION"}
                    changed = db.execute("INSERT OR IGNORE INTO quant_funding VALUES(?,?,?,?,?,?,?)", (identity,
                        position["id"], leg["symbol"], at, event["received_at"], cashflow, _json(data))).rowcount
                    if not changed:
                        continue
                    _set(db, "wallet_balance", float(_get(db, "wallet_balance"))+cashflow)
                    position["funding_usdt"] += cashflow
                    _journal(db, now, "FUNDING_SETTLED_SIMULATION", data, "funding-"+identity)
                    if "closed" in position:
                        position["net_pnl_usdt"] += cashflow
                        db.execute("UPDATE quant_trades SET funding=?,net_pnl=?,data=? WHERE id=?",
                            (position["funding_usdt"], position["net_pnl_usdt"], _json(position), position["id"]))
                    else:
                        db.execute("UPDATE quant_positions SET data=? WHERE id=?", (_json(position), position["id"]))
            if "closed" in position and not _pending_funding(db, position, now):
                db.execute("DELETE FROM quant_pending_funding WHERE position_id=?", (position["id"],))

    def _close(self, db, position, markets, now, reason):
        projection = _projection(position, markets, now, self.config)
        if not projection["mark_complete"]:
            _journal(db, now, "EXIT_WAIT_FOR_FRESH_LEGS", {"position_id": position["id"], "reason": reason},
                     _id("exit-wait", position["id"], int(now//60)))
            return False
        realized, fees, slip, stress_cost = 0., 0., 0., 0.
        legs = []
        for original in position["legs"]:
            leg = dict(original)
            book = _book(markets, leg)
            side = 1 if leg["direction"] == "LONG" else -1
            reference = book["bid"] if side == 1 else book["ask"]
            fill = reference*(1-side*self.config.slippage_bps/10000)
            leg_fee = leg["quantity"]*fill*self.config.fee_bps/10000
            pnl = side*leg["quantity"]*(fill-leg["entry_price"])
            realized += pnl
            fees += leg_fee
            slip += leg["quantity"]*abs(fill-reference)
            if reason == "VIRTUAL_MARGIN_STRESS_EXIT" and leg["venue"] == "FUTURES_REFERENCE":
                stress_cost += leg["quantity"]*fill*self.config.leg_failure_stress_fraction
            leg.update(exit_price=fill, exit_reference=reference, exit_at=_iso(now),
                       exit_priced_at=_iso(book["at"]), exit_received_at=_iso(book["received_at"]),
                       exit_fee_usdt=leg_fee, realized_price_pnl_usdt=pnl)
            legs.append(leg)
        net = realized-position["entry_fees_usdt"]-fees-stress_cost+position["funding_usdt"]
        closed = {**position, "legs": legs, "closed": now, "closed_at": _iso(now), "reason": reason,
                  "net_pnl_usdt": net, "exit_fees_usdt": fees, "realized_price_pnl_usdt": realized,
                  "costs_usdt": position["entry_fees_usdt"]+fees+position["entry_slippage_usdt"]+slip+stress_cost,
                  "stress_costs_usdt":stress_cost,"exit_slippage_usdt":slip,
                  "environment": "SHADOW", "hedge_atomic": False}
        db.execute("INSERT INTO quant_trades VALUES(?,?,?,?,?,?,?,?)", (position["id"], position["strategy"],
                   position["opened"], now, net, closed["costs_usdt"], position["funding_usdt"], _json(closed)))
        db.execute("DELETE FROM quant_positions WHERE id=?", (position["id"],))
        if _pending_funding(db, closed, now):
            db.execute("INSERT OR IGNORE INTO quant_pending_funding VALUES(?)", (position["id"],))
        _set(db, "wallet_balance", float(_get(db, "wallet_balance"))+realized-fees-stress_cost)
        _set(db, "fees_usdt", float(_get(db, "fees_usdt"))+fees)
        _set(db, "slippage_usdt", float(_get(db, "slippage_usdt"))+slip)
        _set(db,"stress_costs_usdt",float(_get(db,"stress_costs_usdt","0"))+stress_cost)
        if stress_cost:
            _journal(db,now,"MARGIN_STRESS_COST_SIMULATION",{"position_id":position["id"],
                     "stress_costs_usdt":stress_cost,"kind":"SIMULATED_STRESS_COST",
                     "fraction":self.config.leg_failure_stress_fraction,"reason":reason},"margin-stress-"+position["id"])
        _journal(db, now, "PAIR_CLOSED_SIMULATION", closed, "closed-"+position["id"])
        return True

    def _protect(self, db, markets, now):
        closed_assets = set()
        for position in _positions(db):
            projection = _projection(position, markets, now, self.config)
            reason = None
            margin_stress = False
            for leg in position["legs"]:
                book = _book(markets,leg)
                if leg["venue"] == "FUTURES_REFERENCE" and _fresh_book(book,now):
                    mark = book.get("mark_price")
                    if type(mark) in (int,float) and math.isfinite(mark) and mark > 0:
                        signed = 1 if leg["direction"] == "LONG" else -1
                        leg_loss = max(0,-signed*leg["quantity"]*(mark-leg["entry_price"]))
                        leg_loss += max(0,-position["funding_usdt"])
                        full_collateral = leg["quantity"]*leg["entry_price"]
                        margin_stress |= leg_loss >= full_collateral*self.config.virtual_margin_stress_fraction
            if self.kill_switch_path.exists():
                reason = "KILL_SWITCH_HYPOTHETICAL_EXIT"
            elif margin_stress:
                reason = "VIRTUAL_MARGIN_STRESS_EXIT"
            elif now-position["opened"] >= position["max_hold_seconds"]:
                reason = "MAXIMUM_HOLD"
            elif projection["mark_complete"] and projection["net_pnl_usdt"] <= -position["risk_budget_usdt"]:
                reason = "ESTIMATED_PAIR_STOP"
            elif position["strategy"] == "FUNDING_CARRY":
                future = markets.get(position["instrument"], {}).get("futures")
                if _fresh_book(future, now) and type(future.get("observed_funding_rate")) in (int,float) and future["observed_funding_rate"] <= 0:
                    reason = "ADVERSE_FUNDING_SIGN"
            if reason:
                if self._close(db, position, markets, now, reason):
                    closed_assets.update(leg["symbol"] for leg in position["legs"])
        return closed_assets

    def _wallet(self, db, markets, now):
        positions = [_projection(position, markets, now, self.config) for position in _positions(db)]
        complete = (not db.execute("SELECT 1 FROM quant_pending_funding LIMIT 1").fetchone()
                    and all(position["mark_complete"] and not _pending_funding(db, position, now) for position in positions))
        balance = float(_get(db, "wallet_balance"))
        collateral = sum(position["collateral_usdt"] for position in positions)
        equity = balance+sum(position["unrealized_pnl_usdt"] for position in positions) if complete else None
        gross = sum(position["gross_exposure_usdt"] for position in positions) if complete else None
        return positions, balance, collateral, equity, gross

    def _open(self, db, signal, strategy, instrument, markets, now, risk, gross_budget, decision_id):
        stress = self.config.pair_stop_fraction+self.config.leg_failure_stress_fraction+2*(self.config.fee_bps+self.config.slippage_bps)/10000
        gross_budget = min(gross_budget, risk/stress)
        proposed = signal.get("legs")
        if not isinstance(proposed, list) or len(proposed) != 2:
            return "INVALID_MODEL_LEGS"
        if any(not isinstance(leg, dict) or leg.get("symbol") not in SYMBOLS
               or leg.get("venue") not in {"SPOT_REFERENCE", "FUTURES_REFERENCE"}
               or leg.get("direction") not in {"LONG", "SHORT"} for leg in proposed):
            return "INVALID_MODEL_LEGS"
        if strategy == "FUNDING_CARRY" and [(leg["symbol"], leg["venue"], leg["direction"]) for leg in proposed] != [
                (instrument, "SPOT_REFERENCE", "LONG"), (instrument, "FUTURES_REFERENCE", "SHORT")]:
            return "INVALID_CARRY_HEDGE"
        if strategy == "STATISTICAL_ARBITRAGE":
            # Current exploratory model never opens; future promotion needs a
            # separately reviewed qualification/cohort, not an arbitrary AI reply.
            return "COINTEGRATION_NOT_INDEPENDENTLY_VALIDATED"
        books = [_book(markets, leg) for leg in proposed]
        if any(not _fresh_book(book, now) for book in books):
            return "STALE_OR_MISSING_LEG"
        if abs(books[0]["at"]-books[1]["at"]) > 30:
            return "LEG_TIMESTAMP_MISMATCH"
        # Funding carry uses equal underlying quantity, not equal USDT legs.
        quantity = gross_budget/sum(_mid(book) for book in books)
        legs, fees, slippage, collateral = [], 0., 0., 0.
        for index, (proposal, book) in enumerate(zip(proposed, books)):
            side = 1 if proposal["direction"] == "LONG" else -1
            reference = book["ask"] if side == 1 else book["bid"]
            fill = reference*(1+side*self.config.slippage_bps/10000)
            notional = quantity*fill
            capacity = book.get("ask_depth_usdt" if side == 1 else "bid_depth_usdt")
            if type(capacity) not in (int,float) or not math.isfinite(capacity) or capacity < notional*20:
                return "INSUFFICIENT_LEG_LIQUIDITY"
            if self.fill_checker and not self.fill_checker(proposal, index):
                # Model a first-leg fill and adverse unwind, even though no pair
                # position is committed. This cost belongs to the virtual ledger.
                if legs:
                    failed = legs[0]
                    loss = failed["quantity"]*failed["entry_price"]*(self.config.leg_failure_stress_fraction
                            +2*self.config.slippage_bps/10000+2*self.config.fee_bps/10000)
                    _set(db, "wallet_balance", float(_get(db, "wallet_balance"))-loss)
                    failed_notional = failed["quantity"]*failed["entry_price"]
                    _set(db, "fees_usdt", float(_get(db,"fees_usdt"))+failed_notional*2*self.config.fee_bps/10000)
                    _set(db, "slippage_usdt", float(_get(db,"slippage_usdt"))+failed_notional*2*self.config.slippage_bps/10000)
                    _journal(db, now, "LEG_FAILURE_UNWIND_SIMULATION", {"decision_id": decision_id,
                        "failed_leg": index, "simulated_loss_usdt": loss, "execution_enabled": False}, "leg-failure-"+decision_id)
                return "SIMULATED_LEG_FAILURE"
            fee = notional*self.config.fee_bps/10000
            slip = quantity*abs(fill-reference)
            fees += fee
            slippage += slip
            collateral += notional
            legs.append({"symbol": proposal["symbol"], "venue": proposal["venue"], "direction": proposal["direction"],
                "quantity": quantity, "entry_price": fill, "entry_reference": reference, "entry_fee_usdt": fee,
                "entry_priced_at": _iso(book["at"]), "entry_received_at": _iso(book["received_at"]),
                "leverage": 1, "margin_model": "FULL_NOTIONAL_VIRTUAL_COLLATERAL"})
        balance = float(_get(db, "wallet_balance"))
        reserved = sum(position["collateral_usdt"] for position in _positions(db))
        if collateral+fees > balance-reserved:
            return "INSUFFICIENT_VIRTUAL_COLLATERAL"
        position = {"id": decision_id, "strategy": strategy, "instrument": instrument, "opened": now,
                    "legs": legs, "collateral_usdt": collateral, "entry_fees_usdt": fees,
                    "entry_slippage_usdt": slippage, "funding_usdt": 0., "risk_budget_usdt": risk,
                    "max_hold_seconds": self.config.funding_max_hold_seconds,
                    "hedge_atomic": False, "environment": "SHADOW", "decision_id": decision_id,
                    "funding_anchor": books[1].get("next_funding_at"),
                    "funding_interval_seconds": books[1].get("funding_interval_seconds")}
        db.execute("INSERT INTO quant_positions VALUES(?,?,?,?)", (decision_id, strategy, now, _json(position)))
        _set(db, "wallet_balance", balance-fees)
        _set(db, "fees_usdt", float(_get(db, "fees_usdt"))+fees)
        _set(db, "slippage_usdt", float(_get(db, "slippage_usdt"))+slippage)
        _journal(db, now, "PAIR_OPENED_SIMULATION", position, "opened-"+decision_id)
        return None

    def _risk_halt(self, db, now, equity):
        instant = datetime.fromtimestamp(now, UTC)
        day = instant.replace(hour=0,minute=0,second=0,microsecond=0)
        week = day-timedelta(days=day.weekday())
        saved = json.loads(_get(db,"risk_baselines","{}"))
        rows = {}
        for period, beginning, duration, limit in (("daily",day,1,self.config.daily_loss_limit),
                                                  ("weekly",week,7,self.config.weekly_loss_limit)):
            key = beginning.isoformat()
            baseline = saved.get(period,{})
            if baseline.get("key") != key:
                baseline = {"key":key,"at":None,"equity":None,"halted":False}
            current = type(equity) in (int,float) and math.isfinite(equity) and equity > 0
            if baseline["equity"] is None and current:
                baseline.update(at=now,equity=equity)
                _journal(db,now,"RISK_BASELINE_OBSERVED",{"period":period,"period_start":_iso(beginning.timestamp()),
                         "baseline_at":_iso(now),"baseline_equity":equity,
                         "method":"FIRST_VALID_LEDGER_EQUITY_WITHIN_UTC_PERIOD"},"baseline-"+period+"-"+key)
            observed_return = (equity/baseline["equity"]-1)*100 if current and baseline["equity"] is not None else None
            if observed_return is not None and observed_return <= -limit*100:
                if not baseline["halted"]:
                    _journal(db,now,"ENTRY_LOSS_HALT",{"period":period,"return_pct":observed_return,"limit_pct":limit*100},
                             "risk-halt-"+period+"-"+key)
                baseline["halted"] = True
            saved[period] = baseline
            rows[period] = {"period_start":_iso(beginning.timestamp()),"baseline_at":_iso(baseline["at"]),
                            "baseline_equity":baseline["equity"],"return_pct":observed_return,"limit_pct":limit*100,
                            "halted":baseline["halted"],"resets_at":_iso((beginning+timedelta(days=duration)).timestamp())}
        state = "HALTED" if any(row["halted"] for row in rows.values()) else "READY" if all(row["return_pct"] is not None for row in rows.values()) else "UNKNOWN"
        result = {"state":state,"at":_iso(now),"method":"FIRST_VALID_LEDGER_EQUITY_WITHIN_UTC_PERIOD",**rows}
        _set(db,"risk_baselines",_json(saved))
        _set(db,"risk_halt",_json(result))
        return result

    def tick(self):
        if not self._initialized:
            self.initialize()
        if not self._lease(self.clock()):
            return False
        source = self.source(self.clock())  # Network runs only on this optional thread.
        now = self.clock()
        with self._lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._owned(db, now) or self._stop.is_set():
                return False
            markets = self._store_source(db, source, now)
            self._settle_funding(db, markets, now)
            closed_assets = self._protect(db, markets, now)  # Always before entry models/pauses.
            positions, balance, collateral, equity, gross = self._wallet(db, markets, now)
            risk_halt = self._risk_halt(db,now,equity)
            hypotheses = {"spot_fee_rate": self.config.fee_bps/10000,
                          "futures_fee_rate": self.config.fee_bps/10000,
                          "slippage_rate": self.config.slippage_bps/10000,
                          "available_virtual_usdt": max(0, balance-collateral),
                          "risk_budget_usdt": equity*self.config.risk_per_trade if equity is not None else 0.}
            stress = self.config.pair_stop_fraction+self.config.leg_failure_stress_fraction+2*(self.config.fee_bps+self.config.slippage_bps)/10000
            gross_budget = min(equity*self.config.max_exposure_fraction/self.config.max_positions,
                              hypotheses["risk_budget_usdt"]/stress) if equity is not None and equity > 0 else 0.
            hypotheses["notional_usdt"] = gross_budget/2
            candidates = []
            for symbol in SYMBOLS:
                row = markets.get(symbol, {})
                try:
                    result = self.model_funding(row.get("spot"), row.get("futures"), row.get("history", []), now, hypotheses)
                except Exception as exc:
                    result = {"decision": "REJECT", "reason": "MODEL_ERROR", "metrics": {}, "evidence": {"error": type(exc).__name__}, "legs": []}
                candidates.append(("FUNDING_CARRY", symbol, result))
            aligned = [json.loads(row[0]) for row in db.execute("SELECT data FROM quant_observations WHERE received<=? ORDER BY at DESC LIMIT 1440", (now,))][::-1]
            for a, b in (("BTCUSDT", "ETHUSDT"), ("BTCUSDT", "SOLUSDT"), ("ETHUSDT", "SOLUSDT")):
                try:
                    result = self.model_statarb(aligned, now, {**hypotheses, "symbol_a": a, "symbol_b": b})
                except Exception as exc:
                    result = {"decision": "REJECT", "reason": "MODEL_ERROR", "metrics": {}, "evidence": {"error": type(exc).__name__}, "legs": []}
                candidates.append(("STATISTICAL_ARBITRAGE", a+"/"+b, result))
            def candidate_priority(candidate):
                metrics = candidate[2].get("metrics", {}) if isinstance(candidate[2], dict) else {}
                edge = metrics.get("conditional_net_estimate_usdt") if isinstance(metrics, dict) else None
                return (-(edge if type(edge) in (int,float) and math.isfinite(edge) else -1e100), candidate[0], candidate[1])
            candidates.sort(key=candidate_priority)
            for strategy, instrument, result in candidates:
                if not self._owned(db, self.clock()) or self._stop.is_set():
                    db.rollback()
                    return False
                if not isinstance(result, dict) or len(_json(result).encode()) > 12000:
                    result = {"decision": "REJECT", "reason": "INVALID_MODEL_RESULT", "metrics": {}, "evidence": {}, "legs": []}
                identity = _id(RULE_VERSION, strategy, instrument, int(now//60))
                if db.execute("SELECT 1 FROM quant_decisions WHERE id=?", (identity,)).fetchone():
                    continue
                action = result.get("decision") if result.get("decision") in {"WAIT", "REJECT", "OPEN_SHADOW"} else "REJECT"
                reason = result.get("reason", "INVALID_MODEL_RESULT")
                if action == "OPEN_SHADOW":
                    positions, balance, collateral, equity, gross = self._wallet(db, markets, now)
                    if _get(db, "paused") or self.kill_switch_path.exists():
                        reason = "INDEPENDENT_PAUSE"
                    elif instrument in closed_assets:
                        reason = "PROTECTIVE_EXIT_COOLDOWN"
                    elif risk_halt["state"] != "READY":
                        reason = "DAILY_OR_WEEKLY_ENTRY_HALT" if risk_halt["state"] == "HALTED" else "RISK_BASELINE_OR_VALUATION_UNKNOWN"
                    elif equity is None or gross is None:
                        reason = "UNPRICED_VIRTUAL_PORTFOLIO"
                    elif len(positions) >= self.config.max_positions:
                        reason = "MAXIMUM_HYPOTHETICAL_POSITIONS"
                    elif any(leg["symbol"] == instrument for position in positions for leg in position["legs"]):
                        reason = "DUPLICATE_ASSET_EXPOSURE"
                    elif gross+gross_budget > equity*self.config.max_exposure_fraction:
                        reason = "GROSS_EXPOSURE_CAP"
                    else:
                        reason = self._open(db, result, strategy, instrument, markets, now,
                                            max(0,equity)*self.config.risk_per_trade, gross_budget, identity)
                    if reason:
                        action = "REJECT"
                    else:
                        action, reason = "OPEN_SHADOW", "ACCEPTED_HYPOTHETICAL_PAIR"
                decision = {"id": identity, "strategy": strategy, "instrument": instrument, "at": _iso(now),
                            "action": action, "reason": str(reason)[:120], "model": result,
                            "model_assumptions": {**hypotheses, **({"symbol_a": instrument.split("/")[0],
                                "symbol_b": instrument.split("/")[1]} if strategy == "STATISTICAL_ARBITRAGE" else {})},
                            "environment": "SHADOW", "rule_version": RULE_VERSION,
                            "available_at_decision": {"observation_cutoff": _iso(now),
                                "aligned_observations": len(aligned), "source_digest": _id(source),
                                "hypotheses_digest": _id(json.loads(_get(db, "hypotheses")))}}
                db.execute("INSERT INTO quant_decisions VALUES(?,?,?,?,?,?)", (identity, strategy, instrument, now, action, _json(decision)))
            positions, balance, collateral, equity, gross = self._wallet(db, markets, now)
            self._risk_halt(db,now,equity)
            if equity is not None:
                peak = max(equity, float(_get(db, "peak_equity")))
                drawdown = max(float(_get(db, "drawdown_pct")), (1-equity/peak)*100 if peak > 0 else 0.)
                _set(db, "peak_equity", peak)
                _set(db, "drawdown_pct", drawdown)
            db.execute("INSERT OR IGNORE INTO quant_equity VALUES(?,?,?)", (int(now//60)*60, equity,
                       _json({"at": _iso(now), "equity": equity, "gross_exposure_usdt": gross, "collateral_usdt": collateral})))
            _set(db, "last_evaluation", now)
            _set(db, "updated_at", now)
            _set(db, "kill_switch_active", "1" if self.kill_switch_path.exists() else "")
            _set(db, "lease_until", now+120)
            health = json.loads(_get(db, "health", "{}"))
            health["last_success_at"] = _iso(now)
            health["last_error"] = None
            _set(db, "health", _json(health))
            if not self._owned(db, self.clock()) or self._stop.is_set():
                db.rollback()
                return False
        return True

    def snapshot(self, *, now=None):
        return quant_snapshot(self.data_dir, now=self.clock() if now is None else now)


def pause_quant(data_dir, paused):
    """Independent authenticated caller may pause entries, never change risk/mode."""
    if type(paused) is not bool:
        raise ValueError("Quant pause must be boolean")
    path = Path(data_dir)/DB_NAME
    if not path.is_file():
        return False
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        _set(db, "paused", "owner pause" if paused else "")
        _journal(db, time.time(), "PAUSE_CHANGED", {"paused": paused, "protective_simulation_continues": True})
    return True


def replay_quant_decision(data_dir, decision_id):
    """Re-run a recorded numerical model using evidence received at that instant.

    Replays the model, not portfolio overrides or fills. Source history and minute
    observations are immutable; no current API, later funding/news or later quote
    is consulted. This is an audit replay, not independent strategy validation.
    """
    if not isinstance(decision_id, str) or not re.fullmatch(r"[a-f0-9]{32}", decision_id):
        raise ValueError("Invalid Quant decision identity")
    with _connect(Path(data_dir)/DB_NAME, readonly=True) as db:
        stored = db.execute("SELECT at,data FROM quant_decisions WHERE id=?", (decision_id,)).fetchone()
        if stored is None:
            raise ValueError("Quant decision not found")
        decision, now = json.loads(stored["data"]), stored["at"]
        digest = decision["available_at_decision"]["source_digest"]
        frozen = db.execute("SELECT data FROM quant_sources WHERE id=?", (digest,)).fetchone()
        if frozen is None:
            raise ValueError("Contemporaneous Quant source evidence unavailable")
        source = json.loads(frozen[0])
        if source["at"] > now:
            raise ValueError("Quant source received after decision")
        hypotheses = decision.get("model_assumptions")
        if hypotheses is None:
            raise ValueError("Frozen model assumptions unavailable")
        if decision["strategy"] == "FUNDING_CARRY":
            market = next((row for row in source["markets"] if row["symbol"] == decision["instrument"]), {})
            history = []
            for event in market.get("history", []):
                row = db.execute("SELECT data FROM quant_source_funding WHERE symbol=? AND at=?",
                                 (decision["instrument"], event["at"])).fetchone()
                if row is None:
                    raise ValueError("Frozen funding evidence unavailable")
                historical = json.loads(row[0])
                history.append({**historical, "received_at": event["received_at"]})
            replay = funding_signal(market.get("spot"), market.get("futures"), history, now, hypotheses)
        elif decision["strategy"] == "STATISTICAL_ARBITRAGE":
            aligned = [json.loads(row[0]) for row in db.execute("SELECT data FROM quant_observations WHERE received<=? ORDER BY at DESC LIMIT 1440", (now,))][::-1]
            replay = statarb_signal(aligned, now, hypotheses)
        else:
            raise ValueError("Unrecognized recorded Quant model")
        return {"decision_id": decision_id, "mode": "SHADOW", "replayed_at": _iso(now),
                "model_matches": _json(replay) == _json(decision["model"]),
                "recorded_action": decision["action"], "recorded_reason": decision["reason"],
                "replayed_model": replay, "execution_enabled": False,
                "limitation": "MODEL_REPLAY_NOT_PORTFOLIO_FILL_REPLAY_OR_INDEPENDENT_VALIDATION"}


def _not_started(now):
    return {"schema": 1, "engine": "QUANT_ARBITRAGE", "mode": "SHADOW", "state": "NOT_STARTED",
            "initialized": False, "enabled": False, "execution_enabled": False, "controls_available": False,
            "at": _iso(now), "updated_at": None, "freshness": {"state": "UNAVAILABLE", "age_seconds": None},
            "positions": [], "performance": {"initial_capital": None, "equity": None, "net_pnl": None, "closed_trades": None},
            "strategies": [{"id": item, "state": "NOT_STARTED"} for item in STRATEGIES], "promotion_allowed": False}


def quant_snapshot(data_dir, *, now=None):
    """Read-only bounded projection. Missing DB never creates a fictitious wallet."""
    now = time.time() if now is None else _number(now, positive=True)
    result = _not_started(now)
    path = Path(data_dir)/DB_NAME
    if not path.is_file():
        return result
    try:
        with _connect(path, readonly=True) as db:
            config = QuantConfig(**{key: value for key,value in json.loads(_get(db, "hypotheses")).items() if key != "rule_version"})
            source = json.loads(_get(db, "source"))
            markets = {row["symbol"]: row for row in source.get("markets", [])[:3]}
            at = float(_get(db, "market_updated_at")) if _get(db, "market_updated_at") else None
            age = max(0, now-at) if at is not None else None
            fresh = at is not None and 0 <= now-at <= config.stale_seconds
            paused = bool(_get(db, "paused") or _get(db, "kill_switch_active"))
            projections = [_projection(position, markets, now, config) for position in _positions(db)]
            pending = any(_pending_funding(db, position, now) for position in projections)
            closed_pending = bool(db.execute("SELECT 1 FROM quant_pending_funding LIMIT 1").fetchone())
            priced = fresh and not pending and not closed_pending and all(position["mark_complete"] for position in projections)
            balance = float(_get(db, "wallet_balance"))
            collateral = sum(position["collateral_usdt"] for position in projections)
            equity = balance+sum(position["unrealized_pnl_usdt"] for position in projections) if priced else None
            trades = db.execute("SELECT strategy,COUNT(*) count,SUM(net_pnl) net,SUM(CASE WHEN net_pnl>0 THEN 1 ELSE 0 END) wins,SUM(CASE WHEN net_pnl>0 THEN net_pnl ELSE 0 END) profit,SUM(CASE WHEN net_pnl<0 THEN -net_pnl ELSE 0 END) loss,SUM(costs) costs,SUM(funding) funding FROM quant_trades GROUP BY strategy").fetchall()
            totals = {row["strategy"]: dict(row) for row in trades}
            decisions = [json.loads(row[0]) for row in db.execute("SELECT data FROM quant_decisions ORDER BY at DESC,id LIMIT 12")]
            market = []
            for symbol in SYMBOLS:
                row = markets.get(symbol, {})
                spot, future = row.get("spot"), row.get("futures")
                current = fresh and _fresh_book(spot, now) and _fresh_book(future, now)
                market.append({"symbol": symbol, "state": "FRESH" if current else "UNAVAILABLE",
                    "spot_price": _mid(spot) if current else None,
                    "futures_price": _mid(future) if current else None,
                    "basis_bps": (_mid(future)/_mid(spot)-1)*10000 if current else None,
                    "observed_funding_rate": future.get("observed_funding_rate") if current else None,
                    "next_funding_at": _iso(future.get("next_funding_at")) if current else None,
                    "funding_interval_seconds": future.get("funding_interval_seconds") if current else None,
                    "at": _iso(min(spot["at"],future["at"])) if current else None,
                    "received_at": _iso(max(spot["received_at"],future["received_at"])) if current else None})
            count = sum(row["count"] for row in totals.values())
            wins = sum(row["wins"] for row in totals.values())
            profit = sum(row["profit"] or 0 for row in totals.values())
            loss = sum(row["loss"] or 0 for row in totals.values())
            initial = float(_get(db, "initial_capital"))
            funding = db.execute("SELECT COALESCE(SUM(cashflow),0) FROM quant_funding").fetchone()[0]
            strategies = []
            for identifier in STRATEGIES:
                t = totals.get(identifier, {})
                strategy_decisions = [decision for decision in decisions if decision["strategy"] == identifier][:6]
                strategies.append({"id": identifier, "state": "OBSERVING" if fresh else "UNAVAILABLE",
                    "signals": [{"instrument": decision["instrument"], "action": decision["action"], "reason": decision["reason"],
                                "at": decision["at"], "metrics": decision["model"].get("metrics", {}),
                                "qualification": decision["model"].get("evidence", {}).get("qualification")} for decision in strategy_decisions],
                    "performance": {"closed_trades": t.get("count",0), "net_pnl_usdt": t.get("net",0.),
                                    "simulated_funding_usdt": t.get("funding",0.), "costs_usdt": t.get("costs",0.)}})
            benchmark = db.execute("SELECT data FROM quant_observations ORDER BY at LIMIT 1").fetchone()
            starting = json.loads(benchmark[0]) if benchmark else None
            benchmarks = []
            for row in market:
                base = starting["prices"].get(row["symbol"]) if starting else None
                benchmarks.append({"symbol": row["symbol"], "started_at": _iso(starting["at"]) if starting else None,
                    "buy_hold_return_pct": (row["spot_price"]/base-1)*100 if row["spot_price"] and base else None,
                    "cash_return_pct": 0. if starting and fresh else None,
                    "method": "CONTEMPORANEOUS_SPOT_MID_GROSS_NO_COSTS_NOT_STRATEGY_NET_COMPARABLE"})
            all_current = fresh and all(row["state"] == "FRESH" for row in market)
            result.update(initialized=True, enabled=config.enabled, state="PAUSED" if paused else "SHADOW" if all_current else "DEGRADED",
                controls_available=True, updated_at=_iso(at), last_evaluation=_iso(float(_get(db,"last_evaluation"))) if _get(db,"last_evaluation") else None,
                freshness={"state": "FRESH" if fresh else "STALE" if at else "UNAVAILABLE", "age_seconds": age},
                positions=projections, market=market, strategies=strategies,
                decisions=[{**{key:value for key,value in row.items() if key not in {"model", "model_assumptions"}},
                            "metrics": row["model"].get("metrics", {}),
                            "qualification": row["model"].get("evidence", {}).get("qualification")} for row in decisions],
                funding=[json.loads(row[0]) for row in db.execute("SELECT data FROM quant_funding ORDER BY at DESC LIMIT 10")],
                performance={"initial_capital": initial, "equity": equity, "cash": balance-collateral if fresh else None,
                    "collateral_usdt": collateral if fresh else None,
                    "gross_exposure_usdt": sum(p["gross_exposure_usdt"] for p in projections) if priced else None,
                    "net_pnl": equity-initial if equity is not None else None,
                    "return_pct": (equity/initial-1)*100 if equity is not None else None,
                    "drawdown_pct": float(_get(db,"drawdown_pct")), "closed_trades": count, "wins": wins if not closed_pending else None,
                    "win_rate": wins/count*100 if count and not closed_pending else None, "profit_factor": profit/loss if loss and not closed_pending else None,
                    "costs_usdt": float(_get(db,"fees_usdt"))+float(_get(db,"slippage_usdt"))+float(_get(db,"stress_costs_usdt","0")),
                    "stress_costs_usdt":float(_get(db,"stress_costs_usdt","0")),
                    "simulated_funding_usdt": funding, "observation_days": max(0,now-float(_get(db,"started_at")))/86400},
                limits={"gross_usdt": equity*config.max_exposure_fraction if equity is not None else None,
                        "risk_per_trade_fraction": config.risk_per_trade, "max_positions": config.max_positions,
                        "stale_seconds": config.stale_seconds, "evaluation_interval_seconds": config.evaluation_interval},
                sources=source.get("sources",[])[:12], health={**json.loads(_get(db,"health","{}")), **source.get("health",{})},
                data_quality={"market": "COMPLETE" if all_current else "PARTIAL",
                              "funding": "PENDING_AUTHORITATIVE_EVENTS" if pending or closed_pending else "COMPLETE_OBSERVED_SCHEDULE",
                              "execution": "SIMULATED_NON_ATOMIC", "statistical_qualification": "EXPLORATORY_SCREEN_ONLY"},
                benchmarks=benchmarks, limitations=list(LIMITATIONS), paused=paused)
            result["risk_halt"] = json.loads(_get(db,"risk_halt")) if _get(db,"risk_halt") else _unknown_risk(config,now)
            journal = []
            for row in db.execute("SELECT id,at,kind,data FROM quant_journal ORDER BY sequence DESC LIMIT 12"):
                payload = json.loads(row["data"])
                journal.append({"id": row["id"], "at": _iso(row["at"]), "kind": row["kind"],
                                "position_id": payload.get("position_id", payload.get("id")) if row["kind"] != "COHORT_STARTED" else None,
                                "decision_id": payload.get("decision_id"), "reason": payload.get("reason"),
                                "simulated_loss_usdt": payload.get("simulated_loss_usdt"),
                                "stress_costs_usdt":payload.get("stress_costs_usdt"),
                                "fees_usdt":payload.get("entry_fees_usdt",0)+payload.get("exit_fees_usdt",0) if "entry_fees_usdt" in payload else None,
                                "slippage_usdt":payload.get("entry_slippage_usdt",0)+payload.get("exit_slippage_usdt",0) if "entry_slippage_usdt" in payload else None})
            result["journal"] = journal
            # Retain every live leg and financial total; thin historical detail only.
            while len(_json(result).encode()) > 20000 and result["decisions"]:
                result["decisions"].pop()
            while len(_json(result).encode()) > 20000 and result["journal"]:
                result["journal"].pop()
            while len(_json(result).encode()) > 20000 and result["funding"]:
                result["funding"].pop()
            for strategy in result["strategies"]:
                while len(_json(result).encode()) > 20000 and strategy["signals"]:
                    strategy["signals"].pop()
            if len(_json(result).encode()) > 20000:
                raise ValueError("Quant projection exceeds bounded envelope")
            return result
    except Exception as exc:
        result.update(state="DEGRADED", health={"last_error": "SHADOW_LEDGER_UNAVAILABLE", "error_type": type(exc).__name__})
        return result
