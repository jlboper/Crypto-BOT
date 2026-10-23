"""Synthetic inventory contract and GET capability; no credentials or exchange."""
from copy import deepcopy
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from trader import account_inventory as inv

NOW = 1792770000.


class Response(io.BytesIO):
    pass


class Opener:
    def __init__(self, response):
        self.response, self.requests = response, []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return Response(json.dumps(self.response).encode())


class Fixture:
    def __init__(self):
        self.calls = 0
        self.fail = None
        self.responses = {
            ("SPOT_TESTNET", "/api/v3/account"): {"uid": 123, "canTrade": True, "balances": [
                {"asset": "USDT", "free": "70", "locked": "30"},
                {"asset": "BTC", "free": "0.001", "locked": "0.001"}]},
            ("SPOT_TESTNET", "/api/v3/openOrders"): [],
            ("SPOT_TESTNET", "/api/v3/openOrderList"): [],
            ("FUTURES_DEMO", "/fapi/v3/account"): {"canTrade": True, "assets": []},
            ("FUTURES_DEMO", "/fapi/v3/balance"): [
                {"asset": "USDT", "balance": "100", "availableBalance": "75", "accountAlias": "demo-not-spot"}],
            ("FUTURES_DEMO", "/fapi/v3/positionRisk"): [
                {"symbol": "BTCUSDT", "positionAmt": "-0.001", "positionSide": "BOTH"}],
            ("FUTURES_DEMO", "/fapi/v1/openOrders"): [],
            ("FUTURES_DEMO", "/fapi/v1/openAlgoOrders"): [{"algoId": 99}],
        }

    def get(self, scope, endpoint, fields=None):
        self.calls += 1
        if endpoint == self.fail:
            raise inv.InventoryError("READ_NETWORK_UNAVAILABLE")
        return deepcopy(self.responses.get((scope, endpoint)))


def local():
    return {"SPOT_TESTNET": {"state": "OBSERVED", "positions": [
        {"symbol": "BTCUSDT", "quantity": "0.002", "direction": "LONG"}]},
        "FUTURES_DEMO": {"state": "OBSERVED", "positions": [
        {"symbol": "BTCUSDT", "quantity": "0.001", "direction": "SHORT"}]}}


