from dataclasses import replace
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

from trader.live_transport import (LiveCredentials, LiveError, LiveReadOnlyTransport, LiveOrderIntent,
    LiveOrderTransport, ExecutionGrant, LiveSubmissionJournal, HOSTS, WRITE, MAX_RESPONSE)
from trader.live_account import (LiveAccountAudit, EncryptedAuditStore, credentials_from_environment,
    PERMISSION_FIELDS, AUTHORITY)

NOW = 1_700_000_000_000
KEY = "LiveKeyForSyntheticTestsOnly"
SECRET = "LiveSecretForSyntheticTestsOnly"
POLICY = "a" * 64


class Response:
    def __init__(self, value):
        self.raw = value if type(value) is bytes else json.dumps(value).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        return self.raw[:limit]


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return Response(item)


class FakeAuthority:
    """Synthetic issuer: never installed in a trading process."""
    def __init__(self):
        self.used = set()
    def consume(self, grant, intent, *, now_utc_ms):
        if grant.nonce in self.used or grant.proof != "synthetic" or grant.intent_digest != intent.digest():
            return False
        self.used.add(grant.nonce)
        return True


def pair():
    return LiveCredentials(KEY, SECRET)


def intent(*, scope="SPOT_LIVE", purpose="ENTRY", method="POST", endpoint=None, fields=None, client="future-live-1"):
    if endpoint is None:
        endpoint = "/api/v3/order" if scope == "SPOT_LIVE" else "/fapi/v1/order"
    if fields is None:
        fields = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.001", "type": "MARKET", "newClientOrderId": client}
        if scope == "FUTURES_LIVE":
            fields.update(positionSide="BOTH", reduceOnly="false")
    return LiveOrderIntent(scope, purpose, method, endpoint, tuple(fields.items()), client, POLICY, NOW + 20_000)


def grant(value, nonce="nonce-1"):
    return ExecutionGrant(value.digest(), nonce, "reservation-1", "owner-authorization-1", POLICY,
                          pair().fingerprint(), value.expires_utc_ms, "synthetic")


