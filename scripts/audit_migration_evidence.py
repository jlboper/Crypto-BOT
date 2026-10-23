"""Audit supplied forward receipts and/or a joint SIM budget; never call APIs."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_BYTES = 32 * 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _integer(value):
    if len(value) > 80:
        raise ValueError("JSON_INTEGER_BOUNDS")
    return int(value)


def _decimal(value):
    if len(value) > 80:
        raise ValueError("JSON_DECIMAL_BOUNDS")
    return Decimal(value)


def _constant(_):
    raise ValueError("NONSTANDARD_JSON_CONSTANT")


def main(argv=None):
    sys.path.insert(0, str(ROOT))
    from trader.migration_evidence import evaluate_forward_cohort, evaluate_joint_budget
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Existing strict JSON: schema=1, cohort=null|object, joint_budget=null|object")
    args = parser.parse_args(argv)
    report = {"schema": 1, "mode": "READ_ONLY_MIGRATION_EVIDENCE", "state": "INVALID_INPUT",
              "execution_enabled": False, "financial_authorization": False, "promotion_allowed": False,
              "reservations_enabled": False, "automatic_activation": False, "cohort": None, "joint_budget": None,
              "error": None}
    try:
        if args.input.is_symlink() or not args.input.is_file() or args.input.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("INPUT_FILE_BOUNDS")
        with args.input.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("INPUT_FILE_BOUNDS")
        value = json.loads(raw, object_pairs_hook=_unique, parse_int=_integer,
                           parse_float=_decimal, parse_constant=_constant)
        if (type(value) is not dict or set(value) != {"schema", "cohort", "joint_budget"}
                or type(value["schema"]) is not int or value["schema"] != 1
                or value["cohort"] is None and value["joint_budget"] is None):
            raise ValueError("CLOSED_AUDIT_SCHEMA_REQUIRED")
        if value["cohort"] is not None:
            cohort = value["cohort"]
            if type(cohort) is not dict or set(cohort) != {"registration", "receipts", "now", "expected_digest"}:
                raise ValueError("CLOSED_COHORT_AUDIT_REQUIRED")
            report["cohort"] = evaluate_forward_cohort(**cohort)
        if value["joint_budget"] is not None:
            report["joint_budget"] = evaluate_joint_budget(value["joint_budget"])
        reports = [report[key] for key in ("cohort", "joint_budget") if report[key] is not None]
        if any(item["state"] == "INVALID_INPUT" for item in reports):
            raise ValueError("INVALID_EVIDENCE_OR_SCENARIO")
        report["state"] = "SUPPLIED_EVIDENCE_EVALUATED"
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        report["error"] = "SUPPLIED_INPUT_UNAVAILABLE_OR_INVALID"
        print(json.dumps(report, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
        return 2
    print(json.dumps(report, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
    return 0 if all(item["state"] in {"FEASIBLE_HYPOTHESIS", "SUPPLIED_FORWARD_COVERAGE_ONLY"}
                    for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
