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

    def forward_scorecard(self) -> dict:
        with self._connect() as db:
            trades = [dict(row) for row in db.execute(
                "SELECT direction,gross_pnl,opened_at,closed_at FROM forward_trades ORDER BY id"
            )]
            equity = [dict(row) for row in db.execute(
                "SELECT wallet_balance,available_balance,unrealized_pnl,created_at FROM forward_equity ORDER BY id"
            )]
        values = [float(row["wallet_balance"]) + float(row["unrealized_pnl"]) for row in equity]
        peak = 0.0
        max_drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak * 100.0)
        observed_days = 0.0
        if len(equity) >= 2:
            try:
                first = datetime.fromisoformat(str(equity[0]["created_at"]).replace("Z", "+00:00"))
                last = datetime.fromisoformat(str(equity[-1]["created_at"]).replace("Z", "+00:00"))
                observed_days = max(0.0, (last - first).total_seconds() / 86400.0)
            except ValueError:
                observed_days = 0.0
        gross = sum(float(row["gross_pnl"]) for row in trades)
        winners = [float(row["gross_pnl"]) for row in trades if float(row["gross_pnl"]) > 0]
        losers = [float(row["gross_pnl"]) for row in trades if float(row["gross_pnl"]) < 0]
        long_rows = [row for row in trades if row["direction"] == "LONG"]
        short_rows = [row for row in trades if row["direction"] == "SHORT"]
        gains = sum(winners)
        losses = abs(sum(losers))
        return {
            "status": "REVIEW_REQUIRED" if observed_days >= 30 and len(trades) >= 30 else "INSUFFICIENT_EVIDENCE",
            "observed_days": observed_days,
            "equity_points": len(equity),
            "closed_trades": len(trades),
            "gross_realized_pnl_usdt": gross,
            "win_rate_pct": (100.0 * len(winners) / len(trades)) if trades else None,
            "profit_factor": (gains / losses) if losses > 0 else (None if not gains else 999.0),
            "sampled_max_drawdown_pct": max_drawdown,
            "account_return_pct": ((values[-1] / values[0] - 1.0) * 100.0) if len(values) >= 2 and values[0] > 0 else None,
            "long_closed_trades": len(long_rows),
            "long_gross_pnl_usdt": sum(float(row["gross_pnl"]) for row in long_rows),
            "short_closed_trades": len(short_rows),
            "short_gross_pnl_usdt": sum(float(row["gross_pnl"]) for row in short_rows),
            "consecutive_errors": int(self.setting("forward_consecutive_errors") or 0),
            "error_total": int(self.setting("forward_error_total") or 0),
            "cycle_total": int(self.setting("forward_cycle_total") or 0),
        }

    def forward_snapshot(self) -> dict:
        with self._connect() as db:
            position = db.execute("SELECT * FROM forward_position WHERE singleton=1").fetchone()
            trades = [dict(row) for row in db.execute(
                "SELECT * FROM forward_trades ORDER BY id DESC LIMIT 20"
            )]
            equity = [dict(row) for row in db.execute(
                "SELECT * FROM forward_equity ORDER BY id DESC LIMIT 120"
            )]
        scorecard = self.forward_scorecard()
        return {
            "position": dict(position) if position else None,
            "trades": trades,
            "equity": list(reversed(equity)),
            "closed_trades": scorecard["closed_trades"],
            "gross_pnl": scorecard["gross_realized_pnl_usdt"],
            "scorecard": scorecard,
        }

