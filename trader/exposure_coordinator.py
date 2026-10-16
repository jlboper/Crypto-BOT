"""Admission preparation for shared simulated accounts; no execution capability.

Current Market Pulse only uses SHADOW:<engine> scopes. The existing Spot broker
is deliberately unchanged. Sharing its Testnet funds stays blocked until BOTH
brokers participate in one reservation/reconciliation protocol in a reviewed release.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from pathlib import Path


class ExposureCoordinator:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS reservations (identity TEXT PRIMARY KEY, scope TEXT NOT NULL, symbol TEXT NOT NULL, engine TEXT NOT NULL, notional REAL NOT NULL, stop_risk REAL NOT NULL, UNIQUE(scope,symbol))")

    @staticmethod
    def scope(environment, account_identity, engine):
        if environment not in {"SHADOW", "PAPER", "SPOT_TESTNET", "FUTURES_DEMO"}:
            raise ValueError("Unsupported capital environment")
        if not account_identity or not engine or any(len(v)>80 for v in (account_identity, engine)):
            raise ValueError("Missing capital identity")
        # Fictional portfolios never share an exchange account or another engine's cash.
        return f"{environment}:{engine if environment == 'SHADOW' else account_identity}"

    def reserve(self, *, identity, scope, symbol, engine, notional, stop_risk,
                available_cash, exposure_limit, stop_risk_limit):
        numbers = (notional, stop_risk, available_cash, exposure_limit, stop_risk_limit)
        if any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in numbers) or notional <= 0:
            raise ValueError("Invalid exposure evidence")
        if not all(isinstance(v, str) and 0 < len(v) <= 160 for v in (identity, scope, symbol, engine)):
            raise ValueError("Missing reservation identity")
        if scope.split(":", 1)[0] not in {"SHADOW", "PAPER", "SPOT_TESTNET", "FUTURES_DEMO"}:
            raise ValueError("Unsupported capital environment")
        with closing(sqlite3.connect(self.path, timeout=1)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT scope,symbol,engine,notional,stop_risk FROM reservations WHERE identity=?", (identity,)).fetchone()
            if prior is not None:
                return {"accepted": prior == (scope, symbol, engine, notional, stop_risk), "reason": "IDEMPOTENT_IDENTITY"}
            if db.execute("SELECT 1 FROM reservations WHERE scope=? AND symbol=?", (scope, symbol)).fetchone():
                return {"accepted": False, "reason": "ASSET_ALREADY_RESERVED"}
            used, risk = db.execute("SELECT COALESCE(SUM(notional),0),COALESCE(SUM(stop_risk),0) FROM reservations WHERE scope=?", (scope,)).fetchone()
            if used+notional > min(available_cash, exposure_limit) or risk+stop_risk > stop_risk_limit:
                return {"accepted": False, "reason": "GLOBAL_CAPITAL_LIMIT"}
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?)", (identity, scope, symbol, engine, notional, stop_risk))
            return {"accepted": True, "reason": "RESERVED"}

    def release_reconciled(self, identity, *, confirmed_flat):
        if confirmed_flat is not True:
            raise ValueError("Fresh confirmed-flat reconciliation required")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM reservations WHERE identity=?", (identity,))


def pulse_execution_admission(environment):
    """This release cannot promote or submit, even with an invented approval flag."""
    if environment != "SHADOW":
        return {"allowed": False, "reason": "OWNER_PROMOTION_AND_SHARED_ACCOUNT_INTEGRATION_REQUIRED"}
    return {"allowed": True, "reason": "HYPOTHETICAL_LEDGER_ONLY"}
