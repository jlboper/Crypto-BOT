"""Cached migration work report. Reading never starts audits, APIs or simulations.

This report separates observed Testnet/Demo cuts from synthetic safety recipes.
Checks passing do not waive the immutable readiness blockers in live_preparation.
No financial totals, account IDs, order IDs, credentials or provider text cross
the shared portal contract. Reports are evidence, never trading authority.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import re

MAX_BYTES = 8000
FLAGS = ("execution_enabled", "controls_enabled", "reservations_enabled", "promotion_allowed",
         "financial_authorization", "automatic_activation", "can_veto", "accounts_linked",
         "complete_exchange_inventory", "history_complete")
KEYS = {"schema", "engine", "mode", "at", "autonomy_level", "source_version", *FLAGS,
        "qualified_days", "accounts", "checks", "costs", "cohort"}
ACCOUNT_KEYS = {"environment", "state", "at", "identity", "quantity_check", "local_positions",
                "exchange_positions", "open_orders", "conditional_orders"}
COUNT_KEYS = ("local_positions", "exchange_positions", "open_orders", "conditional_orders")
CHECK_KEYS = {"id", "state", "passed", "total"}
QUANTITY_STATES = {"UNKNOWN", "BALANCE_COVERS_LOCAL_AT_CUT", "EXACT_QUANTITIES_AT_CUT",
                   "DIFFERENT_CUT_REQUIRES_RECONCILIATION"}


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def _stamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(timespec="milliseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def _count(value, maximum=10000):
    return type(value) is int and 0 <= value <= maximum


def _amount(value):
    return (type(value) is str and len(value) <= 14
            and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", value) is not None
            and len(value.partition(".")[2]) <= 2 and 0 < Decimal(value) <= 1_000_000_000)


def valid_migration_audit(value):
    try:
        if (type(value) is not dict or set(value) != KEYS or type(value["schema"]) is not int
                or value["schema"] != 1 or value["engine"] != "MIGRATION_AUDIT" or value["mode"] != "READ_ONLY"
                or type(value["autonomy_level"]) is not int or value["autonomy_level"] != 0
                or any(value[key] is not False for key in FLAGS) or value["qualified_days"] is not None
                or not _stamp(value["at"]) or type(value["source_version"]) is not str
                or not re.fullmatch(r"(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})\.(?:0|[1-9][0-9]{0,2})", value["source_version"])
                or len(_encode(value)) > MAX_BYTES or type(value["accounts"]) is not list or len(value["accounts"]) != 2):
            return False
        for row, environment in zip(value["accounts"], ("SPOT_TESTNET", "FUTURES_DEMO")):
            if (type(row) is not dict or set(row) != ACCOUNT_KEYS or row["environment"] != environment
                    or row["state"] not in {"UNKNOWN", "OBSERVED", "PARTIAL"}
                    or row["identity"] not in {"UNKNOWN", "PRODUCT_ID_REPORTED_NOT_LINKED"}
                    or row["quantity_check"] not in QUANTITY_STATES
                    or row["at"] is not None and (not _stamp(row["at"]) or row["at"] > value["at"])
                    or any(row[key] is not None and not _count(row[key]) for key in COUNT_KEYS)):
                return False
        if type(value["checks"]) is not list or len(value["checks"]) != 3:
            return False
        for row, identifier in zip(value["checks"], ("CAPITAL_FLOW", "RISK_LATCHES", "RECOVERY")):
            if type(row) is not dict or set(row) != CHECK_KEYS or row["id"] != identifier:
                return False
            if row["state"] in ("NOT_RUN", "UNAVAILABLE"):
                if row["passed"] is not None or row["total"] is not None:
                    return False
            elif (row["state"] not in ("PASSED", "FAILED") or not _count(row["total"], 1000) or row["total"] == 0
                    or not _count(row["passed"], 1000) or row["passed"] > row["total"]
                    or (row["state"] == "PASSED") != (row["passed"] == row["total"])):
                return False
        costs = value["costs"]
        if (type(costs) is not dict or set(costs) != {"state", "scenarios", "feasible", "rejected", "proposal_usd", "hypothetical_usdt"}
                or costs["state"] not in {"UNKNOWN", "FEASIBLE_HYPOTHESIS", "REJECTED_HYPOTHESIS", "MIXED"}
                or any(not _count(costs[key], 100) for key in ("scenarios", "feasible", "rejected"))
                or costs["feasible"]+costs["rejected"] != costs["scenarios"]
                or any(costs[key] is not None and not _amount(costs[key]) for key in ("proposal_usd", "hypothetical_usdt"))):
            return False
        if costs["state"] != ("UNKNOWN" if not costs["scenarios"] else "MIXED" if costs["feasible"] and costs["rejected"]
                              else "FEASIBLE_HYPOTHESIS" if costs["feasible"] else "REJECTED_HYPOTHESIS"):
            return False
        cohort = value["cohort"]
        return (type(cohort) is dict and set(cohort) == {"state", "receipt_days", "missing_windows"}
            and cohort["state"] in {"NOT_REGISTERED", "UNKNOWN", "INCOMPLETE", "SUPPLIED_RECEIPTS_ONLY"}
            and (cohort["receipt_days"] is None or _count(cohort["receipt_days"], 36500))
            and (cohort["missing_windows"] is None or _count(cohort["missing_windows"], 50_000_000)))
    except (KeyError, TypeError, ValueError, ArithmeticError, RecursionError):
        return False


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def read_migration_audit(path):
    """An absent/invalid cached report stays absent; GET never writes or retries."""
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES:
            return None
        value = json.loads(raw, object_pairs_hook=_unique)
        return value if valid_migration_audit(value) else None
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def _checks(identifier, report):
    unknown = {"id": identifier, "state": "NOT_RUN" if report is None else "UNAVAILABLE", "passed": None, "total": None}
    if report is None or type(report) is not dict:
        return unknown
    if identifier == "RISK_LATCHES" and report.get("engine") == "RISK_LATCHES_REHEARSAL":
        if (report.get("mode") != "SYNTHETIC_ONLY" or report.get("operational_evidence") is not False
                or any(report.get(key) is not False for key in ("admission_authority", "execution_enabled", "promotion_allowed", "live_implemented"))):
            return unknown
        report = {"state": "PASSED" if report.get("state") == "PASS" else "FAILED" if report.get("state") == "FAIL" else "UNAVAILABLE",
                  "checks": report.get("scenarios"), "execution_enabled": False, "controls_enabled": False}
    if report.get("execution_enabled") is not False or report.get("controls_enabled") is not False:
        return unknown
    rows = report.get("checks")
    if type(rows) is not list or not 1 <= len(rows) <= 1000 or any(type(row) is not dict or type(row.get("passed")) is not bool for row in rows):
        return unknown
    passed = sum(row["passed"] for row in rows)
    state = "PASSED" if passed == len(rows) else "FAILED"
    if report.get("state") != state:
        return unknown
    return {"id": identifier, "state": state, "passed": passed, "total": len(rows)}


def build_migration_audit(*, version, inventory=None, capital=None, risk=None, joint_reports=(), cohort=None, now=None):
    """Select explicitly supplied reports; does not run recipes or read wallets."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("UTC_REPORT_CUT_REQUIRED")
    at = now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    accounts = []
    for environment in ("SPOT_TESTNET", "FUTURES_DEMO"):
        item = {"environment": environment, "state": "UNKNOWN", "at": None, "identity": "UNKNOWN",
                "quantity_check": "UNKNOWN", **{key: None for key in COUNT_KEYS}}
        if (type(inventory) is dict and inventory.get("mode") == "READ_ONLY_TEST_ENVIRONMENTS"
                and all(inventory.get(key) is False for key in FLAGS if key not in ("can_veto",))
                and type(inventory.get("accounts")) is list):
            rows = [r for r in inventory["accounts"] if type(r) is dict and r.get("environment") == environment]
            if len(rows) == 1:
                item.update({key: rows[0].get(key) for key in ACCOUNT_KEYS if key not in ("at", "environment")})
                item["at"] = rows[0].get("at")
                if item["at"] is None:
                    # Older explicit audit files retain per-request receipts.
                    # Use their earliest cut conservatively, never report end.
                    names = ("account", "open_orders", "conditional_orders") if environment == "SPOT_TESTNET" else ("account", "balance", "positions", "open_orders", "conditional_orders")
                    obs = rows[0].get("observations", {})
                    stamps = [obs[name].get("requested_at", inventory.get("started_at")) for name in names
                              if type(obs.get(name)) is dict and obs[name].get("state") == "OBSERVED"]
                    if rows[0].get("local_at") is not None:
                        stamps.append(rows[0]["local_at"])
                    item["at"] = min(stamps) if stamps and all(_stamp(stamp) for stamp in stamps) else None
        accounts.append(item)
    checks = [_checks("CAPITAL_FLOW", capital), _checks("RISK_LATCHES", risk)]
    recovery = {"id": "RECOVERY", "state": "NOT_RUN", "passed": None, "total": None}
    if all(row["state"] in ("PASSED", "FAILED") for row in checks):
        # These are the supplied synthetic recipes, not a Windows reboot or a
        # rollback of operating data. The UI labels that distinction explicitly.
        total = sum(row["total"] for row in checks)
        passed = sum(row["passed"] for row in checks)
        recovery.update(state="PASSED" if passed == total else "FAILED", passed=passed, total=total)
    checks.append(recovery)
    costs = {"state": "UNKNOWN", "scenarios": 0, "feasible": 0, "rejected": 0,
             "proposal_usd": None, "hypothetical_usdt": None}
    if not isinstance(joint_reports, (tuple, list)) or len(joint_reports) > 100:
        raise ValueError("BOUNDED_SCENARIO_REPORTS_REQUIRED")
    for report in joint_reports:
        if (type(report) is not dict or report.get("mode") != "HYPOTHETICAL_JOINT_BUDGET"
                or report.get("state") not in ("FEASIBLE_HYPOTHESIS", "REJECTED_HYPOTHESIS")
                or any(report.get(key) is not False for key in ("execution_enabled", "financial_authorization", "promotion_allowed", "reservations_enabled", "automatic_activation", "ready_for_live"))):
            raise ValueError("VALIDATED_HYPOTHETICAL_REPORT_REQUIRED")
        costs["scenarios"] += 1
        costs["feasible" if report["state"] == "FEASIBLE_HYPOTHESIS" else "rejected"] += 1
        if costs["scenarios"] == 1:
            costs.update(proposal_usd=report["proposal_amount_usd"], hypothetical_usdt=report["total_capital_usdt"])
        elif (costs["proposal_usd"] != report["proposal_amount_usd"] or costs["hypothetical_usdt"] != report["total_capital_usdt"]):
            raise ValueError("SCENARIO_ENVELOPES_NOT_COMPARABLE")
    if costs["scenarios"]:
        costs["state"] = "MIXED" if costs["feasible"] and costs["rejected"] else "FEASIBLE_HYPOTHESIS" if costs["feasible"] else "REJECTED_HYPOTHESIS"
    cohort_state = {"state": "NOT_REGISTERED", "receipt_days": None, "missing_windows": None}
    if type(cohort) is dict and cohort.get("mode") == "READ_ONLY_FORWARD_RECEIPTS" and cohort.get("ready_for_live") is False:
        state = cohort.get("state")
        cohort_state.update(state="SUPPLIED_RECEIPTS_ONLY" if state == "SUPPLIED_FORWARD_COVERAGE_ONLY" else state if state in ("UNKNOWN", "INCOMPLETE") else "UNKNOWN",
                            receipt_days=cohort.get("receipt_complete_days"), missing_windows=cohort.get("missing_windows"))
    result = {"schema": 1, "engine": "MIGRATION_AUDIT", "mode": "READ_ONLY", "at": at,
              "autonomy_level": 0, "source_version": version, **{key: False for key in FLAGS},
              "qualified_days": None, "accounts": accounts, "checks": checks, "costs": costs, "cohort": cohort_state}
    if not valid_migration_audit(result):
        raise ValueError("MIGRATION_AUDIT_CONTRACT_INVALID")
    return result