class LiveTransportTests(unittest.TestCase):
    def read_transport(self, **kwargs):
        return LiveReadOnlyTransport({"SPOT_LIVE": pair(), "FUTURES_LIVE": pair()},
                                     clock=lambda: NOW / 1000, monotonic=lambda: 10, **kwargs)

    def write_transport(self, folder, authority=None):
        return LiveOrderTransport({"SPOT_LIVE": pair(), "FUTURES_LIVE": pair()},
            clock=lambda: NOW / 1000, monotonic=lambda: 10,
            journal=LiveSubmissionJournal(Path(folder) / "LIVE_SUBMISSION_test.sqlite3"), authority=authority)

    def test_credentials_repr_and_segregated_names(self):
        self.assertNotIn(KEY, repr(pair()))
        self.assertNotIn(SECRET, repr(pair()))
        with self.assertRaisesRegex(LiveError, "NO_SEPARATE_LIVE_CREDENTIALS"):
            credentials_from_environment({"BINANCE_API_KEY": KEY, "BINANCE_API_SECRET": SECRET,
                                          "BINANCE_FUTURES_API_KEY": KEY, "BINANCE_FUTURES_API_SECRET": SECRET})
        found = credentials_from_environment({"BINANCE_LIVE_SPOT_API_KEY": KEY, "BINANCE_LIVE_SPOT_API_SECRET": SECRET})
        self.assertEqual(set(found), {"SPOT_LIVE"})

    def test_no_testnet_scope_or_tuple_credentials(self):
        for credentials in ({"SPOT_TESTNET": pair()}, {"SPOT_LIVE": (KEY, SECRET)}, {}):
            with self.assertRaises(LiveError):
                LiveReadOnlyTransport(credentials)

    def test_get_only_fixed_hosts_and_no_arbitrary_host_fields(self):
        transport = self.read_transport()
        for scope, route, fields in (("SPOT_LIVE", "https://evil.test", {}),
                ("SPOT_LIVE", "/sapi/v1/capital/withdraw/apply", {}),
                ("SPOT_TESTNET", "/api/v3/account", {}),
                ("SPOT_LIVE", "/api/v3/account", {"base_url": "http://127.0.0.1"})):
            with self.assertRaises(LiveError):
                transport.get(scope, route, fields)
        with self.assertRaisesRegex(LiveError, "LIVE_EXECUTION_LOCKED"):
            transport._request("SPOT_LIVE", "POST", "/api/v3/order", {})
        self.assertEqual(transport.calls, 0)

    def test_signed_get_hmac_and_request_budget(self):
        import hmac
        opener = Opener([{"serverTime": NOW}, {"balances": []}])
        transport = self.read_transport(max_calls=2)
        with patch.object(transport, "_opener", return_value=opener):
            transport.get("SPOT_LIVE", "/api/v3/account")
            with self.assertRaises(LiveError):
                transport.get("SPOT_LIVE", "/api/v3/account")
        request = opener.requests[-1]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.startswith(HOSTS["SPOT_LIVE"] + "/api/v3/account?"))
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        query = urllib.parse.urlencode(sorted((k, v[0]) for k, v in params.items() if k != "signature"))
        self.assertEqual(params["signature"], [hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()])
        self.assertEqual(request.get_header("X-mbx-apikey"), KEY)

    def test_invalid_server_clock_prevents_private_request(self):
        for response in ({"serverTime": "bad"}, {}, {"serverTime": True}):
            opener = Opener([response])
            transport = self.read_transport()
            with patch.object(transport, "_opener", return_value=opener), self.assertRaisesRegex(LiveError, "LIVE_CLOCK_UNVERIFIED"):
                transport.get("SPOT_LIVE", "/api/v3/account")
            self.assertEqual(len(opener.requests), 1)

    def test_http_and_malicious_error_text_are_closed(self):
        transport = self.read_transport()
        error = urllib.error.HTTPError("https://secret-in-url", 429, SECRET, {}, io.BytesIO(KEY.encode()))
        opener = Opener([error])
        with patch.object(transport, "_opener", return_value=opener), self.assertRaisesRegex(LiveError, "LIVE_RATE_LIMITED") as caught:
            transport.get("SPOT_LIVE", "/api/v3/time")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(len(opener.requests), 1)

    def test_bounded_and_strict_json(self):
        for body, code in ((b"x" * (MAX_RESPONSE + 1), "SIZE_LIMIT"),
                           (b'{"x":1,"x":2}', "INVALID_RESPONSE"), (b'{"x":NaN}', "INVALID_RESPONSE")):
            transport = self.read_transport()
            with patch.object(transport, "_opener", return_value=Opener([body])), self.assertRaisesRegex(LiveError, code):
                transport.get("SPOT_LIVE", "/api/v3/time")

    def test_proxy_and_redirect_disabled(self):
        opener = LiveReadOnlyTransport._opener()
        self.assertFalse(any(getattr(handler, "proxies", None) for handler in opener.handlers))
        redirect = [h for h in opener.handlers if hasattr(h, "redirect_request")]
        self.assertTrue(redirect)
        self.assertIsNone(redirect[0].redirect_request(None, None, None, None, None, None))

    def test_default_live_write_is_locked_even_valid_intent(self):
        value = intent()
        transport = LiveOrderTransport({"SPOT_LIVE": pair()})
        with patch.object(transport, "_opener") as network, self.assertRaisesRegex(LiveError, "LIVE_EXECUTION_LOCKED"):
            transport.submit(value, grant(value))
        network.assert_not_called()

    def test_exact_grant_account_policy_expiry_checks_before_network(self):
        value = intent()
        with tempfile.TemporaryDirectory() as folder:
            transport = self.write_transport(folder, FakeAuthority())
            original = grant(value)
            for invalid in (replace(original, intent_digest="b" * 64), replace(original, account_fingerprint="b" * 64),
                            replace(original, policy_digest="b" * 64), replace(original, expires_utc_ms=NOW),
                            replace(original, nonce="bad&timestamp=1")):
                with patch.object(transport, "_opener") as network, self.assertRaises(LiveError):
                    transport.submit(value, invalid)
                network.assert_not_called()

    def test_authorized_fake_route_single_dispatch_and_restart_fence(self):
        value = intent()
        with tempfile.TemporaryDirectory() as folder:
            transport = self.write_transport(folder, FakeAuthority())
            opener = Opener([{"serverTime": NOW}, {"orderId": 99, "status": "NEW"}])
            with patch.object(transport, "_opener", return_value=opener):
                result = transport.submit(value, grant(value))
                with self.assertRaises(LiveError):
                    transport.submit(value, grant(value))
            self.assertEqual([r.get_method() for r in opener.requests], ["GET", "POST"])
            self.assertEqual(result["state"], "ACK_REQUIRES_RECONCILIATION")
            self.assertFalse(result["execution_confirmed"])
            self.assertFalse(result["reservation_release_allowed"])
            # Even an accidentally new issuer after restart cannot reuse a client.
            restarted = self.write_transport(folder, FakeAuthority())
            with patch.object(restarted, "_opener", return_value=Opener([{"serverTime": NOW}])), self.assertRaisesRegex(LiveError, "ALREADY_CLAIMED"):
                restarted.submit(value, grant(value, "nonce-2"))

    def test_timeout_unknown_persists_and_never_retries(self):
        value = intent(scope="FUTURES_LIVE")
        with tempfile.TemporaryDirectory() as folder:
            transport = self.write_transport(folder, FakeAuthority())
            opener = Opener([{"serverTime": NOW}, TimeoutError(SECRET)])
            with patch.object(transport, "_opener", return_value=opener):
                result = transport.submit(value, grant(value))
            self.assertEqual(result["state"], "UNKNOWN")
            self.assertEqual(len(opener.requests), 2)
            self.assertNotIn(SECRET, json.dumps(result))
            with closing(sqlite3.connect(transport.journal.path)) as db:
                self.assertEqual(db.execute("SELECT state FROM live_submissions").fetchone()[0], "UNKNOWN")

    def test_unknown_reconciles_with_exact_identifier_get(self):
        value = intent(scope="FUTURES_LIVE")
        transport = LiveOrderTransport({"FUTURES_LIVE": pair()}, clock=lambda: NOW / 1000, monotonic=lambda: 0)
        opener = Opener([{"serverTime": NOW}, {"status": "PARTIALLY_FILLED"}])
        with patch.object(transport, "_opener", return_value=opener):
            result = transport.reconcile(value)
        self.assertEqual(result["status"], "PARTIALLY_FILLED")
        self.assertEqual(opener.requests[-1].get_method(), "GET")
        self.assertIn("origClientOrderId=future-live-1", opener.requests[-1].full_url)

    def test_journal_rejects_an_existing_financial_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "LIVE_SUBMISSION_not_ours.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY)")
                db.execute("INSERT INTO positions VALUES (1)")
                db.commit()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(LiveError, "UNRECOGNIZED_LIVE_JOURNAL"):
                LiveSubmissionJournal(path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_authority_failure_does_not_claim_or_dispatch(self):
        class FailedAuthority:
            def consume(self, *args, **kwargs):
                raise RuntimeError(SECRET)
        value = intent()
        with tempfile.TemporaryDirectory() as folder:
            transport = self.write_transport(folder, FailedAuthority())
            opener = Opener([{"serverTime": NOW}])
            with patch.object(transport, "_opener", return_value=opener), self.assertRaisesRegex(LiveError, "LIVE_AUTHORITY_UNAVAILABLE"):
                transport.submit(value, grant(value))
            self.assertEqual(len(opener.requests), 1)
            with closing(sqlite3.connect(transport.journal.path)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM live_submissions").fetchone()[0], 0)

    def test_cancel_has_exact_target_and_requires_its_own_grant(self):
        value = intent(method="DELETE", purpose="CANCEL", fields={"symbol": "BTCUSDT", "origClientOrderId": "future-live-1"})
        with self.assertRaises(LiveError):
            replace(value, fields=tuple({"symbol": "BTCUSDT", "orderId": "12"}.items()))
        with tempfile.TemporaryDirectory() as folder:
            transport = self.write_transport(folder, FakeAuthority())
            opener = Opener([{"serverTime": NOW}, {"status": "CANCELED"}])
            with patch.object(transport, "_opener", return_value=opener):
                result = transport.submit(value, grant(value))
            self.assertEqual(opener.requests[-1].get_method(), "DELETE")
            self.assertFalse(result["reservation_release_allowed"])

    def test_only_prepared_trade_routes_no_transfers_or_settings(self):
        for scope, endpoint in (("SPOT_LIVE", "/sapi/v1/capital/withdraw/apply"),
                                ("SPOT_LIVE", "/sapi/v1/asset/transfer"),
                                ("FUTURES_LIVE", "/fapi/v1/leverage"),
                                ("FUTURES_LIVE", "/fapi/v1/marginType"),
                                ("FUTURES_LIVE", "/fapi/v1/allOpenOrders")):
            with self.assertRaisesRegex(LiveError, "WRITE_ENDPOINT_BLOCKED"):
                intent(scope=scope, endpoint=endpoint)

    def test_numeric_arbitrary_fields_and_hedge_mode_fail_closed(self):
        valid = dict(intent(scope="FUTURES_LIVE").fields)
        for patch_fields in ({"quantity": "NaN"}, {"quantity": "-1"}, {"quantity": "1e5"},
                             {"positionSide": "LONG"}, {"reduceOnly": "true"}, {"callback": "evil"}):
            with self.assertRaises(LiveError):
                intent(scope="FUTURES_LIVE", fields=valid | patch_fields)

    def test_futures_protective_order_reduce_only_actual_algo_api(self):
        fields = {"symbol": "BTCUSDT", "side": "SELL", "type": "STOP_MARKET", "quantity": "0.001",
                  "clientAlgoId": "stop-1", "algoType": "CONDITIONAL", "triggerPrice": "90000",
                  "workingType": "MARK_PRICE", "priceProtect": "TRUE", "positionSide": "BOTH", "reduceOnly": "true"}
        value = intent(scope="FUTURES_LIVE", purpose="PROTECT", endpoint="/fapi/v1/algoOrder", fields=fields, client="stop-1")
        self.assertEqual(dict(value.fields)["reduceOnly"], "true")
        for change in ({"reduceOnly": "false"}, {"type": "MARKET"}, {"workingType": "CONTRACT_PRICE"}):
            with self.assertRaises(LiveError):
                replace(value, fields=tuple((fields | change).items()))

    def test_spot_oco_native_prices_ids_and_no_buy_protection(self):
        fields = {"symbol": "BTCUSDT", "side": "SELL", "quantity": "0.001", "listClientOrderId": "oco-1",
                  "aboveClientOrderId": "tp-1", "belowClientOrderId": "sl-1", "aboveType": "LIMIT_MAKER",
                  "abovePrice": "110000", "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": "90000",
                  "belowPrice": "89900", "belowTimeInForce": "GTC"}
        value = intent(purpose="PROTECT", endpoint="/api/v3/orderList/oco", fields=fields, client="oco-1")
        for change in ({"side": "BUY"}, {"abovePrice": "80000"}, {"belowClientOrderId": "tp-1"}):
            with self.assertRaises(LiveError):
                replace(value, fields=tuple((fields | change).items()))


class LiveAccountTests(unittest.TestCase):
    def audit(self, responder, **kwargs):
        transport = LiveReadOnlyTransport({"SPOT_LIVE": pair(), "FUTURES_LIVE": pair()})
        transport.get = responder
        return LiveAccountAudit(transport, symbols=["BTCUSDT"], start_utc_ms=NOW - 1000,
            end_utc_ms=NOW, clock=lambda: NOW / 1000, **kwargs)

    @staticmethod
    def responder(scope, endpoint, params=None):
        if endpoint == "/api/v3/account":
            return {"canTrade": True, "uid": "PRIVATE_UID", "balances": [{"asset": "USDT", "free": "25", "locked": "2"}, {"asset": "币", "free": "1", "locked": "0"}]}
        if endpoint == "/fapi/v3/account":
            return {"assets": [{"asset": "USDT", "walletBalance": "25", "availableBalance": "20", "unrealizedProfit": "-1"}],
                    "positions": [], "totalWalletBalance": "25", "availableBalance": "20", "totalUnrealizedProfit": "-1", "totalMarginBalance": "24"}
        if endpoint == "/sapi/v1/account/apiRestrictions":
            return {key: key in {"enableReading", "ipRestrict"} for key in PERMISSION_FIELDS}
        if endpoint == "/fapi/v1/accountConfig":
            return {"dualSidePosition": False, "multiAssetsMargin": False, "canTrade": True}
        if endpoint == "/sapi/v1/asset/transfer":
            return {"rows": [], "total": 0}
        if endpoint in {"/api/v3/exchangeInfo", "/fapi/v1/exchangeInfo"}:
            return {"symbols": []}
        if endpoint in {"/api/v3/account/commission", "/fapi/v1/commissionRate"}:
            return {"symbol": "BTCUSDT"}
        if endpoint in {"/api/v3/ticker/price", "/fapi/v2/ticker/price"}:
            return {"symbol": "BTCUSDT", "price": "100000"}
        return []

    def test_wallets_not_merged_permissions_scope_unknown_and_no_authority(self):
        report = self.audit(self.responder).run()
        self.assertFalse(report["wallets_merged"])
        self.assertFalse(any(report["authority"].values()))
        self.assertFalse(report["account_history_complete"])
        self.assertFalse(report["initial_inventory_certified"])
        self.assertNotIn("PRIVATE_UID", json.dumps(report))
        spot = report["wallets"]["SPOT_LIVE"]
        futures = report["wallets"]["FUTURES_LIVE"]
        self.assertTrue(spot["permissions"]["withdrawals_disabled"])
        self.assertTrue(spot["permissions"]["ip_restricted"])
        self.assertEqual(futures["permissions"]["status"], "UNKNOWN")
        self.assertEqual(futures["account"]["reported_totals"]["availableBalance"], "20")
        self.assertFalse(futures["account"]["ledger_reconciled"])

    def test_account_config_does_not_infer_permission_from_balance(self):
        def respond(scope, endpoint, params=None):
            if endpoint == "/fapi/v1/accountConfig":
                return {"canTrade": True}
            return self.responder(scope, endpoint, params)
        report = self.audit(respond).run()
        self.assertEqual(report["wallets"]["FUTURES_LIVE"]["current"]["account_config"]["status"], "UNKNOWN")

    def test_missing_source_unknown_not_zero(self):
        def respond(scope, endpoint, params=None):
            if endpoint in {"/fapi/v1/income", "/sapi/v1/account/apiRestrictions"}:
                raise LiveError("LIVE_HTTP_UNAVAILABLE")
            return self.responder(scope, endpoint, params)
        report = self.audit(respond).run()
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIsNone(report["wallets"]["SPOT_LIVE"]["permissions"]["withdrawals_disabled"])
        income = report["wallets"]["FUTURES_LIVE"]["history"]["FUNDING_FEE"]
        self.assertFalse(income["window_complete"])

    def test_invalid_duplicate_balances_and_numbers_unknown(self):
        def respond(scope, endpoint, params=None):
            if endpoint == "/api/v3/account":
                return {"canTrade": True, "balances": [{"asset": "USDT", "free": "NaN", "locked": "0"}]}
            return self.responder(scope, endpoint, params)
        self.assertEqual(self.audit(respond).run()["wallets"]["SPOT_LIVE"]["account"]["status"], "UNKNOWN")

    def test_trade_pagination_cursor_exact_window_and_no_fromid_time_mix(self):
        requests = []
        def respond(scope, endpoint, params=None):
            requests.append(dict(params or {}))
            index = params.get("fromId", 10)
            return [{"id": index, "time": NOW - 500}, {"id": index + 1, "time": NOW - 400}]
        audit = self.audit(respond, max_pages=1, page_size=2)
        first = audit._history("SPOT_LIVE", "trades_BTCUSDT", "/api/v3/myTrades", {"symbol": "BTCUSDT"})
        self.assertFalse(first["window_complete"])
        self.assertEqual(first["cursor"]["next"], 12)
        resumed = self.audit(respond, max_pages=1, page_size=2, cursors={"SPOT_LIVE:trades_BTCUSDT": first["cursor"]})
        second = resumed._history("SPOT_LIVE", "trades_BTCUSDT", "/api/v3/myTrades", {"symbol": "BTCUSDT"})
        self.assertEqual(second["rows_previously_observed"], 2)
        self.assertIn("fromId", requests[-1])
        self.assertNotIn("startTime", requests[-1])
        self.assertNotIn("endTime", requests[-1])
        wrong = self.audit(respond, page_size=3, cursors={"SPOT_LIVE:trades_BTCUSDT": first["cursor"]})
        self.assertEqual(wrong._history("SPOT_LIVE", "trades_BTCUSDT", "/api/v3/myTrades", {"symbol": "BTCUSDT"})["reason"], "CURSOR_BINDING_MISMATCH")

    def test_duplicate_trade_ids_and_stale_data_not_complete(self):
        def respond(scope, endpoint, params=None):
            return [{"id": 1, "time": NOW - 500}, {"id": 1, "time": NOW - 500}]
        item = self.audit(respond, page_size=2)._history("SPOT_LIVE", "trades_BTCUSDT", "/api/v3/myTrades", {"symbol": "BTCUSDT"})
        self.assertEqual(item["status"], "UNKNOWN")
        self.assertFalse(item["window_complete"])

    def test_income_bisection_is_bounded_resumable_no_undocumented_page(self):
        requested = []
        def respond(scope, endpoint, params=None):
            requested.append(params)
            if params["endTime"] - params["startTime"] > 600:
                return [{"time": NOW - 500, "tranId": 1, "incomeType": "FUNDING_FEE", "income": "-1", "asset": "USDT"}]
            return []
        audit = self.audit(respond, max_pages=1, page_size=1)
        first = audit._history("FUTURES_LIVE", "FUNDING_FEE", "/fapi/v1/income", {"incomeType": "FUNDING_FEE"}, pagination="time")
        self.assertFalse(first["window_complete"])
        self.assertEqual(len(first["cursor"]["windows"]), 2)
        resumed = self.audit(respond, max_pages=3, page_size=1, cursors={"FUTURES_LIVE:FUNDING_FEE": first["cursor"]})
        second = resumed._history("FUTURES_LIVE", "FUNDING_FEE", "/fapi/v1/income", {"incomeType": "FUNDING_FEE"}, pagination="time")
        self.assertTrue(second["window_complete"])
        self.assertFalse(any("page" in p for p in requested))

    def test_raw_encrypted_retention_has_no_plaintext_fallback(self):
        import base64
        with tempfile.TemporaryDirectory() as folder:
            store = EncryptedAuditStore(Path(folder) / "private", protect=lambda data: b"TEST-CIPHER:" + base64.b64encode(data))
            report = self.audit(self.responder, raw_store=store).run()
            self.assertTrue(report["raw_encrypted_retention"])
            self.assertTrue((store.directory / "audit.json").is_file())
            self.assertNotIn(b"PRIVATE_UID", next(store.directory.glob("*.dpapi")).read_bytes())
            invalid = EncryptedAuditStore(Path(folder) / "invalid", protect=lambda data: data)
            with self.assertRaisesRegex(LiveError, "ENCRYPTION_REQUIRED"):
                invalid.retain({"sensitive": "PRIVATE_UID"})

    def test_no_evidence_directory_inside_git(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / ".git").mkdir()
            with self.assertRaisesRegex(LiveError, "OUTSIDE_GIT"):
                EncryptedAuditStore(Path(folder) / "evidence")

    def test_auditor_rejects_write_transport_future_or_oversized_window(self):
        transport = LiveOrderTransport({"SPOT_LIVE": pair()})
        with self.assertRaisesRegex(LiveError, "GET_ONLY"):
            LiveAccountAudit(transport, symbols=["BTCUSDT"], start_utc_ms=NOW - 1000, end_utc_ms=NOW, clock=lambda: NOW / 1000)
        for start, end in ((NOW, NOW + 1), (NOW - 86_400_001, NOW)):
            with self.assertRaises(LiveError):
                LiveAccountAudit(LiveReadOnlyTransport({"SPOT_LIVE": pair()}), symbols=["BTCUSDT"],
                    start_utc_ms=start, end_utc_ms=end, clock=lambda: NOW / 1000)


if __name__ == "__main__":
    unittest.main()
