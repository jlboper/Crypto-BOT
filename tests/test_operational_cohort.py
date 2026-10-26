"""Durable synthetic cohorts; no exchange, operating files or credential lookup."""
from contextlib import closing
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace

from trader.migration_evidence import FINGERPRINT_KEYS, evaluate_forward_cohort, register_forward_cohort
from trader.operational_cohort import (FLAGS, OperationalCohortStore,
                                      fingerprints_for_config, semantic_source_digest, semantic_engine_digest, iso)


START = 1792800000.0  # Exact UTC 300-second boundary.
FINGERPRINTS = {key: hashlib.sha256(key.encode()).hexdigest() for key in FINGERPRINT_KEYS}


def evidence(complete=False, source=True):
    return {"source_digest": "a"*64, **{key: complete for key in FLAGS}, "source_complete": source}


class OperationalCohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"cohorts.sqlite3"
        self.store = OperationalCohortStore(self.path)
        self.store.initialize()

    def register(self, now=START, fingerprints=None):
        return self.store.register("SPOT", "SPOT_TESTNET", fingerprints or FINGERPRINTS, now=now)

    def test_registry_survives_restart_and_same_semantics_does_not_reset(self):
        first = self.register()
        restarted = OperationalCohortStore(self.path)
        restarted.initialize()
        second = restarted.register("SPOT", "SPOT_TESTNET", FINGERPRINTS, now=START+86400)
        self.assertEqual(first, second)
        self.assertEqual(restarted.verify_chain()["records"], 1)

    def test_changed_material_semantics_creates_retained_new_epoch(self):
        first = self.register()
        changed = {**FINGERPRINTS, "strategy": "b"*64}
        second = self.register(START+300, changed)
        self.assertNotEqual(first["cohort_id"], second["cohort_id"])
        self.assertEqual(len(self.store.snapshot(now=START+300)["scopes"]), 2)

    def test_ast_ignores_documentation_format_comments_but_not_executable_change(self):
        one = semantic_source_digest('"""old documentation"""\nx = 1\n')
        self.assertEqual(one, semantic_source_digest('"""new docs"""\n# release change\nx=1\n'))
        self.assertNotEqual(one, semantic_source_digest('x=2\n'))

    def test_config_fingerprints_exclude_ui_release_paths_but_include_ai_and_risk(self):
        @dataclass
        class Section:
            threshold: float = 1
            enabled: bool = True
            database_path: Path = Path("unused")
        source_root = Path(self.temp.name)/"source"
        source_root.mkdir()
        names = ("engine.py", "strategy.py", "indicators.py", "testnet_broker.py", "testnet_transport.py", "testnet.py",
                 "spot_preflight.py", "risk_control.py", "ai_advisor.py", "broker.py", "database.py", "native_protection.py",
                 "domain.py", "exchange.py", "migration_evidence.py", "migration_costs.py")
        for name in names:
            (source_root/name).write_text("x = 1\n", encoding="utf-8")
        config = SimpleNamespace(risk=Section(), strategy=Section(), ai=Section(), paper=Section(),
            bot=SimpleNamespace(mode="testnet", timeframe="1h", universe_size=10, cycle_seconds=300, protection_seconds=30),
            dashboard=SimpleNamespace(host="localhost", port=8888), version="0.10.54")
        first = fingerprints_for_config(config, "SPOT", source_root=source_root)
        config.dashboard.port, config.version = 9999, "0.10.55"
        config.risk.database_path = Path("different")
        self.assertEqual(first, fingerprints_for_config(config, "SPOT", source_root=source_root))
        config.ai.enabled = False
        self.assertNotEqual(first["ai_review"], fingerprints_for_config(config, "SPOT", source_root=source_root)["ai_review"])
        config.risk.threshold = 2
        self.assertNotEqual(first["configuration"], fingerprints_for_config(config, "SPOT", source_root=source_root)["configuration"])
        (source_root/"strategy.py").write_text("x=2\n", encoding="utf-8")
        self.assertNotEqual(first["source"], fingerprints_for_config(config, "SPOT", source_root=source_root)["source"])

    def test_missing_financial_source_manifest_is_never_silently_ignored(self):
        with self.assertRaises(FileNotFoundError):
            fingerprints_for_config(object(), "SPOT", source_root=Path(self.temp.name))

    def test_named_observer_bootstrap_changes_preserve_financial_engine_fingerprint(self):
        base = '''from .strategy import SwingStrategy
class TradingEngine:
    def __init__(self, config):
        self.config = config
    def cycle(self):
        return self.config.risk.limit
    def _run_supervised_loop(self):
        self.cycle()
    def _create_market_pulse(self):
        return 1
    def run_forever(self):
        self._run_supervised_loop()
'''
        changed = base.replace('return 1', 'return 99').replace('self._run_supervised_loop()\n', 'self._create_market_pulse()\n        self._run_supervised_loop()\n')
        self.assertEqual(semantic_engine_digest(base), semantic_engine_digest('import os\n'+changed))
        guarded = base.replace('self.config = config', 'if config.bot.mode == "live":\n            raise RuntimeError("LIVE_RUNTIME_ADAPTER_NOT_COMMISSIONED")\n        self.config = config')
        self.assertEqual(semantic_engine_digest(base), semantic_engine_digest(guarded))
        self.assertNotEqual(semantic_engine_digest(base), semantic_engine_digest(guarded.replace('RuntimeError(', 'ValueError(')))
        self.assertNotEqual(semantic_engine_digest(base), semantic_engine_digest(base.replace('return self.config.risk.limit', 'return self.config.risk.limit*2')))
        self.assertNotEqual(semantic_engine_digest(base), semantic_engine_digest(base.replace('self.cycle()', 'self.cycle(); self.cycle()')))
        self.assertNotEqual(semantic_engine_digest(base), semantic_engine_digest('from .risk import approval\n'+base))

    def test_registration_is_prospective_and_closed_supported_scope(self):
        reg = self.register(START+30)
        self.assertIn("starts_at", reg)
        with self.assertRaises(ValueError):
            self.store.observe(reg, evidence(), now=START)
        with self.assertRaises(ValueError):
            self.store.register("SPOT", "LIVE", FINGERPRINTS, now=START)
        with self.assertRaises(ValueError):
            self.store.register("SPOT", "SPOT_TESTNET", {}, now=START)

    def test_receipts_do_not_claim_complete_financial_history_from_local_snapshot(self):
        reg = self.register()
        for slot in range(289):
            self.store.observe(reg, evidence(), now=START+slot*300)
        scope = self.store.snapshot(now=START+86460)["scopes"][0]
        self.assertEqual(scope["operational_coverage_days"], 1)
        self.assertEqual(scope["operational_valid_receipts"], 288)
        self.assertEqual(scope["valid_receipts"], 0)
        self.assertIsNone(scope["qualified_days"])

    def test_explicit_complete_receipts_reuse_pure_forward_contract(self):
        reg = self.register()
        for slot in range(289):
            self.store.observe(reg, evidence(complete=True), now=START+slot*300)
        value = self.store.snapshot(now=START+86460)
        self.assertEqual(value["scopes"][0]["qualified_days"], 1)
        self.assertFalse(value["ready_for_live"])

    def test_gap_and_late_backfill_are_not_invented(self):
        reg = self.register()
        for offset in (0, 300, 1500, 1800):
            self.store.observe(reg, evidence(), now=START+offset)
        scope = self.store.snapshot(now=START+1861)["scopes"][0]
        self.assertEqual(scope["operational_valid_receipts"], 2)
        self.assertEqual(scope["operational_missing_windows"], 4)
        with self.assertRaises(ValueError):
            self.store.observe(reg, evidence(), now=START+600)

    def test_incomplete_start_endpoint_does_not_qualify_next_window(self):
        reg = self.register()
        self.store.observe(reg, evidence(source=False), now=START)
        self.store.observe(reg, evidence(), now=START+300)
        self.assertEqual(self.store.snapshot(now=START+361)["scopes"][0]["operational_valid_receipts"], 0)

    def test_exact_capture_replay_is_idempotent_and_conflict_rejected(self):
        reg = self.register()
        first = self.store.observe(reg, evidence(), now=START, identity="same")
        self.assertEqual(first, self.store.observe(reg, evidence(), now=START, identity="same"))
        with self.assertRaisesRegex(ValueError, "EVIDENCE_ID_CONFLICT"):
            self.store.observe(reg, evidence(source=False), now=START, identity="same")
        self.assertEqual(self.store.verify_chain()["records"], 2)

    def test_proposal_replay_does_not_refresh_observation_time(self):
        reg = self.register()
        self.store.observe(reg, evidence(), now=START+1, identity="proposal:one", kind="PROPOSAL")
        self.store.observe(reg, evidence(), now=START+100, identity="proposal:one", kind="PROPOSAL")
        self.assertEqual(self.store.snapshot(now=START+100)["head"]["at"], START+1)

    def test_scope_never_combines_testnet_demo_or_shadow(self):
        for engine, environment in (("SPOT", "SPOT_TESTNET"), ("FUTURES", "FUTURES_DEMO"),
                                    ("AI_MARKET_PULSE", "SHADOW"), ("QUANT_ARBITRAGE", "SHADOW")):
            self.store.register(engine, environment, FINGERPRINTS, now=START)
        value = self.store.snapshot(now=START)
        self.assertEqual(len(value["scopes"]), 4)
        self.assertNotIn("total_capital", value)

    def test_retained_anchor_and_mutation_detection(self):
        reg = self.register()
        self.store.observe(reg, evidence(), now=START)
        anchor = self.store.verify_chain()["anchor"]
        self.assertEqual(self.store.verify_chain(expected_anchor=anchor)["state"], "VALID_LOCAL_CHAIN")
        self.assertEqual(self.store.verify_chain(expected_anchor="f"*64)["state"], "INVALID")
        with closing(sqlite3.connect(self.path)) as db, db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE observations SET at=1")
            db.execute("DROP TRIGGER observations_no_update")
            db.execute("UPDATE observations SET at=at+1 WHERE sequence=2")
        self.assertEqual(self.store.verify_chain()["reason"], "CHAIN_CONTENT_MISMATCH")

    def test_retained_prefix_anchor_survives_legitimate_append(self):
        reg = self.register()
        anchor = self.store.verify_chain()["anchor"]
        self.store.observe(reg, evidence(), now=START)
        verified = self.store.verify_chain(expected_anchor=anchor)
        self.assertEqual(verified["state"], "VALID_LOCAL_CHAIN")
        self.assertNotEqual(verified["anchor"], anchor)

    def test_cached_streaming_summary_matches_replay_with_original_pure_contract(self):
        import json
        reg = self.register()
        for offset in (0, 300, 600, 1800, 2100):
            self.store.observe(reg, evidence(complete=True), now=START+offset)
        with closing(self.store.connect(True)) as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM receipts ORDER BY slot")]
        replay = evaluate_forward_cohort(reg, rows, now=iso(START+2161), expected_digest=register_forward_cohort(reg).digest)
        cached = self.store.snapshot(now=START+2161)["scopes"][0]
        for key in ("qualified_days", "valid_receipts", "invalid_receipts", "missing_windows", "reason_codes", "state"):
            self.assertEqual(cached[key], replay[key], key)

    def test_every_writer_connection_receives_the_configured_page_limit(self):
        bounded = OperationalCohortStore(self.path, max_bytes=65536)
        with closing(bounded.connect()) as one:
            self.assertEqual(one.execute("PRAGMA max_page_count").fetchone()[0], 16)
        with closing(bounded.connect()) as two:
            self.assertEqual(two.execute("PRAGMA max_page_count").fetchone()[0], 16)

    def test_clock_regression_does_not_show_future_coverage(self):
        reg = self.register()
        self.store.observe(reg, evidence(), now=START+300)
        value = self.store.snapshot(now=START+100)
        self.assertEqual(value["state"], "CLOCK_REGRESSION")
        self.assertEqual(value["scopes"], [])

    def test_retention_does_not_delete_prior_evidence(self):
        bounded = OperationalCohortStore(self.path, max_records=1)
        reg = bounded.register("SPOT", "SPOT_TESTNET", FINGERPRINTS, now=START)
        with self.assertRaisesRegex(ValueError, "RETENTION_FULL"):
            bounded.observe(reg, evidence(), now=START)
        self.assertEqual(bounded.verify_chain()["records"], 1)

    def test_future_registration_and_clock_regression_rejected(self):
        self.register()
        with self.assertRaisesRegex(ValueError, "CLOCK_REGRESSION"):
            self.register(START-1)


if __name__ == "__main__":
    unittest.main()
