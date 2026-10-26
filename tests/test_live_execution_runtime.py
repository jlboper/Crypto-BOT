"""Prepared production workflow exercised through fake HTTPS only."""
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

from trader.central_admission import CentralAdmission, EntryProposal, OperatingCapability, Scope
from trader.live_transport import ExecutionGrant, LiveError, LiveOrderIntent, LiveOrderTransport, LiveSubmissionJournal
from trader.live_execution_runtime import LiveExecutionCoordinator, NativeProtectionPlan
from tests.test_central_admission import Clock, NOW, U, facts, policy
from tests.test_live_preproduction import pair, Response


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SyntheticOwner:
    """Explicit fake owner, never a default authorization."""
    def __init__(self):
        self.enabled, self.cap_calls, self.protective_calls = True, 0, 0

    def capability(self, scope, policy_fingerprint, terms_fingerprint, now):
        self.cap_calls += 1
        if not self.enabled:
            raise LiveError("SYNTHETIC_OWNER_REVOKED")
        return OperatingCapability(scope, policy_fingerprint, terms_fingerprint, "SYNTHETIC_OWNER",
                                   now - 1, now + 30, "SYNTHETIC_APPROVAL_ONLY")

    def verifier(self, capability, **bindings):
        return self.enabled and capability.proof == "SYNTHETIC_APPROVAL_ONLY"

    def grant(self, intent, *, claim_id, reservation_id, terms_fingerprint, capability, now):
        return ExecutionGrant(intent.digest(), "GRANT-" + digest([intent.digest(), claim_id]), reservation_id,
            "SYNTHETIC_OWNER", intent.policy_digest, pair().fingerprint(), intent.expires_utc_ms,
            "ENTRY-" + digest([claim_id, terms_fingerprint, intent.digest()]))

    def verify_grant(self, grant, intent, *, claim, now):
        return (self.enabled and grant.reservation_id == claim["ticket_id"] and grant.intent_digest == intent.digest()
            and grant.proof == "ENTRY-" + digest([claim["claim_id"], claim["terms_fingerprint"], intent.digest()]))

    def protective_grant(self, intent, position, *, now):
        self.protective_calls += 1
        return ExecutionGrant(intent.digest(), "EXIT-" + digest([intent.digest(), position.fingerprint]), position.ticket_id,
            "SYNTHETIC_OWNER", intent.policy_digest, pair().fingerprint(), intent.expires_utc_ms,
            "PROTECTIVE-" + digest([intent.digest(), position.fingerprint]))

    def verify_protective_grant(self, grant, intent, position, *, now):
        return grant.proof == "PROTECTIVE-" + digest([intent.digest(), position.fingerprint])


