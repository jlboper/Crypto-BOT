"""Supervised USDⓈ-M Futures Testnet lab.

This is intentionally separate from the automatic Spot engine. It supports
readiness checks and a small reversible LONG/SHORT smoke round trip using
1x/2x/3x isolated leverage. It has no production host and no LIVE mode.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
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

    def check(self) -> dict:
        account = self._account()
        positions = self._position_rows()
        balance = _decimal(account.get("totalWalletBalance", "0"))
        available = _decimal(account.get("availableBalance", "0"))
        return {
            "ok": True,
            "environment": "USD-M FUTURES TESTNET",
            "can_trade": bool(account.get("canTrade", False)),
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
        try:
            signed_request("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": "false"})
        except FuturesTestnetExecutionError as exc:
            if exc.code != -4059:
                raise
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
        if not rows or not isinstance(rows[0], dict):
            raise FuturesTestnetExecutionError("Futures Testnet symbol unavailable")
        return rows[0]

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

    def smoke(self, *, direction: str, leverage: int) -> dict:
        direction = direction.upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("Futures Testnet direction must be LONG or SHORT")
        if not self.settings.enabled:
            raise ValueError("Futures Testnet lab is disabled")
        pending = self.reconcile_pending()
        if pending and not pending["resolved"]:
            raise FuturesTestnetExecutionError("Futures Testnet order still pending")

        account = self._account()
        if not bool(account.get("canTrade", False)):
            raise FuturesTestnetExecutionError("Futures Testnet account cannot trade")
        available = _decimal(account.get("availableBalance", "0"))
        margin = Decimal(str(self.settings.smoke_margin_usdt))
        if available < margin * Decimal("1.25"):
            raise FuturesTestnetExecutionError("Insufficient Futures Testnet margin")

        occupied = {row.get("symbol") for row in self._position_rows()}
        symbol = next((candidate for candidate in self.SYMBOLS if candidate not in occupied), None)
        if symbol is None:
            raise FuturesTestnetExecutionError("No isolated Futures Testnet symbol available")

        self._configure(symbol, leverage)
        price, funding = self._reference(symbol)
        info = self._symbol_info(symbol)
        quantity = self._quantity(info, price, margin * Decimal(leverage))
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
            exit_price = _decimal(closed.get("avgPrice", "0"))
            if exit_price <= 0:
                raise FuturesTestnetExecutionError("Futures Testnet close missing average price")
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
                "margin_usdt": float(margin),
                "position_notional_usdt": float(margin * Decimal(leverage)),
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
