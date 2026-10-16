"""Synthetic contract/safety tests; no bot, exchange, database or filesystem I/O."""
import copy
import json
import math
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from trader.portfolio_guardian import (
    MAX_ASSETS, MAX_BYTES, build_guardian, engine_catalog, guardian_unavailable,
    quant_not_started,
)


NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
STAMP = NOW.isoformat()


def dashboard():
    return {
        "status": {"mode": "PAPER", "cycle_seconds": 300,
                   "risk": {"max_total_exposure_pct": .6}},
        "positions": [{"symbol": "BTCUSDT", "quantity": 2, "entry_price": 99,
                       "market_price": 100, "stop_price": 90}],
        "equity": [{"equity": 1000, "cash": 800, "created_at": STAMP}],
        "paper_scorecard": {"prices_at": STAMP, "price_status": "fresh"},
        "futures_forward": {
            "enabled": True, "cycle_diagnostic": {"at": STAMP},
            "positions": [
                {"symbol": "BTCUSDT", "direction": "LONG", "quantity": 1,
                 "entry_price": 99, "mark_price": 100, "stop_price": 90,
                 "priced_at": STAMP, "leverage": 3},
                {"symbol": "ETHUSDT", "direction": "SHORT", "quantity": 2,
                 "entry_price": 21, "mark_price": 20, "stop_price": 25,
                 "priced_at": STAMP, "leverage": 2}],
            "native_protection": {"positions": {"BTCUSDT": {"status": "ARMED"},
                                                 "ETHUSDT": {"status": "ARMED"}}},
            "equity": [{"wallet_balance": 1000, "unrealized_pnl": 10,
                        "available_balance": 900, "created_at": STAMP}],
            "portfolio_budget": {"at": STAMP, "notional_usdt": 140,
                                 "stop_loss_usdt": 20.7, "cost_buffer_pct": .005},
            "guardrails": {"forward_total_notional_usdt": 300,
                           "forward_total_stop_loss_usdt": 7.5}},
        "market_pulse": {
            "mode": "SHADOW", "state": "SHADOW", "updated_at": STAMP,
            "freshness": {"state": "FRESH", "age_seconds": 0},
            "market": [{"symbol": "BTCUSDT", "fresh": True, "at": STAMP}],
            "positions": [{"symbol": "BTCUSDT", "quantity": .5,
                           "mark_price": 100, "stop": 98}],
            "performance": {"initial_capital": 1000, "equity": 1000, "cash": 950}},
    }


def scopes(result):
    return {scope["id"]: scope for scope in result["scopes"]}


