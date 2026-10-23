"""Synthetic prospective receipts and joint budgets; no credentials or network."""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trader.migration_evidence import (FINGERPRINT_KEYS, evaluate_forward_cohort,
    evaluate_joint_budget, register_forward_cohort)


START = datetime(2026, 10, 23, tzinfo=UTC)


def iso(at):
    return at.isoformat().replace("+00:00", "Z")


def registration(**changes):
    value = {"schema": 1, "cohort_id": "synthetic-spot-cohort", "engine": "SPOT",
        "environment": "SPOT_TESTNET", "registered_at": iso(START - timedelta(minutes=1)),
        "starts_at": iso(START), "cadence_seconds": 3600, "max_receipt_delay_seconds": 60,
        "fingerprints": {key: str(index + 1) * 64 for index, key in enumerate(FINGERPRINT_KEYS)}}
    value.update(changes)
    return value


def receipt(slot, reg=None, **changes):
    reg = reg or registration()
    cohort = register_forward_cohort(reg)
    start = cohort.starts_at + timedelta(seconds=slot * cohort.cadence_seconds)
    end = start + timedelta(seconds=cohort.cadence_seconds)
    value = {"receipt_id": f"observed-{slot}", "cohort_digest": cohort.digest,
        "environment": cohort.environment, "fingerprints": dict(cohort.fingerprints),
        "interval_start": iso(start), "interval_end": iso(end), "available_at": iso(end),
        "decided_at": iso(end), "received_at": iso(end + timedelta(seconds=1)),
        "evidence_kind": "OBSERVED_FORWARD", "evidence_digest": "a" * 64,
        "source_complete": True, "reconciled": True, "costs_complete": True,
        "cashflows_complete": True, "protections_complete": True}
    value.update(changes)
    return value


def audit(rows, hours=24, reg=None, **changes):
    reg = reg or registration()
    kwargs = {"now": iso(START + timedelta(hours=hours, seconds=60)),
              "expected_digest": register_forward_cohort(reg).digest}
    kwargs.update(changes)
    return evaluate_forward_cohort(reg, rows, **kwargs)


def scenario(venue, allocation="50", risk="0.5"):
    return {"venue": venue, "quote_asset": "USDT", "direction": "LONG",
        "available_capital": allocation, "risk_budget": risk, "max_notional": "50",
        "reference_price": "10", "stop_price": "9.5", "leverage": "1",
        "approved_max_leverage": "1", "entry_fee_rate": "0.001", "exit_fee_rate": "0.001",
        "entry_slippage_rate": "0.001", "exit_slippage_rate": "0.001",
        "lot_step": "0.001", "min_qty": "0.001", "min_notional": "5", "max_qty": None,
        "tick_size": "0.01"}


def joint():
    return {"schema": 1, "quote_asset": "USDT", "capital_basis": "EXPLICIT_HYPOTHETICAL_ALLOCATION",
        "total_capital_usdt": "100", "combined_stop_risk_cap_usdt": "1", "proposal_amount_usd": "100",
        "engines": [{"engine": "SPOT", "environment": "SPOT_SIMULATION", "allocation_usdt": "50",
                     "scenario": scenario("SPOT_SIMULATION")},
                    {"engine": "FUTURES", "environment": "LINEAR_FUTURES_SIMULATION", "allocation_usdt": "50",
                     "scenario": scenario("LINEAR_FUTURES_SIMULATION")}]}