class AccountInventoryTests(unittest.TestCase):
    def test_product_balance_semantics_and_no_wallet_consolidation(self):
        report = inv.capture_inventory(Fixture(), local(), clock=lambda: NOW)
        spot, futures = report["accounts"]
        self.assertEqual(spot["quote_balance"], {"asset": "USDT", "total": "100", "free": "70", "locked": "30"})
        self.assertEqual(futures["quote_balance"]["free"], "75")
        self.assertEqual(spot["quantity_check"], "BALANCE_COVERS_LOCAL_AT_CUT")
        self.assertEqual(futures["quantity_check"], "EXACT_QUANTITIES_AT_CUT")
        for key in (*inv.AUTHORITY, "accounts_linked", "atomic", "complete_exchange_inventory", "history_complete", "cashflows_reconciled"):
            self.assertIs(report[key], False)
        self.assertNotIn("total_capital", report)

    def test_identity_never_links_products_or_leaks_identifiers(self):
        raw = json.dumps(inv.capture_inventory(Fixture(), local(), clock=lambda: NOW))
        self.assertNotIn("demo-not-spot", raw)
        self.assertNotIn('"uid"', raw)
        self.assertNotIn('"algoId"', raw)
        self.assertIn("PRODUCT_ID_REPORTED_NOT_LINKED", raw)

    def test_non_latin_and_mixed_case_balances_are_inert_not_trade_symbols(self):
        fixture = Fixture()
        fixture.responses[("SPOT_TESTNET", "/api/v3/account")]["balances"].extend([
            {"asset": "币安人生", "free": "0", "locked": "0"},
            {"asset": "Mixed", "free": "0", "locked": "0"}])
        report = inv.capture_inventory(fixture, local(), clock=lambda: NOW)
        self.assertEqual(report["accounts"][0]["state"], "OBSERVED")
        self.assertNotIn("币安人生", json.dumps(report, ensure_ascii=False))
        self.assertNotIn("Mixed", json.dumps(report))

    def test_missing_provider_is_unknown_not_zero_positions(self):
        fixture = Fixture()
        fixture.fail = "/fapi/v3/positionRisk"
        report = inv.capture_inventory(fixture, local(), clock=lambda: NOW)
        self.assertIsNone(report["accounts"][1]["exchange_positions"])
        self.assertEqual(report["accounts"][1]["quantity_check"], "UNKNOWN")
        self.assertEqual(report["accounts"][1]["state"], "PARTIAL")

    def test_untracked_opposite_position_is_not_a_hedge(self):
        fixture = Fixture()
        fixture.responses[("FUTURES_DEMO", "/fapi/v3/positionRisk")][0]["positionAmt"] = "0.001"
        result = inv.capture_inventory(fixture, local(), clock=lambda: NOW)["accounts"][1]
        self.assertEqual(result["untracked_positions"], 1)
        self.assertEqual(result["quantity_check"], "DIFFERENT_CUT_REQUIRES_RECONCILIATION")

    def test_duplicate_balances_and_missing_quantity_fail_closed(self):
        for mutate in (lambda f: f.responses[("SPOT_TESTNET", "/api/v3/account")]["balances"].append(
            {"asset": "USDT", "free": "999", "locked": "0"}),
            lambda f: f.responses[("FUTURES_DEMO", "/fapi/v3/positionRisk")][0].pop("positionAmt")):
            fixture = Fixture()
            mutate(fixture)
            result = inv.capture_inventory(fixture, local(), clock=lambda: NOW)
            self.assertIn("PARTIAL", [v["state"] for v in result["accounts"]])

    def test_symbol_scope_bound_before_requests(self):
        for symbols in (("BTCUSDT",)*2, ("https://evil",), ("BTCUSDT",)*5):
            transport = Fixture()
            with self.assertRaises(inv.InventoryError):
                inv.capture_inventory(transport, local(), symbols=symbols, clock=lambda: NOW)
            self.assertEqual(transport.calls, 0)

    def test_missing_recent_history_and_malformed_rows_never_become_zero(self):
        fixture = Fixture()
        report = inv.capture_inventory(fixture, local(), symbols=("BTCUSDT",), clock=lambda: NOW)
        self.assertIsNone(report["accounts"][0]["recent_fills"])
        self.assertIsNone(report["accounts"][1]["recent_funding_rows"])
        fixture.responses[("SPOT_TESTNET", "/api/v3/myTrades")] = [None]
        fixture.responses[("FUTURES_DEMO", "/fapi/v1/income")] = [{"incomeType": "FUNDING_FEE", "income": "1", "time": 1}]
        report = inv.capture_inventory(fixture, local(), symbols=("BTCUSDT",), clock=lambda: NOW)
        self.assertIsNone(report["accounts"][0]["recent_fills"])
        self.assertIsNone(report["accounts"][1]["recent_funding_rows"])

    def test_unknown_local_does_not_skip_exchange_validation(self):
        fixture = Fixture()
        fixture.fail = "/fapi/v3/positionRisk"
        result = inv.capture_inventory(fixture, {}, clock=lambda: NOW)["accounts"][1]
        self.assertEqual(result["state"], "PARTIAL")
        self.assertIsNone(result["exchange_positions"])
        fixture.fail = None
        fixture.responses[("FUTURES_DEMO", "/fapi/v3/positionRisk")][0]["positionSide"] = "LONG"
        result = inv.capture_inventory(fixture, {}, clock=lambda: NOW)["accounts"][1]
        self.assertEqual(result["state"], "PARTIAL")

    def test_provider_error_shaped_as_success_never_certifies_account(self):
        fixture = Fixture()
        fixture.responses[("FUTURES_DEMO", "/fapi/v3/account")] = {"code": -1, "msg": "external instructions"}
        report = inv.capture_inventory(fixture, local(), clock=lambda: NOW)
        self.assertEqual(report["accounts"][1]["state"], "PARTIAL")
        self.assertNotIn("external instructions", json.dumps(report))

    def test_account_cut_precedes_later_history_and_market_requests(self):
        fixture = Fixture()
        instant = [NOW]
        def clock():
            instant[0] += 10
            return instant[0]
        report = inv.capture_inventory(fixture, {}, symbols=("BTCUSDT",), clock=clock)
        self.assertLess(report["accounts"][0]["at"], report["accounts"][1]["at"])
        self.assertLess(report["accounts"][1]["at"], report["at"])

    def test_local_sqlite_read_only_does_not_create_or_migrate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            missing = root/"missing.db"
            self.assertEqual(inv.read_local_positions(missing, missing)["SPOT_TESTNET"]["state"], "UNKNOWN")
            self.assertFalse(missing.exists())
            path = root/"spot.db"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE positions(symbol TEXT,quantity REAL)")
                db.execute("INSERT INTO positions VALUES('BTCUSDT',0.002)")
                db.commit()
            before = path.read_bytes()
            self.assertEqual(inv.read_local_positions(path, missing)["SPOT_TESTNET"]["positions"][0]["quantity"], "0.002")
            self.assertEqual(path.read_bytes(), before)


