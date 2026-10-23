"""Cached audit contract, authority boundaries and no-network/no-mutation reads."""
from copy import deepcopy
from datetime import UTC, datetime
import json
import hashlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from trader import migration_audit as audit

NOW = datetime(2026, 10, 23, 16, 10, tzinfo=UTC)


def fixture():
    return audit.build_migration_audit(version="0.10.52", now=NOW)


class MigrationAuditTests(unittest.TestCase):
    def test_absence_stays_unknown_never_zero_or_authority(self):
        result = fixture()
        self.assertTrue(audit.valid_migration_audit(result))
        self.assertIsNone(result["qualified_days"])
        for row in result["accounts"]:
            self.assertEqual(row["state"], "UNKNOWN")
            self.assertIsNone(row["at"])
            self.assertTrue(all(row[key] is None for key in audit.COUNT_KEYS))
        self.assertTrue(all(result[key] is False for key in audit.FLAGS))
        self.assertTrue(all(row["state"] == "NOT_RUN" for row in result["checks"]))

    def test_synthetic_pass_is_labelled_no_operating_authority(self):
        capital = {"state": "PASSED", "checks": [{"passed": True}]*2,
                   "execution_enabled": False, "controls_enabled": False}
        risk = {"engine": "RISK_LATCHES_REHEARSAL", "mode": "SYNTHETIC_ONLY", "state": "PASS",
                "scenarios": [{"passed": True}]*3, "execution_enabled": False,
                "operational_evidence": False, "admission_authority": False,
                "promotion_allowed": False, "live_implemented": False}
        result = audit.build_migration_audit(version="0.10.52", capital=capital, risk=risk, now=NOW)
        self.assertEqual([row["total"] for row in result["checks"]], [2, 3, 5])
        self.assertTrue(all(row["state"] == "PASSED" for row in result["checks"]))
        self.assertTrue(all(result[key] is False for key in audit.FLAGS))
        capital["checks"][0] = {"passed": False}
        capital["state"] = "FAILED"
        result = audit.build_migration_audit(version="0.10.52", capital=capital, risk=risk, now=NOW)
        self.assertEqual(result["checks"][2]["state"], "FAILED")
        risk["admission_authority"] = True
        result = audit.build_migration_audit(version="0.10.52", risk=risk, now=NOW)
        self.assertEqual(result["checks"][1]["state"], "UNAVAILABLE")

    def test_report_cannot_inject_controls_private_fields_or_certified_days(self):
        for mutate in ([lambda x, key=key: x.update({key: True}) for key in audit.FLAGS]
                       + [lambda x: x.update(qualified_days=30), lambda x: x.update(account_id="private"),
                          lambda x: x["accounts"][0].update(secret="private"),
                          lambda x: x.update(source_version="<script>"),
                          lambda x: x.update(at="2026-02-30T00:00:00.000Z")]):
            result = fixture()
            mutate(result)
            self.assertFalse(audit.valid_migration_audit(result))

    def test_state_count_compatibility_and_bool_rejection(self):
        for row in ({"id": "CAPITAL_FLOW", "state": "PASSED", "passed": 0, "total": 0},
                    {"id": "CAPITAL_FLOW", "state": "PASSED", "passed": 1, "total": 2},
                    {"id": "CAPITAL_FLOW", "state": "FAILED", "passed": 2, "total": 2},
                    {"id": "CAPITAL_FLOW", "state": "NOT_RUN", "passed": 0, "total": 0},
                    {"id": "CAPITAL_FLOW", "state": "PASSED", "passed": True, "total": 1}):
            result = fixture()
            result["checks"][0] = row
            self.assertFalse(audit.valid_migration_audit(result))

    def test_cached_file_read_never_creates_or_modifies(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"missing"/"latest.json"
            self.assertIsNone(audit.read_migration_audit(path))
            self.assertFalse(path.parent.exists())
            path = Path(folder)/"latest.json"
            raw = audit._encode(fixture())
            path.write_bytes(raw)
            before = path.stat().st_mtime_ns
            for _ in range(3):
                self.assertEqual(audit.read_migration_audit(path), fixture())
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, before)
            path.write_bytes(b'{"schema":1,"schema":1}')
            self.assertIsNone(audit.read_migration_audit(path))
            path.write_bytes(b"x"*8001)
            self.assertIsNone(audit.read_migration_audit(path))

    def test_projection_has_no_api_model_or_recipe_calls(self):
        from trader.portal_snapshot import migration_audit_projection
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = SimpleNamespace(bot=SimpleNamespace(database_path=root/"data"/"testnet.db"))
            with patch("socket.socket.connect", side_effect=AssertionError("NETWORK_FORBIDDEN")):
                self.assertIsNone(migration_audit_projection(config))
            self.assertFalse((root/"data").exists())

    def test_publisher_hashes_exact_read_and_rejects_explicit_empty_bundle(self):
        from scripts.publish_migration_audit import read, main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/"input.json"
            raw = b'{"joint_reports":[],"cohort":null}'
            path.write_bytes(raw)
            value, digest = read(path)
            path.write_text('{"changed":true}')
            self.assertEqual(value, {"joint_reports": [], "cohort": None})
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
            for invalid in ("{}", "[]", "null", "false"):
                path.write_text(invalid)
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["--evidence", str(path), "--output-dir", str(root/"migration-audit")]), 2)
                self.assertFalse((root/"migration-audit").exists())

    def test_cohort_coverage_is_supplied_not_certified_and_account_cut_preserved(self):
        from trader.account_inventory import AUTHORITY
        cut = "2026-10-23T15:00:00.000Z"
        inv = {"mode": "READ_ONLY_TEST_ENVIRONMENTS", **AUTHORITY, "accounts_linked": False,
               "complete_exchange_inventory": False, "history_complete": False, "at": cut,
               "accounts": [{"environment": env, "at": cut, "state": "OBSERVED", "identity": "PRODUCT_ID_REPORTED_NOT_LINKED",
                  "quantity_check": "UNKNOWN", "local_positions": 2, "exchange_positions": None,
                  "open_orders": 4, "conditional_orders": 2} for env in ("SPOT_TESTNET", "FUTURES_DEMO")]}
        cohort = {"mode": "READ_ONLY_FORWARD_RECEIPTS", "state": "SUPPLIED_FORWARD_COVERAGE_ONLY",
                  "ready_for_live": False, "receipt_complete_days": 30, "missing_windows": 0}
        report = audit.build_migration_audit(version="0.10.52", inventory=inv, cohort=cohort, now=NOW)
        self.assertTrue(all(row["at"] == cut for row in report["accounts"]))
        self.assertIsNone(report["qualified_days"])
        self.assertEqual(report["cohort"]["receipt_days"], 30)
        self.assertEqual(report["cohort"]["state"], "SUPPLIED_RECEIPTS_ONLY")


if __name__ == "__main__":
    unittest.main()
