"""Closed optional preproduction DTO: no account or journal writes on reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trader.preproduction_status import (PACKAGE_IDS, SOURCE_REQUIREMENTS,
    read_preproduction_status, valid_preproduction_status, canonical_source_sha256)
from trader.operational_cohort import OperationalCohortStore
from tests.test_operational_cohort import FINGERPRINTS, START, evidence


def fixture():
    # This path must not exist; projection reads must not create it.
    with TemporaryDirectory() as directory:
        data = Path(directory)/"absent"
        value = read_preproduction_status(data, "0.10.54", now=START)
        assert not data.exists()
        return value


class PreproductionStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, payload):
        path = self.root/"live-preproduction"/name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_absent_data_stays_absent_and_defaults_have_no_authority(self):
        value = fixture()
        self.assertTrue(valid_preproduction_status(value))
        self.assertEqual(value["connection"]["state"], "NOT_CONFIGURED")
        self.assertFalse(value["owner_authorization"])
        self.assertFalse(value["execution_enabled"])
        self.assertEqual(len(value["packages"]), 5)
        self.assertIn("ACCOUNT_RECONCILIATION_INCOMPLETE", value["blockers"])

    def test_closed_fields_refuse_credential_ids_authority_and_automatic_ready(self):
        for mutate in (lambda x:x.update(execution_enabled=True), lambda x:x.update(owner_authorization=True),
                       lambda x:x.update(ready_for_live=True), lambda x:x["connection"].update(api_key="secret"),
                       lambda x:x["connection"]["scopes"][0].update(uid="private"),
                       lambda x:x["packages"][0].update(state="LIVE_READY"), lambda x:x.update(schema=True)):
            value = fixture()
            mutate(value)
            self.assertFalse(valid_preproduction_status(value))

    def test_duplicate_unknown_nested_and_future_connection_fields_fail_closed(self):
        for payload in ('{"schema":1,"schema":1}', '{"schema":1,"secret":"do-not-show"}', '{"value":NaN}'):
            path = self.root/"live-preproduction"/"connection-status.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            value = read_preproduction_status(self.root, "0.10.54", now=START)
            self.assertEqual(value["connection"]["state"], "UNAVAILABLE")
            self.assertNotIn("do-not-show", json.dumps(value))

    def test_readonly_account_cut_is_retained_not_refreshed_by_get(self):
        value = fixture()
        connection = value["connection"]
        connection.update(state="READ_ONLY_VERIFIED", at=value["at"])
        for row in connection["scopes"]:
            row.update(identity="REPORTED", permissions="UNKNOWN", at=value["at"])
        self.write("connection-status.json", connection)
        result = read_preproduction_status(self.root, "0.10.54", now=START+86400)
        self.assertEqual(result["connection"]["at"], value["at"])
        self.assertTrue(valid_preproduction_status(result))
        self.assertIn("ACCOUNT_RECONCILIATION_INCOMPLETE", result["blockers"])

    def test_cohort_projection_keeps_local_days_distinct_from_financial_days(self):
        store = OperationalCohortStore(self.root/"operational-cohorts.sqlite3")
        store.initialize()
        registration = store.register("SPOT", "SPOT_TESTNET", FINGERPRINTS, now=START)
        store.observe(registration, evidence(), now=START)
        before = store.path.read_bytes()
        value = read_preproduction_status(self.root, "0.10.54", now=START)
        self.assertTrue(valid_preproduction_status(value))
        self.assertEqual(len(value["cohort"]["scopes"]), 1)
        self.assertIsNone(value["cohort"]["scopes"][0]["qualified_days"])
        self.assertEqual(store.path.read_bytes(), before)

    def test_complete_spot_futures_do_not_require_shadow_qualification_or_grant_authority(self):
        from trader.operational_cohort import iso
        def scope(engine, environment, qualified):
            return {"active": True, "engine": engine, "environment": environment,
                "registered_at": iso(START), "starts_at": iso(START), "last_capture_at": iso(START),
                "source_at": iso(START), "source_complete": True, "stale": False,
                "operational_coverage_days": 30, "qualified_days": qualified,
                "operational_missing_windows": 0}
        rows = [scope("SPOT", "SPOT_TESTNET", 30), scope("FUTURES", "FUTURES_DEMO", 30),
                scope("AI_MARKET_PULSE", "SHADOW", None), scope("QUANT_ARBITRAGE", "SHADOW", None)]
        with patch("trader.preproduction_status.OperationalCohortStore.snapshot", return_value={"state":"OBSERVING", "scopes":rows}):
            value = read_preproduction_status(self.root, "0.10.54", now=START)
        self.assertNotIn("FORWARD_COHORT_INCOMPLETE", value["blockers"])
        self.assertIn("OWNER_ACTIVATION_REQUIRED", value["blockers"])
        self.assertIn("ACCOUNT_RECONCILIATION_INCOMPLETE", value["blockers"])
        self.assertFalse(value["execution_enabled"])
        for incomplete in (rows[1:], rows[:1], [rows[0], {**rows[1], "qualified_days":29}, *rows[2:]],
                           [rows[0], {**rows[1], "qualified_days":None}, *rows[2:]]):
            with patch("trader.preproduction_status.OperationalCohortStore.snapshot", return_value={"state":"OBSERVING", "scopes":incomplete}):
                value = read_preproduction_status(self.root, "0.10.54", now=START)
            self.assertIn("FORWARD_COHORT_INCOMPLETE", value["blockers"])

    def technical(self):
        source = self.root/"code"
        (source/"trader").mkdir(parents=True)
        hashes = {}
        for name in {name for group in SOURCE_REQUIREMENTS.values() for name in group}:
            relative = "trader/"+name
            raw = ("# synthetic source for "+name+"\n").encode("ascii")
            (source/relative).write_bytes(raw)
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        report = {"schema":1, "at":fixture()["at"], "source_version":"0.10.54",
            "packages":[{"id":name,"state":"TESTED_PREPARED"} for name in PACKAGE_IDS], "source_hashes":hashes}
        return source, report

    def test_matching_artifact_can_report_tests_but_never_authorize_or_certify_account(self):
        source, report = self.technical()
        self.write("technical-status.json", report)
        value = read_preproduction_status(self.root, "0.10.55", now=START, source_root=source)
        self.assertTrue(all(row["state"] == "TESTED_PREPARED" for row in value["packages"]))
        self.assertFalse(value["execution_enabled"])
        self.assertIn("ACCOUNT_RECONCILIATION_INCOMPLETE", value["blockers"])
        self.assertIn("OWNER_ACTIVATION_REQUIRED", value["blockers"])

    def test_source_change_or_omission_withdraws_test_claims(self):
        source, report = self.technical()
        self.write("technical-status.json", report)
        (source/"trader"/"central_admission.py").write_text("changed\n", encoding="utf-8")
        value = read_preproduction_status(self.root, "0.10.54", now=START, source_root=source)
        self.assertIn("SOURCE_CHANGED", value["blockers"])
        self.assertFalse(any(row["state"] == "TESTED_PREPARED" for row in value["packages"]))
        # Restore the synthetic source so omission is independently rejected.
        (source/"trader"/"central_admission.py").write_bytes(b"# synthetic source for central_admission.py\n")
        del report["source_hashes"]["trader/live_transport.py"]
        self.write("technical-status.json", report)
        value = read_preproduction_status(self.root, "0.10.54", now=START, source_root=source)
        self.assertFalse(any(row["state"] == "TESTED_PREPARED" for row in value["packages"]))

    def test_technical_source_hashes_normalize_crlf_only_and_preserve_semantic_changes(self):
        source, report = self.technical()
        for file in (source/"trader").glob("*.py"):
            file.write_bytes(file.read_bytes().replace(b"\n", b"\r\n"))
        self.write("technical-status.json", report)
        value = read_preproduction_status(self.root, "0.10.54", now=START, source_root=source)
        self.assertTrue(all(row["state"] == "TESTED_PREPARED" for row in value["packages"]))
        self.assertEqual(canonical_source_sha256(b"x=1\r\n"), canonical_source_sha256(b"x=1\n"))
        self.assertNotEqual(canonical_source_sha256(b"x=1\n"), canonical_source_sha256(b"x=2\n"))
        self.assertNotEqual(canonical_source_sha256(b"x=1\n"), canonical_source_sha256(b"\xef\xbb\xbfx=1\n"))

    def test_path_traversal_manifest_is_rejected_without_opening_outside_sources(self):
        source, report = self.technical()
        report["source_hashes"]["../.env"] = "a"*64
        self.write("technical-status.json", report)
        value = read_preproduction_status(self.root, "0.10.54", now=START, source_root=source)
        self.assertIn("TECHNICAL_REPORT_UNAVAILABLE", value["blockers"])


if __name__ == "__main__":
    unittest.main()