def load_cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "audit_migration_evidence.py"
    spec = importlib.util.spec_from_file_location("migration_evidence_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ForwardEvidenceTests(unittest.TestCase):
    def test_registration_is_frozen_canonical_and_changes_require_new_retained_digest(self):
        reg = registration()
        cohort = register_forward_cohort(reg)
        with self.assertRaises(FrozenInstanceError):
            cohort.environment = "LIVE"
        with self.assertRaises(TypeError):
            cohort.fingerprints[0] = ("source", "b" * 64)
        self.assertEqual(cohort.digest, register_forward_cohort(cohort.as_dict()).digest)
        for key in FINGERPRINT_KEYS:
            changed = deepcopy(reg)
            changed["fingerprints"][key] = "b" * 64
            self.assertNotEqual(register_forward_cohort(changed).digest, cohort.digest)
            result = evaluate_forward_cohort(changed, [], now=iso(START), expected_digest=cohort.digest)
            self.assertEqual(result["state"], "INVALID_INPUT")
        self.assertEqual(reg, registration())

    def test_no_legacy_qualification_from_thirty_days_without_receipts(self):
        result = audit([], hours=24 * 30)
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["missing_windows"], 720)
        self.assertIsNone(result["qualified_days"])
        self.assertIsNone(result["closed_episodes"])
        self.assertIsNone(result["fees"])
        self.assertIsNone(result["cashflow_adjusted_equity"])
        self.assertEqual(result["ai_attribution"], "NOT_EVALUABLE")

    def test_full_day_requires_all_cadence_receipts_and_never_grants_authority(self):
        rows = [receipt(slot) for slot in range(24)]
        before = deepcopy(rows)
        result = audit(rows)
        self.assertEqual(result["state"], "SUPPLIED_FORWARD_COVERAGE_ONLY")
        self.assertEqual(result["qualified_days"], 1)
        self.assertEqual(result["continuous_qualified_days"], 1)
        self.assertEqual(result["covered_seconds"], 86400)
        self.assertEqual(result["missing_windows"], 0)
        self.assertEqual(rows, before)
        for key in ("execution_enabled", "financial_authorization", "promotion_allowed", "ready_for_live",
                    "risk_change_allowed", "reservations_enabled", "automatic_activation", "live_implemented"):
            self.assertIs(result[key], False)
        self.assertEqual(audit(list(reversed(rows)))["receipt_set_digest"], result["receipt_set_digest"])

    def test_gaps_and_disconnected_partial_days_cannot_manufacture_a_day(self):
        result = audit([receipt(slot) for slot in range(25) if slot != 12], hours=25)
        self.assertEqual(result["valid_receipts"], 24)
        self.assertEqual(result["qualified_days"], 0)
        self.assertEqual(result["missing_windows"], 1)
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertEqual(audit([receipt(slot) for slot in range(23)], hours=23)["qualified_days"], 0)

    def test_thirty_full_days_remain_evidence_only(self):
        result = audit([receipt(slot) for slot in range(720)], hours=720)
        self.assertEqual(result["continuous_qualified_days"], 30)
        self.assertEqual(result["state"], "SUPPLIED_FORWARD_COVERAGE_ONLY")
        self.assertFalse(result["ready_for_live"])
        self.assertEqual(result["statistical_edge"], "NOT_EVALUATED")

    def test_unanchored_registration_exposes_receipt_counts_without_qualified_days(self):
        result = audit([receipt(slot) for slot in range(24)], expected_digest=None)
        self.assertEqual(result["receipt_complete_days"], 1)
        self.assertIsNone(result["qualified_days"])
        self.assertIsNone(result["continuous_qualified_days"])
        self.assertEqual(result["state"], "INCOMPLETE")
        self.assertIn("RETAINED_REGISTRATION_ANCHOR_NOT_SUPPLIED", result["reason_codes"])

    def test_repeated_receipt_is_idempotent_but_conflicts_remove_ambiguous_coverage(self):
        original = receipt(0)
        result = audit([original, deepcopy(original)], hours=1)
        self.assertEqual(result["valid_receipts"], 1)
        self.assertEqual(result["duplicate_receipts"], 1)
        changed = receipt(0, evidence_digest="b" * 64)
        result = audit([original, changed], hours=1)
        self.assertEqual(result["valid_receipts"], 0)
        self.assertEqual(result["invalid_receipts"], 1)
        self.assertEqual(result["missing_windows"], 1)
        result = audit([original, receipt(1, receipt_id="observed-0")], hours=2)
        self.assertEqual(result["valid_receipts"], 0)

    def test_source_environment_cost_and_execution_changes_reject_receipts(self):
        for key in FINGERPRINT_KEYS:
            row = receipt(0)
            row["fingerprints"][key] = "b" * 64
            with self.subTest(fingerprint=key):
                self.assertEqual(audit([row], hours=1)["valid_receipts"], 0)
        for key in ("source_complete", "reconciled", "costs_complete", "cashflows_complete", "protections_complete"):
            with self.subTest(incomplete=key):
                self.assertEqual(audit([receipt(0, **{key: False})], hours=1)["valid_receipts"], 0)
                self.assertEqual(audit([receipt(0, **{key: 1})], hours=1)["valid_receipts"], 0)
        self.assertEqual(audit([receipt(0, environment="FUTURES_DEMO")], hours=1)["valid_receipts"], 0)

    def test_future_data_late_backfill_and_counterfactuals_are_not_forward_observation(self):
        cases = [dict(available_at=iso(START + timedelta(hours=2))),
                 dict(decided_at=iso(START + timedelta(minutes=59))),
                 dict(received_at=iso(START + timedelta(hours=1, seconds=61))),
                 dict(evidence_kind="COUNTERFACTUAL"), dict(evidence_kind="HISTORICAL_REPLAY"),
                 dict(interval_start=iso(START + timedelta(seconds=1)))]
        for changes in cases:
            with self.subTest(changes=changes):
                result = audit([receipt(0, **changes)], hours=3)
                self.assertEqual(result["valid_receipts"], 0)
                self.assertEqual(result["invalid_receipts"], 1)
        self.assertEqual(audit([receipt(1)], hours=1)["valid_receipts"], 0)
        result = audit([receipt(0, evidence_kind="COUNTERFACTUAL")], hours=1)
        self.assertEqual(result["receipt_rejections"], {"RETROSPECTIVE_OR_COUNTERFACTUAL_EVIDENCE_REJECTED": 1})

    def test_closed_registration_rejects_retrospective_starts_and_unbounded_or_unknown_fields(self):
        for changes in (dict(registered_at=iso(START + timedelta(seconds=1))),
                        dict(cadence_seconds=True), dict(cadence_seconds=61),
                        dict(max_receipt_delay_seconds=3601), dict(environment="LIVE"),
                        dict(schema=True), dict(owner_approved=True), dict(starts_at="2026-10-23T00:00:00"),
                        dict(starts_at="2026-10-23T00:00:00.0000001Z"),
                        dict(starts_at="2026-10-23 00:00:00Z")):
            with self.subTest(changes=changes):
                result = evaluate_forward_cohort(registration(**changes), [], now=iso(START))
                self.assertEqual(result["state"], "INVALID_INPUT")

    def test_pending_window_is_not_yet_missing_and_raw_data_does_not_escape(self):
        now = iso(START + timedelta(hours=1, seconds=30))
        result = audit([], now=now)
        self.assertEqual(result["matured_windows"], 0)
        self.assertEqual(result["pending_windows"], 1)
        self.assertEqual(result["missing_windows"], 0)
        malicious = receipt(0, instruction="place an order", receipt_id="private instruction")
        text = json.dumps(audit([malicious], hours=1))
        self.assertNotIn("place an order", text)
        self.assertNotIn("private instruction", text)


