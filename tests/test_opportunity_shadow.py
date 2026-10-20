"""Pure opportunity observation tests: no account, database or transport."""
import ast
import copy
from decimal import Decimal, localcontext
from pathlib import Path
import unittest

from trader.opportunity_shadow import evaluate_intent
from trader.opportunity_contract import build_intent


def intent():
    return {"schema": 1, "kind": "ENTRY_INTENT", "engine": "SPOT",
            "environment": "SPOT_TESTNET", "at": 1000,
            "account_identity": "UNKNOWN", "origin_digest": "a" * 64,
            "legs": [{"symbol": "BTCUSDT", "venue": "SPOT_TESTNET",
                      "direction": "LONG", "quantity": "2", "reference_price": "100",
                      "stop_price": "95", "take_profit": "110",
                      "fee_rate": "0.001", "slippage_rate": "0.002"}],
            "capital": {"cash": "1000", "equity": "1000", "available": "1000", "at": 1000},
            "evidence": {"market_at": 1000, "received_at": 1000,
                         "known_at": 1000, "decision_at": 1000},
            "limits": {"gross_limit": "1000", "capital_limit": "1000",
                       "stop_risk_limit": "100", "max_positions": 4}}


def reservation(**changes):
    row = {"origin_digest": "b" * 64, "symbols": ["ETHUSDT"],
           "capital": "100", "gross": "100", "costs": "1", "stop_risk": "5"}
    row.update(changes)
    return row


