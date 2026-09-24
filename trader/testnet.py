"""Read-only Testnet order planning and a synthetic reconciliation harness.

The planner deliberately stops before Binance's order endpoint.  It uses the
public symbol filters to produce the exact quantity and notional that a future
executor would need, while the lifecycle harness exercises reconciliation
without credentials, network writes, or exchange side effects.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any


class TestnetPlanError(ValueError):
    """The proposed order cannot be normalized safely from public filters."""


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TestnetPlanError(f"invalid {name}") from exc
    if not result.is_finite() or result <= 0:
        raise TestnetPlanError(f"invalid {name}")
    return result


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _filters(symbol_info: dict) -> dict[str, dict]:
    rows = symbol_info.get("filters") if isinstance(symbol_info, dict) else None
    if not isinstance(rows, list):
        raise TestnetPlanError("symbol filters unavailable")
    result = {row.get("filterType"): row for row in rows if isinstance(row, dict) and row.get("filterType")}
    if "LOT_SIZE" not in result:
        raise TestnetPlanError("LOT_SIZE filter unavailable")
    return result


@dataclass(frozen=True)
class TestnetOrderPlan:
    symbol: str
    side: str
    quantity: str
    reference_price: str
    estimated_notional: str
    client_order_id: str
    status: str
    reasons: tuple[str, ...] = ()
    execution_mode: str = "READ_ONLY_DRY_RUN"
    order_submission_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "reference_price": self.reference_price,
            "estimated_notional": self.estimated_notional,
            "client_order_id": self.client_order_id,
            "status": self.status,
            "reasons": list(self.reasons),
            "execution_mode": self.execution_mode,
            "order_submission_enabled": self.order_submission_enabled,
        }


def plan_order(
    symbol: str,
    side: str,
    reference_price: Any,
    symbol_info: dict,
    *,
    quote_amount: Any | None = None,
    quantity: Any | None = None,
    client_order_id: str | None = None,
) -> TestnetOrderPlan:
    """Normalize a future MARKET order using Testnet's public filters.

    The output is a plan only.  No API key is read and no POST/DELETE request
    can be triggered by this function.
    """
    symbol = str(symbol).upper()
    side = str(side).upper()
    if not symbol or side not in {"BUY", "SELL"}:
        raise TestnetPlanError("symbol and side are required")
    price = _decimal(reference_price, "reference price")
    filters = _filters(symbol_info)
    lot = filters["LOT_SIZE"]
    step = _decimal(lot.get("stepSize"), "step size")
    minimum = _decimal(lot.get("minQty"), "minimum quantity")
    maximum = _decimal(lot.get("maxQty"), "maximum quantity")

    if quantity is None:
        if quote_amount is None:
            raise TestnetPlanError("quote amount or quantity is required")
        quote = _decimal(quote_amount, "quote amount")
        raw_quantity = quote / price
    else:
        raw_quantity = _decimal(quantity, "quantity")
    normalized = _floor_step(raw_quantity, step)
    reasons: list[str] = []
    if normalized < minimum:
        reasons.append("LOT_SIZE_MIN")
    if normalized > maximum:
        reasons.append("LOT_SIZE_MAX")
    if normalized <= 0:
        reasons.append("LOT_SIZE_STEP")
    notional = normalized * price
    min_notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
    if min_notional:
        apply_min = min_notional.get("applyToMarket", min_notional.get("applyMinToMarket", True))
        minimum_notional = _decimal(min_notional.get("minNotional"), "minimum notional")
        if apply_min and notional < minimum_notional:
            reasons.append("MIN_NOTIONAL_ESTIMATE")
    if "NOTIONAL" in filters and filters["NOTIONAL"].get("applyMaxToMarket") is True:
        maximum_notional = _decimal(filters["NOTIONAL"].get("maxNotional"), "maximum notional")
        if notional > maximum_notional:
            reasons.append("NOTIONAL_MAX_ESTIMATE")
    digest = hashlib.sha256(f"{symbol}:{side}:{_fmt(normalized)}:{_fmt(price)}".encode()).hexdigest()[:20]
    return TestnetOrderPlan(
        symbol=symbol,
        side=side,
        quantity=_fmt(normalized),
        reference_price=_fmt(price),
        estimated_notional=_fmt(notional),
        client_order_id=client_order_id or f"paper-testnet-{digest}",
        status="READY_FOR_MANUAL_REVIEW" if not reasons else "BLOCKED",
        reasons=tuple(dict.fromkeys(reasons)),
    )


@dataclass
class SyntheticOrder:
    client_order_id: str
    status: str = "NEW"
    executed_quantity: Decimal = Decimal("0")
    seen_events: set[str] = field(default_factory=set)


class SyntheticOrderLifecycle:
    """Small deterministic state machine for future Testnet reconciliation."""

    _transitions = {
        "NEW": {"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED"},
        "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCELED"},
        "FILLED": set(),
        "CANCELED": set(),
        "REJECTED": set(),
    }

    def __init__(self, client_order_id: str) -> None:
        self.order = SyntheticOrder(client_order_id=client_order_id)

    def apply(self, event_id: str, status: str, executed_quantity: Any = "0") -> dict[str, Any]:
        event_id = str(event_id)
        status = str(status).upper()
        if event_id in self.order.seen_events:
            return self.snapshot()
        if status not in self._transitions.get(self.order.status, set()):
            raise TestnetPlanError(f"invalid lifecycle transition {self.order.status}->{status}")
        filled = _decimal(executed_quantity, "executed quantity") if str(executed_quantity) != "0" else Decimal("0")
        if filled < self.order.executed_quantity:
            raise TestnetPlanError("executed quantity moved backwards")
        self.order.executed_quantity = filled
        self.order.status = status
        self.order.seen_events.add(event_id)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "client_order_id": self.order.client_order_id,
            "status": self.order.status,
            "executed_quantity": _fmt(self.order.executed_quantity),
            "events_seen": len(self.order.seen_events),
            "reconciled_at": int(time.time()),
        }


def demo_lifecycle() -> list[dict[str, Any]]:
    lifecycle = SyntheticOrderLifecycle("paper-testnet-demo")
    snapshots = [lifecycle.snapshot()]
    snapshots.append(lifecycle.apply("evt-1", "PARTIALLY_FILLED", "0.01"))
    snapshots.append(lifecycle.apply("evt-2", "FILLED", "0.02"))
    return snapshots
