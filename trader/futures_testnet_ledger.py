"""Separate durable ledger for supervised USDⓈ-M Futures Testnet experiments."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class FuturesTestnetLedger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS smoke_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,direction TEXT NOT NULL,
                leverage INTEGER NOT NULL,margin_type TEXT NOT NULL,quantity REAL,entry_price REAL,
                exit_price REAL,liquidation_price REAL,funding_rate REAL,status TEXT NOT NULL,
                created_at TEXT NOT NULL,completed_at TEXT);
            CREATE TABLE IF NOT EXISTS forward_trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,direction TEXT NOT NULL,
                leverage INTEGER NOT NULL,quantity REAL NOT NULL,entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,gross_pnl REAL NOT NULL,exit_reason TEXT NOT NULL,
                opened_at TEXT NOT NULL,closed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS forward_equity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,wallet_balance REAL NOT NULL,
                available_balance REAL NOT NULL,unrealized_pnl REAL NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS forward_signals(
                id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,direction TEXT,
                score INTEGER NOT NULL,long_score INTEGER NOT NULL,short_score INTEGER NOT NULL,
                price REAL NOT NULL,atr REAL NOT NULL,rsi REAL NOT NULL,ema_fast REAL NOT NULL,
                ema_slow REAL NOT NULL,volume_ratio REAL NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shadow_positions(
                strategy_key TEXT NOT NULL,symbol TEXT NOT NULL,direction TEXT NOT NULL,
                entry_price REAL NOT NULL,stop_price REAL NOT NULL,take_profit REAL NOT NULL,
                score INTEGER NOT NULL,opened_at TEXT NOT NULL,PRIMARY KEY(strategy_key,symbol));
            CREATE TABLE IF NOT EXISTS shadow_trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,strategy_key TEXT NOT NULL,symbol TEXT NOT NULL,
                direction TEXT NOT NULL,entry_price REAL NOT NULL,exit_price REAL NOT NULL,
                pnl_pct REAL NOT NULL,exit_reason TEXT NOT NULL,opened_at TEXT NOT NULL,closed_at TEXT NOT NULL);
            """)
            cols = [row["name"] for row in db.execute("PRAGMA table_info(forward_position)")]
            if cols and "singleton" in cols:
                db.execute("ALTER TABLE forward_position RENAME TO forward_position_legacy")
                db.execute("""CREATE TABLE forward_position(
                    symbol TEXT PRIMARY KEY,direction TEXT NOT NULL,leverage INTEGER NOT NULL,
                    quantity REAL NOT NULL,entry_price REAL NOT NULL,stop_price REAL NOT NULL,
                    take_profit REAL NOT NULL,liquidation_price REAL,signal_score INTEGER NOT NULL,
                    opened_at TEXT NOT NULL)""")
                db.execute("""INSERT OR REPLACE INTO forward_position(
                    symbol,direction,leverage,quantity,entry_price,stop_price,take_profit,
                    liquidation_price,signal_score,opened_at)
                    SELECT symbol,direction,leverage,quantity,entry_price,stop_price,take_profit,
                    liquidation_price,signal_score,opened_at FROM forward_position_legacy""")
                db.execute("DROP TABLE forward_position_legacy")
            elif not cols:
                db.execute("""CREATE TABLE forward_position(
                    symbol TEXT PRIMARY KEY,direction TEXT NOT NULL,leverage INTEGER NOT NULL,
                    quantity REAL NOT NULL,entry_price REAL NOT NULL,stop_price REAL NOT NULL,
                    take_profit REAL NOT NULL,liquidation_price REAL,signal_score INTEGER NOT NULL,
                    opened_at TEXT NOT NULL)""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key: str):
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_setting(self, key: str, value) -> None:
        with self._connect() as db:
            if value is None:
                db.execute("DELETE FROM settings WHERE key=?", (key,))
            else:
                db.execute("""INSERT INTO settings(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    (key, json.dumps(value, separators=(",", ":"))))

    def start(self, symbol, direction, leverage, margin_type):
        with self._connect() as db:
            row = db.execute("""INSERT INTO smoke_runs(symbol,direction,leverage,margin_type,status,created_at)
                VALUES(?,?,?,?,?,?)""",(symbol,direction,leverage,margin_type,"RUNNING",datetime.now(UTC).isoformat()))
            return int(row.lastrowid)

    def finish(self, run_id, *, quantity, entry_price, exit_price, liquidation_price, funding_rate, status="COMPLETED"):
        with self._connect() as db:
            db.execute("""UPDATE smoke_runs SET quantity=?,entry_price=?,exit_price=?,liquidation_price=?,
                funding_rate=?,status=?,completed_at=? WHERE id=?""",
                (quantity,entry_price,exit_price,liquidation_price,funding_rate,status,datetime.now(UTC).isoformat(),run_id))

    def set_status(self, run_id, status):
        with self._connect() as db:
            db.execute("UPDATE smoke_runs SET status=?,completed_at=? WHERE id=?",
                       (status,datetime.now(UTC).isoformat(),run_id))

    def fail(self, run_id): self.set_status(run_id,"FAILED")

    def latest(self):
        with self._connect() as db:
            row=db.execute("SELECT * FROM smoke_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def forward_positions(self) -> list[dict]:
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM forward_position ORDER BY symbol")]

    def forward_position(self, symbol: str | None = None):
        with self._connect() as db:
            if symbol:
                row=db.execute("SELECT * FROM forward_position WHERE symbol=?",(symbol,)).fetchone()
            else:
                row=db.execute("SELECT * FROM forward_position ORDER BY symbol LIMIT 1").fetchone()
        return dict(row) if row else None

    def set_forward_position(self, position: dict | None, symbol: str | None = None) -> None:
        target = symbol or (position or {}).get("symbol")
        if not target:
            raise ValueError("Futures forward symbol required")
        with self._connect() as db:
            if position is None:
                db.execute("DELETE FROM forward_position WHERE symbol=?",(target,))
            else:
                db.execute("""INSERT INTO forward_position(
                    symbol,direction,leverage,quantity,entry_price,stop_price,take_profit,
                    liquidation_price,signal_score,opened_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET direction=excluded.direction,leverage=excluded.leverage,
                    quantity=excluded.quantity,entry_price=excluded.entry_price,stop_price=excluded.stop_price,
                    take_profit=excluded.take_profit,liquidation_price=excluded.liquidation_price,
                    signal_score=excluded.signal_score,opened_at=excluded.opened_at""",
                    (position["symbol"],position["direction"],int(position["leverage"]),float(position["quantity"]),
                     float(position["entry_price"]),float(position["stop_price"]),float(position["take_profit"]),
                     position.get("liquidation_price"),int(position["signal_score"]),position["opened_at"]))

    def close_forward_position(self, *, symbol: str | None = None, exit_price: float, gross_pnl: float, exit_reason: str) -> dict:
        position=self.forward_position(symbol)
        if not position: raise ValueError("No Futures forward position")
        closed_at=datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("""INSERT INTO forward_trades(symbol,direction,leverage,quantity,entry_price,exit_price,
                gross_pnl,exit_reason,opened_at,closed_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (position["symbol"],position["direction"],int(position["leverage"]),float(position["quantity"]),
                 float(position["entry_price"]),float(exit_price),float(gross_pnl),str(exit_reason)[:180],
                 position["opened_at"],closed_at))
            db.execute("DELETE FROM forward_position WHERE symbol=?",(position["symbol"],))
        return {**position,"exit_price":float(exit_price),"gross_pnl":float(gross_pnl),
                "exit_reason":str(exit_reason)[:180],"closed_at":closed_at}

    def record_forward_equity(self,wallet_balance,available_balance,unrealized_pnl):
        with self._connect() as db:
            db.execute("INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)",
                       (float(wallet_balance),float(available_balance),float(unrealized_pnl),datetime.now(UTC).isoformat()))
            db.execute("DELETE FROM forward_equity WHERE id NOT IN (SELECT id FROM forward_equity ORDER BY id DESC LIMIT 1000)")

    def record_signal(self,symbol:str,signal:dict):
        with self._connect() as db:
            db.execute("""INSERT INTO forward_signals(symbol,direction,score,long_score,short_score,price,atr,rsi,
                ema_fast,ema_slow,volume_ratio,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (symbol,signal.get("direction"),int(signal["score"]),int(signal["long_score"]),int(signal["short_score"]),
                 float(signal["price"]),float(signal["atr"]),float(signal["rsi"]),float(signal["ema_fast"]),
                 float(signal["ema_slow"]),float(signal["volume_ratio"]),datetime.now(UTC).isoformat()))
            db.execute("DELETE FROM forward_signals WHERE id NOT IN (SELECT id FROM forward_signals ORDER BY id DESC LIMIT 5000)")

    def shadow_step(self,symbol:str,signal:dict,variants:list[dict]):
        now=datetime.now(UTC).isoformat(); price=float(signal["price"])
        with self._connect() as db:
            for v in variants:
                key=v["key"]
                row=db.execute("SELECT * FROM shadow_positions WHERE strategy_key=? AND symbol=?",(key,symbol)).fetchone()
                if row:
                    r=dict(row); reason=None
                    if r["direction"]=="LONG":
                        if price <= r["stop_price"]: reason="STOP"
                        elif price >= r["take_profit"]: reason="TAKE_PROFIT"
                        elif signal["short_score"] >= v["score"]: reason="OPPOSITE_SIGNAL"
                        pnl=(price/r["entry_price"]-1.0)*100.0
                    else:
                        if price >= r["stop_price"]: reason="STOP"
                        elif price <= r["take_profit"]: reason="TAKE_PROFIT"
                        elif signal["long_score"] >= v["score"]: reason="OPPOSITE_SIGNAL"
                        pnl=(r["entry_price"]/price-1.0)*100.0
                    if reason:
                        db.execute("""INSERT INTO shadow_trades(strategy_key,symbol,direction,entry_price,exit_price,pnl_pct,
                            exit_reason,opened_at,closed_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                            (key,symbol,r["direction"],r["entry_price"],price,pnl,reason,r["opened_at"],now))
                        db.execute("DELETE FROM shadow_positions WHERE strategy_key=? AND symbol=?",(key,symbol))
                    continue
                if signal.get("direction") is None or int(signal["score"]) < int(v["score"]): continue
                distance=max(float(v["atr_mult"])*float(signal["atr"]),0.025*price)
                direction=signal["direction"]
                stop=price-distance if direction=="LONG" else price+distance
                take=price+float(v["rr"])*distance if direction=="LONG" else price-float(v["rr"])*distance
                db.execute("""INSERT OR IGNORE INTO shadow_positions(strategy_key,symbol,direction,entry_price,stop_price,
                    take_profit,score,opened_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (key,symbol,direction,price,stop,take,int(signal["score"]),now))

    def shadow_scorecard(self):
        with self._connect() as db:
            rows=[dict(r) for r in db.execute("""SELECT strategy_key,COUNT(*) trades,
                SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END) wins,COALESCE(SUM(pnl_pct),0) pnl_pct
                FROM shadow_trades GROUP BY strategy_key ORDER BY pnl_pct DESC""")]
        for r in rows:
            r["win_rate_pct"]=100.0*r["wins"]/r["trades"] if r["trades"] else None
            r["leverage_simulated_return_pct"]={str(x):float(r["pnl_pct"])*x for x in (1,2,3)}
        return rows

    def forward_scorecard(self) -> dict:
        with self._connect() as db:
            trades=[dict(r) for r in db.execute("SELECT symbol,direction,gross_pnl,opened_at,closed_at FROM forward_trades ORDER BY id")]
            equity=[dict(r) for r in db.execute("SELECT wallet_balance,available_balance,unrealized_pnl,created_at FROM forward_equity ORDER BY id")]
        values=[float(r["wallet_balance"])+float(r["unrealized_pnl"]) for r in equity]
        peak=0.0; max_dd=0.0
        for value in values:
            peak=max(peak,value)
            if peak>0: max_dd=max(max_dd,(peak-value)/peak*100.0)
        observed=0.0
        if len(equity)>=2:
            first=datetime.fromisoformat(equity[0]["created_at"].replace("Z","+00:00"))
            last=datetime.fromisoformat(equity[-1]["created_at"].replace("Z","+00:00"))
            observed=max(0.0,(last-first).total_seconds()/86400.0)
        pnl=[float(r["gross_pnl"]) for r in trades]; winners=[x for x in pnl if x>0]; losers=[x for x in pnl if x<0]
        by_symbol={}
        for symbol in sorted({r["symbol"] for r in trades}):
            sr=[r for r in trades if r["symbol"]==symbol]
            by_symbol[symbol]={}
            for direction in ("LONG","SHORT"):
                dr=[r for r in sr if r["direction"]==direction]
                by_symbol[symbol][direction]={"trades":len(dr),"gross_pnl_usdt":sum(float(r["gross_pnl"]) for r in dr),
                    "win_rate_pct":100.0*sum(float(r["gross_pnl"])>0 for r in dr)/len(dr) if dr else None}
        return {"status":"REVIEW_REQUIRED" if observed>=30 and len(trades)>=30 else "INSUFFICIENT_EVIDENCE",
            "observed_days":observed,"equity_points":len(equity),"closed_trades":len(trades),
            "gross_realized_pnl_usdt":sum(pnl),"win_rate_pct":100.0*len(winners)/len(trades) if trades else None,
            "profit_factor":sum(winners)/abs(sum(losers)) if losers else (999.0 if winners else None),
            "sampled_max_drawdown_pct":max_dd,
            "account_return_pct":((values[-1]/values[0]-1)*100.0) if len(values)>=2 and values[0]>0 else None,
            "long_closed_trades":sum(r["direction"]=="LONG" for r in trades),
            "long_gross_pnl_usdt":sum(float(r["gross_pnl"]) for r in trades if r["direction"]=="LONG"),
            "short_closed_trades":sum(r["direction"]=="SHORT" for r in trades),
            "short_gross_pnl_usdt":sum(float(r["gross_pnl"]) for r in trades if r["direction"]=="SHORT"),
            "by_symbol_direction":by_symbol,"consecutive_errors":int(self.setting("forward_consecutive_errors") or 0),
            "error_total":int(self.setting("forward_error_total") or 0),
            "incident_total":int(self.setting("forward_incident_sequence") or 0),
            "failure_attempt_total":int(self.setting("forward_failure_attempt_total") or self.setting("forward_error_total") or 0),
            "cycle_total":int(self.setting("forward_cycle_total") or 0),
            "evidence_gap":self.setting("forward_evidence_gap")}

    def observation_health(self,cycle_seconds:int,now:datetime|None=None)->dict:
        now=now or datetime.now(UTC); since_iso=datetime.fromtimestamp(now.timestamp()-86400,UTC).isoformat()
        with self._connect() as db:
            first=db.execute("SELECT created_at FROM forward_equity ORDER BY id LIMIT 1").fetchone()
            recent=[dict(r) for r in db.execute("SELECT created_at FROM forward_equity WHERE created_at>=? ORDER BY id DESC LIMIT 200",(since_iso,))]
            closed=db.execute("SELECT COUNT(*) total,COALESCE(SUM(gross_pnl),0) pnl FROM forward_trades WHERE closed_at>=?",(since_iso,)).fetchone()
            position_count=int(db.execute("SELECT COUNT(*) n FROM forward_position").fetchone()["n"])
        def parse(v):
            try:return datetime.fromisoformat(str(v).replace("Z","+00:00")) if v else None
            except ValueError:return None
        first_at=parse(first["created_at"]) if first else None
        period_start=max(datetime.fromtimestamp(now.timestamp()-86400,UTC),first_at) if first_at else now
        elapsed=max(0.0,(now-period_start).total_seconds()); expected=max(1,int(elapsed/cycle_seconds)+1) if first_at else 0
        times=sorted(v for v in (parse(r["created_at"]) for r in recent) if v); gaps=[(b-a).total_seconds() for a,b in zip(times,times[1:])]
        samples=len(recent); coverage=min(100.0,100.0*samples/expected) if expected else 0.0
        pending=self.setting("forward_pending_order"); consecutive=int(self.setting("forward_consecutive_errors") or 0)
        starting=first_at is None or elapsed<cycle_seconds*2; journal_clear=not bool(pending)
        state="STARTING" if starting else ("OK" if coverage>=90 and consecutive==0 and journal_clear else "WATCH" if coverage>=70 and consecutive<3 and journal_clear else "ATTENTION")
        return {"window_hours":24,"state":state,"samples":samples,"expected_samples":expected,"cycle_coverage_pct":round(coverage,1),
            "average_cycle_gap_seconds":round(sum(gaps)/len(gaps),1) if gaps else None,
            "last_cycle_age_seconds":round(max(0.0,(now-times[-1]).total_seconds()),1) if times else None,
            "closed_trades":int(closed["total"] or 0),"realized_pnl_usdt":round(float(closed["pnl"] or 0.0),8),
            "consecutive_errors":consecutive,
            "errors_total":int(self.setting("forward_error_total") or 0),
            "incident_total":int(self.setting("forward_incident_sequence") or 0),
            "failure_attempt_total":int(self.setting("forward_failure_attempt_total") or self.setting("forward_error_total") or 0),
            "integrity":{"order_journal_clear":journal_clear,"local_position_count_valid":position_count<=3,
                         "evidence_gap_clear":not bool(self.setting("forward_evidence_gap"))}}

    def forward_snapshot(self)->dict:
        with self._connect() as db:
            positions=[dict(r) for r in db.execute("SELECT * FROM forward_position ORDER BY symbol")]
            trades=[dict(r) for r in db.execute("SELECT * FROM forward_trades ORDER BY id DESC LIMIT 50")]
            signals=[dict(r) for r in db.execute("SELECT * FROM forward_signals ORDER BY id DESC LIMIT 60")]
            equity=[dict(r) for r in db.execute("SELECT * FROM forward_equity ORDER BY id DESC LIMIT 120")]
        score=self.forward_scorecard()
        return {"position":positions[0] if len(positions)==1 else None,"positions":positions,"trades":trades,
            "signals":signals,"equity":list(reversed(equity)),"closed_trades":score["closed_trades"],
            "gross_pnl":score["gross_realized_pnl_usdt"],"scorecard":score,"shadow_scorecard":self.shadow_scorecard()}
