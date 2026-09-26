"""Supervised USDⓈ-M Futures Testnet lab.

This is intentionally separate from the automatic Spot engine. It supports
readiness checks and a small reversible LONG/SHORT smoke round trip using
1x/2x/3x isolated leverage. It has no production host and no LIVE mode.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
import math
import secrets

from .futures_testnet_ledger import FuturesTestnetLedger
from .futures_testnet_transport import (
    FuturesTestnetExecutionError,
    public_request,
    signed_request,
)


def _decimal(value) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise FuturesTestnetExecutionError("Invalid Futures Testnet numeric value")
    return result


def _floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise FuturesTestnetExecutionError("Invalid Futures Testnet quantity step")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


class FuturesTestnetLab:
    SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    # Each quantity is validated with /order/test immediately before use.
    # BTCUSDT 0.001 is already used by Verificar Futures and therefore known
    # to be accepted by the current Demo account without executing an order.
    SMOKE_QUANTITIES = {
        "BTCUSDT": Decimal("0.001"),
        "ETHUSDT": Decimal("0.01"),
        "BNBUSDT": Decimal("0.1"),
        "SOLUSDT": Decimal("0.1"),
        "XRPUSDT": Decimal("10"),
    }

    def __init__(self, settings):
        self.settings = settings
        self.ledger = FuturesTestnetLedger(settings.database_path)

    def _position_rows(self, symbol: str | None = None) -> list[dict]:
        payload = signed_request("GET", "/fapi/v3/positionRisk", {"symbol": symbol} if symbol else {})
        if not isinstance(payload, list):
            raise FuturesTestnetExecutionError("Invalid Futures Testnet position response")
        rows = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            amount = _decimal(row.get("positionAmt", "0"))
            if amount != 0:
                rows.append(row)
        return rows

    def _account(self) -> dict:
        payload = signed_request("GET", "/fapi/v3/account", {})
        if not isinstance(payload, dict):
            raise FuturesTestnetExecutionError("Invalid Futures Testnet account response")
        return payload

    def _trade_probe(self, symbol: str = "BTCUSDT") -> bool:
        """Validate TRADE permission without public-data dependency or execution."""
        # 0.001 BTC is deliberately conservative for BTCUSDT test-order validation:
        # it is above the historical MARKET minQty and does not execute on /order/test.
        result = signed_request("POST", "/fapi/v1/order/test", {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.001",
        })
        if result not in ({}, None):
            if not isinstance(result, dict):
                raise FuturesTestnetExecutionError("Invalid Futures Demo test-order response")
        return True

    def _validate_smoke_quantity(self, symbol: str, direction: str) -> Decimal:
        quantity = self.SMOKE_QUANTITIES.get(symbol)
        if quantity is None:
            raise FuturesTestnetExecutionError("No bounded Futures Demo smoke quantity")
        side = "BUY" if direction == "LONG" else "SELL"
        result = signed_request("POST", "/fapi/v1/order/test", {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": format(quantity, "f"),
        })
        if result not in ({}, None) and not isinstance(result, dict):
            raise FuturesTestnetExecutionError("Invalid Futures Demo smoke preflight response")
        return quantity

    def check(self) -> dict:
        account = self._account()
        positions = self._position_rows()
        balance = _decimal(account.get("totalWalletBalance", "0"))
        available = _decimal(account.get("availableBalance", "0"))
        trade_probe = self._trade_probe()
        return {
            "ok": True,
            "environment": "USD-M FUTURES DEMO",
            "can_trade": trade_probe,
            "reported_can_trade": bool(account.get("canTrade", False)),
            "trade_probe": trade_probe,
            "wallet_balance": float(balance),
            "available_balance": float(available),
            "open_positions": len(positions),
            "margin_type": self.settings.margin_type,
            "position_mode": self.settings.position_mode,
            "allowed_leverage": [1, 2, 3][: self.settings.max_leverage],
            "latest_smoke": self.ledger.latest(),
            "live_enabled": False,
        }

    def _configure(self, symbol: str, leverage: int) -> None:
        if leverage not in {1, 2, 3} or leverage > self.settings.max_leverage:
            raise ValueError("Futures Testnet leverage must be 1x, 2x or 3x")
        mode = signed_request("GET", "/fapi/v1/positionSide/dual", {})
        if not isinstance(mode, dict) or "dualSidePosition" not in mode:
            raise FuturesTestnetExecutionError("Futures Testnet position mode unavailable")
        if bool(mode["dualSidePosition"]):
            signed_request("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": "false"})
        try:
            signed_request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
        except FuturesTestnetExecutionError as exc:
            if exc.code != -4046:
                raise
        response = signed_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})
        if not isinstance(response, dict) or int(response.get("leverage", 0)) != leverage:
            raise FuturesTestnetExecutionError("Futures Testnet leverage confirmation mismatch")

    @staticmethod
    def _symbol_info(symbol: str) -> dict:
        payload = public_request("GET", "/fapi/v1/exchangeInfo", {"symbol": symbol})
        rows = payload.get("symbols", []) if isinstance(payload, dict) else []
        row = next((item for item in rows if isinstance(item, dict) and item.get("symbol") == symbol), None)
        if row is None:
            raise FuturesTestnetExecutionError("Futures Testnet symbol unavailable")
        return row

    @staticmethod
    def _reference(symbol: str) -> tuple[Decimal, float | None]:
        price_payload = public_request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        price = _decimal(price_payload.get("price", "0") if isinstance(price_payload, dict) else "0")
        if price <= 0:
            raise FuturesTestnetExecutionError("Invalid Futures Testnet reference price")
        premium = public_request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        funding = None
        if isinstance(premium, dict):
            try:
                candidate = float(premium.get("lastFundingRate"))
                if math.isfinite(candidate):
                    funding = candidate
            except (TypeError, ValueError):
                pass
        return price, funding

    @staticmethod
    def _probe_quantity(info: dict, price: Decimal, target_notional: Decimal) -> Decimal:
        """Smallest valid MARKET quantity for /order/test; this order is never executed."""
        filters = {row.get("filterType"): row for row in info.get("filters", []) if isinstance(row, dict)}
        lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
        step = _decimal(lot.get("stepSize", "0"))
        minimum = _decimal(lot.get("minQty", "0"))
        if step <= 0 or minimum <= 0:
            raise FuturesTestnetExecutionError("Futures Demo quantity filters unavailable")
        notional_filter = filters.get("MIN_NOTIONAL") or {}
        minimum_notional = _decimal(notional_filter.get("notional", "0"))
        required_notional = max(target_notional, minimum_notional)
        by_notional = (required_notional / price / step).to_integral_value(rounding=ROUND_CEILING) * step
        quantity = max(minimum, by_notional)
        return (quantity / step).to_integral_value(rounding=ROUND_CEILING) * step

    @staticmethod
    def _quantity(info: dict, price: Decimal, notional: Decimal) -> Decimal:
        filters = {row.get("filterType"): row for row in info.get("filters", []) if isinstance(row, dict)}
        lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
        step = _decimal(lot.get("stepSize", "0"))
        minimum = _decimal(lot.get("minQty", "0"))
        quantity = _floor_step(notional / price, step)
        if quantity < minimum or quantity <= 0:
            raise FuturesTestnetExecutionError("Futures Testnet smoke quantity below exchange minimum")
        notional_filter = filters.get("MIN_NOTIONAL") or {}
        minimum_notional = _decimal(notional_filter.get("notional", "0"))
        if quantity * price < minimum_notional:
            raise FuturesTestnetExecutionError("Futures Testnet smoke notional below exchange minimum")
        return quantity

    def _query_order(self, pending: dict) -> dict:
        result = signed_request("GET", "/fapi/v1/order", {
            "symbol": pending["symbol"],
            "origClientOrderId": pending["client_order_id"],
        })
        if not isinstance(result, dict) or result.get("clientOrderId") != pending["client_order_id"]:
            raise FuturesTestnetExecutionError("Futures Testnet order identity mismatch")
        return result

    def _submit(self, *, run_id: int, phase: str, symbol: str, side: str,
                quantity: Decimal, reduce_only: bool) -> dict:
        existing = self.ledger.setting("pending_order")
        if existing:
            raise FuturesTestnetExecutionError("Futures Testnet order requires reconciliation")
        client_id = "cait-fut-" + secrets.token_hex(8)
        pending = {
            "run_id": run_id,
            "phase": phase,
            "symbol": symbol,
            "side": side,
            "quantity": str(quantity),
            "reduce_only": reduce_only,
            "client_order_id": client_id,
        }
        self.ledger.set_setting("pending_order", pending)
        fields = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": format(quantity, "f"),
            "newClientOrderId": client_id,
            "newOrderRespType": "RESULT",
        }
        if reduce_only:
            fields["reduceOnly"] = "true"
        try:
            result = signed_request("POST", "/fapi/v1/order", fields)
        except FuturesTestnetExecutionError:
            # Do not retry. A later read-only order query must resolve identity/status.
            raise
        if not isinstance(result, dict) or result.get("clientOrderId") != client_id:
            raise FuturesTestnetExecutionError("Futures Testnet order identity mismatch")
        if result.get("status") != "FILLED":
            raise FuturesTestnetExecutionError("Futures Testnet MARKET order requires reconciliation")
        self.ledger.set_setting("pending_order", None)
        return result

    def forward_submit(self, *, symbol: str, side: str, quantity: Decimal, reduce_only: bool) -> dict:
        """Submit one forward-test order with a journal separate from smoke tests."""
        existing = self.ledger.setting("forward_pending_order")
        if existing:
            raise FuturesTestnetExecutionError("Futures forward order requires reconciliation")
        client_id = "cait-fwd-" + secrets.token_hex(8)
        pending = {
            "symbol": symbol,
            "side": side,
            "quantity": str(quantity),
            "reduce_only": reduce_only,
            "client_order_id": client_id,
        }
        self.ledger.set_setting("forward_pending_order", pending)
        fields = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": format(quantity, "f"),
            "newClientOrderId": client_id,
            "newOrderRespType": "RESULT",
        }
        if reduce_only:
            fields["reduceOnly"] = "true"
        result = signed_request("POST", "/fapi/v1/order", fields)
        if not isinstance(result, dict) or result.get("clientOrderId") != client_id:
            raise FuturesTestnetExecutionError("Futures forward order identity mismatch")
        if result.get("status") != "FILLED":
            raise FuturesTestnetExecutionError("Futures forward MARKET order requires reconciliation")
        # The caller clears the journal only after the corresponding local
        # position/trade commit. This closes the power-loss window between a
        # confirmed Binance fill and durable local accounting.
        return result

    def reconcile_forward_pending(self) -> dict | None:
        pending = self.ledger.setting("forward_pending_order")
        if not pending:
            return None
        result = signed_request("GET", "/fapi/v1/order", {
            "symbol": pending["symbol"],
            "origClientOrderId": pending["client_order_id"],
        })
        if not isinstance(result, dict) or result.get("clientOrderId") != pending["client_order_id"]:
            raise FuturesTestnetExecutionError("Futures forward order identity mismatch")
        status = str(result.get("status", ""))
        if status in {"NEW", "PARTIALLY_FILLED"}:
            return {"resolved": False, "status": status, "pending": pending}
        if status not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}:
            raise FuturesTestnetExecutionError("Unknown Futures forward order state")
        if status != "FILLED":
            self.ledger.set_setting("forward_pending_order", None)
        return {"resolved": True, "status": status, "pending": pending, "order": result}

    def _execution_price(self, order: dict, symbol: str) -> Decimal:
        """Resolve a filled order price without resubmitting the order."""
        for candidate in (order,):
            avg = _decimal(candidate.get("avgPrice", "0"))
            if avg > 0:
                return avg
            qty = _decimal(candidate.get("executedQty", "0"))
            quote = _decimal(candidate.get("cumQuote", "0"))
            if qty > 0 and quote > 0:
                return quote / qty
        client_id = str(order.get("clientOrderId") or "")
        if not client_id:
            raise FuturesTestnetExecutionError("Futures Testnet close missing order identity")
        queried = signed_request("GET", "/fapi/v1/order", {
            "symbol": symbol,
            "origClientOrderId": client_id,
        })
        if not isinstance(queried, dict) or queried.get("clientOrderId") != client_id:
            raise FuturesTestnetExecutionError("Futures Testnet order identity mismatch")
        avg = _decimal(queried.get("avgPrice", "0"))
        if avg > 0:
            return avg
        qty = _decimal(queried.get("executedQty", "0"))
        quote = _decimal(queried.get("cumQuote", "0"))
        if qty > 0 and quote > 0:
            return quote / qty
        raise FuturesTestnetExecutionError("Futures Testnet close missing execution price")

    def reconcile_pending(self) -> dict | None:
        pending = self.ledger.setting("pending_order")
        if not pending:
            return None
        result = self._query_order(pending)
        status = str(result.get("status", ""))
        if status in {"NEW", "PARTIALLY_FILLED"}:
            return {"resolved": False, "status": status, "phase": pending["phase"]}
        if status not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}:
            raise FuturesTestnetExecutionError("Unknown Futures Testnet order state")
        self.ledger.set_setting("pending_order", None)
        return {"resolved": True, "status": status, "phase": pending["phase"]}

    def recover(self) -> dict:
        """Resolve a prior smoke write and flatten only its recorded symbol."""
        pending = self.ledger.setting("pending_order")
        pending_result = self.reconcile_pending() if pending else None
        if pending_result and not pending_result["resolved"]:
            return {"ok": False, "pending": True, **pending_result, "live_enabled": False}

        latest = self.ledger.latest()
        if not latest or latest.get("status") == "COMPLETED":
            return {"ok": True, "pending": False, "position_closed": True, "message": "No Futures recovery required", "live_enabled": False}
        symbol = str(latest["symbol"])
        rows = self._position_rows(symbol)
        if not rows:
            self.ledger.set_status(int(latest["id"]), "RECOVERED_FLAT")
            return {"ok": True, "pending": False, "position_closed": True, "symbol": symbol, "live_enabled": False}
        if len(rows) != 1:
            raise FuturesTestnetExecutionError("Futures recovery found ambiguous positions")
        row = rows[0]
        amount = _decimal(row.get("positionAmt", "0"))
        if amount == 0:
            self.ledger.set_status(int(latest["id"]), "RECOVERED_FLAT")
            return {"ok": True, "pending": False, "position_closed": True, "symbol": symbol, "live_enabled": False}
        expected_direction = str(latest.get("direction", ""))
        expected_sign = 1 if expected_direction == "LONG" else -1
        actual_sign = 1 if amount > 0 else -1
        if actual_sign != expected_sign:
            raise FuturesTestnetExecutionError("Futures recovery direction mismatch")
        if int(float(row.get("leverage", 0) or 0)) != int(latest.get("leverage", 0)):
            raise FuturesTestnetExecutionError("Futures recovery leverage mismatch")
        if str(row.get("marginType", "")).lower() != "isolated":
            raise FuturesTestnetExecutionError("Futures recovery margin type mismatch")
        side = "SELL" if amount > 0 else "BUY"
        result = self._submit(
            run_id=int(latest["id"]), phase="RECOVERY_CLOSE", symbol=symbol, side=side,
            quantity=abs(amount), reduce_only=True,
        )
        if self._position_rows(symbol):
            raise FuturesTestnetExecutionError("Futures recovery close left an open position")
        self.ledger.set_status(int(latest["id"]), "RECOVERED")
        return {
            "ok": True,
            "pending": False,
            "position_closed": True,
            "symbol": symbol,
            "close_order_id": result.get("orderId"),
            "live_enabled": False,
        }

    def smoke(self, *, direction: str, leverage: int) -> dict:
        direction = direction.upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("Futures Testnet direction must be LONG or SHORT")
        if leverage not in {1, 2, 3} or leverage > self.settings.max_leverage:
            raise ValueError("Futures Testnet leverage must be 1x, 2x or 3x")
        if not self.settings.enabled:
            raise ValueError("Futures Testnet lab is disabled")
        if self.ledger.setting("pending_order"):
            raise FuturesTestnetExecutionError("Futures Testnet recovery required")
        latest = self.ledger.latest()
        if latest and latest.get("status") not in {"COMPLETED", "RECOVERED", "RECOVERED_FLAT"}:
            raise FuturesTestnetExecutionError("Futures Testnet recovery required")

        account = self._account()
        if not self._trade_probe():
            raise FuturesTestnetExecutionError("Futures Demo trade permission probe failed")
        available = _decimal(account.get("availableBalance", "0"))
        margin = Decimal(str(self.settings.smoke_margin_usdt))
        if available < margin * Decimal("1.25"):
            raise FuturesTestnetExecutionError("Insufficient Futures Testnet margin")

        occupied = {row.get("symbol") for row in self._position_rows()}
        symbol = next((candidate for candidate in self.SYMBOLS if candidate not in occupied), None)
        if symbol is None:
            raise FuturesTestnetExecutionError("No isolated Futures Testnet symbol available")

        self._configure(symbol, leverage)
        quantity = self._validate_smoke_quantity(symbol, direction)
        funding = None
        run_id = self.ledger.start(symbol, direction, leverage, self.settings.margin_type)
        open_side = "BUY" if direction == "LONG" else "SELL"
        close_side = "SELL" if direction == "LONG" else "BUY"
        try:
            opened = self._submit(
                run_id=run_id, phase="OPEN", symbol=symbol, side=open_side,
                quantity=quantity, reduce_only=False,
            )
            rows = self._position_rows(symbol)
            if len(rows) != 1:
                raise FuturesTestnetExecutionError("Futures Testnet open position not found")
            position = rows[0]
            amount = _decimal(position.get("positionAmt", "0"))
            if (direction == "LONG" and amount <= 0) or (direction == "SHORT" and amount >= 0):
                raise FuturesTestnetExecutionError("Futures Testnet position direction mismatch")
            actual_qty = abs(amount)
            entry = _decimal(position.get("entryPrice", opened.get("avgPrice", "0")))
            liquidation_raw = _decimal(position.get("liquidationPrice", "0"))
            liquidation = float(liquidation_raw) if liquidation_raw > 0 else None

            closed = self._submit(
                run_id=run_id, phase="CLOSE", symbol=symbol, side=close_side,
                quantity=actual_qty, reduce_only=True,
            )
            remaining = self._position_rows(symbol)
            if remaining:
                raise FuturesTestnetExecutionError("Futures Testnet smoke close left an open position")
            exit_price = self._execution_price(closed, symbol)
            self.ledger.finish(
                run_id,
                quantity=float(actual_qty),
                entry_price=float(entry),
                exit_price=float(exit_price),
                liquidation_price=liquidation,
                funding_rate=funding,
            )
            return {
                "ok": True,
                "symbol": symbol,
                "direction": direction,
                "leverage": leverage,
                "margin_type": "ISOLATED",
                "position_mode": "ONE_WAY",
                "margin_usdt": float((actual_qty * entry) / Decimal(leverage)),
                "position_notional_usdt": float(actual_qty * entry),
                "quantity": float(actual_qty),
                "entry_price": float(entry),
                "exit_price": float(exit_price),
                "liquidation_price": liquidation,
                "funding_rate": funding,
                "position_closed": True,
                "live_enabled": False,
            }
        except Exception:
            self.ledger.fail(run_id)
            raise