class FakeVenue:
    def __init__(self, admission, *, status="FILLED", fail_entry=False, fail_native=False):
        self.admission = admission
        self.status, self.fail_entry, self.fail_native = status, fail_entry, fail_native
        self.orders, self.algos, self.requests = {}, {}, []
        self.position = Decimal(0)
        self.before_dispatch_states, self.bad_native = [], False

    def open(self, request, timeout):
        method, url = request.get_method(), urllib.parse.urlsplit(request.full_url)
        params = urllib.parse.parse_qs((request.data or url.query.encode()).decode())
        p = {key: value[0] for key, value in params.items()}
        self.requests.append((method, url.path, p))
        if url.path.endswith("/time"):
            return Response({"serverTime": int(NOW * 1000)})
        if method == "POST" and url.path == "/fapi/v1/order":
            client = p["newClientOrderId"]
            if p.get("reduceOnly") == "true":
                status, executed = "FILLED", Decimal(p["quantity"])
                self.position += executed if p["side"] == "BUY" else -executed
            else:
                with closing(sqlite3.connect(self.admission.path)) as db:
                    self.before_dispatch_states.append(db.execute("SELECT state FROM tickets").fetchone()[0])
                    self.assert_consumed = db.execute("SELECT COUNT(*) FROM transport_grants").fetchone()[0] == 1
                status = self.status
                executed = Decimal(p["quantity"]) if status == "FILLED" else Decimal(p["quantity"]) / 2 if status == "PARTIALLY_FILLED" else Decimal(0)
                self.position = executed if p["side"] == "BUY" else -executed
            self.orders[client] = {"clientOrderId": client, "symbol": p["symbol"], "side": p["side"],
                "status": status, "origQty": p["quantity"], "executedQty": str(executed), "cumQuote": str(executed * 100), "orderId": len(self.orders) + 1}
            if self.fail_entry and p.get("reduceOnly") == "false":
                raise TimeoutError("synthetic unknown after venue execution")
            return Response(self.orders[client])
        if method == "GET" and url.path == "/fapi/v1/order":
            return Response(self.orders[p["origClientOrderId"]] if "origClientOrderId" in p else next(row for row in self.orders.values() if row["orderId"] == int(p["orderId"])))
        if method == "GET" and url.path == "/fapi/v3/positionRisk":
            return Response([{"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": str(self.position)}])
        if method == "POST" and url.path == "/fapi/v1/algoOrder":
            client = p["clientAlgoId"]
            self.algos[client] = {"clientAlgoId": client, "symbol": p["symbol"], "side": p["side"],
                "positionSide": p["positionSide"], "algoStatus": "NEW", "orderType": p["type"], "quantity": p["quantity"],
                "triggerPrice": p["triggerPrice"], "reduceOnly": not self.bad_native, "priceProtect": True, "workingType": p["workingType"]}
            if self.fail_native:
                raise TimeoutError("synthetic unknown native submission")
            return Response(self.algos[client])
        if method == "GET" and url.path == "/fapi/v1/algoOrder":
            return Response(self.algos[p["clientAlgoId"]])
        if method == "DELETE" and url.path == "/fapi/v1/algoOrder":
            self.algos[p["clientAlgoId"]]["algoStatus"] = "CANCELED"
            return Response({"code": 200})
        if method == "GET" and url.path == "/fapi/v1/openOrders":
            return Response([row for row in self.orders.values() if row["status"] in {"NEW", "PARTIALLY_FILLED"}])
        if method == "GET" and url.path == "/fapi/v1/openAlgoOrders":
            return Response([row for row in self.algos.values() if row["algoStatus"] == "NEW"])
        raise AssertionError("Unexpected synthetic route: " + method + " " + url.path)


class LiveCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.clock, self.policy = Clock(), policy()
        self.scope = Scope("SYNTHETIC_LIVE_ACCOUNT", "FUTURES_LIVE", "USDT")
        self.owner = SyntheticOwner()
        self.admission = CentralAdmission(self.directory / "central-admission-live.sqlite3", scope=self.scope,
            policy=self.policy, clock=self.clock, capability_verifier=self.owner.verifier)
        self.admission.initialize()
        self.transport = LiveOrderTransport({"FUTURES_LIVE": pair()},
            journal=LiveSubmissionJournal(self.directory / "LIVE_SUBMISSION_synthetic.sqlite3"), clock=self.clock, monotonic=lambda: 0)
        self.coordinator = LiveExecutionCoordinator(self.admission, self.transport, provider=self.owner,
            protection_factory=self.plan, clock=self.clock)
        self.venue = FakeVenue(self.admission)
        self.patch = patch.object(self.transport, "_opener", return_value=self.venue)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.intent, self.proposal = self.make_entry()

    def plan(self, proposal, entry, position, now):
        quantity = position.quantity if position is not None else dict(entry.fields)["quantity"]
        result = []
        for client, kind, price in (("native-stop-1", "STOP_MARKET", "95"), ("native-tp-1", "TAKE_PROFIT_MARKET", "110")):
            fields = {"symbol": "BTCUSDT", "side": "SELL", "type": kind, "quantity": quantity, "clientAlgoId": client,
                      "algoType": "CONDITIONAL", "triggerPrice": price, "workingType": "MARK_PRICE", "priceProtect": "TRUE",
                      "positionSide": "BOTH", "reduceOnly": "true"}
            result.append(LiveOrderIntent("FUTURES_LIVE", "PROTECT", "POST", "/fapi/v1/algoOrder", tuple(fields.items()),
                client, self.policy.fingerprint, int(now * 1000) + 20_000))
        return NativeProtectionPlan(tuple(result))

    def make_entry(self):
        fields = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "1", "type": "MARKET", "newClientOrderId": "entry-1",
                  "positionSide": "BOTH", "reduceOnly": "false"}
        initial = LiveOrderIntent("FUTURES_LIVE", "ENTRY", "POST", "/fapi/v1/order", tuple(fields.items()),
            "entry-1", self.policy.fingerprint, int(self.clock() * 1000) + 20_000)
        plan = self.plan(None, initial, None, self.clock())
        risk = {"quantity": "1", "reference_price": "100", "stop_price": "95", "reference_utc_ms": str(int(self.clock() * 1000)),
                "protection_plan_fingerprint": plan.terms_fingerprint}
        value = replace(initial, risk_terms=tuple(risk.items()))
        proposal = EntryProposal("PROPOSAL_1", self.scope, "FUTURES", "BTCUSDT", "LONG", 100 * U, 100 * U, 2 * U,
            7 * U, 1000, "CRYPTO_FACTOR", self.clock(), value.expires_utc_ms / 1000, 10, 10, 5, 1000 * U,
            True, True, True, "SYNTHETIC_STRATEGY_V1", value.digest())
        return value, proposal

    def execute(self, event="ENTRY_1", account_facts=None):
        return self.coordinator.execute_entry(self.proposal, account_facts or facts(self.scope), self.intent, event_id=event)

    def test_complete_entry_uses_central_atomic_handoff_native_verification(self):
        result = self.execute()
        self.assertEqual(result["state"], "OPEN")
        self.assertTrue(result["protection_verified"])
        self.assertFalse(result["reservation_release_allowed"])
        self.assertEqual(self.venue.before_dispatch_states, ["UNKNOWN"])
        self.assertTrue(self.venue.assert_consumed)
        self.assertEqual(sum(m == "POST" and path == "/fapi/v1/order" for m, path, _ in self.venue.requests), 1)
        self.assertEqual(sum(m == "POST" and path == "/fapi/v1/algoOrder" for m, path, _ in self.venue.requests), 2)
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)
        with closing(sqlite3.connect(self.admission.path)) as db:
            self.assertTrue(db.execute("SELECT nonce FROM transport_grants").fetchone()[0].startswith("GRANT-"))

    def test_default_owner_absent_never_reserves_or_networks(self):
        self.coordinator.provider = None
        self.assertEqual(self.execute()["state"], "BLOCKED")
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        self.assertEqual(self.venue.requests, [])

    def test_exact_notional_risk_quantity_and_plan_bindings(self):
        for mutation in ({"gross_units": 101 * U, "principal_units": 101 * U}, {"inclusive_stop_risk_units": 8 * U},
                         {"execution_plan_fingerprint": "b" * 64}, {"engine_id": "QUANT"}):
            with self.subTest(mutation=mutation), self.assertRaises(LiveError):
                self.coordinator.execute_entry(replace(self.proposal, **mutation), facts(self.scope), self.intent, event_id="INVALID")
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        self.assertEqual(self.venue.requests, [])

    def test_changed_native_client_ids_cannot_pass_plan_hash(self):
        original = self.coordinator.protection_factory
        def changed(proposal, entry, position, now):
            plan = original(proposal, entry, position, now)
            first = plan.intents[0]
            fields = dict(first.fields) | {"clientAlgoId": "new-unapproved-stop"}
            return NativeProtectionPlan((replace(first, fields=tuple(fields.items()), client_id="new-unapproved-stop"), plan.intents[1]))
        self.coordinator.protection_factory = changed
        with self.assertRaisesRegex(LiveError, "PROTECTION_PLAN_BINDING"):
            self.execute()
        self.assertEqual(self.venue.requests, [])

    def test_duplicate_entry_and_restart_can_only_reconcile(self):
        self.execute()
        posts = sum(method == "POST" for method, _, _ in self.venue.requests)
        self.assertEqual(self.execute()["state"], "RECONCILIATION_REQUIRED")
        transport = LiveOrderTransport({"FUTURES_LIVE": pair()}, journal=self.transport.journal, clock=self.clock, monotonic=lambda: 0)
        restarted = LiveExecutionCoordinator(self.admission, transport, provider=self.owner, protection_factory=self.plan, clock=self.clock)
        with patch.object(transport, "_opener", return_value=self.venue):
            result = restarted.reconcile_by_client_id(self.proposal.proposal_id, self.intent, event_id="AFTER_RESTART")
        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(sum(method == "POST" for method, _, _ in self.venue.requests), posts)

    def test_timeout_after_fill_unknown_then_exact_get_no_entry_retry(self):
        self.venue.fail_entry = True
        self.assertEqual(self.execute()["state"], "UNKNOWN")
        self.assertEqual(self.admission.ticket_terms("PROPOSAL_1")["state"], "UNKNOWN")
        self.venue.fail_entry = False
        self.assertEqual(self.coordinator.reconcile_by_client_id("PROPOSAL_1", self.intent, event_id="GET_AFTER_TIMEOUT")["state"], "OPEN")
        self.assertEqual(sum(m == "POST" and path == "/fapi/v1/order" for m, path, _ in self.venue.requests), 1)

    def test_partial_fill_keeps_entire_reservation_and_protects_confirmed_quantity(self):
        self.venue.status = "PARTIALLY_FILLED"
        result = self.execute()
        self.assertEqual(result["state"], "PARTIAL")
        self.assertEqual(result["position"].quantity, "0.5")
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)
        self.assertEqual({row["quantity"] for row in self.venue.algos.values()}, {"0.5"})

    def test_new_ack_not_fill_or_open_and_capital_retained(self):
        self.venue.status = "NEW"
        result = self.execute()
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertNotIn("protection_verified", result)
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)
        self.assertFalse(self.venue.algos)

    def test_cancelled_unfilled_releases_after_sibling_queries(self):
        self.venue.status = "CANCELED"
        result = self.execute()
        self.assertEqual(result["state"], "CANCELLED")
        self.assertTrue(result["reservation_release_allowed"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        self.assertTrue(any(path == "/fapi/v1/openAlgoOrders" for _, path, _ in self.venue.requests))

    def test_uncertain_native_latches_recovery_without_native_resend(self):
        self.venue.fail_native = True
        self.assertEqual(self.execute()["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.admission.ticket_terms("PROPOSAL_1")["state"], "RECOVERY_REQUIRED")
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)
        self.assertIn("NATIVE_STOP_NOT_VERIFIED", self.admission.snapshot()["reasons"])
        self.venue.fail_native = False
        self.coordinator.reconcile_by_client_id("PROPOSAL_1", self.intent, event_id="GET_PROTECTION")
        self.assertEqual(sum(m == "POST" and path == "/fapi/v1/algoOrder" and p["clientAlgoId"] == "native-stop-1" for m, path, p in self.venue.requests), 1)
        self.assertEqual(self.admission.snapshot()["state"], "RECOVERY_REQUIRED")

    def test_native_without_reduce_only_never_certifies_protection(self):
        self.venue.bad_native = True
        result = self.execute()
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertNotIn("protection_verified", result)

    def test_stale_or_incomplete_facts_block_before_network(self):
        for account in (replace(facts(self.scope), observed_at=NOW - 31), replace(facts(self.scope), identity_verified=False),
                        replace(facts(self.scope), orders_reconciled=False)):
            result = self.execute(event="BAD-" + digest(str(account)), account_facts=account)
            self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(self.venue.requests, [])

    def test_protective_close_ignores_entry_halt_and_ack_does_not_release(self):
        position = self.execute()["position"]
        self.admission.set_manual_halt(True, actor="OWNER", event_id="MANUAL_HALT")
        fields = {"symbol": "BTCUSDT", "side": "SELL", "quantity": "1", "type": "MARKET", "newClientOrderId": "close-1",
                  "positionSide": "BOTH", "reduceOnly": "true"}
        close = LiveOrderIntent("FUTURES_LIVE", "CLOSE", "POST", "/fapi/v1/order", tuple(fields.items()), "close-1",
            self.policy.fingerprint, int(self.clock() * 1000) + 20_000)
        cap_calls = self.owner.cap_calls
        answer = self.coordinator.execute_protective(close, position, event_id="PROTECTIVE_CLOSE")
        self.assertEqual(answer["state"], "ACK_REQUIRES_RECONCILIATION")
        self.assertEqual(self.owner.cap_calls, cap_calls)
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)
        held = self.coordinator.reconcile_exit_by_client_id("PROPOSAL_1", self.intent, close, event_id="EXIT_GET_1")
        self.assertEqual(held["state"], "RECONCILIATION_REQUIRED")
        self.coordinator.cancel_native_after_flat("PROPOSAL_1", self.intent, event_id="FLAT_CANCEL")
        final = self.coordinator.reconcile_exit_by_client_id("PROPOSAL_1", self.intent, close, event_id="EXIT_GET_2")
        self.assertEqual(final["state"], "CLOSED")
        self.assertTrue(final["reservation_release_allowed"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        self.assertTrue(self.admission.snapshot()["losses"]["manual"])
        self.assertEqual(sum(method == "DELETE" for method, _, _ in self.venue.requests), 2)

    def test_native_cancel_refused_while_position_open(self):
        self.execute()
        with self.assertRaisesRegex(LiveError, "POSITION_NOT_FLAT"):
            self.coordinator.cancel_native_after_flat("PROPOSAL_1", self.intent, event_id="UNSAFE_CANCEL")
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.venue.requests))

    def test_actual_fill_over_budget_still_gets_native_stop_before_recovery(self):
        original = self.venue.open
        def higher_price(request, timeout):
            response = original(request, timeout)
            if request.get_method() == "GET" and urllib.parse.urlsplit(request.full_url).path == "/fapi/v1/order":
                raw = json.loads(response.raw)
                raw["cumQuote"] = "101"
                return Response(raw)
            return response
        with patch.object(self.venue, "open", side_effect=higher_price):
            result = self.execute()
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertIn("ACTUAL_FILL_EXCEEDS_RESERVED_PRINCIPAL", result["reasons"])
        self.assertIn("native-stop-1", self.venue.algos)
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)

    def test_futures_short_uses_buy_reduce_only_protection(self):
        original_plan = self.plan
        def short_plan(proposal, entry, position, now):
            plan = original_plan(proposal, entry, position, now)
            legs = []
            for leg in plan.intents:
                fields = dict(leg.fields)
                fields.update(side="BUY", triggerPrice="105" if fields["type"] == "STOP_MARKET" else "90")
                legs.append(replace(leg, fields=tuple(fields.items())))
            return NativeProtectionPlan(tuple(legs))
        self.coordinator.protection_factory = short_plan
        fields = dict(self.intent.fields) | {"side": "SELL"}
        metadata = dict(self.intent.risk_terms) | {"stop_price": "105"}
        preliminary = replace(self.intent, fields=tuple(fields.items()))
        metadata["protection_plan_fingerprint"] = short_plan(None, preliminary, None, self.clock()).terms_fingerprint
        self.intent = replace(preliminary, risk_terms=tuple(metadata.items()))
        self.proposal = replace(self.proposal, direction="SHORT", execution_plan_fingerprint=self.intent.digest())
        result = self.execute()
        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["position"].direction, "SHORT")
        self.assertEqual(self.venue.position, Decimal(-1))
        self.assertEqual({row["side"] for row in self.venue.algos.values()}, {"BUY"})

    def test_partial_protective_exit_never_releases_remaining_position_capital(self):
        position = self.execute()["position"]
        fields = {"symbol": "BTCUSDT", "side": "SELL", "quantity": "0.5", "type": "MARKET", "newClientOrderId": "partial-close-1",
                  "positionSide": "BOTH", "reduceOnly": "true"}
        close = LiveOrderIntent("FUTURES_LIVE", "CLOSE", "POST", "/fapi/v1/order", tuple(fields.items()), "partial-close-1",
            self.policy.fingerprint, int(self.clock() * 1000) + 20_000)
        self.coordinator.execute_protective(close, position, event_id="PARTIAL_CLOSE")
        result = self.coordinator.reconcile_exit_by_client_id("PROPOSAL_1", self.intent, close, event_id="PARTIAL_CLOSE_GET")
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertFalse(result["reservation_release_allowed"])
        self.assertEqual(self.venue.position, Decimal("0.5"))
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)

    def test_native_stop_fill_reconciles_read_only_after_flat_and_siblings_clear(self):
        self.execute()
        self.venue.algos["native-stop-1"].update(algoStatus="FINISHED", actualOrderId="88")
        self.venue.algos["native-tp-1"]["algoStatus"] = "CANCELED"
        self.venue.orders["native-result"] = {"orderId": 88, "symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH",
            "reduceOnly": True, "status": "FILLED", "executedQty": "1"}
        self.venue.position = Decimal(0)
        writes = sum(method != "GET" for method, _, _ in self.venue.requests)
        result = self.coordinator.reconcile_native_exit_by_client_id("PROPOSAL_1", self.intent, event_id="NATIVE_EXIT_GET")
        self.assertEqual(result["state"], "CLOSED")
        self.assertTrue(result["reservation_release_allowed"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        self.assertEqual(sum(method != "GET" for method, _, _ in self.venue.requests), writes)

    def test_flat_account_without_owned_exit_fill_is_not_released(self):
        self.execute()
        self.venue.position = Decimal(0)
        result = self.coordinator.reconcile_native_exit_by_client_id("PROPOSAL_1", self.intent, event_id="FLAT_UNKNOWN_CAUSE")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertFalse(result["reservation_release_allowed"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)


class FakeSpotVenue:
    def __init__(self, admission):
        self.admission, self.orders, self.lists, self.requests = admission, {}, {}, []
        self.base_fee = Decimal("0.001")
        self.quantity = Decimal(0)

    def open(self, request, timeout):
        method, url = request.get_method(), urllib.parse.urlsplit(request.full_url)
        params = urllib.parse.parse_qs((request.data or url.query.encode()).decode())
        p = {key: value[0] for key, value in params.items()}
        self.requests.append((method, url.path, p))
        if url.path.endswith("/time"):
            return Response({"serverTime": int(NOW * 1000)})
        if method == "POST" and url.path == "/api/v3/order":
            self.quantity = Decimal(p["quantity"]) - self.base_fee
            self.orders[p["newClientOrderId"]] = {"clientOrderId": p["newClientOrderId"], "symbol": p["symbol"],
                "side": p["side"], "status": "FILLED", "origQty": p["quantity"], "executedQty": p["quantity"],
                "cummulativeQuoteQty": "100", "orderId": 777}
            return Response(self.orders[p["newClientOrderId"]])
        if method == "GET" and url.path == "/api/v3/order":
            return Response(self.orders[p["origClientOrderId"]])
        if method == "GET" and url.path == "/api/v3/myTrades":
            return Response([{"id": 1, "orderId": 777, "symbol": "BTCUSDT", "qty": "1", "commission": str(self.base_fee), "commissionAsset": "BTC"}])
        if method == "GET" and url.path == "/api/v3/account":
            return Response({"balances": [{"asset": "BTC", "free": str(self.quantity), "locked": "0"}]})
        if method == "POST" and url.path == "/api/v3/orderList/oco":
            self.lists[p["listClientOrderId"]] = {"listClientOrderId": p["listClientOrderId"], "symbol": p["symbol"], "listOrderStatus": "EXECUTING"}
            for client, kind, price, stop in ((p["aboveClientOrderId"], p["aboveType"], p["abovePrice"], None),
                    (p["belowClientOrderId"], p["belowType"], p["belowPrice"], p["belowStopPrice"])):
                self.orders[client] = {"clientOrderId": client, "symbol": p["symbol"], "side": "SELL", "status": "NEW",
                    "type": kind, "origQty": p["quantity"], "price": price, "stopPrice": stop}
            return Response(self.lists[p["listClientOrderId"]])
        if method == "GET" and url.path == "/api/v3/orderList":
            return Response(self.lists[p["origClientOrderId"]])
        if method == "GET" and url.path == "/api/v3/openOrders":
            return Response([row for row in self.orders.values() if row["status"] in {"NEW", "PARTIALLY_FILLED"}])
        if method == "GET" and url.path == "/api/v3/openOrderList":
            return Response([row for row in self.lists.values() if row["listOrderStatus"] == "EXECUTING"])
        raise AssertionError("Unexpected synthetic Spot route: " + method + " " + url.path)


class SpotLiveCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock, self.policy = Clock(), policy()
        self.scope = Scope("SYNTHETIC_SPOT_ACCOUNT", "SPOT_LIVE", "USDT")
        self.owner = SyntheticOwner()
        directory = Path(self.temp.name)
        self.admission = CentralAdmission(directory / "central-admission-spot.sqlite3", scope=self.scope,
            policy=self.policy, clock=self.clock, capability_verifier=self.owner.verifier)
        self.admission.initialize()
        self.transport = LiveOrderTransport({"SPOT_LIVE": pair()}, journal=LiveSubmissionJournal(directory / "LIVE_SUBMISSION_spot.sqlite3"),
            clock=self.clock, monotonic=lambda: 0)
        self.coordinator = LiveExecutionCoordinator(self.admission, self.transport, provider=self.owner, protection_factory=self.plan, clock=self.clock)
        self.venue = FakeSpotVenue(self.admission)
        self.patch = patch.object(self.transport, "_opener", return_value=self.venue)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        fields = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "1", "type": "MARKET", "newClientOrderId": "spot-entry-1"}
        preliminary = LiveOrderIntent("SPOT_LIVE", "ENTRY", "POST", "/api/v3/order", tuple(fields.items()), "spot-entry-1",
            self.policy.fingerprint, int(self.clock() * 1000) + 20_000)
        metadata = {"quantity": "1", "reference_price": "100", "stop_price": "95", "reference_utc_ms": str(int(self.clock() * 1000)),
                    "protection_plan_fingerprint": self.plan(None, preliminary, None, self.clock()).terms_fingerprint}
        self.intent = replace(preliminary, risk_terms=tuple(metadata.items()))
        self.proposal = EntryProposal("SPOT_PROPOSAL_1", self.scope, "SPOT", "BTCUSDT", "LONG", 100 * U, 100 * U, 2 * U,
            7 * U, 1000, "CRYPTO_FACTOR", self.clock(), self.intent.expires_utc_ms / 1000, 10, 10, 5, 1000 * U,
            True, True, True, "SYNTHETIC_SPOT_STRATEGY", self.intent.digest())

    def plan(self, proposal, entry, position, now):
        quantity = position.quantity if position else dict(entry.fields)["quantity"]
        fields = {"symbol": "BTCUSDT", "side": "SELL", "quantity": quantity, "listClientOrderId": "spot-oco-1",
            "aboveClientOrderId": "spot-tp-1", "belowClientOrderId": "spot-sl-1", "aboveType": "LIMIT_MAKER", "abovePrice": "110",
            "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": "95", "belowPrice": "94.9", "belowTimeInForce": "GTC"}
        return NativeProtectionPlan((LiveOrderIntent("SPOT_LIVE", "PROTECT", "POST", "/api/v3/orderList/oco", tuple(fields.items()),
            "spot-oco-1", self.policy.fingerprint, int(now * 1000) + 20_000),))

    def test_spot_uses_net_base_quantity_after_commission_and_verifies_both_oco_legs(self):
        result = self.coordinator.execute_entry(self.proposal, facts(self.scope), self.intent, event_id="SPOT_ENTRY")
        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["position"].quantity, "0.999")
        self.assertTrue(result["protection_verified"])
        self.assertEqual(self.venue.orders["spot-sl-1"]["origQty"], "0.999")
        self.assertTrue(any(m == "GET" and p.get("origClientOrderId") == "spot-sl-1" for m, _, p in self.venue.requests))
        self.assertTrue(any(m == "GET" and p.get("origClientOrderId") == "spot-tp-1" for m, _, p in self.venue.requests))

    def test_spot_missing_fee_history_never_claims_full_quantity_or_protected(self):
        original = self.venue.open
        def missing_history(request, timeout):
            if urllib.parse.urlsplit(request.full_url).path == "/api/v3/myTrades":
                return Response([])
            return original(request, timeout)
        with patch.object(self.venue, "open", side_effect=missing_history):
            result = self.coordinator.execute_entry(self.proposal, facts(self.scope), self.intent, event_id="SPOT_FEES_UNKNOWN")
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertNotIn("protection_verified", result)
        self.assertFalse(self.venue.lists)
        self.assertEqual(self.admission.snapshot()["reserved_units"], 102 * U)

    def test_spot_native_oco_fill_requires_flat_wallet_and_no_siblings_before_release(self):
        self.coordinator.execute_entry(self.proposal, facts(self.scope), self.intent, event_id="SPOT_ENTRY")
        self.venue.orders["spot-sl-1"].update(status="FILLED", executedQty="0.999")
        self.venue.orders["spot-tp-1"].update(status="CANCELED", executedQty="0")
        self.venue.lists["spot-oco-1"]["listOrderStatus"] = "ALL_DONE"
        self.venue.quantity = Decimal(0)
        writes = sum(method != "GET" for method, _, _ in self.venue.requests)
        result = self.coordinator.reconcile_native_exit_by_client_id("SPOT_PROPOSAL_1", self.intent, event_id="SPOT_NATIVE_EXIT")
        self.assertEqual(result["state"], "CLOSED")
        self.assertTrue(result["reservation_release_allowed"])
        self.assertEqual(self.admission.snapshot()["reserved_units"], 0)
        self.assertEqual(sum(method != "GET" for method, _, _ in self.venue.requests), writes)


if __name__ == "__main__":
    unittest.main()
