"""Durable, prospective observation receipts. No financial authority.

The local hash chain detects accidental changes when checked against a retained
anchor. It is not a signed external attestation or exchange certification.
Operational snapshots never manufacture missing cost/cashflow reconciliation.
"""
from __future__ import annotations

import ast
from contextlib import closing
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .migration_evidence import (FINGERPRINT_KEYS, evaluate_forward_cohort,
                                 register_forward_cohort)

SCOPES = {"SPOT": {"SPOT_TESTNET", "PAPER"}, "FUTURES": {"FUTURES_DEMO"},
          "AI_MARKET_PULSE": {"SHADOW"}, "QUANT_ARBITRAGE": {"SHADOW"}}
FLAGS = ("source_complete", "reconciled", "costs_complete", "cashflows_complete", "protections_complete")
MAX_PAYLOAD = 8192
ZERO_HASH = "0" * 64
AUTHORITY = {"execution_enabled": False, "controls_enabled": False,
             "financial_authorization": False, "automatic_activation": False,
             "ready_for_live": False, "reservations_enabled": False}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def iso(at):
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def epoch(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300800:
        raise ValueError("UTC_TIME_REQUIRED")
    return float(value)


def semantic_source_digest(source):
    """Ignore comments, formatting and docstrings; executable AST changes count."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                del body[0]
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode("utf-8")).hexdigest()


def semantic_engine_digest(source):
    """Retain trading/protection logic; omit only named observer bootstrap.

    The exact fail-closed LIVE guard has no effect on Testnet/PAPER decisions.
    We do not omit a weakened/different guard, financial loop, import, risk
    check, constructor assignment or an unknown helper.
    """
    tree = ast.parse(source)
    excluded = {"run_forever", "_create_market_pulse", "_create_guardian_shadow",
                "_create_quant_shadow", "_create_opportunity_observer"}
    expected_guard = ast.parse('if config.bot.mode == "live":\n    raise RuntimeError("LIVE_RUNTIME_ADAPTER_NOT_COMMISSIONED")').body[0]
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "TradingEngine":
            continue
        node.body = [item for item in node.body if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) or item.name not in excluded]
        for method in node.body:
            if isinstance(method, ast.FunctionDef) and method.name == "__init__":
                method.body = [statement for statement in method.body
                    if not isinstance(statement, ast.If) or ast.dump(statement, include_attributes=False) != ast.dump(expected_guard, include_attributes=False)]
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    # `os` was introduced exclusively for an explicit SEC-contact setting in
    # the omitted Pulse bootstrap. All financial/unknown imports are retained.
    tree.body = [node for node in tree.body if not (isinstance(node, ast.Import)
        and len(node.names) == 1 and node.names[0].name == "os" and node.names[0].asname is None and "os" not in used)]
    return semantic_source_digest(ast.unparse(tree))


def fingerprints_for_config(config, engine, *, source_root=None):
    """Trusted config projection, excluding paths, UI, release and credentials.

    Call only with the already-loaded supervisor configuration. This function
    does not load .env, inspect arbitrary settings or open operating databases.
    Source AST fingerprints are conservative: a financial-module code change
    creates a new cohort, while portal/docs/release changes do not.
    """
    if engine not in SCOPES:
        raise ValueError("ENGINE_SCOPE_REQUIRED")
    root = Path(source_root) if source_root is not None else Path(__file__).parent
    modules = {
        "SPOT": ("engine.py", "strategy.py", "indicators.py", "testnet_broker.py", "testnet_transport.py", "testnet.py", "spot_preflight.py", "risk_control.py", "ai_advisor.py", "broker.py", "database.py", "native_protection.py", "domain.py", "exchange.py"),
        "FUTURES": ("engine.py", "futures_forward.py", "futures_strategy.py", "futures_testnet.py", "futures_testnet_transport.py", "futures_testnet_ledger.py", "ai_advisor.py", "risk_control.py", "native_protection.py", "domain.py", "exchange.py"),
        "AI_MARKET_PULSE": ("market_pulse.py", "market_pulse_ai.py", "market_pulse_news.py", "market_pulse_universe.py", "market_pulse_transport.py", "market_pulse_institutional.py"),
        "QUANT_ARBITRAGE": ("quant_shadow.py", "quant_models.py", "quant_public.py"),
    }[engine]
    source = {name: (semantic_engine_digest if name == "engine.py" else semantic_source_digest)(
        (root / name).read_text(encoding="utf-8-sig")) for name in modules}
    source["receipt_contract"] = semantic_source_digest((root / "migration_evidence.py").read_text(encoding="utf-8-sig"))
    def section(name):
        value = getattr(config, name, None)
        if not is_dataclass(value):
            raise ValueError("TRUSTED_CONFIG_REQUIRED")
        return {key: item for key, item in asdict(value).items()
                if not isinstance(item, Path) and key not in {"host", "port"}}
    risk, strategy, ai, costs = section("risk"), section("strategy"), section("ai"), section("paper")
    bot = {key: getattr(config.bot, key) for key in ("mode", "timeframe", "universe_size", "cycle_seconds", "protection_seconds")}
    if engine == "FUTURES":
        strategy = section("futures_testnet")
    elif engine == "AI_MARKET_PULSE":
        strategy = section("market_pulse")
    elif engine == "QUANT_ARBITRAGE":
        strategy = section("quant_arbitrage")
    values = {"source": source, "strategy": strategy, "configuration": {"bot": bot, "risk": risk},
              "ai_review": ai, "execution": {"risk": risk, "policy": "EXISTING_EXECUTION_UNCHANGED_V1"},
              "cost_method": {"settings": costs, "implementation": semantic_source_digest((root / "migration_costs.py").read_text(encoding="utf-8-sig"))}}
    return {key: digest(values[key]) for key in FINGERPRINT_KEYS}


class OperationalCohortStore:
    """Append-only evidence plus immutable registrations in a dedicated SQLite."""

    def __init__(self, path, *, clock=time.time, max_records=200_000, max_bytes=256 * 1024 * 1024):
        self.path, self.clock = Path(path), clock
        if type(max_records) is not int or not 1 <= max_records <= 500_000:
            raise ValueError("RECORD_LIMIT_REQUIRED")
        if type(max_bytes) is not int or not 65536 <= max_bytes <= 512 * 1024 * 1024:
            raise ValueError("BYTE_LIMIT_REQUIRED")
        self.max_records, self.max_bytes = max_records, max_bytes

    def connect(self, readonly=False):
        if readonly:
            db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1)
        else:
            db = sqlite3.connect(self.path, timeout=.1)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        if readonly:
            db.execute("PRAGMA query_only=ON")
        else:
            # This limit belongs to a connection; initialization alone is not
            # a durable size cap for subsequent writer connections.
            pagesize = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute("PRAGMA max_page_count=" + str(max(16, self.max_bytes // pagesize)))
        return db

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS cohorts(digest TEXT PRIMARY KEY,engine TEXT NOT NULL,
                environment TEXT NOT NULL,registered REAL NOT NULL,registration TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS cohort_scope ON cohorts(engine,environment,registered);
              CREATE TABLE IF NOT EXISTS observations(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT UNIQUE NOT NULL,cohort TEXT NOT NULL,at REAL NOT NULL,kind TEXT NOT NULL,
                payload TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS observation_cohort ON observations(cohort,sequence);
              CREATE TABLE IF NOT EXISTS receipts(cohort TEXT NOT NULL,slot INTEGER NOT NULL,
                payload TEXT NOT NULL,operational INTEGER NOT NULL DEFAULT 0,
                financial INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(cohort,slot));
              CREATE TABLE IF NOT EXISTS cohort_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS cohorts_no_update BEFORE UPDATE ON cohorts BEGIN SELECT RAISE(ABORT,'immutable cohort'); END;
              CREATE TRIGGER IF NOT EXISTS cohorts_no_delete BEFORE DELETE ON cohorts BEGIN SELECT RAISE(ABORT,'immutable cohort'); END;
              CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
              CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
              CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
              CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
            """)
            pagesize = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute("PRAGMA max_page_count=" + str(max(16, self.max_bytes // pagesize)))
            columns = {row[1] for row in db.execute("PRAGMA table_info(receipts)")}
            # Additive compatibility for a development journal created before
            # these cached validated bits existed; no historic claim is inferred.
            for name in ("operational", "financial"):
                if name not in columns:
                    db.execute(f"ALTER TABLE receipts ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _scope(engine, environment):
        if engine not in SCOPES or environment not in SCOPES[engine]:
            raise ValueError("OBSERVATION_SCOPE_REQUIRED")

    def register(self, engine, environment, fingerprints, *, cadence_seconds=300, max_receipt_delay_seconds=60, now=None):
        self._scope(engine, environment)
        at = epoch(self.clock() if now is None else now)
        # Validate using the existing pure contract before accessing storage.
        if type(cadence_seconds) is not int or cadence_seconds < 60:
            raise ValueError("CADENCE_REQUIRED")
        starts = math.ceil(at / cadence_seconds) * cadence_seconds
        base = {"schema": 1, "cohort_id": "pending", "engine": engine, "environment": environment,
                "registered_at": iso(at), "starts_at": iso(starts), "cadence_seconds": cadence_seconds,
                "max_receipt_delay_seconds": max_receipt_delay_seconds, "fingerprints": fingerprints}
        register_forward_cohort(base)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM cohorts WHERE engine=? AND environment=? ORDER BY registered DESC,rowid DESC LIMIT 1", (engine, environment)).fetchone()
            if prior:
                old = json.loads(prior["registration"])
                if at < prior["registered"]:
                    raise ValueError("CLOCK_REGRESSION")
                if (old["fingerprints"] == fingerprints and old["cadence_seconds"] == cadence_seconds
                        and old["max_receipt_delay_seconds"] == max_receipt_delay_seconds):
                    return old
            if db.execute("SELECT COUNT(*) FROM cohorts").fetchone()[0] >= 64:
                raise ValueError("COHORT_RETENTION_FULL")
            base["cohort_id"] = engine + ":" + digest(base)[:48]
            cohort = register_forward_cohort(base)
            db.execute("INSERT INTO cohorts VALUES(?,?,?,?,?)", (cohort.digest, engine, environment, at, canonical(base)))
            self._append(db, cohort.digest, at, "REGISTERED", {"registration_digest": cohort.digest}, "register:" + cohort.digest)
        return base

    def _append(self, db, cohort, at, kind, payload, identity):
        encoded = canonical(payload)
        if len(encoded) > MAX_PAYLOAD:
            raise ValueError("BOUNDED_EVIDENCE_REQUIRED")
        existing = db.execute("SELECT * FROM observations WHERE id=?", (identity,)).fetchone()
        if existing:
            same = (existing["cohort"], existing["kind"], existing["payload"]) == (cohort, kind, encoded)
            if not same or kind != "PROPOSAL" and existing["at"] != at:
                raise ValueError("EVIDENCE_ID_CONFLICT")
            return existing["hash"]
        if db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] >= self.max_records:
            raise ValueError("RETENTION_FULL")
        previous = db.execute("SELECT hash,at FROM observations ORDER BY sequence DESC LIMIT 1").fetchone()
        if previous and at < previous["at"]:
            raise ValueError("CLOCK_REGRESSION")
        previous_hash = previous["hash"] if previous else ZERO_HASH
        value = {"id": identity, "cohort": cohort, "at": at, "kind": kind, "payload": payload, "previous": previous_hash}
        value_hash = digest(value)
        db.execute("INSERT INTO observations(id,cohort,at,kind,payload,previous,hash) VALUES(?,?,?,?,?,?,?)",
                   (identity, cohort, at, kind, encoded, previous_hash, value_hash))
        return value_hash

    def observe(self, registration, evidence, *, now=None, identity=None, kind="CAPTURE"):
        """Store bounded evidence; all completeness flags must be explicit booleans.

        A snapshot from local SQLite alone must set reconciliation/cashflows
        false. Incomplete receipts are retained and rejected by the pure audit.
        Missing windows are never retrospectively filled.
        """
        cohort = register_forward_cohort(registration)
        at = epoch(self.clock() if now is None else now)
        if at < cohort.registered_at.timestamp():
            raise ValueError("CAPTURE_BEFORE_REGISTRATION")
        if kind not in {"CAPTURE", "PROPOSAL", "ERROR"} or type(evidence) is not dict:
            raise ValueError("CLOSED_EVIDENCE_REQUIRED")
        if any(type(evidence.get(key)) is not bool for key in FLAGS):
            raise ValueError("EXPLICIT_COMPLETENESS_REQUIRED")
        identity = identity or digest({"cohort": cohort.digest, "kind": kind, "at": at, "evidence": evidence})
        if type(identity) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", identity):
            raise ValueError("EVIDENCE_ID_REQUIRED")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM cohorts WHERE digest=?", (cohort.digest,)).fetchone():
                raise ValueError("DURABLE_REGISTRATION_REQUIRED")
            existing = db.execute("SELECT 1 FROM observations WHERE id=?", (identity,)).fetchone()
            previous = db.execute("SELECT at,payload FROM observations WHERE cohort=? AND kind='CAPTURE' ORDER BY sequence DESC LIMIT 1", (cohort.digest,)).fetchone()
            evidence_hash = self._append(db, cohort.digest, at, kind, evidence, identity)
            if existing or kind != "CAPTURE":
                return evidence_hash
            elapsed = at - cohort.starts_at.timestamp()
            completed = int(elapsed // cohort.cadence_seconds)
            if completed <= 0:
                return evidence_hash
            slot = completed - 1
            if slot >= 50_000:
                raise ValueError("RECEIPT_RETENTION_FULL")
            start = cohort.starts_at.timestamp() + slot * cohort.cadence_seconds
            end = start + cohort.cadence_seconds
            if at > end + cohort.max_receipt_delay_seconds:
                return evidence_hash  # Explicit gap, never manufacture earlier windows.
            continuous = previous is not None and previous["at"] <= start + cohort.max_receipt_delay_seconds and at - previous["at"] <= cohort.cadence_seconds + cohort.max_receipt_delay_seconds
            prior_flags = json.loads(previous["payload"]) if previous else {}
            flags = {key: evidence[key] and prior_flags.get(key) is True and continuous for key in FLAGS}
            receipt = {"receipt_id": "receipt:" + digest({"cohort": cohort.digest, "slot": slot}),
                "cohort_digest": cohort.digest, "environment": cohort.environment,
                "fingerprints": dict(cohort.fingerprints), "interval_start": iso(start), "interval_end": iso(end),
                "available_at": iso(at), "decided_at": iso(at), "received_at": iso(at),
                "evidence_kind": "OBSERVED_FORWARD", "evidence_digest": evidence_hash, **flags}
            # Validate once at capture. Portal reads need only compact ordered
            # slot metadata; raw receipts remain available for explicit replay.
            financial = evaluate_forward_cohort(registration, [receipt], now=iso(at), expected_digest=cohort.digest)["valid_receipts"] == 1
            local_receipt = {**receipt, **{flag: True for flag in FLAGS}}
            operational = receipt["source_complete"] and evaluate_forward_cohort(
                registration, [local_receipt], now=iso(at), expected_digest=cohort.digest)["valid_receipts"] == 1
            db.execute("INSERT OR IGNORE INTO receipts(cohort,slot,payload,operational,financial) VALUES(?,?,?,?,?)",
                       (cohort.digest, slot, canonical(receipt), int(operational), int(financial)))
        return evidence_hash

    def verify_chain(self, *, expected_anchor=None):
        previous, count = ZERO_HASH, 0
        retained_found = expected_anchor is None
        with closing(self.connect(True)) as db:
            for row in db.execute("SELECT * FROM observations ORDER BY sequence LIMIT ?", (self.max_records + 1,)):
                if row["previous"] != previous:
                    return {"state": "INVALID", "reason": "CHAIN_LINK_MISMATCH", "records": count}
                payload = {"id": row["id"], "cohort": row["cohort"], "at": row["at"], "kind": row["kind"],
                           "payload": json.loads(row["payload"]), "previous": previous}
                if digest(payload) != row["hash"]:
                    return {"state": "INVALID", "reason": "CHAIN_CONTENT_MISMATCH", "records": count}
                previous, count = row["hash"], count + 1
                retained_found = retained_found or previous == expected_anchor
        if count > self.max_records or not retained_found:
            return {"state": "INVALID", "reason": "RETAINED_ANCHOR_MISMATCH", "records": count}
        return {"state": "VALID_LOCAL_CHAIN", "records": count, "anchor": previous,
                "external_attestation": False}

    def snapshot(self, *, now=None):
        at = epoch(self.clock() if now is None else now)
        value = {"schema": 1, "state": "UNAVAILABLE", "at": iso(at), "scopes": [], **AUTHORITY,
                 "limitations": ["LOCAL_OBSERVATIONS_NOT_EXCHANGE_CERTIFICATION", "NO_AUTOMATIC_THIRTY_DAY_APPROVAL",
                                 "LEGACY_HISTORY_NOT_BACKFILLED", "HASH_CHAIN_NOT_EXTERNAL_ATTESTATION"]}
        if not self.path.exists():
            return value
        with closing(self.connect(True)) as db:
            newest = db.execute("SELECT at FROM observations ORDER BY sequence DESC LIMIT 1").fetchone()
            if newest is not None and newest["at"] > at:
                value["state"] = "CLOCK_REGRESSION"
                return value
            registrations = db.execute("SELECT * FROM cohorts ORDER BY registered,rowid LIMIT 65").fetchall()
            if len(registrations) > 64:
                value["state"] = "RETENTION_FULL"
                return value
            active = {(row["engine"], row["environment"]): row["digest"] for row in registrations}
            for row in registrations:
                reg = json.loads(row["registration"])
                audit = evaluate_forward_cohort(reg, [], now=iso(at), expected_digest=row["digest"])
                matured = audit["matured_windows"]
                # Two tiny run accumulators, streaming integers rather than
                # materializing up to 50,000 nested receipt JSON objects per GET.
                stats = [{"valid": 0, "before_matured": 0, "last": None, "run": 0, "days": 0} for _ in range(2)]
                total = 0
                cadence = reg["cadence_seconds"]
                for item in db.execute("SELECT slot,operational,financial FROM receipts WHERE cohort=? ORDER BY slot LIMIT 50000", (row["digest"],)):
                    total += 1
                    for index, column in enumerate(("operational", "financial")):
                        if item[column] != 1:
                            continue
                        stat = stats[index]
                        slot = item["slot"]
                        if stat["last"] is not None and slot != stat["last"]+1:
                            stat["days"] += stat["run"]*cadence//86400
                            stat["run"] = 0
                        stat["valid"] += 1
                        stat["before_matured"] += int(slot < matured)
                        stat["run"] += 1
                        stat["last"] = slot
                for stat in stats:
                    stat["days"] = stat["days"]+stat["run"]*cadence//86400 if stat["valid"] else None
                    stat["missing"] = matured-stat["before_matured"]
                local, financial = stats
                reasons = []
                if total-financial["valid"]:
                    reasons.append("RECEIPT_REJECTED")
                if not financial["valid"]:
                    reasons.append("NO_VALID_FORWARD_RECEIPTS")
                if financial["missing"]:
                    reasons.append("MISSING_CADENCE_WINDOWS")
                last = db.execute("SELECT at,hash FROM observations WHERE cohort=? ORDER BY sequence DESC LIMIT 1", (row["digest"],)).fetchone()
                capture = db.execute("SELECT payload,at FROM observations WHERE cohort=? AND kind='CAPTURE' ORDER BY sequence DESC LIMIT 1", (row["digest"],)).fetchone()
                source = json.loads(capture["payload"]) if capture else {}
                value["scopes"].append({"engine": row["engine"], "environment": row["environment"],
                    "active": active[(row["engine"], row["environment"])] == row["digest"],
                    "cohort_id": reg["cohort_id"], "registered_at": reg["registered_at"], "starts_at": reg["starts_at"],
                    "registration_digest": row["digest"], "last_at": iso(last["at"]) if last else None,
                    "last_capture_at": iso(capture["at"]) if capture else None,
                    "source_state": source.get("state", "NOT_CAPTURED"),
                    "source_at": source.get("source_at"), "source_complete": source.get("source_complete", False),
                    "stale": (capture is None or source.get("source_complete") is not True
                              or not 0 <= at-capture["at"] <= 2*reg["cadence_seconds"]),
                    "qualified_days": financial["days"], "receipt_complete_days": financial["days"],
                    "operational_coverage_days": local["days"],
                    "operational_valid_receipts": local["valid"],
                    "operational_missing_windows": local["missing"],
                    "valid_receipts": financial["valid"], "invalid_receipts": total-financial["valid"],
                    "missing_windows": financial["missing"], "reason_codes": sorted(reasons) or ["NO_FINANCIAL_OR_LIVE_AUTHORITY"],
                    "state": "UNKNOWN" if not financial["valid"] else "INCOMPLETE" if reasons else "SUPPLIED_FORWARD_COVERAGE_ONLY"})
            head = db.execute("SELECT sequence,hash,at FROM observations ORDER BY sequence DESC LIMIT 1").fetchone()
            value["head"] = dict(head) if head else None
        value["state"] = "OBSERVING" if value["scopes"] else "NOT_REGISTERED"
        return value