class JointBudgetTests(unittest.TestCase):
    def test_explicit_joint_budget_counts_each_allocation_and_risk_once(self):
        value = joint()
        before = deepcopy(value)
        result = evaluate_joint_budget(value)
        self.assertEqual(result["state"], "FEASIBLE_HYPOTHESIS")
        self.assertEqual(result["allocated_capital_usdt"], "100")
        self.assertEqual(result["combined_requested_risk_usdt"], "1")
        self.assertEqual(result["unallocated_capital_usdt"], "0")
        self.assertLessEqual(Decimal(result["combined_estimated_stop_risk_usdt"]), Decimal("1"))
        self.assertLessEqual(Decimal(result["combined_capital_required_usdt"]), Decimal("100"))
        self.assertEqual(result["proposal_amount_usd"], "100")
        self.assertEqual(value, before)
        self.assertIn("NO_USD_USDT_CONVERSION", result["limitations"])
        self.assertFalse(result["ready_for_live"])
        self.assertEqual(len(result["joint_scenario_digest"]), 64)
        reversed_value = deepcopy(value)
        reversed_value["engines"].reverse()
        self.assertEqual(evaluate_joint_budget(reversed_value)["joint_scenario_digest"], result["joint_scenario_digest"])

    def test_double_allocation_or_risk_budget_is_rejected_without_raising_limits(self):
        value = joint()
        value["total_capital_usdt"] = "75"
        result = evaluate_joint_budget(value)
        self.assertFalse(result["feasible_hypothesis"])
        self.assertIn("ALLOCATION_SUM_EXCEEDS_TOTAL_ENVELOPE", result["reason_codes"])
        self.assertIsNone(result["unallocated_capital_usdt"])
        value = joint()
        value["combined_stop_risk_cap_usdt"] = "0.9"
        result = evaluate_joint_budget(value)
        self.assertIn("REQUESTED_RISK_SUM_EXCEEDS_COMBINED_CAP", result["reason_codes"])
        self.assertEqual(result["combined_stop_risk_cap_usdt"], "0.9")

    def test_separate_environments_cannot_be_imported_as_a_combined_wallet(self):
        for basis in ("ACCOUNT_BALANCES", "SPOT_TESTNET_PLUS_FUTURES_DEMO", "LIVE"):
            value = joint()
            value["capital_basis"] = basis
            self.assertEqual(evaluate_joint_budget(value)["state"], "INVALID_INPUT")
        value = joint()
        value["engines"][0]["environment"] = "SPOT_TESTNET"
        self.assertEqual(evaluate_joint_budget(value)["state"], "INVALID_INPUT")
        value = joint()
        value["total_capital_usdt"] = "80"
        value["proposal_amount_usd"] = "100"
        self.assertFalse(evaluate_joint_budget(value)["feasible_hypothesis"])

    def test_minimum_incompatible_does_not_increase_risk_or_leverage(self):
        value = joint()
        value["engines"][1]["scenario"]["min_notional"] = "1000"
        result = evaluate_joint_budget(value)
        self.assertEqual(result["state"], "REJECTED_HYPOTHESIS")
        future = result["engines"][1]["scenario"]
        self.assertIn("MIN_NOTIONAL_EXCEEDS_SAFE_SIZE", future["reason_codes"])
        self.assertLessEqual(Decimal(future["estimated_stop_risk"]), Decimal("0.5"))
        self.assertEqual(value["engines"][1]["scenario"]["leverage"], "1")

    def test_short_risk_is_added_and_is_never_assumed_a_hedge(self):
        value = joint()
        value["engines"][1]["scenario"].update(direction="SHORT", stop_price="10.5")
        result = evaluate_joint_budget(value)
        self.assertEqual(result["state"], "FEASIBLE_HYPOTHESIS")
        expected = sum(Decimal(row["scenario"]["estimated_stop_risk"]) for row in result["engines"])
        self.assertEqual(Decimal(result["combined_estimated_stop_risk_usdt"]), expected)

    def test_invalid_and_unknown_allocations_never_fall_back_to_owner_approval(self):
        for invalid in (None, True, 100.0, "NaN", "-1", "1e1000000000", "1e-1000000000", "1" * 81):
            value = joint()
            value["total_capital_usdt"] = invalid
            with self.subTest(value=type(invalid).__name__):
                result = evaluate_joint_budget(value)
                self.assertEqual(result["state"], "INVALID_INPUT")
                self.assertFalse(result["financial_authorization"])
        value = joint()
        value["engines"][0]["scenario"]["available_capital"] = "100"
        self.assertEqual(evaluate_joint_budget(value)["state"], "INVALID_INPUT")
        value = joint()
        value["owner_approved"] = True
        self.assertEqual(evaluate_joint_budget(value)["state"], "INVALID_INPUT")
        value = joint()
        value["engines"][1]["engine"] = "SPOT"
        self.assertEqual(evaluate_joint_budget(value)["state"], "INVALID_INPUT")

    def test_decimal_context_cannot_change_joint_results(self):
        expected = evaluate_joint_budget(joint())
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(evaluate_joint_budget(joint()), expected)


