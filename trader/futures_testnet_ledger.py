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
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS smoke_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                leverage INTEGER NOT NULL,
                margin_type TEXT NOT NULL,
                quantity REAL,
                entry_price REAL,
                exit_price REAL,
                liquidation_price REAL,
                funding_rate REAL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS forward_position(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                leverage INTEGER NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                take_profit REAL NOT NULL,
                liquidation_price REAL,
                signal_score INTEGER NOT NULL,
                opened_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forward_trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                leverage INTEGER NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                gross_pnl REAL NOT NULL,
                exit_reason TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                closed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forward_equity(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_balance REAL NOT NULL,
                available_balance REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            """)
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
    def setting(self, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None
    def set_setting(self, key: str, value: dict | None):
        with self._connect() as db:
            if value is None:
                db.execute("DELETE FROM settings WHERE key=?", (key,))
            else:
                db.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, separators=(",", ":"))),
                )
            db.commit()
    def start(self, symbol: str, direction: str, leverage: int, margin_type: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "INSERT INTO smoke_runs(symbol,direction,leverage,margin_type,status,created_at) VALUES(?,?,?,?,?,?)",
                (symbol,direction,leverage,margin_type,"RUNNING",datetime.now(UTC).isoformat()),
            )
            db.commit()
            return int(row.lastrowid)
    def finish(self, run_id: int, *, quantity: float, entry_price: float, exit_price: float,
               liquidation_price: float | None, funding_rate: float | None, status: str = "COMPLETED"):
        with self._connect() as db:
            db.execute(
                """UPDATE smoke_runs SET quantity=?,entry_price=?,exit_price=?,liquidation_price=?,
                   funding_rate=?,status=?,completed_at=? WHERE id=?""",
                (quantity,entry_price,exit_price,liquidation_price,funding_rate,status,
                 datetime.now(UTC).isoformat(),run_id),
            )
            db.commit()
    def set_status(self, run_id: int, status: str):
        with self._connect() as db:
            db.execute("UPDATE smoke_runs SET status=?,completed_at=? WHERE id=?",
                       (status, datetime.now(UTC).isoformat(), run_id))
            db.commit()
    def fail(self, run_id: int):
        self.set_status(run_id, "FAILED")
    def latest(self) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM smoke_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def forward_position(self) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM forward_position WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def set_forward_position(self, position: dict | None) -> None:
        with self._connect() as db:
            if position is None:
                db.execute("DELETE FROM forward_position WHERE singleton=1")
            else:
                db.execute(
                    """INSERT INTO forward_position(
                       singleton,symbol,direction,leverage,quantity,entry_price,stop_price,take_profit,
                       liquidation_price,signal_score,opened_at
                    ) VALUES(1,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(singleton) DO UPDATE SET
                       symbol=excluded.symbol,direction=excluded.direction,leverage=excluded.leverage,
                       quantity=excluded.quantity,entry_price=excluded.entry_price,
                       stop_price=excluded.stop_price,take_profit=excluded.take_profit,
                       liquidation_price=excluded.liquidation_price,signal_score=excluded.signal_score,
                       opened_at=excluded.opened_at""",
                    (
                        position["symbol"], position["direction"], int(position["leverage"]),
                        float(position["quantity"]), float(position["entry_price"]),
                        float(position["stop_price"]), float(position["take_profit"]),
                        position.get("liquidation_price"), int(position["signal_score"]),
                        position["opened_at"],
                    ),
                )
            db.commit()

    def close_forward_position(self, *, exit_price: float, gross_pnl: float, exit_reason: str) -> dict:
        position = self.forward_position()
        if not position:
            raise ValueError("No Futures forward position")
        closed_at = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute(
                """INSERT INTO forward_trades(
                   symbol,direction,leverage,quantity,entry_price,exit_price,gross_pnl,exit_reason,opened_at,closed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    position["symbol"], position["direction"], int(position["leverage"]),
                    float(position["quantity"]), float(position["entry_price"]), float(exit_price),
                    float(gross_pnl), str(exit_reason)[:180], position["opened_at"], closed_at,
                ),
            )
            db.execute("DELETE FROM forward_position WHERE singleton=1")
            db.commit()
        return {**position, "exit_price": float(exit_price), "gross_pnl": float(gross_pnl),
                "exit_reason": str(exit_reason)[:180], "closed_at": closed_at}

    def record_forward_equity(self, wallet_balance: float, available_balance: float, unrealized_pnl: float) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)",
                (float(wallet_balance), float(available_balance), float(unrealized_pnl), datetime.now(UTC).isoformat()),
            )
            db.execute(
                """DELETE FROM forward_equity WHERE id NOT IN
                   (SELECT id FROM forward_equity ORDER BY id DESC LIMIT 1000)"""
            )
            db.commit()

    def forward_snapshot(self) -> dict:
        with self._connect() as db:
            position = db.execute("SELECT * FROM forward_position WHERE singleton=1").fetchone()
            trades = [dict(row) for row in db.execute(
                "SELECT * FROM forward_trades ORDER BY id DESC LIMIT 20"
            )]
            equity = [dict(row) for row in db.execute(
                "SELECT * FROM forward_equity ORDER BY id DESC LIMIT 1000"
            )]
            aggregate = db.execute(
                """SELECT COUNT(*) AS closed,
                          COALESCE(SUM(gross_pnl),0) AS pnl,
                          COALESCE(SUM(CASE WHEN gross_pnl>0 THEN 1 ELSE 0 END),0) AS wins,
                          MIN(closed_at) AS first_close
                   FROM forward_trades"""
            ).fetchone()
            first_equity = db.execute(
                "SELECT created_at FROM forward_equity ORDER BY id ASC LIMIT 1"
            ).fetchone()
        chronological = list(reversed(equity))
        peak = None
        max_drawdown = 0.0
        for row in chronological:
            value = float(row["wallet_balance"]) + float(row["unrealized_pnl"])
            peak = value if peak is None else max(peak, value)
            if peak and peak > 0:
                max_drawdown = min(max_drawdown, (value / peak - 1.0) * 100.0)
        closed = int(aggregate["closed"])
        first_at = (first_equity["created_at"] if first_equity else aggregate["first_close"])
        observed_days = 0.0
        if first_at:
            try:
                observed_days = max(0.0, (datetime.now(UTC) - datetime.fromisoformat(first_at)).total_seconds() / 86400.0)
            except (TypeError, ValueError):
                observed_days = 0.0
        return {
            "position": dict(position) if position else None,
            "trades": trades,
            "equity": chronological[-120:],
            "closed_trades": closed,
            "gross_pnl": float(aggregate["pnl"]),
            "winning_trades": int(aggregate["wins"]),
            "win_rate_pct": (100.0 * int(aggregate["wins"]) / closed) if closed else None,
            "max_drawdown_pct": max_drawdown,
            "observed_days": observed_days,
            "first_observed_at": first_at,
            "cycles": int(self.setting("forward_cycles") or 0),
            "consecutive_errors": int(self.setting("forward_consecutive_errors") or 0),
            "last_cycle": self.setting("forward_last_cycle"),
            "latest_signal": self.setting("forward_last_signal"),
            "last_ai_review": self.setting("forward_last_ai_review"),
            "last_error": self.setting("forward_last_error"),
        }

