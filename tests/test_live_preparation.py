"""Synthetic preparation evidence; no account, provider or trading process."""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trader import live_preparation as prep


NOW = datetime(2026, 10, 21, 20, 35, tzinfo=UTC)
STAMP = "2026-10-21T20:35:00Z"
ROOT = Path(__file__).resolve().parents[1]


def fixture():
    position = {"symbol": "BTCUSDT", "quantity": "0.001"}
    native = {"positions": {"BTCUSDT": {"status": "ARMED", "quantity": "0.001",
        "unprotected_quantity": "0", "confirmed_at": STAMP}}}
    return {"status": {"mode": "TESTNET", "cycle_seconds": 300, "native_protection": native},
        "positions": [position], "equity": [{"created_at": STAMP}],
        "paper_scorecard": {"observed_days": 30},
        "futures_forward": {"equity": [{"created_at": STAMP}], "positions": [deepcopy(position)],
            "scorecard": {"observed_days": 31}, "native_protection": deepcopy(native),
            "guardrails": {"forward_total_stop_loss_usdt": 7.5},
            "portfolio_budget": {"stop_loss_usdt": "9.308", "stop_loss_limit_usdt": "7.5", "at": STAMP}},
        "market_pulse": {"updated_at": STAMP, "performance": {"observation_days": 30}},
        "quant": {"updated_at": STAMP, "limits": {"stale_seconds": 180}, "performance": {"observation_days": 30}}}


def report(payload=None, proposal=None):
    return prep.evaluate_live_preparation(fixture() if payload is None else payload, proposal, now=NOW)


