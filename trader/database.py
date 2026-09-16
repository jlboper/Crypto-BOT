from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .domain import AIReview, Position, Signal


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize read/modify/write accounting and roll back on any failure."""
        if getattr(self._local, "connection", None) is not None:
            raise RuntimeError("nested transaction")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._local.connection = connection
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            finally:
                self._local.connection = None

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    high_water REAL NOT NULL,
                    atr REAL NOT NULL,
                    entry_fee REAL NOT NULL,
                    opened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL,
                    realized_pnl REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    price REAL NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    risk_multiplier REAL NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS equity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    exposure REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS equity_time ON equity(created_at);
                CREATE TABLE IF NOT EXISTS entry_attempts (
                    symbol TEXT NOT NULL, candle_time INTEGER NOT NULL,
                    PRIMARY KEY(symbol, candle_time)
                );
                """
            )

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def initialize_cash(self, amount: float) -> None:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('paper_cash',?)", (f"{amount:.12f}",))

    def claim_entry(self, symbol: str, candle_time: int) -> bool:
        with self.connect() as db:
            return db.execute("INSERT OR IGNORE INTO entry_attempts VALUES(?,?)", (symbol, candle_time)).rowcount == 1

    def prune_diagnostics(self, before: str) -> None:
        """Keep financial history; bound only expendable diagnostics."""
        with self.connect() as db:
            for table in ("signals", "events", "ai_reviews"):
                db.execute(f"DELETE FROM {table} WHERE created_at < ?", (before,))
            db.execute("DELETE FROM entry_attempts WHERE candle_time < ?",
                       (int(datetime.fromisoformat(before).timestamp() * 1000),))

    def cash(self) -> float:
        return float(self.setting("paper_cash", "0") or 0)

    def set_cash(self, amount: float) -> None:
        self.set_setting("paper_cash", f"{amount:.12f}")

    def record_market_snapshot(self, prices: dict[str, float]) -> str:
        created_at = datetime.now(UTC).isoformat()
        payload = json.dumps({symbol: float(price) for symbol, price in prices.items()}, separators=(",", ":"))
        with self.connect() as db:
            db.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (("market_prices", payload), ("market_prices_at", created_at)),
            )
        return created_at

    def market_snapshot(self) -> tuple[dict[str, float], str | None]:
        raw = self.setting("market_prices", "{}") or "{}"
        try:
            decoded = json.loads(raw)
            prices = {str(symbol): float(price) for symbol, price in decoded.items()}
        except (TypeError, ValueError, json.JSONDecodeError):
            prices = {}
        return prices, self.setting("market_prices_at")

    def positions(self) -> list[Position]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM positions ORDER BY opened_at").fetchall()
        return [Position(**dict(row)) for row in rows]

    def position(self, symbol: str) -> Position | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        return Position(**dict(row)) if row else None

    def upsert_position(self, position: Position) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO positions(symbol, quantity, entry_price, stop_price, take_profit, high_water, atr, entry_fee, opened_at)
                VALUES(:symbol, :quantity, :entry_price, :stop_price, :take_profit, :high_water, :atr, :entry_fee, :opened_at)
                ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, stop_price=excluded.stop_price,
                take_profit=excluded.take_profit, high_water=excluded.high_water, atr=excluded.atr""",
                position.to_dict(),
            )

    def delete_position(self, symbol: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))

    def record_trade(self, symbol: str, side: str, quantity: float, price: float, fee: float, pnl: float, reason: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO trades(symbol, side, quantity, price, fee, realized_pnl, reason, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (symbol, side, quantity, price, fee, pnl, reason, datetime.now(UTC).isoformat()),
            )

    def record_signal(self, signal: Signal) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO signals(symbol, action, score, price, payload, created_at) VALUES(?,?,?,?,?,?)",
                (signal.symbol, signal.action, signal.score, signal.price, json.dumps(signal.to_dict()), signal.created_at),
            )

    def record_ai_review(self, symbol: str, review: AIReview) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO ai_reviews(symbol, verdict, confidence, risk_multiplier, reason, created_at) VALUES(?,?,?,?,?,?)",
                (symbol, review.verdict, review.confidence, review.risk_multiplier, review.reason, datetime.now(UTC).isoformat()),
            )

    def record_equity(self, equity: float, cash: float, exposure: float) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO equity(equity, cash, exposure, created_at) VALUES(?,?,?,?)",
                (equity, cash, exposure, datetime.now(UTC).isoformat()),
            )

    def first_equity_since(self, iso_time: str) -> float | None:
        with self.connect() as db:
            row = db.execute("SELECT equity FROM equity WHERE created_at >= ? ORDER BY created_at LIMIT 1", (iso_time,)).fetchone()
        return float(row["equity"]) if row else None

    def equity_at_or_before(self, iso_time: str) -> float | None:
        with self.connect() as db:
            row = db.execute("SELECT equity FROM equity WHERE created_at<=? ORDER BY created_at DESC LIMIT 1", (iso_time,)).fetchone()
        return float(row["equity"]) if row else None

    def event(self, level: str, message: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(level, message, created_at) VALUES(?,?,?)",
                (level, message[:1000], datetime.now(UTC).isoformat()),
            )

    def recent(self, table: str, limit: int = 50) -> list[dict[str, Any]]:
        allowed = {"trades", "signals", "equity", "events", "ai_reviews"}
        if table not in allowed:
            raise ValueError("invalid table")
        with self.connect() as db:
            rows = db.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
