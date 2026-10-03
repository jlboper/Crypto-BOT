"""Durable, owned exchange protection. No LIVE transport, no blind POST retry.

UNSENT is safe to submit; SENDING is committed before the network call and may
only be queried after a crash. A missing historical lookup never proves that a
write failed. Journals survive accounting until every sibling is terminal.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json
import secrets

from .futures_testnet_transport import signed_request as futures_request, FuturesTestnetExecutionError
from .testnet_transport import TERMINAL, TestnetExecutionError

FUTURES_KEY = "forward_native_protection"
SPOT_KEY = "spot_native_protection"
NATIVE_PROTECTION_PROTOCOL = 1
ALGO_TERMINAL = {"CANCELED", "EXPIRED", "REJECTED", "FINISHED"}
# Explicit validation/rejection codes only. Timeouts, 5xx, duplicates and
# unknown errors are ambiguous and must retain SENDING for identity lookup.
DEFINITE_REJECTION = {-1013, -1100, -1101, -1102, -1103, -1111, -1116, -1121,
                      -2021, -4164}


def rejected(error):
    return getattr(error, "code", None) in DEFINITE_REJECTION and not getattr(error, "uncertain", False)


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Non-finite native protection value")
    return result


def price_tick(info, value, *, up=True):
    filters = {row["filterType"]: row for row in info.get("filters", [])}
    rule = filters.get("PRICE_FILTER", {})
    tick = decimal(rule.get("tickSize", 0))
    if tick <= 0:
        raise ValueError("Native protection PRICE_FILTER unavailable")
    price = (decimal(value) / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick
    minimum = decimal(rule.get("minPrice", 0)); maximum = decimal(rule.get("maxPrice", 0))
    if price <= 0 or price < minimum or (maximum > 0 and price > maximum):
        raise ValueError("Native protection price outside exchange filter")
    return format(price, "f")


def same_position(local, original):
    return local is not None and all(local.get(key) == original.get(key)
        for key in ("symbol", "opened_at", "quantity", "entry_price", "direction"))


def projection(records):
    """Only cached evidence; never perform a signed read from the portal."""
    return {"supported": True, "positions": {symbol: {
        "status": row.get("status", "UNCONFIRMED"),
        "stop_price": row.get("stop_price"), "take_profit": row.get("take_profit"),
        "quantity": row.get("quantity", row.get("position", {}).get("quantity")),
        "unprotected_quantity": max(0.0, float(row.get("position", {}).get("quantity", 0)) - float(row.get("quantity", row.get("position", {}).get("quantity", 0)))),
        "confirmed_at": row.get("confirmed_at"),
        "error": row.get("error"),
    } for symbol, row in records.items()}}


class FuturesNativeProtection:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.ledger

    def records(self):
        records = self.db.setting(FUTURES_KEY) or {}
        if not isinstance(records, dict):
            raise FuturesTestnetExecutionError("Invalid Futures native journal")
        return records

    def save(self, records):
        self.db.set_setting(FUTURES_KEY, records)

    def _query(self, record, leg):
        response = futures_request("GET", "/fapi/v1/algoOrder", {"clientAlgoId": leg["id"]})
        self._validate(record, leg, response)
        return response

    @staticmethod
    def _validate(record, leg, response):
        side = "SELL" if record["position"]["direction"] == "LONG" else "BUY"
        if (not isinstance(response, dict) or response.get("symbol") != record["position"]["symbol"]
            or response.get("clientAlgoId") != leg["id"] or response.get("side") != side
            or response.get("orderType") != leg["type"] or response.get("positionSide") != "BOTH"
            or response.get("workingType") != "MARK_PRICE"
            or response.get("closePosition") not in (True, "true")
            or decimal(response.get("triggerPrice", 0)) != decimal(leg["price"])
            or response.get("algoStatus") not in {"NEW", "TRIGGERING", "TRIGGERED"} | ALGO_TERMINAL):
            raise FuturesTestnetExecutionError("Futures native order identity/status mismatch")
        algo_id = response.get("algoId")
        if not isinstance(algo_id, int) or algo_id <= 0 or (leg.get("algo_id") and leg["algo_id"] != algo_id):
            raise FuturesTestnetExecutionError("Futures native algo id mismatch")
        leg["algo_id"] = algo_id
        leg["state"] = "CONFIRMED"
        leg["response"] = response

    def _fill(self, record, leg, response):
        order_id = response.get("actualOrderId")
        if not order_id or str(order_id) == "0":
            if response["algoStatus"] in {"TRIGGERING", "TRIGGERED", "FINISHED"}:
                raise FuturesTestnetExecutionError("Futures native trigger awaits execution evidence")
            return None
        order = futures_request("GET", "/fapi/v1/order", {
            "symbol": record["position"]["symbol"], "orderId": order_id})
        original = record["position"]
        side = "SELL" if original["direction"] == "LONG" else "BUY"
        if (not isinstance(order, dict) or order.get("symbol") != original["symbol"]
            or str(order.get("orderId")) != str(order_id) or order.get("side") != side
            or order.get("positionSide") != "BOTH"
            or order.get("status") not in TERMINAL | {"NEW", "PARTIALLY_FILLED"}):
            raise FuturesTestnetExecutionError("Futures native execution identity mismatch")
        executed = decimal(order.get("executedQty", 0))
        if order["status"] == "FILLED" and executed == decimal(original["quantity"]):
            if self.engine._actual_rows(original["symbol"]):
                raise FuturesTestnetExecutionError("Futures native fill awaits confirmed flatness")
            local = self.db.forward_position(original["symbol"])
            if local is not None:
                if not same_position(local, original):
                    raise FuturesTestnetExecutionError("Futures native fill belongs to another position")
                price = self.engine.lab._execution_price(order, original["symbol"])
                pnl = (decimal(price) - decimal(original["entry_price"])) * executed
                if original["direction"] == "SHORT": pnl = -pnl
                trade = self.db.close_forward_position(symbol=original["symbol"], exit_price=float(price),
                    gross_pnl=float(pnl), exit_reason=leg["reason"])
                # A stale opening journal predates the installed protection.
                pending = self.db.setting("forward_pending_order")
                if pending and pending.get("symbol") == original["symbol"] and not pending.get("reduce_only"):
                    self.db.set_setting("forward_pending_order", None)
                    self.db.set_setting("forward_open_plan", None)
                return trade
            return record.get("trade") or {"symbol": original["symbol"], "exit_reason": leg["reason"]}
        if executed > 0 or order["status"] not in TERMINAL:
            raise FuturesTestnetExecutionError("Futures native execution is unresolved or partial")
        return None

    def reconcile(self, symbol, *, cancel=False):
        records = self.records(); record = records.get(symbol)
        if not record: return None
        try:
            if cancel:
                record["cancel_requested"] = True; record["status"] = "CANCELING"
                self.save(records)
            trade = None
            for leg in record["legs"]:
                if leg["state"] in {"UNSENT", "REJECTED"}: continue
                response = self._query(record, leg)
                self.save(records)
                found = self._fill(record, leg, response)
                if found:
                    trade = found; record["trade"] = found; record["cancel_requested"] = True
                    record["status"] = "CLEANUP"; self.save(records)
            local = self.db.forward_position(symbol)
            if local is None:
                if self.engine._actual_rows(symbol):
                    raise FuturesTestnetExecutionError("Futures native orphan with untracked exposure")
                record["cancel_requested"] = True
            elif not same_position(local, record["position"]):
                raise FuturesTestnetExecutionError("Futures native journal position mismatch")
            elif not record.get("cancel_requested"):
                self.engine._assert_identity(symbol, local, self.engine._actual_rows(symbol))
            if record.get("cancel_requested"):
                for leg in record["legs"]:
                    if leg["state"] in {"UNSENT", "REJECTED"}: continue
                    response = self._query(record, leg)
                    found = self._fill(record, leg, response)
                    if found: trade = found; record["trade"] = found
                    if response["algoStatus"] == "NEW":
                        self.save(records)  # cancellation intent survives an uncertain DELETE
                        futures_request("DELETE", "/fapi/v1/algoOrder", {"clientAlgoId": leg["id"]})
                        response = self._query(record, leg)
                        found = self._fill(record, leg, response)
                        if found: trade = found; record["trade"] = found
                    if response["algoStatus"] not in ALGO_TERMINAL:
                        raise FuturesTestnetExecutionError("Futures native cancellation awaits terminal status")
                    self.save(records)
                del records[symbol]; self.save(records)
                return trade
            terminal = [leg for leg in record["legs"] if leg.get("response", {}).get("algoStatus") in ALGO_TERMINAL]
            if terminal:
                # Clean the surviving sibling before a fresh pair is considered.
                self.reconcile(symbol, cancel=True)
                return trade
            if all(leg.get("response", {}).get("algoStatus") == "NEW" for leg in record["legs"]):
                record["status"] = "ARMED"; record["confirmed_at"] = datetime.now(UTC).isoformat()
                record.pop("error", None); self.save(records)
            return trade
        except Exception as exc:
            record["status"] = "UNCONFIRMED"; record["error"] = str(exc)[:180]
            self.save(records)
            raise

    def ensure(self, local):
        symbol = local["symbol"]
        self.reconcile(symbol)
        current = self.db.forward_position(symbol)
        if current is None: return
        records = self.records(); record = records.get(symbol)
        if record and record["status"] == "ARMED": return
        if record and any(leg["state"] == "REJECTED" for leg in record["legs"]):
            raise FuturesTestnetExecutionError("Futures native order was rejected; local exits remain available, new entries blocked")
        self.engine._validated_rows(symbol, current)
        if record is None:
            info = self.engine.lab._symbol_info(symbol)
            up = current["direction"] == "LONG"
            stop = price_tick(info, current["stop_price"], up=up)
            take = price_tick(info, current["take_profit"], up=up)
            rows = self.engine._validated_rows(symbol, current)
            mark = decimal(rows[0].get("markPrice", 0))
            if not (decimal(stop) < mark < decimal(take) if up else decimal(take) < mark < decimal(stop)):
                raise FuturesTestnetExecutionError("Futures native trigger range already crossed")
            record = {"position": current, "stop_price": stop, "take_profit": take, "status": "INSTALLING",
                "legs": [{"id": "cait-n-" + secrets.token_hex(12), "type": kind, "price": price,
                    "reason": reason, "state": "UNSENT"} for kind, price, reason in (
                        ("STOP_MARKET", stop, "STOP"), ("TAKE_PROFIT_MARKET", take, "TAKE_PROFIT"))]}
            records[symbol] = record; self.save(records)
            if not self.db.setting("native_protection_started_at"):
                self.db.set_setting("native_protection_started_at", datetime.now(UTC).isoformat())
        for leg in record["legs"]:
            if leg["state"] != "UNSENT": continue
            self.engine._validated_rows(symbol, current)
            leg["state"] = "SENDING"; self.save(records)
            try:
                response = futures_request("POST", "/fapi/v1/algoOrder", {
                    "symbol": symbol, "algoType": "CONDITIONAL", "side": "SELL" if current["direction"] == "LONG" else "BUY",
                    "positionSide": "BOTH", "type": leg["type"], "triggerPrice": leg["price"],
                    "closePosition": "true", "workingType": "MARK_PRICE", "clientAlgoId": leg["id"]})
            except Exception as exc:
                if rejected(exc): leg["state"] = "REJECTED"
                record["status"] = "BLOCKED" if leg["state"] == "REJECTED" else "UNCONFIRMED"
                record["error"] = str(exc)[:180]; self.save(records)
                raise
            self._validate(record, leg, response); self.save(records)
        self.reconcile(symbol)

    def reconcile_all(self):
        return [trade for symbol in list(self.records()) if (trade := self.reconcile(symbol))]


class SpotNativeProtection:
    def __init__(self, broker):
        self.broker = broker; self.db = broker.db

    def request(self, *args):
        # Share the broker's transport and its test seam, never a LIVE client.
        from . import testnet_broker
        return testnet_broker.signed_request(*args)

    def records(self):
        records = json.loads(self.db.setting(SPOT_KEY) or "{}")
        if not isinstance(records, dict): raise TestnetExecutionError("Invalid Spot native journal")
        return records

    def save(self, records):
        self.db.set_setting(SPOT_KEY, json.dumps(records, separators=(",", ":")))

    @staticmethod
    def preflight(info, stop, take):
        if info.get("ocoAllowed") is not True or not {"STOP_LOSS", "TAKE_PROFIT"}.issubset(info.get("orderTypes", [])):
            raise TestnetExecutionError("Spot Testnet native OCO market protection unavailable")
        return price_tick(info, stop), price_tick(info, take)

    def _query(self, record):
        response = self.request("GET", "/api/v3/orderList", {"origClientOrderId": record["id"]})
        if (not isinstance(response, dict) or response.get("symbol") != record["position"]["symbol"]
            or response.get("listClientOrderId") != record["id"] or response.get("contingencyType") != "OCO"
            or response.get("listOrderStatus") not in {"EXECUTING", "ALL_DONE", "REJECT"}
            or not isinstance(response.get("orderListId"), int)
            or (record.get("list_id") is not None and record["list_id"] != response["orderListId"])):
            raise TestnetExecutionError("Spot native OCO identity/status mismatch")
        members = response.get("orders", [])
        if len(members) != 2 or {row.get("clientOrderId") for row in members} != {leg["id"] for leg in record["legs"]}:
            raise TestnetExecutionError("Spot native OCO member identity mismatch")
        record["list_id"] = response["orderListId"]
        orders = []
        for leg in record["legs"]:
            order = self.request("GET", "/api/v3/order", {"symbol": response["symbol"], "origClientOrderId": leg["id"]})
            pending = {"symbol": response["symbol"], "client_order_id": leg["id"], "side": "SELL",
                "base_asset": record["base_asset"], "position": record["position"], "reason": leg["reason"]}
            fill = self.broker._normalize_fill_with_trades(order, pending)
            member = next(row for row in members if row["clientOrderId"] == leg["id"])
            if (order.get("type") != leg["type"] or decimal(order.get("stopPrice", 0)) != decimal(leg["price"])
                or decimal(order.get("origQty", 0)) != decimal(record["quantity"])
                or order.get("orderId") != member.get("orderId") or order.get("orderListId") != record["list_id"]
                or decimal(fill["executed_qty"]) > decimal(record["quantity"])):
                raise TestnetExecutionError("Spot native leg quantity/trigger identity mismatch")
            pending.update(fill); orders.append(pending)
        return orders

    def reconcile(self, symbol, *, cancel=False):
        records = self.records(); record = records.get(symbol)
        if not record: return None
        try:
            if cancel:
                record["cancel_requested"] = True; record["status"] = "CANCELING"; self.save(records)
            if record["state"] in {"UNSENT", "REJECTED"}:
                if cancel:
                    del records[symbol]; self.save(records)
                return None
            orders = self._query(record); self.save(records)
            if record.get("cancel_requested") and any(order["status"] not in TERMINAL for order in orders):
                self.request("DELETE", "/api/v3/orderList", {"symbol": symbol, "listClientOrderId": record["id"]})
                orders = self._query(record); self.save(records)
            # Account terminal executions atomically with existing unique receipts.
            # Keep native receipts out of the unrelated MARKET order journal.
            pnl = 0.0; filled = False
            for order in orders:
                if order["status"] in TERMINAL and decimal(order["executed_qty"]) > 0:
                    self.broker._apply_terminal_fill(order, native=True)
                    pnl += float(order.get("realized_pnl", 0)); filled = True
            if all(order["status"] in TERMINAL for order in orders):
                del records[symbol]; self.save(records)
                return pnl if filled else None
            local = self.db.position(symbol)
            if local is None or not same_position(local.to_dict(), record["position"]):
                raise TestnetExecutionError("Spot native journal position mismatch")
            if any(order["status"] != "NEW" for order in orders) or record.get("cancel_requested"):
                raise TestnetExecutionError("Spot native execution/cancellation awaits reconciliation")
            record["state"] = "CONFIRMED"; record["status"] = "ARMED"
            record["confirmed_at"] = datetime.now(UTC).isoformat(); record.pop("error", None)
            self.save(records)
            return None
        except Exception as exc:
            record["status"] = "UNCONFIRMED"; record["error"] = str(exc)[:180]; self.save(records)
            raise

    def ensure(self, position):
        symbol = position.symbol
        self.reconcile(symbol)
        position = self.db.position(symbol)
        if position is None: return
        from .exchange import BinanceClient
        from .testnet import plan_order
        client = BinanceClient(timeout=10)
        records = self.records(); record = records.get(symbol)
        if record and record["state"] == "REJECTED":
            raise TestnetExecutionError("Spot native OCO was rejected; local exits remain available, new entries blocked")
        if record and record["status"] == "ARMED" and record["position"]["stop_price"] == position.stop_price:
            return
        # Trailing updates replace the pair only after confirmed cancellation.
        if record and record["status"] == "ARMED":
            self.reconcile(symbol, cancel=True)
            position = self.db.position(symbol)
            if position is None: return
            records = self.records(); record = records.get(symbol)
        if record is None:
            info = client.testnet_symbol_info(symbol)
            stop, take = self.preflight(info, position.stop_price, position.take_profit)
            reference = client.testnet_reference_price(symbol)
            if not decimal(stop) < decimal(reference) < decimal(take):
                raise TestnetExecutionError("Spot native trigger range already crossed")
            plan = plan_order(symbol, "SELL", reference, info, quantity=position.quantity)
            if plan.status != "READY_FOR_MANUAL_REVIEW" or decimal(plan.quantity) <= 0:
                raise TestnetExecutionError("Spot native protection quantity below exchange filters (dust)")
            if self.broker._account_balance(str(info.get("baseAsset", ""))) < decimal(plan.quantity):
                raise TestnetExecutionError("Insufficient free Spot balance for native protection")
            record = {"id": "cait-oco-" + secrets.token_hex(12), "position": position.to_dict(),
                "quantity": plan.quantity, "base_asset": str(info["baseAsset"]), "stop_price": stop, "take_profit": take,
                "status": "INSTALLING", "state": "UNSENT", "legs": [
                    {"id": "cait-n-" + secrets.token_hex(12), "type": kind, "price": price, "reason": reason}
                    for kind, price, reason in (("TAKE_PROFIT", take, "take profit"), ("STOP_LOSS", stop, "protective stop"))]}
            records[symbol] = record; self.save(records)
            if not self.db.setting("native_protection_started_at"):
                self.db.set_setting("native_protection_started_at", datetime.now(UTC).isoformat())
        if record["state"] == "UNSENT":
            record["state"] = "SENDING"; self.save(records)
            above, below = record["legs"]
            try:
                self.request("POST", "/api/v3/orderList/oco", {"symbol": symbol, "side": "SELL", "quantity": record["quantity"],
                    "listClientOrderId": record["id"], "aboveType": above["type"], "aboveClientOrderId": above["id"],
                    "aboveStopPrice": above["price"], "belowType": below["type"], "belowClientOrderId": below["id"],
                    "belowStopPrice": below["price"], "newOrderRespType": "RESULT"})
            except Exception as exc:
                if rejected(exc): record["state"] = "REJECTED"
                record["status"] = "BLOCKED" if record["state"] == "REJECTED" else "UNCONFIRMED"
                record["error"] = str(exc)[:180]; self.save(records)
                raise
        self.reconcile(symbol)

    def reconcile_all(self):
        for symbol in list(self.records()): self.reconcile(symbol)

    def ensure_all(self):
        self.reconcile_all()
        for position in self.db.positions(): self.ensure(position)