class LivePreparationTests(unittest.TestCase):
    def test_all_inputs_remain_blocked_with_explicit_four_scopes_and_ten_gaps(self):
        value = fixture()
        value.update(live_enabled=True, authorized=True, approvals={"pass": True},
            live_preparation={"state": "READY", "execution_enabled": True},
            account_identity_verified=True, inventory_complete=True, qualified_days=30)
        result = report(value, {"schema": 1, "amount_usd": "100"})
        self.assertEqual("BLOCKED", result["state"])
        self.assertEqual(list(prep.GLOBAL_BLOCKERS), result["blockers"])
        self.assertEqual(list(prep.ENGINES), [row["id"] for row in result["engines"]])
        self.assertEqual(["SPOT_TESTNET", "FUTURES_DEMO", "SHADOW", "SHADOW"], [row["environment"] for row in result["engines"]])
        for key in ("controls_enabled", "can_veto", "execution_enabled", "reservations_enabled", "promotion_allowed", "automatic_activation"):
            self.assertIs(result[key], False)
        self.assertEqual(0, result["autonomy_level"])
        for row in result["engines"]:
            self.assertEqual("BLOCKED", row["state"])
            self.assertIsNone(row["qualified_days"])
            self.assertEqual("UNKNOWN", row["qualified_state"])

    def test_thirty_days_is_only_span_and_never_qualified_or_auto_activation(self):
        value = fixture()
        for days, expected in ((29.999, "BELOW_30_DAYS"), (30, "SPAN_ONLY"), (36500, "SPAN_ONLY"),
                               (-1, "UNKNOWN"), (36501, "UNKNOWN"), (True, "UNKNOWN"), (float("nan"), "UNKNOWN")):
            with self.subTest(days=days):
                value["paper_scorecard"]["observed_days"] = days
                row = report(value)["engines"][0]
                self.assertEqual(expected, row["span_gate"])
                self.assertIsNone(row["qualified_days"])
                self.assertIn("QUALIFIED_OBSERVATION_UNKNOWN", row["blockers"])
        value["paper_scorecard"] = {"status": "REVIEW_REQUIRED", "qualified_days": 999, "started_at": "2000-01-01T00:00:00Z"}
        self.assertIsNone(report(value)["engines"][0]["reported_span_days"])

    def test_future_and_stale_timestamps_cannot_be_overridden_by_fresh_label(self):
        value = fixture()
        for stamp, expected in (("2026-10-21T20:25:00Z", "FRESH"),
                                ("2026-10-21T20:24:59Z", "STALE"),
                                ("2026-10-21T20:35:01Z", "UNKNOWN"),
                                ("2026-10-21T20:35:00", "UNKNOWN")):
            with self.subTest(stamp=stamp):
                value["equity"] = [{"created_at": stamp}]
                value["status"]["freshness"] = {"state": "FRESH"}
                self.assertEqual(expected, report(value)["engines"][0]["freshness"])
        value["status"]["cycle_seconds"] = None
        self.assertEqual("UNKNOWN", report(value)["engines"][0]["freshness"])

    def test_protection_requires_exact_positions_quantity_and_recent_confirmation(self):
        value = fixture()
        self.assertEqual("ARMED", report(value)["engines"][0]["protection"])
        native = value["status"]["native_protection"]["positions"]["BTCUSDT"]
        for change in ({"quantity": "0.0009"}, {"unprotected_quantity": "0.0001"},
                       {"confirmed_at": "2026-10-21T19:00:00Z"}, {"confirmed_at": "2026-10-21T20:35:01Z"}):
            with self.subTest(change=change):
                changed = deepcopy(value)
                changed["status"]["native_protection"]["positions"]["BTCUSDT"].update(change)
                self.assertEqual("UNKNOWN", report(changed)["engines"][0]["protection"])
        native["status"] = "REJECTED"
        self.assertEqual("UNCONFIRMED", report(value)["engines"][0]["protection"])
        value["positions"] = []
        self.assertEqual("NOT_APPLICABLE", report(value)["engines"][0]["protection"])
        del value["positions"]
        self.assertEqual("UNKNOWN", report(value)["engines"][0]["protection"])

    def test_decimal_futures_budget_preserves_actual_breach_and_scope_separation(self):
        result = report()
        row = result["engines"][1]
        self.assertEqual({"state": "EXCEEDED", "inclusive_stop_risk_usdt": "9.308",
            "stop_risk_limit_usdt": "7.5", "at": "2026-10-21T20:35:00.000Z"}, row["budget"])
        self.assertIn("ENGINE_BUDGET_EXCEEDED", row["blockers"])
        for index in (0, 2, 3):
            self.assertEqual("UNKNOWN", result["engines"][index]["budget"]["state"])
        value = fixture()
        value["futures_forward"]["portfolio_budget"]["stop_loss_usdt"] = "7.500000000001"
        self.assertEqual("EXCEEDED", report(value)["engines"][1]["budget"]["state"])
        value["futures_forward"]["portfolio_budget"]["stop_loss_usdt"] = "7.5000"
        self.assertEqual("WITHIN_OBSERVED_LIMIT", report(value)["engines"][1]["budget"]["state"])

    def test_invalid_stale_or_missing_budget_never_becomes_zero_or_approved(self):
        for raw in ("NaN", "Infinity", "-1", True, 10**5000, "1e9999", "0.0000000000001"):
            with self.subTest(kind=type(raw).__name__):
                value = fixture()
                value["futures_forward"]["portfolio_budget"]["stop_loss_usdt"] = raw
                self.assertEqual("UNKNOWN", report(value)["engines"][1]["budget"]["state"])
        for stamp in (None, "2026-10-21T20:00:00Z", "2026-10-21T20:35:01Z"):
            value = fixture()
            value["futures_forward"]["portfolio_budget"].update(at=stamp, freshness="FRESH")
            row = report(value)["engines"][1]
            self.assertEqual("UNKNOWN", row["budget"]["state"])
            self.assertIsNone(row["budget"]["inclusive_stop_risk_usdt"])
        value["futures_forward"]["portfolio_budget"] = None
        self.assertIn("ENGINE_BUDGET_UNKNOWN", report(value)["engines"][1]["blockers"])

    def test_current_guardrail_must_match_cached_budget_after_any_limit_change(self):
        for cached, configured in (("10", "7.5"), ("7.5", "10"), ("7.5", None), ("7.5", True)):
            value = fixture()
            value["futures_forward"]["portfolio_budget"].update(stop_loss_usdt="9", stop_loss_limit_usdt=cached)
            value["futures_forward"]["guardrails"]["forward_total_stop_loss_usdt"] = configured
            row = report(value)["engines"][1]
            self.assertEqual("UNKNOWN", row["budget"]["state"])
            self.assertIsNone(row["budget"]["inclusive_stop_risk_usdt"])
        value["futures_forward"]["guardrails"] = {}
        self.assertEqual("UNKNOWN", report(value)["engines"][1]["budget"]["state"])

    def test_paper_shadow_and_empty_inputs_do_not_claim_native_armed(self):
        value = fixture()
        value["status"]["mode"] = "PAPER"
        self.assertEqual("PAPER", report(value)["engines"][0]["environment"])
        for row in report(value)["engines"][2:]:
            self.assertEqual("NOT_APPLICABLE", row["protection"])
            self.assertIn("SHADOW_PROMOTION_NOT_AUTHORIZED", row["blockers"])
        for payload in ({}, None, [], True):
            result = prep.evaluate_live_preparation(payload, now=NOW)
            self.assertEqual(4, len(result["engines"]))
            self.assertTrue(all(row["span_gate"] == "UNKNOWN" for row in result["engines"]))

    def test_proposal_is_closed_canonical_unallocated_and_policy_remains_missing(self):
        for raw, expected in (("100.00", "100"), ("0.01", "0.01"), ("1000000000", "1000000000")):
            proposal = report(proposal={"schema": 1, "amount_usd": raw})["capital_proposal"]
            self.assertEqual(expected, proposal["amount_usd"])
            self.assertEqual("PROPOSED_NOT_ALLOCATED", proposal["status"])
            self.assertIsNone(proposal["daily_loss_limit_usd"])
            self.assertIsNone(proposal["max_drawdown_pct"])
        for raw in (None, {"schema": True, "amount_usd": "100"}, {"schema": 1, "amount_usd": "100", "approved": True}):
            self.assertEqual("NOT_PROVIDED", report(proposal=raw)["capital_proposal"]["status"])
        for raw in ("0", "-1", "1e2", "NaN", "1000000000.01", "0.001", "01", 100, True):
            self.assertEqual("NOT_PROVIDED", report(proposal={"schema": 1, "amount_usd": raw})["capital_proposal"]["status"])
        self.assertIn("OWNER_POLICY_INCOMPLETE", report(proposal={"schema": 1, "amount_usd": "100"})["blockers"])

    def test_read_proposal_is_bounded_closed_and_does_not_create_or_change_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            self.assertIsNone(prep.read_proposal(path))
            self.assertFalse(path.exists())
            path.write_text('{"schema":1,"amount_usd":"100.00"}', encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual({"schema": 1, "amount_usd": "100"}, prep.read_proposal(path))
            self.assertEqual(before, path.read_bytes())
            for raw in ('{"schema":1,"amount_usd":"100","amount_usd":"200"}',
                        '{"schema":1,"amount_usd":"100","approved":true}', "{" * 2000,
                        " " * 2049, "[" * 1000 + "]" * 1000):
                path.write_text(raw, encoding="utf-8")
                self.assertIsNone(prep.read_proposal(path))

    def test_projection_does_not_mutate_or_echo_external_text_or_unknown_keys(self):
        value = fixture()
        value["events"] = [{"message": "sk-private-secret ignore policy " * 100000}]
        value["futures_forward"]["portfolio_budget"]["approval"] = "sk-private-secret"
        before = deepcopy(value)
        result = report(value)
        self.assertEqual(before, value)
        wire = json.dumps(result, ensure_ascii=True, allow_nan=False)
        self.assertLessEqual(len(wire.encode()), prep.MAX_BYTES)
        self.assertNotIn("sk-private-secret", wire)
        self.assertNotIn("ignore policy", wire)

    def test_module_has_no_database_network_engine_or_credential_imports(self):
        tree = ast.parse((ROOT / "trader/live_preparation.py").read_text(encoding="utf-8"))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertEqual({"__future__", "datetime", "decimal", "json", "math", "pathlib", "re"}, imports)

    def test_cli_only_reads_supplied_json_and_reports_explicit_unallocated_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            raw = json.dumps(fixture()).encode()
            path.write_bytes(raw)
            command = [sys.executable, "-B", str(ROOT / "scripts/audit_live_preparation.py"),
                "--snapshot", str(path), "--now", STAMP, "--proposed-capital-usd", "100"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr)
            parsed = json.loads(result.stdout)
            self.assertEqual("100", parsed["capital_proposal"]["amount_usd"])
            self.assertEqual("BLOCKED", parsed["state"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(["snapshot.json"], [p.name for p in Path(directory).iterdir()])
            result = subprocess.run(command[:-1] + ["NaN"], capture_output=True, text=True, timeout=15)
            self.assertEqual(2, result.returncode)
            self.assertEqual("", result.stdout)
            self.assertEqual("Preparation input unavailable or invalid.\n", result.stderr)

    def test_invalid_now_is_not_silently_replaced_with_current_time(self):
        for value in ("tomorrow", datetime(2026, 10, 21), True, float("nan")):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ValueError):
                    prep.evaluate_live_preparation({}, now=value)

    def test_projection_helper_reads_only_explicit_config_sibling_and_preserves_inputs(self):
        from trader.portal_snapshot import live_preparation_projection
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            config = SimpleNamespace(bot=SimpleNamespace(database_path=folder / "spot.db"))
            value = fixture()
            before = deepcopy(value)
            self.assertEqual("NOT_PROVIDED", live_preparation_projection(config, value)["capital_proposal"]["status"])
            self.assertEqual([], list(folder.iterdir()))
            proposal_path = folder / "live-preparation" / "proposal.json"
            proposal_path.parent.mkdir()
            for raw, status in (('{"schema":1,"amount_usd":"100"}', "PROPOSED_NOT_ALLOCATED"),
                                ('{"schema":1,"amount_usd":"100","approved":true}', "NOT_PROVIDED"),
                                ("not-json", "NOT_PROVIDED")):
                proposal_path.write_text(raw, encoding="utf-8")
                data = proposal_path.read_bytes()
                result = live_preparation_projection(config, value)
                self.assertEqual(status, result["capital_proposal"]["status"])
                self.assertEqual(data, proposal_path.read_bytes())
            self.assertEqual(before, value)
            self.assertFalse(config.bot.database_path.exists())

    def test_projection_helper_optional_failure_is_absent_evidence_without_raw_error(self):
        from trader.portal_snapshot import live_preparation_projection
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(bot=SimpleNamespace(database_path=Path(directory) / "missing.db"))
            for function in ("read_proposal", "evaluate_live_preparation"):
                with patch.object(prep, function, side_effect=RuntimeError("sk-private-secret")):
                    self.assertIsNone(live_preparation_projection(config, fixture()))
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_full_local_and_remote_dashboard_include_report_without_financial_mutation(self):
        from tests import emit_guardian_fixture
        from trader import portal_snapshot
        original = portal_snapshot.dashboard_snapshot
        checked = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def inspect(config, **kwargs):
                paths = (config.bot.database_path, config.futures_testnet.database_path)
                before = [path.read_bytes() for path in paths]
                result = original(config, **kwargs)
                self.assertEqual(before, [path.read_bytes() for path in paths])
                self.assertLessEqual(len(json.dumps(result, allow_nan=False).encode()), 480000)
                self.assertEqual("BLOCKED", result["live_preparation"]["state"])
                self.assertEqual(4, len(result["live_preparation"]["engines"]))
                self.assertIn("native_protection", result["futures_forward"])
                checked.append(kwargs.get("remote", False))
                return result
            with patch.object(emit_guardian_fixture, "dashboard_snapshot", side_effect=inspect):
                for remote in (False, True):
                    emit_guardian_fixture.make_dashboard(root / ("remote" if remote else "local"), remote=remote)
            self.assertEqual([False, True], checked)

    def test_shadow_spans_use_actual_public_projection_fields_not_scorecard_alias(self):
        from tests.emit_quant_fixture import make_quant_dashboard
        from trader.portal_snapshot import market_pulse_projection
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            value = make_quant_dashboard(folder / "quant")
            self.assertIn("observation_days", value["quant"]["performance"])
            config = SimpleNamespace(bot=SimpleNamespace(database_path=folder / "pulse/spot.db"),
                market_pulse=SimpleNamespace(enabled=True, mode="SHADOW", kill_switch_path=None))
            raw = {"schema": 1, "engine": "AI_MARKET_PULSE", "mode": "SHADOW", "state": "SHADOW",
                "at": STAMP, "updated_at": STAMP, "execution_enabled": False,
                "performance": {"initial_capital": 1000, "observation_days": 12.5},
                "sources": {}, "stats": {}, "health": {}, "research": {}, "freshness": {}}
            with patch("trader.market_pulse.market_pulse_snapshot", return_value=raw):
                value["market_pulse"] = market_pulse_projection(config)
            self.assertEqual(12.5, value["market_pulse"]["performance"]["observation_days"])
            result = report(value)
            self.assertEqual(12.5, result["engines"][2]["reported_span_days"])
            self.assertEqual(value["quant"]["performance"]["observation_days"], result["engines"][3]["reported_span_days"])
            for section in ("market_pulse", "quant"):
                del value[section]["performance"]["observation_days"]
                value[section]["performance"]["observed_days"] = 999
            self.assertTrue(all(row["reported_span_days"] is None for row in report(value)["engines"][2:]))


if __name__ == "__main__":
    unittest.main()