class GuardianObserverTests(unittest.TestCase):
    def test_missing_inventory_and_quant_stub_never_invent_zero_capital_or_trades(self):
        result = build_guardian({}, NOW)
        self.assertEqual(result["state"], "PARTIAL")
        for scope in result["scopes"]:
            self.assertIsNone(scope["gross_usdt"])
            self.assertIsNone(scope["position_count"])
            self.assertIsNone(scope["capital"]["equity_usdt"])
        quant = quant_not_started(NOW)
        self.assertEqual(quant["state"], "NOT_STARTED")
        self.assertFalse(quant["initialized"])
        self.assertFalse(quant["execution_enabled"])
        self.assertTrue(all(value is None for value in quant["performance"].values()))
        self.assertEqual(len(engine_catalog({})), 4)

    def test_scoped_gross_net_ignore_leverage_and_have_no_cross_environment_total(self):
        data = dashboard()
        data["futures_forward"]["positions"][0]["leverage"] = 100
        result = build_guardian(data, NOW)
        scope = scopes(result)
        self.assertEqual(scope["SPOT"]["gross_usdt"], 200)
        self.assertEqual(scope["FUTURES"]["gross_usdt"], 140)
        self.assertEqual(scope["FUTURES"]["net_usdt"], 60)
        self.assertEqual(scope["AI_MARKET_PULSE"]["gross_usdt"], 50)
        self.assertNotIn("gross_usdt", result)
        self.assertNotIn("equity_usdt", result)
        self.assertEqual(scope["SPOT"]["assets"][0]["concentration_pct"], 100)
        self.assertEqual(scope["FUTURES"]["capital"]["available_usdt"], 900)
        self.assertIsNone(scope["FUTURES"]["capital"]["cash_usdt"])

    def test_stale_or_absent_marks_stay_unknown_despite_fresh_cycle_and_entry_price(self):
        data = dashboard()
        data["futures_forward"]["positions"][0]["priced_at"] = (NOW - timedelta(minutes=11)).isoformat()
        data["positions"][0]["market_price"] = None
        data["market_pulse"]["market"][0]["fresh"] = False
        scope = scopes(build_guardian(data, NOW))
        self.assertIsNone(scope["SPOT"]["gross_usdt"])
        self.assertIsNone(scope["SPOT"]["capital"]["equity_usdt"])
        self.assertEqual(scope["FUTURES"]["known_gross_usdt"], 40)
        self.assertIsNone(scope["FUTURES"]["gross_usdt"])
        self.assertEqual(scope["FUTURES"]["unpriced_positions"], 1)
        self.assertIsNone(scope["AI_MARKET_PULSE"]["gross_usdt"])
        self.assertIsNone(scope["AI_MARKET_PULSE"]["assets"][0]["mark_price"])

    def test_cross_scope_opposite_direction_remains_observation_not_hedge(self):
        data = dashboard()
        data["futures_forward"]["positions"][0].update(direction="SHORT", stop_price=110)
        result = build_guardian(data, NOW)
        overlap = next(item for item in result["overlaps"] if item["symbol"] == "BTCUSDT")
        self.assertEqual(overlap["classification"], "CROSS_SCOPE_OBSERVATION")
        self.assertIn("SHORT", overlap["directions"])
        self.assertEqual(len(overlap["scopes"]), 3)
        self.assertEqual(scopes(result)["SPOT"]["net_usdt"], 200)
        self.assertEqual(scopes(result)["FUTURES"]["net_usdt"], -140)
        self.assertEqual(result["reservations"]["state"], "NOT_INTEGRATED")
        self.assertIsNone(result["reservations"]["reserved_usdt"])

    def test_cost_inclusive_engine_budget_is_separate_from_nominal_stop_distance(self):
        result = build_guardian(dashboard(), NOW)
        scope = scopes(result)
        self.assertEqual(scope["FUTURES"]["nominal_stop_risk_usdt"], 20)
        self.assertEqual(scope["FUTURES"]["observed_budget"]["stop_risk_usdt"], 20.7)
        self.assertEqual(scope["FUTURES"]["budget_status"]["stop_risk"], "OBSERVED_EXCEEDED")
        self.assertEqual(scope["SPOT"]["limits"]["gross_usdt"], 600)
        self.assertIsNone(scope["AI_MARKET_PULSE"]["limits"]["gross_usdt"])
        self.assertIsNone(scope["QUANT_ARBITRAGE"]["limits"]["stop_risk_usdt"])
        data = dashboard()
        data["futures_forward"]["portfolio_budget"]["at"] = (NOW - timedelta(minutes=11)).isoformat()
        future = scopes(build_guardian(data, NOW))["FUTURES"]
        self.assertEqual(future["budget_status"]["stop_risk"], "UNKNOWN")
        self.assertIsNone(future["observed_budget"]["stop_risk_usdt"])

    def test_crossed_stop_and_unconfirmed_native_protection_do_not_create_zero_risk(self):
        data = dashboard()
        data["status"]["mode"] = "TESTNET"
        data["positions"][0]["stop_price"] = 101
        result = build_guardian(data, NOW)
        spot = scopes(result)["SPOT"]
        self.assertIsNone(spot["nominal_stop_risk_usdt"])
        self.assertEqual(spot["assets"][0]["native_protection"], "UNKNOWN")
        codes = {row["code"] for row in result["alerts"]}
        self.assertIn("PROTECTIVE_THRESHOLD_CROSSED", codes)
        self.assertIn("NATIVE_PROTECTION_UNCONFIRMED", codes)
        self.assertTrue(all(value == "UNKNOWN" for value in result["risk_quality"].values()))

    def test_nan_malformed_and_duplicate_positions_cannot_poison_or_inflate_totals(self):
        data = dashboard()
        data["positions"][0]["market_price"] = math.nan
        data["futures_forward"]["positions"].append(copy.deepcopy(data["futures_forward"]["positions"][0]))
        data["futures_forward"]["guardrails"]["forward_total_notional_usdt"] = math.inf
        result = build_guardian(data, NOW)
        scope = scopes(result)
        self.assertIsNone(scope["SPOT"]["gross_usdt"])
        self.assertIsNone(scope["FUTURES"]["gross_usdt"])
        self.assertEqual(scope["FUTURES"]["known_gross_usdt"], 140)
        self.assertIsNone(scope["FUTURES"]["limits"]["gross_usdt"])
        self.assertIn("DUPLICATE_POSITION", {row["code"] for row in result["alerts"]})
        json.dumps(result, allow_nan=False)

    def test_no_io_no_mutation_and_no_capability_to_control_existing_engines(self):
        data = dashboard()
        before = copy.deepcopy(data)
        with patch("builtins.open", side_effect=AssertionError("filesystem I/O")), \
             patch("sqlite3.connect", side_effect=AssertionError("database I/O")), \
             patch("socket.create_connection", side_effect=AssertionError("network I/O")):
            result = build_guardian(data, NOW)
            fallback = guardian_unavailable(NOW)
            quant_not_started(NOW)
            engine_catalog(data)
        self.assertEqual(data, before)
        for item in (result, fallback):
            for flag in ("can_veto", "controls_enabled", "execution_enabled"):
                self.assertIs(item[flag], False)
        self.assertEqual(fallback["state"], "DEGRADED")
        self.assertEqual(len(fallback["scopes"]), 4)
        self.assertTrue(all(scope["gross_usdt"] is None for scope in fallback["scopes"]))

    def test_fresh_empty_ledger_can_be_zero_but_uninitialized_pulse_cannot(self):
        data = dashboard()
        data["positions"] = []
        data["market_pulse"].update(state="NOT_STARTED", updated_at=None)
        data["market_pulse"]["positions"] = []
        scope = scopes(build_guardian(data, NOW))
        self.assertEqual(scope["SPOT"]["gross_usdt"], 0)
        self.assertEqual(scope["SPOT"]["position_count"], 0)
        self.assertIsNone(scope["AI_MARKET_PULSE"]["gross_usdt"])
        self.assertIsNone(scope["AI_MARKET_PULSE"]["position_count"])

    def test_projection_stays_bounded_and_truncation_never_implies_complete_inventory(self):
        data = dashboard()
        data["positions"] = [{"symbol": f"ASSET{i:02}USDT", "quantity": 1,
                              "market_price": 10, "stop_price": 9} for i in range(100)]
        result = build_guardian(data, NOW)
        self.assertLess(len(json.dumps(result, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()), MAX_BYTES)
        self.assertLessEqual(sum(len(item["assets"]) for item in result["scopes"]), MAX_ASSETS)
        self.assertGreater(result["truncation"]["assets_omitted"], 0)
        self.assertIsNone(scopes(result)["SPOT"]["gross_usdt"])

    def test_missing_futures_direction_is_unknown_instead_of_default_long(self):
        data = dashboard()
        del data["futures_forward"]["positions"][1]["direction"]
        future = scopes(build_guardian(data, NOW))["FUTURES"]
        self.assertIsNone(future["net_usdt"])
        self.assertEqual(future["known_net_usdt"], 100)
        self.assertEqual(future["assets"][1]["direction"], "UNKNOWN")
        self.assertEqual(future["state"], "PARTIAL")

    def test_explicit_uninitialized_futures_with_fresh_diagnostic_stays_unknown(self):
        data = {"futures_forward": {"positions": [], "cycle_diagnostic": {"at": STAMP},
                                   "state": "NOT_STARTED", "enabled": False}}
        future = scopes(build_guardian(data, NOW))["FUTURES"]
        self.assertEqual(future["state"], "NOT_STARTED")
        self.assertIsNone(future["position_count"])
        self.assertIsNone(future["gross_usdt"])
        self.assertIsNone(future["nominal_stop_risk_usdt"])

    def test_large_integer_and_finite_per_asset_sum_overflow_remain_partial(self):
        data = dashboard()
        data["positions"][0]["quantity"] = 10 ** 1000
        result = build_guardian(data, NOW)
        self.assertIsNone(scopes(result)["SPOT"]["gross_usdt"])
        data = dashboard()
        data["positions"] = [{"symbol": symbol, "quantity": 1, "market_price": 1e308,
                              "stop_price": 9e307} for symbol in ("BTCUSDT", "ETHUSDT")]
        result = build_guardian(data, NOW)
        spot = scopes(result)["SPOT"]
        self.assertEqual(spot["state"], "PARTIAL")
        self.assertIsNone(spot["gross_usdt"])
        self.assertIn("AGGREGATE_VALUE_UNKNOWN", {item["code"] for item in result["alerts"]})
        json.dumps(result, allow_nan=False)

    def test_alert_cap_preserves_budget_excess_before_per_position_warning_flood(self):
        data = dashboard()
        data["positions"] = [{"symbol": f"ASSET{i:02}USDT", "quantity": 1,
                              "market_price": None, "stop_price": 9} for i in range(40)]
        result = build_guardian(data, NOW)
        self.assertLessEqual(len(result["alerts"]), 20)
        self.assertGreater(result["truncation"]["alerts_omitted"], 0)
        self.assertEqual(result["alerts"][0]["code"], "OBSERVED_STOP_RISK_LIMIT_EXCEEDED")

    def test_malformed_enum_objects_are_unknown_and_capital_cannot_be_fresh_nan(self):
        data = dashboard()
        data["status"]["mode"] = ["TESTNET"]
        data["futures_forward"]["positions"][0]["direction"] = ["LONG"]
        data["futures_forward"]["native_protection"]["positions"]["BTCUSDT"]["status"] = {"ARMED": True}
        data["futures_forward"]["state"] = []
        data["market_pulse"]["state"] = {}
        data["equity"][0]["equity"] = math.nan
        result = build_guardian(data, NOW)
        scope = scopes(result)
        self.assertIsNone(scope["SPOT"]["gross_usdt"])
        self.assertEqual(scope["SPOT"]["capital"]["state"], "UNKNOWN")
        self.assertIsNone(scope["FUTURES"]["net_usdt"])
        self.assertEqual(scope["FUTURES"]["assets"][0]["native_protection"], "UNKNOWN")
        self.assertIsNone(scope["AI_MARKET_PULSE"]["position_count"])
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
