"""Synthetic recovery incidents; no credentials, exchange or engine process."""
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
import json
import sqlite3
import unittest
import urllib.parse

import test_live_execution_runtime as runtime
from trader.live_execution_runtime import LiveExecutionCoordinator
from trader.live_transport import LiveError, LiveSubmissionJournal
from trader.live_recovery import exact_execution


class OwnedResidualRecoveryTests(unittest.TestCase):
    setUp = runtime.LiveCoordinatorTests.setUp
    plan = runtime.LiveCoordinatorTests.plan
    make_entry = runtime.LiveCoordinatorTests.make_entry
    execute = runtime.LiveCoordinatorTests.execute

    def late_fill(self):
        self.transport.max_calls = 500
        original = self.venue.open
        self.venue.status = "PARTIALLY_FILLED"
        self.missing_trades = False
        self.base_commission = False
        self.close_timeout = False
        self.partial_close = False
        def venue(request, timeout):
            method, url = request.get_method(), urllib.parse.urlsplit(request.full_url)
            values = urllib.parse.parse_qs((request.data or url.query.encode()).decode())
            fields = {key: value[0] for key, value in values.items()}
            if method == "DELETE" and url.path == "/fapi/v1/order":
                raise TimeoutError("synthetic uncertain entry cancellation")
            if method == "GET" and url.path == "/fapi/v1/userTrades":
                order = next(row for row in self.venue.orders.values() if row["orderId"] == int(fields["orderId"]))
                if self.missing_trades or Decimal(order["executedQty"]) == 0:
                    return runtime.Response([])
                return runtime.Response([{"id": order["orderId"] * 100, "orderId": order["orderId"], "symbol": order["symbol"],
                    "side": order["side"], "positionSide": "BOTH", "qty": order["executedQty"], "quoteQty": order["cumQuote"],
                    "commission": "0.01", "commissionAsset": "USDT"}])
            response = original(request, timeout)
            if method == "POST" and url.path == "/fapi/v1/order":
                order = self.venue.orders[fields["newClientOrderId"]]
                order.update(positionSide="BOTH", reduceOnly=fields["reduceOnly"] == "true")
                if fields["reduceOnly"] == "true" and self.partial_close:
                    amount = Decimal(fields["quantity"]) / 2
                    order.update(status="PARTIALLY_FILLED", executedQty=str(amount), cumQuote=str(amount * 100))
                    self.venue.position += amount if fields["side"] == "SELL" else -amount
                if fields["reduceOnly"] == "true" and self.close_timeout:
                    raise TimeoutError("synthetic close accepted before timeout")
            if method == "GET" and url.path == "/fapi/v1/order":
                raw = json.loads(response.raw)
                raw.update(positionSide="BOTH", reduceOnly=raw.get("reduceOnly", raw.get("side") == "SELL"))
                return runtime.Response(raw)
            return response
        self.venue.open = venue
        self.assertEqual(self.execute()["state"], "RECOVERY_REQUIRED")
        self.venue.orders[self.intent.client_id].update(status="FILLED", executedQty="1", cumQuote="100", positionSide="BOTH", reduceOnly=False)
        self.venue.position = Decimal(1)
        self.clock.value += 1

    def reduce(self, event="REDUCE"):
        return self.coordinator.mitigate_residual_by_client_id("PROPOSAL_1", self.intent, event_id=event)

    def close_posts(self):
        return [p for method, path, p in self.venue.requests if method == "POST" and path == "/fapi/v1/order" and p.get("reduceOnly") == "true"]

    def test_exact_terminal_residual_reduced_once_without_touching_original_stops(self):
        self.late_fill()
        validations = []
        self.coordinator.reduction_validator = lambda intent, position, now: validations.append((intent, position, now)) or True
        result = self.reduce()
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertTrue(result["mitigation_confirmed"])
        self.assertFalse(result["reservation_release_allowed"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * runtime.U)
        self.assertEqual(self.venue.position, Decimal("0.5"))
        self.assertEqual(len(self.close_posts()), 1)
        self.assertEqual(self.close_posts()[0]["quantity"], "0.5")
        self.assertEqual({row["quantity"] for row in self.venue.algos.values()}, {"0.5"})
        self.assertFalse(any(method == "DELETE" and path.endswith("algoOrder") for method, path, _ in self.venue.requests))
        self.assertEqual(validations[0][1].quantity, "1")
        pair = self.transport._credentials["FUTURES_LIVE"]
        intents = self.transport.journal.owned_intents("FUTURES_LIVE", pair.fingerprint(), "PROPOSAL_1", "CLOSE")
        self.assertEqual(len(intents), 1)
        records = self.transport.journal.execution_observations(intents[0], pair.fingerprint(), "PROPOSAL_1")
        self.assertEqual(records[0]["trades"][0]["commissionAsset"], "USDT")

    def test_restart_after_expiry_reuses_original_close_for_get_only(self):
        self.late_fill()
        self.close_timeout = True
        self.coordinator.reduction_validator = lambda *args: True
        self.assertTrue(self.reduce()["mitigation_confirmed"])
        pair = self.transport._credentials["FUTURES_LIVE"]
        original = self.transport.journal.owned_intents("FUTURES_LIVE", pair.fingerprint(), "PROPOSAL_1", "CLOSE")[0]
        self.clock.value += 60
        self.transport.authority = None
        self.coordinator = LiveExecutionCoordinator(self.admission, self.transport, provider=self.owner,
            protection_factory=self.plan, reduction_validator=lambda *args: True, clock=self.clock)
        result = self.reduce("RESTART")
        self.assertTrue(result["mitigation_confirmed"])
        self.assertEqual(len(self.close_posts()), 1)
        self.assertEqual(self.transport.journal.owned_intents("FUTURES_LIVE", pair.fingerprint(), "PROPOSAL_1", "CLOSE")[0], original)

    def test_partial_close_keeps_unknown_tail_and_never_posts_again(self):
        self.late_fill()
        self.partial_close = True
        self.coordinator.reduction_validator = lambda *args: True
        first = self.reduce()
        self.assertEqual(first["state"], "RECOVERY_REQUIRED")
        self.assertFalse(first.get("mitigation_confirmed", False))
        self.clock.value += 1
        self.assertEqual(self.reduce("PARTIAL_RECHECK")["state"], "RECOVERY_REQUIRED")
        self.assertEqual(len(self.close_posts()), 1)
        self.assertEqual(self.venue.position, Decimal("0.75"))
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * runtime.U)

    def test_missing_costs_unknown_ownership_or_filters_prevent_close(self):
        self.late_fill()
        self.coordinator.reduction_validator = lambda *args: True
        self.missing_trades = True
        self.assertEqual(self.reduce("MISSING_COSTS")["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.close_posts(), [])
        self.missing_trades = False
        self.venue.position = Decimal("1.01")
        self.assertEqual(self.reduce("EXTRA_INVENTORY")["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.close_posts(), [])
        self.venue.position = Decimal(1)
        self.coordinator.reduction_validator = lambda *args: False
        self.assertIn("CURRENT_REDUCTION_FILTERS_NOT_VERIFIED", self.reduce("BAD_FILTERS")["reasons"])
        self.assertEqual(self.close_posts(), [])

    def test_absent_validator_and_nonterminal_entry_never_close(self):
        self.late_fill()
        self.assertIn("CURRENT_REDUCTION_FILTERS_REQUIRED", self.reduce()["reasons"])
        self.coordinator.reduction_validator = lambda *args: True
        self.venue.orders[self.intent.client_id].update(status="PARTIALLY_FILLED", executedQty="0.5", cumQuote="50")
        self.assertEqual(self.reduce("NONTERMINAL")["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.close_posts(), [])

    def test_validator_race_with_stop_execution_or_extra_position_never_sends(self):
        self.late_fill()
        def changed(intent, position, now):
            self.venue.position = Decimal("0.9")
            return True
        self.coordinator.reduction_validator = changed
        self.assertEqual(self.reduce()["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.close_posts(), [])

    def test_corrupt_retained_close_terms_do_not_regenerate_request(self):
        self.late_fill()
        self.coordinator.reduction_validator = lambda *args: True
        self.assertTrue(self.reduce()["mitigation_confirmed"])
        with closing(sqlite3.connect(self.transport.journal.path)) as db:
            with db:
                db.execute("UPDATE live_submissions SET intent_json='{}' WHERE client_id LIKE 'RC-%'")
        self.assertEqual(self.reduce("CORRUPT_TERMS")["state"], "RECOVERY_REQUIRED")
        self.assertEqual(len(self.close_posts()), 1)

    def test_partial_native_exit_and_unexplained_flat_never_release(self):
        self.late_fill()
        self.venue.algos["native-stop-1"].update(algoStatus="FINISHED", actualOrderId="88")
        self.venue.algos["native-tp-1"]["algoStatus"] = "CANCELED"
        self.venue.orders["native-result"] = {"orderId": 88, "clientOrderId": "native-result", "symbol": "BTCUSDT",
            "side": "SELL", "positionSide": "BOTH", "reduceOnly": True, "status": "FILLED",
            "origQty": "0.5", "executedQty": "0.5", "cumQuote": "47.5"}
        self.venue.position = Decimal(0)
        result = self.coordinator.reconcile_native_exit_by_client_id("PROPOSAL_1", self.intent, event_id="EXTERNAL_FLAT")
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertIn("OWNED_EXITS_DO_NOT_EXPLAIN_ENTRY", result["reasons"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * runtime.U)

    def test_confirmed_reduction_plus_native_exit_explains_exact_flat_quantity(self):
        self.late_fill()
        self.coordinator.reduction_validator = lambda *args: True
        self.assertTrue(self.reduce()["mitigation_confirmed"])
        self.venue.algos["native-stop-1"].update(algoStatus="FINISHED", actualOrderId="88")
        self.venue.algos["native-tp-1"]["algoStatus"] = "CANCELED"
        self.venue.orders["native-result"] = {"orderId": 88, "clientOrderId": "native-result", "symbol": "BTCUSDT",
            "side": "SELL", "positionSide": "BOTH", "reduceOnly": True, "status": "FILLED",
            "origQty": "0.5", "executedQty": "0.5", "cumQuote": "47.5"}
        self.venue.position = Decimal(0)
        result = self.coordinator.reconcile_native_exit_by_client_id("PROPOSAL_1", self.intent, event_id="FULL_OWNED_EXIT")
        self.assertEqual(result["state"], "CLOSED")
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        # Closed position does not acknowledge/remove the financial recovery halt.
        self.assertIn("RESIDUAL_MITIGATED_FINANCIAL_RECONCILIATION_REQUIRED", self.admission.snapshot()["reasons"])

    def test_dispatch_fence_contains_exact_close_terms_before_post(self):
        self.late_fill()
        self.coordinator.reduction_validator = lambda *args: True
        original, checked = self.venue.open, []
        def check(request, timeout):
            if request.get_method() == "POST" and urllib.parse.urlsplit(request.full_url).path == "/fapi/v1/order":
                p = urllib.parse.parse_qs(request.data.decode())
                if p.get("reduceOnly") == ["true"]:
                    with closing(sqlite3.connect(self.transport.journal.path)) as db:
                        row = db.execute("SELECT state,reservation_id,intent_json FROM live_submissions WHERE client_id=?", (p["newClientOrderId"][0],)).fetchone()
                    self.assertEqual(row[:2], ("UNKNOWN", "PROPOSAL_1"))
                    stored = json.loads(row[2])
                    self.assertEqual(dict(stored["fields"])["quantity"], p["quantity"][0])
                    self.assertEqual(stored["purpose"], "CLOSE")
                    checked.append(True)
            return original(request, timeout)
        self.venue.open = check
        self.assertTrue(self.reduce()["mitigation_confirmed"])
        self.assertEqual(checked, [True])

    def test_legacy_unknown_fence_survives_migration_without_inventing_terms(self):
        path = self.directory / "LIVE_SUBMISSION_legacy.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute("CREATE TABLE live_journal_meta (version INTEGER NOT NULL CHECK(version=1))")
                db.execute("INSERT INTO live_journal_meta VALUES (1)")
                db.execute("CREATE TABLE live_submissions (nonce TEXT PRIMARY KEY,scope TEXT NOT NULL,account TEXT NOT NULL,client_id TEXT NOT NULL,method TEXT NOT NULL,endpoint TEXT NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,evidence_digest TEXT,UNIQUE(scope,account,method,endpoint,client_id))")
                pair = self.transport._credentials["FUTURES_LIVE"]
                db.execute("INSERT INTO live_submissions VALUES (?,?,?,?,?,?,?,?,?)", ("legacy", "FUTURES_LIVE", pair.fingerprint(),
                    self.intent.client_id, self.intent.method, self.intent.endpoint, self.intent.digest(), "UNKNOWN", None))
        journal = LiveSubmissionJournal(path)
        receipt = journal.receipt("FUTURES_LIVE", pair.fingerprint(), self.intent.method, self.intent.endpoint, self.intent.client_id)
        self.assertEqual(receipt["state"], "UNKNOWN")
        self.assertFalse(receipt["resend_permitted"])
        self.assertEqual(journal.owned_intents("FUTURES_LIVE", pair.fingerprint(), "PROPOSAL_1", "ENTRY"), ())


class SpotOwnedResidualRecoveryTests(unittest.TestCase):
    setUp = runtime.SpotLiveCoordinatorTests.setUp
    plan = runtime.SpotLiveCoordinatorTests.plan

    def late_fill(self):
        self.transport.max_calls = 500
        original = self.venue.open
        self.venue.base_fee = Decimal("0.0005")
        self.late, self.sell_base_fee, self.extra = False, Decimal(0), Decimal(0)
        self.close_posts = []
        def venue(request, timeout):
            method, url = request.get_method(), urllib.parse.urlsplit(request.full_url)
            values = urllib.parse.parse_qs((request.data or url.query.encode()).decode())
            fields = {key: value[0] for key, value in values.items()}
            if method == "DELETE" and url.path == "/api/v3/order":
                raise TimeoutError("synthetic uncertain entry cancellation")
            if method == "POST" and url.path == "/api/v3/order" and fields["side"] == "SELL":
                self.close_posts.append(fields)
                quantity = Decimal(fields["quantity"])
                self.venue.quantity -= quantity + self.sell_base_fee
                raw = {"clientOrderId": fields["newClientOrderId"], "symbol": fields["symbol"], "side": "SELL",
                    "status": "FILLED", "origQty": fields["quantity"], "executedQty": fields["quantity"],
                    "cummulativeQuoteQty": str(quantity * 100), "orderId": 888}
                self.venue.orders[fields["newClientOrderId"]] = raw
                return runtime.Response(raw)
            if method == "GET" and url.path == "/api/v3/account":
                locked = Decimal(self.venue.orders["spot-sl-1"]["origQty"]) if self.venue.lists else Decimal(0)
                return runtime.Response({"balances": [{"asset": "BTC", "free": str(self.venue.quantity + self.extra - locked), "locked": str(locked)}]})
            if method == "GET" and url.path == "/api/v3/myTrades" and fields["orderId"] == "888":
                order = next(row for row in self.venue.orders.values() if row.get("orderId") == 888)
                return runtime.Response([{"id": 888, "orderId": 888, "symbol": "BTCUSDT", "isBuyer": False,
                    "qty": order["executedQty"], "quoteQty": order["cummulativeQuoteQty"],
                    "commission": str(self.sell_base_fee) if self.sell_base_fee else "0.01", "commissionAsset": "BTC" if self.sell_base_fee else "USDT"}])
            response = original(request, timeout)
            if method == "POST" and url.path == "/api/v3/order" and fields["side"] == "BUY":
                self.venue.orders[self.intent.client_id].update(status="PARTIALLY_FILLED", executedQty="0.5", cummulativeQuoteQty="50")
                self.venue.quantity = Decimal("0.4995")
            return response
        self.venue.open = venue
        result = self.coordinator.execute_entry(self.proposal, runtime.facts(self.scope), self.intent, event_id="SPOT_PARTIAL")
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.venue.orders[self.intent.client_id].update(status="FILLED", executedQty="1", cummulativeQuoteQty="100")
        self.venue.base_fee = Decimal("0.001")
        self.venue.quantity = Decimal("0.999")
        self.clock.value += 1

    def test_spot_residual_uses_net_base_and_preserves_original_oco(self):
        self.late_fill()
        self.coordinator.reduction_validator = lambda *args: True
        result = self.coordinator.mitigate_residual_by_client_id("SPOT_PROPOSAL_1", self.intent, event_id="SPOT_REDUCE")
        self.assertTrue(result["mitigation_confirmed"])
        self.assertEqual(self.close_posts[0]["quantity"], "0.4995")
        self.assertEqual(self.venue.quantity, Decimal("0.4995"))
        self.assertEqual(self.venue.orders["spot-sl-1"]["origQty"], "0.4995")
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * runtime.U)

    def test_spot_external_base_or_unknown_fee_policy_prevents_reduction(self):
        self.late_fill()
        self.extra = Decimal("0.001")
        self.coordinator.reduction_validator = lambda *args: True
        result = self.coordinator.mitigate_residual_by_client_id("SPOT_PROPOSAL_1", self.intent, event_id="EXTRA_BASE")
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.close_posts, [])
        self.extra = Decimal(0)
        self.coordinator.reduction_validator = lambda *args: False
        self.coordinator.mitigate_residual_by_client_id("SPOT_PROPOSAL_1", self.intent, event_id="UNKNOWN_FEES")
        self.assertEqual(self.close_posts, [])


class ExactExecutionTests(unittest.TestCase):
    def setUp(self):
        from test_live_preproduction import intent
        self.intent = intent()
        self.raw = {"clientOrderId": self.intent.client_id, "symbol": "BTCUSDT", "side": "BUY", "status": "FILLED",
            "origQty": "0.001", "executedQty": "0.001", "cummulativeQuoteQty": "100", "orderId": 7}
        self.trade = {"id": 77, "orderId": 7, "symbol": "BTCUSDT", "isBuyer": True, "qty": "0.001", "quoteQty": "100",
            "commission": "0.000001", "commissionAsset": "BTC"}

    def test_base_fees_and_all_cost_assets_are_retained_without_pnl(self):
        cut = exact_execution(self.intent, self.raw, [self.trade])
        self.assertEqual(cut.executed - cut.base_fee, Decimal("0.000999"))
        self.assertEqual(cut.fees, (("BTC", "0.000001"),))
        close = replace(self.intent, purpose="CLOSE", fields=tuple((dict(self.intent.fields) | {"side": "SELL"}).items()))
        sold = exact_execution(close, self.raw | {"side": "SELL"}, [self.trade | {"isBuyer": False}])
        self.assertEqual(sold.executed + sold.base_fee, Decimal("0.001001"))

    def test_duplicate_wrong_side_wrong_order_and_incomplete_costs_are_rejected(self):
        for trades in ([self.trade, self.trade], [], [self.trade | {"isBuyer": False}], [self.trade | {"orderId": 8}],
                       [self.trade | {"commission": None}], [self.trade | {"quoteQty": "99"}]):
            with self.subTest(trades=trades), self.assertRaises(LiveError):
                exact_execution(self.intent, self.raw, trades)


if __name__ == "__main__":
    unittest.main()
