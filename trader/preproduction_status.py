"""Closed, credential-free preproduction projection. All GET paths read only."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from .operational_cohort import OperationalCohortStore

MAX_BYTES = 8000
CONNECTION_EVIDENCE_MAX_AGE_SECONDS = 900
PACKAGE_IDS = ("EVIDENCE", "ACCOUNT", "CAPITAL", "RISK", "EXECUTION")
PACKAGE_STATES = {"IMPLEMENTED_NOT_VALIDATED", "TESTED_PREPARED", "WAITING_OWNER", "WAITING_EVIDENCE", "UNAVAILABLE"}
CONNECTION_STATES = {"NOT_CONFIGURED", "CONFIGURED_UNVERIFIED", "READ_ONLY_VERIFIED", "UNAVAILABLE"}
SCOPES = (("SPOT", "SPOT_TESTNET"), ("FUTURES", "FUTURES_DEMO"), ("AI_MARKET_PULSE", "SHADOW"), ("QUANT_ARBITRAGE", "SHADOW"))
BLOCKERS = {"OWNER_ACTIVATION_REQUIRED", "READ_ONLY_CONNECTION_UNVERIFIED", "FORWARD_COHORT_INCOMPLETE",
            "ACCOUNT_RECONCILIATION_INCOMPLETE", "CAPITAL_PROTOCOL_UNVALIDATED", "RISK_PROTOCOL_UNVALIDATED",
            "EXECUTION_RECOVERY_UNVALIDATED", "TECHNICAL_REPORT_UNAVAILABLE", "SOURCE_CHANGED",
            "LEGACY_AUDIT_REQUIRED", "NO_AUTOMATIC_THIRTY_DAY_APPROVAL"}
SOURCE_REQUIREMENTS = {
    "EVIDENCE": ("operational_cohort.py", "preproduction_observer.py", "migration_evidence.py",
                 "financial_evidence.py", "financial_evidence_io.py"),
    "ACCOUNT": ("live_account.py", "live_transport.py", "live_credentials.py"),
    "CAPITAL": ("central_admission.py", "capital_manager_shadow.py", "capital_flow_shadow.py"),
    "RISK": ("central_admission.py", "risk_latches_shadow.py", "global_risk_shadow.py", "live_policy_review.py"),
    "EXECUTION": ("live_execution_runtime.py", "live_runtime_gate.py", "live_authorization.py", "live_transport.py",
                  "local_protection.py", "live_strategy_adapter.py", "live_proposal_source.py"),
}


def canonical_source_sha256(raw):
    """Schema-1 technical artifacts hash UTF-8 source bytes with LF newlines.

    Only CRLF is normalized; executable content, BOM and other whitespace stay
    part of the digest. Signed-package file hashes remain exact raw-byte hashes.
    """
    if type(raw) is not bytes or len(raw) > 2*1024*1024:
        raise ValueError("BOUNDED_SOURCE_BYTES_REQUIRED")
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _stamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(timespec="milliseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def _version(value):
    return type(value) is str and re.fullmatch(r"(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})", value) is not None


def _keys(value, names):
    return type(value) is dict and set(value) == set(names)


def _number(value, max_value=50_000_000):
    return value is None or type(value) is int and 0 <= value <= max_value


def valid_connection(value, *, at):
    if (not _keys(value, ("schema", "state", "at", "scopes")) or type(value["schema"]) is not int or value["schema"] != 1
            or value["state"] not in CONNECTION_STATES or not (value["at"] is None or _stamp(value["at"]) and value["at"] <= at)
            or type(value["scopes"]) is not list or len(value["scopes"]) != 2):
        return False
    for row, environment in zip(value["scopes"], ("SPOT_LIVE", "FUTURES_LIVE")):
        if (not _keys(row, ("environment", "identity", "permissions", "at")) or row["environment"] != environment
                or row["identity"] not in {"UNKNOWN", "REPORTED"} or row["permissions"] not in {"UNKNOWN", "VERIFIED"}
                or not (row["at"] is None or _stamp(row["at"]) and row["at"] <= at)):
            return False
        if row["permissions"] == "VERIFIED" and (row["identity"] != "REPORTED" or row["at"] is None):
            return False
    if value["state"] == "READ_ONLY_VERIFIED" and (value["at"] is None or any(
            row["identity"] != "REPORTED" or row["permissions"] != "VERIFIED" or row["at"] is None for row in value["scopes"])):
        return False
    if value["state"] == "NOT_CONFIGURED" and (value["at"] is not None or any(row["at"] is not None or row["identity"] != "UNKNOWN" or row["permissions"] != "UNKNOWN" for row in value["scopes"])):
        return False
    return True


def valid_preproduction_status(value):
    try:
        if (not _keys(value, ("schema", "engine", "mode", "at", "source_version", "execution_enabled", "controls_enabled", "owner_authorization", "connection", "cohort", "packages", "blockers"))
                or type(value["schema"]) is not int or value["schema"] != 1 or value["engine"] != "PREPRODUCTION"
                or value["mode"] != "READ_ONLY" or not _stamp(value["at"]) or not _version(value["source_version"])
                or any(value[key] is not False for key in ("execution_enabled", "controls_enabled", "owner_authorization"))
                or len(_json(value)) > MAX_BYTES or not valid_connection(value["connection"], at=value["at"])):
            return False
        cohort = value["cohort"]
        if (not _keys(cohort, ("state", "scopes")) or cohort["state"] not in {"NOT_REGISTERED", "OBSERVING", "PARTIAL", "UNAVAILABLE"}
                or type(cohort["scopes"]) is not list or len(cohort["scopes"]) > 4):
            return False
        seen = set()
        for row in cohort["scopes"]:
            if not _keys(row, ("engine", "environment", "state", "registered_at", "starts_at", "last_capture_at", "source_at", "source_complete", "stale", "operational_days", "qualified_days", "missing_windows")):
                return False
            scope = (row["engine"], row["environment"])
            if scope not in SCOPES or scope in seen or row["state"] not in {"OBSERVING_LOCAL", "STALE", "NOT_CAPTURED", "INCOMPLETE"}:
                return False
            seen.add(scope)
            if (not _stamp(row["registered_at"]) or row["registered_at"] > value["at"] or not _stamp(row["starts_at"])
                    or row["starts_at"] < row["registered_at"] or type(row["source_complete"]) is not bool or type(row["stale"]) is not bool
                    or any(row[key] is not None and (not _stamp(row[key]) or row[key] > value["at"]) for key in ("last_capture_at", "source_at"))
                    or not _number(row["operational_days"], 36500) or not _number(row["qualified_days"], 36500) or not _number(row["missing_windows"])):
                return False
            if row["qualified_days"] is not None and (row["operational_days"] is None or row["qualified_days"] > row["operational_days"]):
                return False
        if cohort["state"] == "NOT_REGISTERED" and cohort["scopes"]:
            return False
        if type(value["packages"]) is not list or len(value["packages"]) != 5:
            return False
        for row, identifier in zip(value["packages"], PACKAGE_IDS):
            if not _keys(row, ("id", "state")) or row["id"] != identifier or row["state"] not in PACKAGE_STATES:
                return False
        return (type(value["blockers"]) is list and 1 <= len(value["blockers"]) <= len(BLOCKERS)
                and len(set(value["blockers"])) == len(value["blockers"])
                and all(type(item) is str and item in BLOCKERS for item in value["blockers"])
                and "OWNER_ACTIVATION_REQUIRED" in value["blockers"])
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_KEY")
        result[key] = value
    return result


def _read(path, max_bytes=32768):
    with Path(path).open("rb") as handle:
        raw = handle.read(max_bytes+1)
    if len(raw) > max_bytes:
        raise ValueError("REPORT_LIMIT")
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE")))


def _normal_stamp(value):
    if value is None:
        return None
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("EXPLICIT_UTC_REQUIRED")
    return stamp.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _empty_connection():
    return {"schema": 1, "state": "NOT_CONFIGURED", "at": None,
        "scopes": [{"environment": name, "identity": "UNKNOWN", "permissions": "UNKNOWN", "at": None}
                   for name in ("SPOT_LIVE", "FUTURES_LIVE")]}


def _technical_packages(path, *, at, source_root):
    report = _read(path)
    if (not _keys(report, ("schema", "at", "source_version", "packages", "source_hashes"))
            or type(report["schema"]) is not int or report["schema"] != 1 or not _stamp(report["at"]) or report["at"] > at
            or not _version(report["source_version"]) or type(report["packages"]) is not list or len(report["packages"]) != 5
            or type(report["source_hashes"]) is not dict or not 1 <= len(report["source_hashes"]) <= 64):
        raise ValueError("TECHNICAL_REPORT_INVALID")
    allowed = {"trader/"+name for files in SOURCE_REQUIREMENTS.values() for name in files}
    for name, claimed in report["source_hashes"].items():
        if name not in allowed or type(claimed) is not str or not re.fullmatch(r"[0-9a-f]{64}", claimed):
            raise ValueError("TECHNICAL_SOURCE_INVALID")
        target = Path(source_root)/name
        with target.open("rb") as handle:
            raw = handle.read(2*1024*1024+1)
        if canonical_source_sha256(raw) != claimed:
            raise ValueError("SOURCE_CHANGED")
    for row, identifier in zip(report["packages"], PACKAGE_IDS):
        if not _keys(row, ("id", "state")) or row["id"] != identifier or row["state"] not in PACKAGE_STATES:
            raise ValueError("TECHNICAL_PACKAGE_INVALID")
        if row["state"] in {"TESTED_PREPARED", "IMPLEMENTED_NOT_VALIDATED"} and any("trader/"+name not in report["source_hashes"] for name in SOURCE_REQUIREMENTS[identifier]):
            raise ValueError("TECHNICAL_SOURCE_OMITTED")
    return report["packages"]


def read_preproduction_status(data_dir, source_version, *, now=None, source_root=None):
    """Read caches/RO cohorts only; never initializes a ledger or probes Binance."""
    at = datetime.fromtimestamp(time.time() if now is None else now, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if not _version(source_version):
        raise ValueError("SOURCE_VERSION_REQUIRED")
    data = Path(data_dir)
    value = {"schema": 1, "engine": "PREPRODUCTION", "mode": "READ_ONLY", "at": at,
        "source_version": source_version, "execution_enabled": False, "controls_enabled": False,
        "owner_authorization": False, "connection": _empty_connection(),
        "cohort": {"state": "NOT_REGISTERED", "scopes": []},
        "packages": [{"id": name, "state": "WAITING_OWNER" if name == "EXECUTION" else "WAITING_EVIDENCE"} for name in PACKAGE_IDS],
        "blockers": ["OWNER_ACTIVATION_REQUIRED", "NO_AUTOMATIC_THIRTY_DAY_APPROVAL", "LEGACY_AUDIT_REQUIRED", "ACCOUNT_RECONCILIATION_INCOMPLETE"]}
    try:
        connection = _read(data/"live-preproduction"/"connection-status.json", MAX_BYTES)
        if not valid_connection(connection, at=at):
            raise ValueError()
        # A successful account cut is historical evidence, not perpetual
        # connectivity or a still-current API privilege certificate. Retain
        # original timestamps; never rejuvenate them when the portal is read.
        if connection['state'] == 'READ_ONLY_VERIFIED':
            cuts = [connection['at'], *(row['at'] for row in connection['scopes'])]
            cutoff = datetime.fromisoformat(at.replace('Z','+00:00')).timestamp() - CONNECTION_EVIDENCE_MAX_AGE_SECONDS
            if any(stamp is None or datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp() < cutoff for stamp in cuts):
                connection = {**connection, 'state':'CONFIGURED_UNVERIFIED',
                    'scopes':[{**row, 'permissions':'UNKNOWN'} for row in connection['scopes']]}
        value["connection"] = connection
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, RecursionError, KeyError):
        value["connection"]["state"] = "UNAVAILABLE"
    if value["connection"]["state"] != "READ_ONLY_VERIFIED":
        value["blockers"].append("READ_ONLY_CONNECTION_UNVERIFIED")
    try:
        store = OperationalCohortStore(data/"operational-cohorts.sqlite3")
        snapshot = store.snapshot(now=time.time() if now is None else now)
        if snapshot["state"] not in {"OBSERVING", "NOT_REGISTERED", "UNAVAILABLE"}:
            raise ValueError("COHORT_SNAPSHOT_UNAVAILABLE")
        active = [row for row in snapshot["scopes"] if row["active"]]
        for row in active:
            result = {"engine": row["engine"], "environment": row["environment"],
                "state": "NOT_CAPTURED" if row["last_capture_at"] is None else "STALE" if row["stale"] else "OBSERVING_LOCAL",
                "registered_at": _normal_stamp(row["registered_at"]), "starts_at": _normal_stamp(row["starts_at"]),
                "last_capture_at": _normal_stamp(row["last_capture_at"]), "source_at": _normal_stamp(row["source_at"]),
                "source_complete": row["source_complete"], "stale": row["stale"],
                "operational_days": row["operational_coverage_days"], "qualified_days": row["qualified_days"],
                "missing_windows": row["operational_missing_windows"]}
            value["cohort"]["scopes"].append(result)
        value["cohort"]["state"] = "OBSERVING" if active else "NOT_REGISTERED"
        if any(row["stale"] for row in active):
            value["cohort"]["state"] = "PARTIAL"
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        value["cohort"] = {"state": "UNAVAILABLE", "scopes": []}
    required_forward = {("SPOT", "SPOT_TESTNET"), ("FUTURES", "FUTURES_DEMO")}
    forward = {(row["engine"], row["environment"]): row for row in value["cohort"]["scopes"]
               if (row["engine"], row["environment"]) in required_forward}
    # This closure concerns Spot/Futures only. Shadow research engines neither
    # qualify those accounts nor keep them blocked forever; both required scopes
    # must still be present with their own independently complete evidence.
    if set(forward) != required_forward or any(row["qualified_days"] is None or row["qualified_days"] < 30 for row in forward.values()):
        value["blockers"].append("FORWARD_COHORT_INCOMPLETE")
    try:
        value["packages"] = _technical_packages(data/"live-preproduction"/"technical-status.json", at=at,
                                               source_root=source_root or Path(__file__).resolve().parents[1])
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        value["blockers"].append("SOURCE_CHANGED" if type(error) is ValueError and str(error) == "SOURCE_CHANGED" else "TECHNICAL_REPORT_UNAVAILABLE")
    # Passing source-bound implementation tests does not certify real account
    # history, deposits/withdrawals, funding or order reconciliation.
    for item, blocker in zip(value["packages"][2:], ("CAPITAL_PROTOCOL_UNVALIDATED", "RISK_PROTOCOL_UNVALIDATED", "EXECUTION_RECOVERY_UNVALIDATED")):
        if item["state"] != "TESTED_PREPARED":
            value["blockers"].append(blocker)
    if not valid_preproduction_status(value):
        raise ValueError("CLOSED_PREPRODUCTION_PROJECTION_REQUIRED")
    return value
