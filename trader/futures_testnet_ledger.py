"""Separate durable ledger for supervised USDⓈ-M Futures Testnet experiments."""
from __future__ import annotations

import json
import sqlite3
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
            """)
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db
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