class OpportunityShadowTests(unittest.TestCase):
    def assert_authority_unknown(self, result):
        self.assertEqual(set(result), {"state", "reason", "hypothetical_state", "gross_notional",
                         "committed_capital", "estimated_costs", "nominal_stop_risk", "stop_risk",
                         "account_identity", "real_admission"})
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["account_identity"], "UNKNOWN")
        self.assertEqual(result["real_admission"], "NOT_EVALUABLE")

    def test_complete_native_evidence_is_only_unverified_hypothesis(self):
        result = evaluate_intent(intent())
        self.assertEqual(result, {"state": "UNKNOWN", "reason": "ACCOUNT_IDENTITY_UNVERIFIED",
                         "hypothetical_state": "RESERVED_UNVERIFIED", "gross_notional": "200",
                         "committed_capital": "200", "estimated_costs": "1.2",
                         "nominal_stop_risk": "10", "stop_risk": "11.2",
                         "account_identity": "UNKNOWN", "real_admission": "NOT_EVALUABLE"})

    def test_both_legs_and_directions_are_gross_never_netted(self):
        payload = intent()
        payload.update(engine="QUANT_ARBITRAGE", environment="SHADOW")
        second = copy.deepcopy(payload["legs"][0])
        second.update(venue="FUTURES_REFERENCE", direction="SHORT", quantity="-2",
                      stop_price="106", take_profit="90", margin="50")
        payload["legs"].append(second)
        result = evaluate_intent(payload)
        self.assertEqual(result["hypothetical_state"], "RESERVED_UNVERIFIED")
        self.assertEqual(result["gross_notional"], "400")
        self.assertEqual(result["committed_capital"], "250")
        self.assertEqual(result["estimated_costs"], "2.4")
        self.assertEqual(result["nominal_stop_risk"], "22")
        self.assertEqual(result["stop_risk"], "24.4")
        self.assert_authority_unknown(result)

    def test_decimal_products_and_sums_are_exact_and_context_independent(self):
        payload = intent()
        payload["legs"][0].update(quantity="0.123456789123456789", reference_price="0.123456789123456789",
                                   stop_price="0.1", take_profit=None)
        expected = "0.015241578780673678515622620750190521"
        with localcontext() as context:
            context.prec = 3
            result = evaluate_intent(payload)
        self.assertEqual(result["gross_notional"], expected)
        self.assertEqual(result["committed_capital"], expected)
        self.assertEqual(result["estimated_costs"], "0.000091449472684042071093735724501143126")

    def test_explicit_zero_costs_are_evidence_and_missing_rates_are_unknown(self):
        payload = intent()
        payload["legs"][0].update(fee_rate="0", slippage_rate="0")
        self.assertEqual(evaluate_intent(payload)["stop_risk"], "10")
        for key in ("fee_rate", "slippage_rate"):
            with self.subTest(key=key):
                candidate = copy.deepcopy(payload)
                candidate["legs"][0].pop(key)
                result = evaluate_intent(candidate)
                self.assertEqual(result["reason"], "COST_EVIDENCE_UNKNOWN")
                self.assertIsNone(result["estimated_costs"])
                self.assertIsNone(result["stop_risk"])
                self.assertEqual(result["nominal_stop_risk"], "10")

    def test_no_float_bool_decimal_object_or_unbounded_money_is_accepted(self):
        values = (1.2, 2, True, Decimal("2"), "NaN", "Infinity", "1e2", " 2", "+2", "02",
                  "-0", "0.000000000000000000000000000000001", "9" * 33)
        for value in values:
            with self.subTest(value=value):
                payload = intent()
                payload["legs"][0]["quantity"] = value
                result = evaluate_intent(payload)
                self.assertEqual(result["hypothetical_state"], "UNKNOWN")
                self.assertEqual(result["reason"], "QUANTITY_OR_PRICE_UNKNOWN")
                self.assertIsNone(result["gross_notional"])

    def test_zero_quantity_and_nonpositive_reference_are_unknown(self):
        for key, value in (("quantity", "0"), ("reference_price", "0"), ("reference_price", "-2")):
            with self.subTest(key=key, value=value):
                payload = intent()
                payload["legs"][0][key] = value
                self.assertEqual(evaluate_intent(payload)["reason"], "QUANTITY_OR_PRICE_UNKNOWN")

    def test_stop_has_to_be_on_the_protective_side_for_each_direction(self):
        for direction, stop in (("LONG", "100"), ("LONG", "101"), ("SHORT", "100"),
                                ("SHORT", "95"), ("LONG", None), ("LONG", "0")):
            with self.subTest(direction=direction, stop=stop):
                payload = intent()
                payload["legs"][0].update(direction=direction, stop_price=stop, take_profit=None)
                result = evaluate_intent(payload)
                self.assertEqual(result["reason"], "STOP_EVIDENCE_UNKNOWN")
                self.assertIsNone(result["nominal_stop_risk"])
                self.assertIsNone(result["stop_risk"])

    def test_short_uses_positive_stop_distance(self):
        payload = intent()
        payload["legs"][0].update(direction="SHORT", stop_price="105", take_profit="90")
        self.assertEqual(evaluate_intent(payload)["stop_risk"], "11.2")

    def test_inconsistent_native_gross_or_target_blocks_reservation(self):
        for key, value, reason in (("gross_notional", "199", "GROSS_EVIDENCE_INCONSISTENT"),
                                   ("take_profit", "99", "TARGET_EVIDENCE_INCONSISTENT")):
            payload = intent()
            payload["legs"][0][key] = value
            self.assertEqual(evaluate_intent(payload)["reason"], reason)
            self.assertEqual(evaluate_intent(payload)["hypothetical_state"], "UNKNOWN")

    def test_native_matching_gross_does_not_replace_quantity_calculation(self):
        payload = intent()
        payload["legs"][0]["gross_notional"] = "200.00"
        self.assertEqual(evaluate_intent(payload)["gross_notional"], "200")

    def test_futures_engine_or_futures_venue_requires_native_margin(self):
        for engine, venue in (("FUTURES", "PAPER"), ("QUANT_ARBITRAGE", "FUTURES_REFERENCE"),
                              ("QUANT_ARBITRAGE", "FUTURES_DEMO"), ("SPOT", "FUTURES")):
            with self.subTest(engine=engine, venue=venue):
                payload = intent()
                payload["engine"] = engine
                payload["legs"][0]["venue"] = venue
                result = evaluate_intent(payload)
                self.assertEqual(result["reason"], "MARGIN_UNKNOWN")
                self.assertIsNone(result["committed_capital"])
                payload["legs"][0]["margin"] = "50"
                result = evaluate_intent(payload)
                self.assertEqual(result["committed_capital"], "50")
                self.assertEqual(result["gross_notional"], "200")

    def test_spot_reference_and_paper_use_principal_without_invented_leverage(self):
        for venue in ("SPOT_TESTNET", "SPOT_REFERENCE", "SPOT", "PAPER"):
            payload = intent()
            payload["legs"][0]["venue"] = venue
            self.assertEqual(evaluate_intent(payload)["committed_capital"], "200")

    def test_invalid_supplied_margin_is_unknown_even_for_spot(self):
        for margin in ("0", "-2", 50.0, "NaN"):
            payload = intent()
            payload["legs"][0]["margin"] = margin
            self.assertEqual(evaluate_intent(payload)["reason"], "MARGIN_UNKNOWN")

    def test_capital_evidence_age_boundary_is_causal(self):
        payload = intent()
        for at, expected in ((910, "ACCOUNT_IDENTITY_UNVERIFIED"), (909.999, "CAPITAL_EVIDENCE_STALE"),
                              (1000.001, "CAPITAL_EVIDENCE_FUTURE"), (None, "CAPITAL_TIMESTAMP_UNKNOWN")):
            with self.subTest(at=at):
                payload["capital"]["at"] = at
                self.assertEqual(evaluate_intent(payload)["reason"], expected)

    def test_all_four_evidence_timestamps_are_required_without_capture_substitution(self):
        for key in ("market_at", "received_at", "known_at", "decision_at"):
            for value in (None, True, "1000", float("nan"), float("inf"), 10 ** 1000):
                with self.subTest(key=key, value=value):
                    payload = intent()
                    payload["evidence"][key] = value
                    payload["limits"]["gross_limit"] = "1"
                    result = evaluate_intent(payload)
                    self.assertEqual(result["reason"], "EVIDENCE_TIMESTAMP_UNKNOWN")
                    self.assertEqual(result["hypothetical_state"], "UNKNOWN")
                    self.assertEqual(result["gross_notional"], "200")
        payload = intent()
        payload.pop("evidence")
        self.assertEqual(evaluate_intent(payload)["reason"], "EVIDENCE_TIMESTAMP_UNKNOWN")

    def test_future_evidence_relative_to_capture_never_admits_or_rejects_historically(self):
        for key in ("market_at", "received_at", "known_at", "decision_at"):
            with self.subTest(key=key):
                payload = intent()
                payload["evidence"][key] = 1000.001
                payload["limits"]["gross_limit"] = "1"
                result = evaluate_intent(payload)
                self.assertEqual(result["reason"], "EVIDENCE_AFTER_CAPTURE")
                self.assertEqual(result["hypothetical_state"], "UNKNOWN")
                self.assertEqual(result["stop_risk"], "11.2")
                self.assert_authority_unknown(result)

    def test_known_received_and_market_must_be_available_at_native_decision(self):
        for key in ("market_at", "received_at", "known_at"):
            with self.subTest(key=key):
                payload = intent()
                payload["at"] = 1100
                payload["evidence"][key] = 1001
                result = evaluate_intent(payload)
                self.assertEqual(result["reason"], "EVIDENCE_AFTER_DECISION")
                self.assertEqual(result["hypothetical_state"], "UNKNOWN")

    def test_provider_clock_lead_is_bounded_and_never_excuses_future_context(self):
        payload = intent()
        payload["at"] = 1010
        payload["evidence"].update(market_at=1005, received_at=1000,
                                    known_at=1005, decision_at=1005)
        payload["capital"]["at"] = 1005
        self.assertEqual(evaluate_intent(payload)["hypothetical_state"], "RESERVED_UNVERIFIED")
        payload["evidence"].update(market_at=1005.001, known_at=1006, decision_at=1006)
        result = evaluate_intent(payload)
        self.assertEqual(result["reason"], "MARKET_RECEIPT_CLOCK_DIVERGENCE")
        self.assertEqual(result["hypothetical_state"], "UNKNOWN")
        payload["evidence"].update(market_at=1001, received_at=1000,
                                    known_at=1000, decision_at=1000)
        payload["capital"]["at"] = 1000
        self.assertEqual(evaluate_intent(payload)["reason"], "EVIDENCE_AFTER_DECISION")

    def test_no_arbitrary_ordering_between_known_and_received_is_invented(self):
        payload = intent()
        payload["evidence"].update(market_at=990, received_at=999, known_at=995, decision_at=1000)
        self.assertEqual(evaluate_intent(payload)["hypothetical_state"], "RESERVED_UNVERIFIED")

    def test_capital_received_after_decision_is_unknown_even_before_capture(self):
        payload = intent()
        payload["at"] = 1100
        payload["capital"]["at"] = 1000.001
        payload["limits"]["capital_limit"] = "1"
        result = evaluate_intent(payload)
        self.assertEqual(result["reason"], "CAPITAL_EVIDENCE_AFTER_DECISION")
        self.assertEqual(result["hypothetical_state"], "UNKNOWN")
        self.assertEqual(result["committed_capital"], "200")

    def test_capital_freshness_uses_decision_not_later_final_capture(self):
        payload = intent()
        payload["at"] = 10000
        payload["capital"]["at"] = 910
        self.assertEqual(evaluate_intent(payload)["hypothetical_state"], "RESERVED_UNVERIFIED")
        payload["capital"]["at"] = 909.999
        self.assertEqual(evaluate_intent(payload)["reason"], "CAPITAL_EVIDENCE_STALE")

    def test_evaluation_does_not_rewrite_frozen_timestamp_evidence(self):
        payload = intent()
        payload["evidence"]["known_at"] = 1000.001
        event = build_intent(engine=payload["engine"], environment=payload["environment"],
                             origin_ref="SYNTHETIC_CAUSALITY_ONLY", strategy_version="frozen-v1",
                             at=payload["at"], legs=payload["legs"], capital=payload["capital"],
                             limits=payload["limits"], evidence=payload["evidence"])
        original_bytes, original_id = event.encoded, event.id
        observed = event.payload()
        before = copy.deepcopy(observed)
        result = evaluate_intent(observed)
        self.assertEqual(result["hypothetical_state"], "UNKNOWN")
        self.assertEqual(observed, before)
        self.assertEqual(event.encoded, original_bytes)
        self.assertEqual(event.id, original_id)
        self.assertEqual(event.payload(), before)

    def test_missing_capital_does_not_substitute_cash_or_equity_for_available(self):
        payload = intent()
        payload["capital"].pop("available")
        result = evaluate_intent(payload)
        self.assertEqual(result["reason"], "AVAILABLE_CAPITAL_UNKNOWN")
        self.assertEqual(result["hypothetical_state"], "UNKNOWN")

    def test_optional_native_capital_values_still_reject_float_money(self):
        for key in ("cash", "equity", "available"):
            payload = intent()
            payload["capital"][key] = 1000.0
            self.assertEqual(evaluate_intent(payload)["hypothetical_state"], "UNKNOWN")

    def test_all_limits_are_required_without_financial_defaults(self):
        for key in ("gross_limit", "capital_limit", "stop_risk_limit", "max_positions"):
            with self.subTest(key=key):
                payload = intent()
                payload["limits"].pop(key)
                result = evaluate_intent(payload)
                self.assertEqual(result["reason"], "LIMIT_EVIDENCE_UNKNOWN")
                self.assertEqual(result["hypothetical_state"], "UNKNOWN")

    def test_known_breaches_are_rejected_without_real_admission(self):
        for key, value, reason in (("gross_limit", "199.99", "GROSS_LIMIT_EXCEEDED"),
                                   ("capital_limit", "201.19", "CAPITAL_LIMIT_EXCEEDED"),
                                   ("stop_risk_limit", "11.19", "STOP_RISK_LIMIT_EXCEEDED"),
                                   ("max_positions", 0, "POSITION_LIMIT_EXCEEDED")):
            with self.subTest(key=key):
                payload = intent()
                payload["limits"][key] = value
                result = evaluate_intent(payload)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["hypothetical_state"], "REJECTED_UNVERIFIED")
                self.assert_authority_unknown(result)

    def test_capital_and_available_checks_reserve_round_trip_costs(self):
        payload = intent()
        payload["capital"]["available"] = "200"
        result = evaluate_intent(payload)
        self.assertEqual(result["reason"], "AVAILABLE_CAPITAL_EXCEEDED")
        payload["capital"]["available"] = "201.2"
        payload["limits"].update(capital_limit="201.2", stop_risk_limit="11.2", gross_limit="200")
        self.assertEqual(evaluate_intent(payload)["hypothetical_state"], "RESERVED_UNVERIFIED")

    def test_negative_available_capital_is_honest_shortfall_not_zero_or_funding(self):
        payload = intent()
        payload["capital"]["available"] = "-100"
        self.assertEqual(evaluate_intent(payload)["reason"], "AVAILABLE_CAPITAL_EXCEEDED")

    def test_prior_reservations_consume_gross_capital_costs_risk_and_slots(self):
        cases = (("gross_limit", "299", "GROSS_LIMIT_EXCEEDED"),
                 ("capital_limit", "302", "CAPITAL_LIMIT_EXCEEDED"),
                 ("stop_risk_limit", "16", "STOP_RISK_LIMIT_EXCEEDED"),
                 ("max_positions", 1, "POSITION_LIMIT_EXCEEDED"))
        for key, value, reason in cases:
            with self.subTest(key=key):
                payload = intent()
                payload["limits"][key] = value
                result = evaluate_intent(payload, [reservation()])
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["gross_notional"], "200")
                self.assertEqual(result["committed_capital"], "200")
        payload = intent()
        payload["capital"]["available"] = "302"
        self.assertEqual(evaluate_intent(payload, [reservation()])["reason"], "AVAILABLE_CAPITAL_EXCEEDED")

    def test_unknown_prior_values_never_become_free_capital_or_risk(self):
        for key in ("capital", "gross", "costs", "stop_risk"):
            with self.subTest(key=key):
                result = evaluate_intent(intent(), [reservation(**{key: None})])
                self.assertEqual(result["reason"], "RESERVATION_EVIDENCE_UNKNOWN")
                self.assertEqual(result["hypothetical_state"], "UNKNOWN")

    def test_known_lower_bound_breach_remains_rejected_with_other_evidence_missing(self):
        payload = intent()
        payload["legs"][0].pop("fee_rate")
        payload["limits"]["stop_risk_limit"] = "9"
        result = evaluate_intent(payload, [reservation(capital=None)])
        self.assertEqual(result["reason"], "STOP_RISK_LIMIT_EXCEEDED")
        self.assertEqual(result["hypothetical_state"], "REJECTED_UNVERIFIED")
        self.assertIsNone(result["stop_risk"])
        self.assertEqual(result["nominal_stop_risk"], "10")

    def test_current_origin_is_excluded_without_releasing_other_reservations(self):
        own = reservation(origin_digest="a" * 64, symbols=["BTCUSDT"], capital="9999")
        result = evaluate_intent(intent(), [own])
        self.assertEqual(result["hypothetical_state"], "RESERVED_UNVERIFIED")
        result = evaluate_intent(intent(), [own, reservation(symbols=["BTCUSDT"])])
        self.assertEqual(result["reason"], "OBSERVED_ASSET_CONFLICT")

    def test_observed_same_asset_conflict_rejects_opposite_directions_without_netting(self):
        payload = intent()
        payload["legs"][0].update(direction="SHORT", stop_price="105", take_profit="90")
        result = evaluate_intent(payload, [reservation(symbols=["BTCUSDT"])])
        self.assertEqual(result["reason"], "OBSERVED_ASSET_CONFLICT")
        self.assertEqual(result["hypothetical_state"], "REJECTED_UNVERIFIED")
        self.assert_authority_unknown(result)

    def test_missing_prior_symbols_and_duplicate_origins_are_unknown(self):
        row = reservation()
        row.pop("symbols")
        self.assertEqual(evaluate_intent(intent(), [row])["reason"], "RESERVATION_SYMBOLS_UNKNOWN")
        self.assertEqual(evaluate_intent(intent(), [reservation(), reservation()])["reason"],
                         "RESERVATION_EVIDENCE_UNKNOWN")

    def test_no_ttl_expiry_or_external_status_implicitly_releases_prior_reservation(self):
        row = reservation(symbols=["BTCUSDT"], expires_at=1, state="UNKNOWN", at=1)
        self.assertEqual(evaluate_intent(intent(), [row])["reason"], "OBSERVED_ASSET_CONFLICT")

    def test_schema_environment_account_identity_and_resource_bounds_fail_closed(self):
        for key, value in (("schema", True), ("schema", 2), ("kind", "SELL"), ("engine", []),
                           ("environment", "LIVE"), ("environment", {}), ("account_identity", "KNOWN"),
                           ("at", True), ("at", float("inf")), ("at", 10 ** 1000)):
            with self.subTest(key=key):
                payload = intent()
                payload[key] = value
                self.assertEqual(evaluate_intent(payload)["reason"], "INVALID_INTENT")
        for legs in ([], [intent()["legs"][0]] * 5, None):
            payload = intent()
            payload["legs"] = legs
            self.assertEqual(evaluate_intent(payload)["reason"], "INVALID_LEGS")
        self.assertEqual(evaluate_intent(intent(), [reservation()] * 257)["reason"], "INVALID_RESERVATIONS")

    def test_malformed_leg_and_reservation_are_safe_unknown(self):
        for leg in (None, {}, {**intent()["legs"][0], "venue": []}):
            payload = intent()
            payload["legs"] = [leg]
            self.assertEqual(evaluate_intent(payload)["reason"], "INVALID_LEG")
        self.assertEqual(evaluate_intent(intent(), [None])["reason"], "RESERVATION_EVIDENCE_UNKNOWN")

    def test_invalid_rates_limits_and_position_types_do_not_get_defaulted(self):
        for field, value in (("fee_rate", "-0.001"), ("slippage_rate", "1.1")):
            payload = intent()
            payload["legs"][0][field] = value
            self.assertEqual(evaluate_intent(payload)["reason"], "COST_EVIDENCE_UNKNOWN")
        for field, value in (("gross_limit", 1000.0), ("capital_limit", "-1"),
                             ("max_positions", True), ("max_positions", "4")):
            payload = intent()
            payload["limits"][field] = value
            self.assertEqual(evaluate_intent(payload)["reason"], "LIMIT_EVIDENCE_UNKNOWN")

    def test_function_does_not_modify_either_input_and_repeat_is_identical(self):
        payload, rows = intent(), [reservation()]
        before = copy.deepcopy((payload, rows))
        first = evaluate_intent(payload, rows)
        self.assertEqual(evaluate_intent(payload, rows), first)
        self.assertEqual((payload, rows), before)

    def test_module_has_only_pure_arithmetic_dependencies_and_no_io(self):
        source = Path(__file__).resolve().parents[1] / "trader" / "opportunity_shadow.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        modules = {node.module if isinstance(node, ast.ImportFrom) else alias.name
                   for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                   for alias in node.names}
        self.assertEqual(modules, {"decimal", "math", "re"})
        forbidden = {"open", "exec", "eval", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden)


if __name__ == "__main__":
    unittest.main()
