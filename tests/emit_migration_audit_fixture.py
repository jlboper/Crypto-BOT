"""Closed synthetic audit fixture; no accounts, ledgers, keys, models or network."""
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.migration_audit import build_migration_audit, valid_migration_audit


def make_audit():
    at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    result = build_migration_audit(version="0.10.52", now=datetime.fromisoformat(at.replace("Z", "+00:00")))
    result.update(accounts=[{"environment": environment, "state": "PARTIAL", "at": at,
            "identity": "PRODUCT_ID_REPORTED_NOT_LINKED", "quantity_check": "UNKNOWN",
            "local_positions": 2 if i == 0 else 1, "exchange_positions": None,
            "open_orders": 0, "conditional_orders": 2 if i == 0 else 1}
            for i, environment in enumerate(("SPOT_TESTNET", "FUTURES_DEMO"))],
        checks=[{"id": identifier, "state": "PASSED", "passed": count, "total": count}
                   for identifier, count in (("CAPITAL_FLOW", 8), ("RISK_LATCHES", 5), ("RECOVERY", 3))],
        costs={"state": "MIXED", "scenarios": 2, "feasible": 1, "rejected": 1,
                  "proposal_usd": "100", "hypothetical_usdt": "80"},
        cohort={"state": "NOT_REGISTERED", "receipt_days": None, "missing_windows": None})
    assert valid_migration_audit(result)
    return result


if __name__ == "__main__":
    print(json.dumps(make_audit(), ensure_ascii=True, allow_nan=False))