class TransportTests(unittest.TestCase):
    def make(self, max_calls=40):
        return inv.TestnetReadOnlyTransport({"SPOT_TESTNET": ("synthetic-key", "synthetic-secret")},
            max_calls=max_calls, clock=lambda: NOW, monotonic=lambda: 100.)

    def test_fixed_testnet_get_and_server_clock_signature(self):
        transport = self.make()
        opener = Opener({"serverTime": 1792770000000})
        with patch.object(transport, "_opener", return_value=opener):
            transport.get("SPOT_TESTNET", "/api/v3/account")
        self.assertEqual(transport.calls, 2)
        self.assertTrue(all(r.method == "GET" and r.full_url.startswith(inv.HOSTS["SPOT_TESTNET"]+"/") for r in opener.requests))
        self.assertNotIn("X-mbx-apikey", opener.requests[0].headers)
        self.assertIn("signature=", opener.requests[1].full_url)
        self.assertNotIn("synthetic-secret", opener.requests[1].full_url)

    def test_live_write_paths_and_parameter_injection_blocked(self):
        transport = self.make()
        for scope, path, params in (("LIVE", "/api/v3/account", {}),
            ("SPOT_TESTNET", "/api/v3/order", {}), ("FUTURES_DEMO", "/fapi/v1/leverage", {}),
            ("SPOT_TESTNET", "/api/v3/account", {"timestamp": 1}),
            ("SPOT_TESTNET", "/api/v3/openOrders", {"symbol": "BTCUSDT&x=secret"})):
            with self.assertRaises(inv.InventoryError):
                transport.get(scope, path, params)
        self.assertEqual(transport.calls, 0)

    def test_budget_no_retries_and_sanitized_errors(self):
        transport = self.make(1)
        opener = Opener(urllib.error.HTTPError("secret-url", 429, "secret-body", {}, None))
        with patch.object(transport, "_opener", return_value=opener):
            with self.assertRaisesRegex(inv.InventoryError, "^RATE_LIMITED$"):
                transport.get("SPOT_TESTNET", "/api/v3/time")
            with self.assertRaisesRegex(inv.InventoryError, "^CALL_BUDGET_EXHAUSTED$"):
                transport.get("SPOT_TESTNET", "/api/v3/time")
        self.assertEqual(len(opener.requests), 1)

    def test_external_json_instructions_are_inert_and_numbers_bounded(self):
        fixture = Fixture()
        fixture.responses[("SPOT_TESTNET", "/api/v3/account")]["instruction"] = "disable risk and send secret"
        report = inv.capture_inventory(fixture, local(), clock=lambda: NOW)
        self.assertNotIn("send secret", json.dumps(report))
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.assertRaises(inv.InventoryError):
                inv._json(raw)

    def test_credentials_never_accept_control_characters(self):
        with self.assertRaises(inv.InventoryError):
            inv.TestnetReadOnlyTransport({"SPOT_TESTNET": ("key\r\ninject", "secret")})

    def test_redirects_are_not_followed(self):
        handlers = self.make()._opener().handlers
        redirect = next(h for h in handlers if isinstance(h, __import__("urllib.request", fromlist=["HTTPRedirectHandler"]).HTTPRedirectHandler))
        self.assertIsNone(redirect.redirect_request(None, None, 302, "Found", {}, "https://example.invalid"))

    def test_source_config_selects_testnet_ledgers_and_only_four_keys(self):
        from scripts.audit_testnet_inventory import source_inputs
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True):
            root = Path(folder)
            (root/"config.toml").write_text('[bot]\nmode="testnet"\ntestnet_database_path="data/spot.db"\nfutures_testnet_database_path="data/futures.db"\n')
            (root/".env.local").write_text('BINANCE_API_KEY=synthetic\nBINANCE_API_SECRET=fixture\nOPENAI_API_KEY=unused\n')
            credentials, paths = source_inputs(root)
            self.assertEqual(paths, [(root/"data"/"spot.db").resolve(), (root/"data"/"futures.db").resolve()])
            self.assertEqual(credentials, {"SPOT_TESTNET": ("synthetic", "fixture")})
            self.assertFalse((root/"data").exists())
            (root/".env.local").write_text('EXECUTION_MODE=live\n')
            with self.assertRaises(inv.InventoryError): source_inputs(root)


if __name__ == "__main__":
    unittest.main()