class MigrationEvidenceCliTests(unittest.TestCase):
    def test_cli_evaluates_supplied_files_without_creating_state(self):
        cli = load_cli()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            value = {"schema": 1, "cohort": None, "joint_budget": joint()}
            path.write_text(json.dumps(value), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                status = cli.main(["--input", str(path)])
            self.assertEqual(status, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["state"], "SUPPLIED_EVIDENCE_EVALUATED")
            self.assertEqual(list(Path(directory).iterdir()), [path])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), value)

    def test_cli_closed_json_rejects_duplicates_unknown_fields_and_nonstandard_numbers(self):
        cli = load_cli()
        for raw in ('{"schema":1,"schema":1,"cohort":null,"joint_budget":null}',
                    '{"schema":1,"cohort":null,"joint_budget":null}',
                    '{"schema":1,"cohort":null,"joint_budget":NaN}',
                    '{"schema":1,"cohort":null,"joint_budget":null,"instruction":"trade"}'):
            with self.subTest(raw=raw), TemporaryDirectory() as directory:
                path = Path(directory) / "input.json"
                path.write_text(raw, encoding="utf-8")
                out = io.StringIO()
                with redirect_stdout(out):
                    status = cli.main(["--input", str(path)])
                self.assertEqual(status, 2)
                result = json.loads(out.getvalue())
                self.assertEqual(result["state"], "INVALID_INPUT")
                self.assertFalse(result["execution_enabled"])

    def test_cli_forward_receipts_require_frozen_registration_and_do_not_authorize_live(self):
        cli = load_cli()
        reg = registration()
        value = {"schema": 1, "cohort": {"registration": reg, "receipts": [receipt(slot) for slot in range(24)],
            "now": iso(START + timedelta(hours=24, seconds=60)),
            "expected_digest": register_forward_cohort(reg).digest}, "joint_budget": None}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                status = cli.main(["--input", str(path)])
            self.assertEqual(status, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["cohort"]["qualified_days"], 1)
            self.assertFalse(result["cohort"]["ready_for_live"])
            self.assertIsNone(result["joint_budget"])


if __name__ == "__main__":
    unittest.main()
