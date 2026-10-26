"""Prepared single-process LIVE workflow, inactive without explicit components.

Quantitative terms, an authenticated local owner provider, durable central
admission and one durable transport fence are all required. No configuration,
credential discovery, background loop, transfer, wallet creation or AI is here.
Reconciliation reads exact client identifiers; HTTP success never means a fill.
Existing native stops remain at Binance independently of this component.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re
import threading
import time
from typing import Protocol

from .central_admission import (AdmissionError, AdmissionFacts, CentralAdmission,
    EntryProposal, OperatingCapability, Reconciliation, Scope)
from .live_transport import ExecutionGrant, LiveError, LiveOrderIntent, LiveOrderTransport, LiveSubmissionJournal

MICRO = Decimal(1_000_000)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _event(event_id, action):
    if type(event_id) is not str or not 1 <= len(event_id) <= 96:
        raise LiveError("LIVE_WORKFLOW_EVENT_ID_REQUIRED")
    return "LIVE-" + _hash([event_id, action])


def _decimal(value, *, signed=False):
    if type(value) not in {str, int} or len(str(value)) > 64:
        raise LiveError("LIVE_RECONCILIATION_NUMBER_UNKNOWN")
    try:
        result = Decimal(value)
        if not result.is_finite() or result.copy_abs() >= Decimal("1e15") or result.as_tuple().exponent < -18 or not signed and result < 0:
            raise ValueError()
    except (ValueError, InvalidOperation):
        raise LiveError("LIVE_RECONCILIATION_NUMBER_UNKNOWN") from None
    return result


def _ceil(value):
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class ConfirmedPosition:
    ticket_id: str
    scope: Scope
    symbol: str
    direction: str
    quantity: str
    entry_price: str
    executed_quantity: str
    cumulative_quote: str
    observed_at: float
    evidence_digest: str
    execution_complete: bool

    @property
    def fingerprint(self):
        return _hash(asdict(self))


@dataclass(frozen=True)
class NativeProtectionPlan:
    intents: tuple[LiveOrderIntent, ...]

    def __post_init__(self):
        if type(self.intents) is not tuple or not 1 <= len(self.intents) <= 2 or any(type(i) is not LiveOrderIntent or i.purpose != "PROTECT" for i in self.intents):
            raise LiveError("NATIVE_PROTECTION_PLAN_REQUIRED")
        if len({i.client_id for i in self.intents}) != len(self.intents):
            raise LiveError("DISTINCT_NATIVE_PROTECTION_IDENTIFIERS_REQUIRED")

    @property
    def terms_fingerprint(self):
        # Quantity is separately bound to the confirmed fill. Native identifiers
        # remain immutable across restart; only the short request expiry renews.
        ignored = {"quantity"}
        terms = [{"scope": i.scope, "method": i.method, "endpoint": i.endpoint,
                  "policy_digest": i.policy_digest, "fields": sorted((k, v) for k, v in i.fields if k not in ignored)} for i in self.intents]
        return _hash(sorted(terms, key=lambda x: json.dumps(x, sort_keys=True)))


class LocalAuthorizationProvider(Protocol):
    def capability(self, scope, policy_fingerprint, terms_fingerprint, now) -> OperatingCapability: ...
    def grant(self, intent, *, claim_id, reservation_id, terms_fingerprint, capability, now) -> ExecutionGrant: ...
    def verify_grant(self, grant, intent, *, claim, now) -> bool: ...
    def protective_grant(self, intent, position, *, now) -> ExecutionGrant: ...
    def verify_protective_grant(self, grant, intent, position, *, now) -> bool: ...


class LiveExecutionCoordinator:
    """Explicit dependency injection only. No default execution authority."""

    def __init__(self, admission, transport, *, provider=None, protection_factory=None, clock=time.time):
        if type(admission) is not CentralAdmission or admission.scope.environment not in {"SPOT_LIVE", "FUTURES_LIVE"}:
            raise LiveError("DEDICATED_LIVE_ADMISSION_REQUIRED")
        if type(transport) is not LiveOrderTransport or type(transport.journal) is not LiveSubmissionJournal or transport.authority is not None:
            raise LiveError("UNOWNED_DEDICATED_LIVE_TRANSPORT_REQUIRED")
        if admission.scope.environment not in transport._credentials:
            raise LiveError("LIVE_TRANSPORT_SCOPE_MISMATCH")
        self.admission, self.transport = admission, transport
        self.provider, self.protection_factory, self.clock = provider, protection_factory, clock
        self._pending, self._lock = {}, threading.Lock()
        transport.authority = self

    def _result(self, state, *, reasons=(), **values):
        return {"state": state, "reasons": list(reasons), "automatic_activation": False,
                "live_mode_selected": False, "reservation_release_allowed": False, **values}

    def _recovery(self, ticket_id, reason, event_id):
        self.admission.mark_recovery(ticket_id, reason, event_id=_event(event_id, "recovery:" + reason))
        return self._result("RECOVERY_REQUIRED", reasons=[reason], ticket_id=ticket_id)

    def _terms(self, proposal, facts, intent):
        if type(proposal) is not EntryProposal or type(facts) is not AdmissionFacts or type(intent) is not LiveOrderIntent:
            raise LiveError("TYPED_LIVE_WORKFLOW_TERMS_REQUIRED")
        expected_engine = "SPOT" if self.admission.scope.environment == "SPOT_LIVE" else "FUTURES"
        if proposal.scope != self.admission.scope or facts.scope != proposal.scope or intent.scope != proposal.scope.environment or proposal.engine_id != expected_engine or intent.purpose != "ENTRY":
            raise LiveError("LIVE_WORKFLOW_SCOPE_ENGINE_MISMATCH")
        if proposal.execution_plan_fingerprint != intent.digest() or intent.policy_digest != self.admission.policy.fingerprint:
            raise LiveError("LIVE_EXECUTION_PLAN_BINDING_MISMATCH")
        fields, terms = dict(intent.fields), dict(intent.risk_terms)
        required = {"quantity", "reference_price", "stop_price", "reference_utc_ms", "protection_plan_fingerprint"}
        if set(terms) != required or fields["symbol"] != proposal.symbol or fields["side"] != ("BUY" if proposal.direction == "LONG" else "SELL"):
            raise LiveError("LIVE_QUANTITATIVE_TERMS_REQUIRED")
        quantity, reference, stop = (_decimal(terms[key]) for key in ("quantity", "reference_price", "stop_price"))
        reference_at = int(terms["reference_utc_ms"]) / 1000
        if quantity <= 0 or reference <= 0 or stop <= 0 or _decimal(fields["quantity"]) != quantity:
            raise LiveError("LIVE_EXACT_QUANTITY_REQUIRED")
        if proposal.direction == "LONG" and stop >= reference or proposal.direction == "SHORT" and stop <= reference:
            raise LiveError("LIVE_STOP_DIRECTION_MISMATCH")
        if fields.get("type") == "LIMIT" and _decimal(fields.get("price")) != reference:
            raise LiveError("LIVE_LIMIT_REFERENCE_MISMATCH")
        if (not reference_at <= proposal.observed_at <= self.clock()
                or self.clock() - reference_at > self.admission.policy.max_data_age_seconds
                or intent.expires_utc_ms != int(proposal.expires_at * 1000)
                or not 0 < intent.expires_utc_ms - int(self.clock() * 1000) <= 30_000):
            raise LiveError("LIVE_PLAN_DATA_OR_EXPIRY_INVALID")
        gross = _ceil(quantity * reference * MICRO)
        stop_risk = _ceil(quantity * abs(reference - stop) * MICRO) + proposal.cost_buffer_units
        if gross != proposal.gross_units or stop_risk != proposal.inclusive_stop_risk_units:
            raise LiveError("LIVE_EXACT_NOTIONAL_STOP_RISK_MISMATCH")
        return quantity

    def _plan(self, proposal, entry_intent, position=None):
        if self.protection_factory is None:
            raise LiveError("NATIVE_PROTECTION_FACTORY_REQUIRED")
        plan = self.protection_factory(proposal, entry_intent, position, self.clock())
        if type(plan) is not NativeProtectionPlan or plan.terms_fingerprint != dict(entry_intent.risk_terms)["protection_plan_fingerprint"]:
            raise LiveError("NATIVE_PROTECTION_PLAN_BINDING_MISMATCH")
        quantity = _decimal(position.quantity if position else dict(entry_intent.fields)["quantity"])
        direction = proposal.direction
        for leg in plan.intents:
            fields = dict(leg.fields)
            if leg.scope != entry_intent.scope or leg.policy_digest != entry_intent.policy_digest or fields["symbol"] != proposal.symbol or fields["side"] != ("SELL" if direction == "LONG" else "BUY") or _decimal(fields["quantity"]) != quantity:
                raise LiveError("NATIVE_PROTECTION_POSITION_MISMATCH")
        stop = _decimal(dict(entry_intent.risk_terms)["stop_price"])
        if entry_intent.scope == "SPOT_LIVE":
            if len(plan.intents) != 1 or not plan.intents[0].endpoint.endswith("/oco") or _decimal(dict(plan.intents[0].fields)["belowStopPrice"]) != stop:
                raise LiveError("NATIVE_SPOT_STOP_REQUIRED")
        else:
            stops = [leg for leg in plan.intents if dict(leg.fields).get("type") == "STOP_MARKET"]
            if len(stops) != 1 or len({dict(leg.fields)["type"] for leg in plan.intents}) != len(plan.intents) or _decimal(dict(stops[0].fields)["triggerPrice"]) != stop:
                raise LiveError("NATIVE_FUTURES_STOP_REQUIRED")
        return plan

    def execute_entry(self, proposal, facts, intent, *, event_id):
        self._terms(proposal, facts, intent)
        self._plan(proposal, intent)  # Prove exact native protection terms first.
        if self.provider is None:
            return self._result("BLOCKED", reasons=["LOCAL_OWNER_AUTHORIZATION_REQUIRED"])
        capability = self.provider.capability(proposal.scope, self.admission.policy.fingerprint, proposal.fingerprint, self.clock())
        reserved = self.admission.assess_and_reserve(proposal, facts, event_id=_event(event_id, "reserve"), capability=capability)
        if not reserved.get("accepted"):
            return self._result("BLOCKED", reasons=reserved.get("reasons", []), admission=reserved)
        claimed = self.admission.claim(proposal.proposal_id, facts, event_id=_event(event_id, "claim"), capability=capability)
        if not claimed.get("new_claim_created") or not claimed.get("claim_ready_for_transport"):
            return self._result("RECONCILIATION_REQUIRED", reasons=["NO_NEW_SUBMISSION_CLAIM"], ticket_id=proposal.proposal_id)
        grant = self.provider.grant(intent, claim_id=claimed["claim_id"], reservation_id=proposal.proposal_id,
            terms_fingerprint=proposal.fingerprint, capability=capability, now=self.clock())
        if type(grant) is not ExecutionGrant:
            return self._recovery(proposal.proposal_id, "AUTHORIZATION_GRANT_UNAVAILABLE", event_id)
        context = {"kind": "ENTRY", "claim": claimed, "facts": facts, "capability": capability,
                   "intent_digest": intent.digest(), "event_id": event_id}
        with self._lock:
            if grant.nonce in self._pending:
                raise LiveError("DUPLICATE_LIVE_WORKFLOW_NONCE")
            self._pending[grant.nonce] = context
        try:
            response = self.transport.submit(intent, grant)
        except LiveError:
            response = {"state": "UNKNOWN"}
        finally:
            with self._lock:
                self._pending.pop(grant.nonce, None)
        if response.get("state") != "ACK_REQUIRES_RECONCILIATION":
            return self._result("UNKNOWN", reasons=["SUBMISSION_RECONCILIATION_REQUIRED"], ticket_id=proposal.proposal_id)
        return self.reconcile_by_client_id(proposal.proposal_id, intent, event_id=event_id)

    def consume(self, grant, intent, *, now_utc_ms):
        """Transport callback: durable central handoff immediately before HTTP."""
        with self._lock:
            context = self._pending.pop(grant.nonce, None)
        if context is None or self.provider is None or context["intent_digest"] != intent.digest():
            return False
        now = now_utc_ms / 1000
        if context["kind"] == "PROTECTIVE":
            return self.provider.verify_protective_grant(grant, intent, context["position"], now=now) is True
        claim = self.admission.get_claim(context["claim"]["claim_id"])
        if self.provider.verify_grant(grant, intent, claim=claim, now=now) is not True:
            return False
        result = self.admission.consume_transport_grant(claim["claim_id"], intent.digest(), context["facts"],
            event_id=_event(context["event_id"], "handoff:" + grant.nonce), capability=context["capability"], transport_nonce=grant.nonce)
        return result.get("transport_permitted") is True and result.get("new_grant_created") is True

    def _ticket(self, ticket_id, intent):
        ticket = self.admission.ticket_terms(ticket_id)
        terms = ticket["terms"]
        proposal = EntryProposal(**{**terms, "scope": Scope(**terms["scope"])})
        if intent.scope != proposal.scope.environment or proposal.execution_plan_fingerprint != intent.digest():
            raise LiveError("LIVE_RECONCILIATION_PLAN_MISMATCH")
        return proposal, ticket

    def _confirmed_fill(self, ticket_id, proposal, intent, raw):
        fields = dict(intent.fields)
        if type(raw) is not dict or raw.get("clientOrderId") != intent.client_id or raw.get("symbol") != proposal.symbol or raw.get("side") != fields["side"]:
            raise LiveError("LIVE_ORDER_IDENTITY_UNKNOWN")
        planned, executed = _decimal(fields["quantity"]), _decimal(raw.get("executedQty"))
        if _decimal(raw.get("origQty")) != planned or executed > planned:
            raise LiveError("LIVE_ORDER_QUANTITY_CONTRADICTION")
        status = raw.get("status")
        if status not in {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}:
            raise LiveError("LIVE_ORDER_STATUS_UNKNOWN")
        terminal = status in {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}
        if status == "FILLED" and executed != planned or status == "PARTIALLY_FILLED" and not 0 < executed < planned or status == "NEW" and executed:
            raise LiveError("LIVE_ORDER_STATUS_QUANTITY_CONTRADICTION")
        if not executed:
            return None, terminal
        quote = _decimal(raw.get("cummulativeQuoteQty") if intent.scope == "SPOT_LIVE" else raw.get("cumQuote"))
        if quote <= 0:
            raise LiveError("LIVE_EXECUTION_QUOTE_UNKNOWN")
        quantity = executed
        evidence = [raw]
        if intent.scope == "SPOT_LIVE":
            order_id = raw.get("orderId")
            if type(order_id) is not int or order_id < 0:
                raise LiveError("LIVE_ORDER_IDENTITY_UNKNOWN")
            trades = self.transport.get(intent.scope, "/api/v3/myTrades", {"symbol": proposal.symbol, "orderId": order_id, "limit": 1000})
            if type(trades) is not list or not 1 <= len(trades) < 1000:
                raise LiveError("LIVE_COMMISSION_RECONCILIATION_REQUIRED")
            seen, total, commission = set(), Decimal(0), Decimal(0)
            base = proposal.symbol[:-4]
            for trade in trades:
                trade_id = trade.get("id") if type(trade) is dict else None
                if type(trade_id) is not int or trade_id in seen or trade.get("orderId") != order_id or trade.get("symbol") != proposal.symbol:
                    raise LiveError("LIVE_COMMISSION_RECONCILIATION_REQUIRED")
                seen.add(trade_id)
                total += _decimal(trade.get("qty"))
                fee = _decimal(trade.get("commission"))
                asset = trade.get("commissionAsset")
                if type(asset) is not str:
                    raise LiveError("LIVE_COMMISSION_RECONCILIATION_REQUIRED")
                if asset == base:
                    commission += fee
            if total != executed or commission >= executed:
                raise LiveError("LIVE_COMMISSION_RECONCILIATION_REQUIRED")
            quantity = executed - commission
            account = self.transport.get(intent.scope, "/api/v3/account")
            balances = account.get("balances") if type(account) is dict else None
            if type(balances) is not list:
                raise LiveError("LIVE_POSITION_INVENTORY_UNKNOWN")
            matches = [row for row in balances if type(row) is dict and row.get("asset") == base]
            if len(matches) != 1 or _decimal(matches[0].get("free")) + _decimal(matches[0].get("locked")) < quantity:
                raise LiveError("LIVE_POSITION_INVENTORY_UNKNOWN")
            evidence += [trades, account]
        else:
            rows = self.transport.get(intent.scope, "/fapi/v3/positionRisk", {"symbol": proposal.symbol})
            matches = [row for row in rows if type(row) is dict and row.get("symbol") == proposal.symbol and row.get("positionSide") == "BOTH"] if type(rows) is list else []
            signed = quantity if proposal.direction == "LONG" else -quantity
            if len(matches) != 1 or _decimal(matches[0].get("positionAmt"), signed=True) != signed:
                raise LiveError("LIVE_POSITION_INVENTORY_UNKNOWN")
            evidence.append(rows)
        return ConfirmedPosition(ticket_id, proposal.scope, proposal.symbol, proposal.direction, format(quantity, "f"),
            format(quote / executed, "f"), format(executed, "f"), format(quote, "f"), self.clock(), _hash(evidence), terminal), terminal

    def _native_verified(self, intent, position):
        p = dict(intent.fields)
        raw = self.transport.reconcile(intent)
        if intent.scope == "FUTURES_LIVE":
            return (type(raw) is dict and raw.get("clientAlgoId") == intent.client_id and raw.get("symbol") == position.symbol
                and raw.get("side") == p["side"] and raw.get("positionSide") == "BOTH" and raw.get("algoStatus") == "NEW"
                and raw.get("orderType") == p["type"] and _decimal(raw.get("quantity")) == _decimal(position.quantity)
                and _decimal(raw.get("triggerPrice")) == _decimal(p["triggerPrice"])
                and (raw.get("reduceOnly") is True or type(raw.get("reduceOnly")) is str and raw["reduceOnly"] in {"true", "TRUE"})
                and (raw.get("priceProtect") is True or type(raw.get("priceProtect")) is str and raw["priceProtect"] in {"true", "TRUE"})
                and raw.get("workingType") == "MARK_PRICE")
        if type(raw) is not dict or raw.get("listClientOrderId") != intent.client_id or raw.get("symbol") != position.symbol or raw.get("listOrderStatus") != "EXECUTING":
            return False
        for client, kind, price, stop in ((p["aboveClientOrderId"], p["aboveType"], p["abovePrice"], None),
                                         (p["belowClientOrderId"], p["belowType"], p["belowPrice"], p["belowStopPrice"])):
            leg = self.transport.get(intent.scope, "/api/v3/order", {"symbol": position.symbol, "origClientOrderId": client})
            if (type(leg) is not dict or leg.get("clientOrderId") != client or leg.get("symbol") != position.symbol
                    or leg.get("side") != "SELL" or leg.get("type") != kind or leg.get("status") != "NEW"
                    or _decimal(leg.get("origQty")) != _decimal(position.quantity)
                    or _decimal(leg.get("price")) != _decimal(price)
                    or stop is not None and _decimal(leg.get("stopPrice")) != _decimal(stop)):
                return False
        return True

    def _protective_dispatch(self, intent, position, *, event_id):
        if self.provider is None:
            raise LiveError("LOCAL_OWNER_PROTECTIVE_AUTHORIZATION_REQUIRED")
        grant = self.provider.protective_grant(intent, position, now=self.clock())
        if type(grant) is not ExecutionGrant:
            raise LiveError("LOCAL_OWNER_PROTECTIVE_AUTHORIZATION_REQUIRED")
        with self._lock:
            if grant.nonce in self._pending:
                raise LiveError("DUPLICATE_LIVE_WORKFLOW_NONCE")
            self._pending[grant.nonce] = {"kind": "PROTECTIVE", "intent_digest": intent.digest(), "position": position, "event_id": event_id}
        try:
            return self.transport.submit(intent, grant)
        finally:
            with self._lock:
                self._pending.pop(grant.nonce, None)

    def _ensure_protection(self, proposal, entry_intent, position, event_id):
        plan = self._plan(proposal, entry_intent, position)
        for leg in plan.intents:
            pair = self.transport._credentials[leg.scope]
            receipt = self.transport.journal.receipt(leg.scope, pair.fingerprint(), leg.method, leg.endpoint, leg.client_id)
            if receipt is None:
                # A new exact native ticket is submitted only once. UNKNOWN is
                # queried on the next pass; it is never automatically resubmitted.
                result = self._protective_dispatch(leg, position, event_id=event_id)
                if result.get("state") != "ACK_REQUIRES_RECONCILIATION":
                    return False
            if not self._native_verified(leg, position):
                return False
        return True

    def _no_sibling_orders(self, proposal):
        endpoints = (("/api/v3/openOrders", {"symbol": proposal.symbol}), ("/api/v3/openOrderList", {})) if proposal.scope.environment == "SPOT_LIVE" else (
            ("/fapi/v1/openOrders", {"symbol": proposal.symbol}), ("/fapi/v1/openAlgoOrders", {"symbol": proposal.symbol}))
        for endpoint, params in endpoints:
            rows = self.transport.get(proposal.scope.environment, endpoint, params)
            if type(rows) is not list or rows:
                return False
        return True

    def reconcile_by_client_id(self, ticket_id, intent, *, event_id):
        proposal, ticket = self._ticket(ticket_id, intent)
        if ticket.get("claim_id") is None:
            return self._result("UNKNOWN", reasons=["NO_SUBMISSION_CLAIM"], ticket_id=ticket_id)
        try:
            raw = self.transport.reconcile(intent)
            position, terminal = self._confirmed_fill(ticket_id, proposal, intent, raw)
            if position is None:
                if terminal and self._no_sibling_orders(proposal):
                    event = Reconciliation(_event(event_id, "cancelled:" + _hash(raw)), ticket_id, "BINANCE_LIVE_SIGNED_GET",
                        _event(event_id, "order-evidence:" + _hash(raw)), self.clock(), proposal.scope, "CANCELLED", 0, True, True, True)
                    result = self.admission.reconcile(event)
                    return self._result(result["state"], ticket_id=ticket_id, reservation_release_allowed=result.get("reservation_released", False))
                return self._result("UNKNOWN", reasons=["ORDER_PENDING_OR_SIBLINGS_UNCERTAIN"], ticket_id=ticket_id)
            principal = _ceil(_decimal(position.cumulative_quote) * MICRO * Decimal(1000) / Decimal(proposal.leverage_milli))
            if not self._ensure_protection(proposal, intent, position, event_id):
                return self._recovery(ticket_id, "NATIVE_STOP_NOT_VERIFIED", event_id)
            if principal > proposal.principal_units:
                # A budget violation still gets native protection first. It may
                # block entries, never suppress an existing position's stop.
                return self._recovery(ticket_id, "ACTUAL_FILL_EXCEEDS_RESERVED_PRINCIPAL", event_id)
            state = "OPEN" if terminal else "PARTIAL"
            event = Reconciliation(_event(event_id, "position:" + position.evidence_digest), ticket_id, "BINANCE_LIVE_SIGNED_GET",
                _event(event_id, "position-evidence:" + position.evidence_digest), position.observed_at, proposal.scope, state, principal, terminal, False, False)
            result = self.admission.reconcile(event)
            if not result.get("accepted"):
                return self._result("RECOVERY_REQUIRED", reasons=result.get("reasons", []), ticket_id=ticket_id)
            return self._result(state, ticket_id=ticket_id, protection_verified=True, position=position)
        except (LiveError, AdmissionError):
            return self._recovery(ticket_id, "LIVE_RECONCILIATION_OR_PROTECTION_UNKNOWN", event_id)

    def execute_protective(self, intent, position, *, event_id):
        """No entry capability, loss-gate, Guardian or AI dependency."""
        if type(intent) is not LiveOrderIntent or type(position) is not ConfirmedPosition or intent.purpose not in {"PROTECT", "CLOSE"}:
            raise LiveError("CONFIRMED_PROTECTIVE_POSITION_REQUIRED")
        if position.scope != self.admission.scope or intent.scope != position.scope.environment or intent.policy_digest != self.admission.policy.fingerprint:
            raise LiveError("PROTECTIVE_SCOPE_POLICY_MISMATCH")
        ticket = self.admission.ticket_terms(position.ticket_id)
        terms = ticket["terms"]
        if ticket.get("claim_id") is None or terms["symbol"] != position.symbol or terms["direction"] != position.direction or ticket["state"] in {"CANCELLED", "CLOSED"}:
            raise LiveError("PROTECTIVE_OWNED_TICKET_REQUIRED")
        fields = dict(intent.fields)
        if fields["symbol"] != position.symbol or fields["side"] != ("SELL" if position.direction == "LONG" else "BUY") or not 0 < _decimal(fields["quantity"]) <= _decimal(position.quantity):
            raise LiveError("PROTECTIVE_QUANTITY_DIRECTION_MISMATCH")
        if not 0 <= self.clock() - position.observed_at <= self.admission.policy.max_data_age_seconds:
            raise LiveError("PROTECTIVE_POSITION_STALE")
        # Confirm current venue quantity immediately, independently of entry risk.
        if intent.scope == "FUTURES_LIVE":
            rows = self.transport.get(intent.scope, "/fapi/v3/positionRisk", {"symbol": position.symbol})
            matches = [r for r in rows if type(r) is dict and r.get("symbol") == position.symbol and r.get("positionSide") == "BOTH"] if type(rows) is list else []
            signed = _decimal(position.quantity) * (1 if position.direction == "LONG" else -1)
            if len(matches) != 1 or _decimal(matches[0].get("positionAmt"), signed=True) != signed:
                raise LiveError("PROTECTIVE_POSITION_NOT_CONFIRMED")
        else:
            account = self.transport.get(intent.scope, "/api/v3/account")
            matches = [r for r in account.get("balances", []) if type(r) is dict and r.get("asset") == position.symbol[:-4]] if type(account) is dict else []
            if len(matches) != 1 or _decimal(matches[0].get("free")) + _decimal(matches[0].get("locked")) < _decimal(position.quantity):
                raise LiveError("PROTECTIVE_POSITION_NOT_CONFIRMED")
        result = self._protective_dispatch(intent, position, event_id=event_id)
        # Entry capital is deliberately retained until a separate position-zero
        # plus sibling-order reconciliation, not merely a close-order ACK.
        return self._result(result["state"], ticket_id=position.ticket_id, protective_request=True)

    def _flat_position(self, ticket_id, entry_intent):
        proposal, ticket = self._ticket(ticket_id, entry_intent)
        if ticket.get("claim_id") is None:
            raise LiveError("OWNED_SUBMISSION_CLAIM_REQUIRED")
        raw = self.transport.reconcile(entry_intent)
        entry_fields = dict(entry_intent.fields)
        if (type(raw) is not dict or raw.get("clientOrderId") != entry_intent.client_id or raw.get("symbol") != proposal.symbol
                or raw.get("side") != entry_fields["side"] or _decimal(raw.get("origQty")) != _decimal(entry_fields["quantity"])
                or not 0 < _decimal(raw.get("executedQty")) <= _decimal(entry_fields["quantity"])):
            raise LiveError("OWNED_ENTRY_EXECUTION_UNKNOWN")
        if entry_intent.scope == "FUTURES_LIVE":
            current = self.transport.get(entry_intent.scope, "/fapi/v3/positionRisk", {"symbol": proposal.symbol})
            if type(current) is not list or any(type(row) is not dict or row.get("symbol") != proposal.symbol or row.get("positionSide") != "BOTH" or _decimal(row.get("positionAmt"), signed=True) != 0 for row in current):
                raise LiveError("POSITION_NOT_FLAT_OR_UNKNOWN")
        else:
            current = self.transport.get(entry_intent.scope, "/api/v3/account")
            balances = current.get("balances") if type(current) is dict else None
            rows = [row for row in balances if type(row) is dict and row.get("asset") == proposal.symbol[:-4]] if type(balances) is list else []
            if len(rows) != 1 or _decimal(rows[0].get("free")) + _decimal(rows[0].get("locked")) != 0:
                raise LiveError("POSITION_NOT_FLAT_OR_UNKNOWN")
        quote = _decimal(raw.get("cummulativeQuoteQty") if entry_intent.scope == "SPOT_LIVE" else raw.get("cumQuote"))
        executed = _decimal(raw.get("executedQty"))
        return proposal, ConfirmedPosition(ticket_id, proposal.scope, proposal.symbol, proposal.direction, "0",
            format(quote / executed, "f"), format(executed, "f"), format(quote, "f"), self.clock(), _hash([raw, current]), True)

    def cancel_native_after_flat(self, ticket_id, entry_intent, *, event_id):
        """Exact native targets only, after a fresh signed venue flat check."""
        proposal, position = self._flat_position(ticket_id, entry_intent)
        plan = self._plan(proposal, entry_intent)
        results = []
        for leg in plan.intents:
            endpoint = "/api/v3/orderList" if leg.scope == "SPOT_LIVE" else "/fapi/v1/algoOrder"
            key = "origClientOrderId" if leg.scope == "SPOT_LIVE" else "clientAlgoId"
            fields = {key: leg.client_id}
            if leg.scope == "SPOT_LIVE":
                fields["symbol"] = proposal.symbol
            cancellation = LiveOrderIntent(leg.scope, "CANCEL", "DELETE", endpoint, tuple(fields.items()),
                leg.client_id, leg.policy_digest, int(self.clock() * 1000) + 20_000)
            pair = self.transport._credentials[leg.scope]
            receipt = self.transport.journal.receipt(leg.scope, pair.fingerprint(), cancellation.method, cancellation.endpoint, cancellation.client_id)
            if receipt is None:
                result = self._protective_dispatch(cancellation, position, event_id=event_id)
                results.append(result["state"])
            else:
                results.append("RECONCILIATION_REQUIRED")
        return self._result("RECONCILIATION_REQUIRED", ticket_id=ticket_id, cancellations=results)

    def reconcile_exit_by_client_id(self, ticket_id, entry_intent, close_intent, *, event_id):
        """Release only after exact close, flat position and no sibling orders."""
        proposal, _ = self._ticket(ticket_id, entry_intent)
        if (type(close_intent) is not LiveOrderIntent or close_intent.purpose != "CLOSE" or close_intent.scope != entry_intent.scope
                or close_intent.policy_digest != self.admission.policy.fingerprint):
            raise LiveError("EXACT_CLOSE_INTENT_REQUIRED")
        fields = dict(close_intent.fields)
        if fields["symbol"] != proposal.symbol or fields["side"] != ("SELL" if proposal.direction == "LONG" else "BUY"):
            raise LiveError("CLOSE_DIRECTION_SYMBOL_MISMATCH")
        pair = self.transport._credentials[close_intent.scope]
        receipt = self.transport.journal.receipt(close_intent.scope, pair.fingerprint(), close_intent.method, close_intent.endpoint, close_intent.client_id)
        if receipt is None or receipt["intent_digest"] != close_intent.digest():
            raise LiveError("OWNED_CLOSE_SUBMISSION_RECEIPT_REQUIRED")
        try:
            raw = self.transport.reconcile(close_intent)
            if (type(raw) is not dict or raw.get("clientOrderId") != close_intent.client_id or raw.get("symbol") != proposal.symbol
                    or raw.get("side") != fields["side"] or raw.get("status") != "FILLED"
                    or _decimal(raw.get("executedQty")) != _decimal(fields["quantity"])
                    or _decimal(raw.get("origQty")) != _decimal(fields["quantity"])):
                return self._result("UNKNOWN", ticket_id=ticket_id, reasons=["CLOSE_EXECUTION_NOT_COMPLETE"])
            _, position = self._flat_position(ticket_id, entry_intent)
            if not self._no_sibling_orders(proposal):
                return self._result("RECONCILIATION_REQUIRED", ticket_id=ticket_id, reasons=["NATIVE_SIBLINGS_STILL_PRESENT"])
            principal = _ceil(_decimal(position.cumulative_quote) * MICRO * Decimal(1000) / Decimal(proposal.leverage_milli))
            event = Reconciliation(_event(event_id, "closed:" + _hash([raw, position.evidence_digest])), ticket_id,
                "BINANCE_LIVE_SIGNED_GET", _event(event_id, "closed-evidence:" + _hash([raw, position.evidence_digest])), self.clock(), proposal.scope,
                "CLOSED", principal, True, True, True)
            result = self.admission.reconcile(event)
            return self._result(result["state"], ticket_id=ticket_id, reservation_release_allowed=result.get("reservation_released", False))
        except (LiveError, AdmissionError):
            return self._recovery(ticket_id, "CLOSE_OR_FLAT_RECONCILIATION_UNKNOWN", event_id)

    def reconcile_native_exit_by_client_id(self, ticket_id, entry_intent, *, event_id):
        """Observe an independently executed native stop/TP; no new write."""
        proposal, _ = self._ticket(ticket_id, entry_intent)
        try:
            _, position = self._flat_position(ticket_id, entry_intent)
            plan = self._plan(proposal, entry_intent)
            matched, evidence = False, []
            for native in plan.intents:
                fields = dict(native.fields)
                if native.scope == "FUTURES_LIVE":
                    raw = self.transport.reconcile(native)
                    evidence.append(raw)
                    if (type(raw) is not dict or raw.get("clientAlgoId") != native.client_id
                            or raw.get("symbol") != proposal.symbol or raw.get("algoStatus") != "FINISHED"):
                        continue
                    order_id = raw.get("actualOrderId")
                    if type(order_id) not in {int, str} or not re.fullmatch(r"[0-9]{1,20}", str(order_id), re.ASCII):
                        raise LiveError("NATIVE_ACTUAL_EXECUTION_UNKNOWN")
                    actual = self.transport.get(native.scope, "/fapi/v1/order", {"symbol": proposal.symbol, "orderId": int(order_id)})
                    if (type(actual) is not dict or actual.get("orderId") != int(order_id)
                            or actual.get("symbol") != proposal.symbol or actual.get("side") != fields["side"]
                            or actual.get("positionSide") != "BOTH"
                            or not (actual.get("reduceOnly") is True or type(actual.get("reduceOnly")) is str and actual["reduceOnly"] in {"true", "TRUE"})
                            or actual.get("status") != "FILLED"
                            or not 0 < _decimal(actual.get("executedQty")) <= _decimal(dict(entry_intent.fields)["quantity"])):
                        raise LiveError("NATIVE_ACTUAL_EXECUTION_UNKNOWN")
                    evidence.append(actual)
                    matched = True
                else:
                    listing = self.transport.reconcile(native)
                    evidence.append(listing)
                    if (type(listing) is not dict or listing.get("listClientOrderId") != native.client_id
                            or listing.get("symbol") != proposal.symbol or listing.get("listOrderStatus") != "ALL_DONE"):
                        continue
                    for client, kind in ((fields["aboveClientOrderId"], fields["aboveType"]), (fields["belowClientOrderId"], fields["belowType"])):
                        raw = self.transport.get(native.scope, "/api/v3/order", {"symbol": proposal.symbol, "origClientOrderId": client})
                        evidence.append(raw)
                        if (type(raw) is not dict or raw.get("clientOrderId") != client or raw.get("symbol") != proposal.symbol
                                or raw.get("side") != "SELL" or raw.get("type") != kind):
                            raise LiveError("NATIVE_ACTUAL_EXECUTION_UNKNOWN")
                        if raw.get("status") == "FILLED" and 0 < _decimal(raw.get("executedQty")) <= _decimal(dict(entry_intent.fields)["quantity"]):
                            matched = True
            if not matched:
                return self._result("UNKNOWN", ticket_id=ticket_id, reasons=["OWNED_NATIVE_EXECUTION_NOT_CONFIRMED"])
            if not self._no_sibling_orders(proposal):
                return self._result("RECONCILIATION_REQUIRED", ticket_id=ticket_id, reasons=["NATIVE_SIBLINGS_STILL_PRESENT"])
            evidence_hash = _hash([position.evidence_digest, evidence])
            principal = _ceil(_decimal(position.cumulative_quote) * MICRO * Decimal(1000) / Decimal(proposal.leverage_milli))
            event = Reconciliation(_event(event_id, "native-closed:" + evidence_hash), ticket_id,
                "BINANCE_LIVE_SIGNED_GET", _event(event_id, "native-closed-evidence:" + evidence_hash), self.clock(), proposal.scope,
                "CLOSED", principal, True, True, True)
            result = self.admission.reconcile(event)
            return self._result(result["state"], ticket_id=ticket_id, reservation_release_allowed=result.get("reservation_released", False))
        except (LiveError, AdmissionError):
            return self._recovery(ticket_id, "NATIVE_EXIT_RECONCILIATION_UNKNOWN", event_id)
