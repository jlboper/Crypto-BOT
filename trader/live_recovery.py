"""Exact owned execution accounting for prepared LIVE recovery.

Only contemporaneous signed order/trade responses are accepted. These helpers
do not submit, infer ownership from balances, compute PnL or release capital.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .live_transport import LiveError


TERMINAL = frozenset({"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"})


def number(value):
    if type(value) not in {str, int} or len(str(value)) > 64:
        raise LiveError("OWNED_EXECUTION_NUMBER_UNKNOWN")
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result >= Decimal("1e15") or result.as_tuple().exponent < -18:
            raise ValueError()
        return result
    except (ValueError, InvalidOperation):
        raise LiveError("OWNED_EXECUTION_NUMBER_UNKNOWN") from None


@dataclass(frozen=True)
class OwnedExecution:
    executed: Decimal
    quote: Decimal
    base_fee: Decimal
    fees: tuple[tuple[str, str], ...]
    trade_ids: tuple[int, ...]
    terminal: bool
    order_id: int


def exact_execution(intent, raw, trades):
    """Check every fill belongs to this retained request and totals match GET."""
    fields = dict(intent.fields)
    if (type(raw) is not dict or raw.get("clientOrderId") != intent.client_id
            or raw.get("symbol") != fields["symbol"] or raw.get("side") != fields["side"]
            or number(raw.get("origQty")) != number(fields["quantity"])
            or type(raw.get("orderId")) is not int or raw["orderId"] < 0):
        raise LiveError("OWNED_EXECUTION_IDENTITY_UNKNOWN")
    reduce_only = raw.get("reduceOnly") is True or type(raw.get("reduceOnly")) is str and raw["reduceOnly"] in {"true", "TRUE"}
    reduce_only_known = type(raw.get("reduceOnly")) is bool or type(raw.get("reduceOnly")) is str and raw["reduceOnly"] in {"true", "TRUE", "false", "FALSE"}
    if intent.scope == "FUTURES_LIVE" and (raw.get("positionSide") != "BOTH"
            or not reduce_only_known or reduce_only != (fields.get("reduceOnly") == "true")):
        raise LiveError("OWNED_EXECUTION_REDUCE_ONLY_UNKNOWN")
    executed = number(raw.get("executedQty"))
    planned = number(fields["quantity"])
    state = raw.get("status")
    if (state not in TERMINAL | {"NEW", "PARTIALLY_FILLED"} or executed > planned
            or state == "FILLED" and executed != planned
            or state == "NEW" and executed != 0
            or state == "PARTIALLY_FILLED" and not 0 < executed < planned):
        raise LiveError("OWNED_EXECUTION_STATE_QUANTITY_UNKNOWN")
    quote = number(raw.get("cummulativeQuoteQty") if intent.scope == "SPOT_LIVE" else raw.get("cumQuote"))
    if type(trades) is not list or len(trades) >= 1000 or bool(executed) != bool(trades) or bool(executed) != bool(quote):
        raise LiveError("OWNED_EXECUTION_TRADES_INCOMPLETE")
    seen, total, total_quote, base_fee, fees = set(), Decimal(0), Decimal(0), Decimal(0), {}
    for trade in trades:
        trade_id = trade.get("id") if type(trade) is dict else None
        if (type(trade_id) is not int or trade_id < 0 or trade_id in seen
                or trade.get("orderId") != raw["orderId"] or trade.get("symbol") != fields["symbol"]):
            raise LiveError("OWNED_EXECUTION_TRADES_INCOMPLETE")
        if intent.scope == "SPOT_LIVE":
            if type(trade.get("isBuyer")) is not bool or trade["isBuyer"] != (fields["side"] == "BUY"):
                raise LiveError("OWNED_EXECUTION_TRADE_SIDE_UNKNOWN")
        elif trade.get("side") != fields["side"] or trade.get("positionSide") != "BOTH":
            raise LiveError("OWNED_EXECUTION_TRADE_SIDE_UNKNOWN")
        quantity, trade_quote, fee = number(trade.get("qty")), number(trade.get("quoteQty")), number(trade.get("commission"))
        asset = trade.get("commissionAsset")
        if quantity <= 0 or trade_quote <= 0 or type(asset) is not str or not re.fullmatch(r"[A-Z0-9]{1,24}", asset, re.ASCII):
            raise LiveError("OWNED_EXECUTION_COSTS_UNKNOWN")
        seen.add(trade_id)
        total += quantity
        total_quote += trade_quote
        fees[asset] = fees.get(asset, Decimal(0)) + fee
        if intent.scope == "SPOT_LIVE" and asset == fields["symbol"][:-4]:
            base_fee += fee
    if total != executed or total_quote != quote or intent.purpose == "ENTRY" and base_fee >= executed and executed:
        raise LiveError("OWNED_EXECUTION_TOTALS_DIFFER")
    return OwnedExecution(executed, quote, base_fee, tuple(sorted((asset, format(fee, "f")) for asset, fee in fees.items())),
                          tuple(sorted(seen)), state in TERMINAL, raw["orderId"])
