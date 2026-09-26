"""Automatic Binance Spot Testnet broker for the unified trading engine.

This module can only write to https://testnet.binance.vision. It keeps a
separate local accounting database, journals an order intent before the POST,
and reconciles uncertain/partial responses by client order id before allowing
another write. There is deliberately no production host or LIVE mode here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import math
import secrets
import time

from .broker import PaperBroker
from .domain import Position, Signal
from .risk_control import profile_multiplier
from .testnet import plan_order
from .testnet_execution import _signed, TestnetExecutionError, TERMINAL


class BinanceTestnetBroker(PaperBroker):
    """Paper risk/accounting with actual Spot Testnet MARKET fills."""

    PENDING_KEY = "unified_testnet_pending_order"

    def _pending(self) -> dict | None:
        raw = self.db.setting(self.PENDING_KEY)
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TestnetExecutionError("Invalid unified Testnet journal") from exc
        if not isinstance(value, dict):
            raise TestnetExecutionError("Invalid unified Testnet journal")
        return value

    def _save_pending(self, value: dict | None) -> None:
        self.db.set_setting(self.PENDING_KEY, json.dumps(value, separators=(",", ":")) if value else "")

    @staticmethod
    def _safe_fill(data: dict, expected: dict) -> dict:
        if (
            not isinstance(data, dict)
            or data.get("symbol") != expected["symbol"]
            or data.get("clientOrderId") != expected["client_order_id"]
            or data.get("side") != expected["side"]
            or data.get("status") not in TERMINAL | {"NEW", "PARTIALLY_FILLED"}
        ):
            raise TestnetExecutionError("Unified Testnet order identity/status mismatch")
        qty = Decimal(str(data.get("executedQty", "0")))
        quote = Decimal(str(data.get("cummulativeQuoteQty", "0")))
        if not qty.is_finite() or not quote.is_finite() or qty < 0 or quote < 0:
            raise TestnetExecutionError("Invalid unified Testnet fill")
        commission_quote = Decimal("0")
        commission_base = Decimal("0")
        base_asset = expected.get("base_asset")
        for fill in data.get("fills", []) or []:
            if not isinstance(fill, dict):
                continue
            amount = Decimal(str(fill.get("commission", "0")))
            if not amount.is_finite() or amount < 0:
                raise TestnetExecutionError("Invalid unified Testnet commission")
            if fill.get("commissionAsset") == "USDT":
                commission_quote += amount
            elif base_asset and fill.get("commissionAsset") == base_asset:
                commission_base += amount
        return {
            "status": str(data["status"]),
            "executed_qty": str(qty),
            "cumulative_quote": str(quote),
            "commission_quote": str(commission_quote),
            "commission_base": str(commission_base),
        }

    @staticmethod
    def _account_balance(asset: str) -> Decimal:
        account = _signed("GET", "/api/v3/account", {})
        for row in account.get("balances", []):
            if row.get("asset") != asset:
                continue
            free = Decimal(str(row.get("free", "0")))
            locked = Decimal(str(row.get("locked", "0")))
            if all(value.is_finite() and value >= 0 for value in (free, locked)):
                return free
        raise TestnetExecutionError(f"Testnet {asset} balance unavailable")

    def reconcile_pending(self) -> bool:
        """Return True only when no unresolved exchange write remains."""
        pending = self._pending()
        if not pending:
            return True
        response = _signed(
            "GET",
            "/api/v3/order",
            {"symbol": pending["symbol"], "origClientOrderId": pending["client_order_id"]},
        )
        pending.update(self._safe_fill(response, pending))
        self._save_pending(pending)
        if pending["status"] in {"NEW", "PARTIALLY_FILLED"}:
            return False
        if pending["status"] not in TERMINAL:
            return False
        if Decimal(str(pending.get("executed_qty", "0"))) > 0:
            self._apply_terminal_fill(pending)
        self._save_pending(None)
        return True

    def _submit_market(self, pending: dict, fields: dict) -> dict:
        if self._pending():
            raise TestnetExecutionError("Unresolved unified Testnet order")
        self._save_pending(pending)  # durable receipt before the only POST
        try:
            response = _signed("POST", "/api/v3/order", fields)
        except Exception:
            # Never retry a write. The next cycle/read-only reconciliation decides.
            raise
        pending.update(self._safe_fill(response, pending))
        self._save_pending(pending)
        if pending["status"] in TERMINAL:
            if Decimal(str(pending.get("executed_qty", "0"))) > 0:
                self._apply_terminal_fill(pending)
            self._save_pending(None)
        return pending

    def _validate_buy(self, signal: Signal, quantity: float) -> None:
        if signal.action != "BUY" or any(
            type(v) not in (int, float) or not math.isfinite(v) or v <= 0
            for v in (quantity, signal.price, signal.stop_price, signal.take_profit, signal.atr)
        ):
            raise ValueError("invalid buy values")
        if not signal.stop_price < signal.price < signal.take_profit:
            raise ValueError("invalid protection levels")
        if self.db.position(signal.symbol):
            raise ValueError(f"position already exists for {signal.symbol}")
        if len(self.db.positions()) >= self.risk.max_positions:
            raise ValueError("position count limit")
        prices, _ = self.db.market_snapshot()
        equity, cash, exposure = self.equity(prices)
        gross = signal.price * quantity
        if gross > equity * self.risk.max_position_pct + 1e-8:
            raise ValueError("position exposure limit")
        if exposure + gross > equity * self.risk.max_total_exposure_pct + 1e-8:
            raise ValueError("total exposure limit")
        estimated_stop = signal.stop_price * (1 - self.settings.slippage_rate)
        estimated_fill = signal.price * (1 + self.settings.slippage_rate)
        estimated_loss = quantity * (
            estimated_fill - estimated_stop
            + self.settings.fee_rate * (estimated_fill + estimated_stop)
        )
        risk_factor = profile_multiplier(self.db)
        if risk_factor <= 0 or estimated_loss > equity * self.risk.risk_per_trade_pct * risk_factor + 1e-8:
            raise ValueError("per-trade risk limit")
        if gross * (1 + self.settings.fee_rate) > cash + 1e-8:
            raise ValueError("insufficient Testnet allocation")

    def buy(self, signal: Signal, quantity: float, reason: str) -> Position:
        self._validate_buy(signal, quantity)
        if not self.reconcile_pending():
            raise TestnetExecutionError("Testnet order still pending")
        from .exchange import BinanceClient

        client = BinanceClient(timeout=10)
        info = client.testnet_symbol_info(signal.symbol)
        base_asset = str(info.get("baseAsset", ""))
        reference = client.testnet_reference_price(signal.symbol)
        plan = plan_order(signal.symbol, "BUY", reference, info, quantity=quantity)
        if plan.status != "READY_FOR_MANUAL_REVIEW":
            raise TestnetExecutionError("Testnet filters reject engine quantity")
        quote_estimate = Decimal(plan.estimated_notional)
        if self._account_balance("USDT") < quote_estimate:
            raise TestnetExecutionError("Insufficient Spot Testnet USDT")
        client_id = "cait-auto-" + secrets.token_hex(10)
        pending = {
            "client_order_id": client_id,
            "symbol": signal.symbol,
            "side": "BUY",
            "planned_qty": plan.quantity,
            "base_asset": base_asset,
            "reason": reason,
            "signal": signal.to_dict(),
            "created_at": datetime.now(UTC).isoformat(),
            "status": "UNCERTAIN",
        }
        result = self._submit_market(
            pending,
            {
                "symbol": signal.symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": plan.quantity,
                "newClientOrderId": client_id,
                "newOrderRespType": "FULL",
            },
        )
        if result["status"] != "FILLED":
            raise TestnetExecutionError("Testnet BUY awaits reconciliation")
        position = self.db.position(signal.symbol)
        if position is None:
            raise TestnetExecutionError("Filled Testnet BUY missing local position")
        return position

    def sell(
        self,
        position: Position,
        market_price: float,
        reason: str,
        *,
        manual_cooldown_until: float | None = None,
    ) -> float:
        if manual_cooldown_until is not None:
            raise ValueError("manual PAPER cooldown is unavailable in Testnet engine")
        current = self.db.position(position.symbol)
        if current != position:
            raise ValueError("position absent or stale; duplicate sell blocked")
        if not math.isfinite(market_price) or market_price <= 0:
            raise ValueError("invalid market price")
        if not self.reconcile_pending():
            raise TestnetExecutionError("Testnet order still pending")
        from .exchange import BinanceClient

        client = BinanceClient(timeout=10)
        info = client.testnet_symbol_info(position.symbol)
        base_asset = str(info.get("baseAsset", ""))
        available = min(Decimal(str(position.quantity)), self._account_balance(base_asset))
        plan = plan_order(
            position.symbol,
            "SELL",
            client.testnet_reference_price(position.symbol),
            info,
            quantity=str(available),
        )
        if plan.status != "READY_FOR_MANUAL_REVIEW" or Decimal(plan.quantity) <= 0:
            raise TestnetExecutionError("Testnet filters reject engine close")
        client_id = "cait-auto-" + secrets.token_hex(10)
        pending = {
            "client_order_id": client_id,
            "symbol": position.symbol,
            "side": "SELL",
            "planned_qty": plan.quantity,
            "base_asset": base_asset,
            "reason": reason,
            "position": position.to_dict(),
            "created_at": datetime.now(UTC).isoformat(),
            "status": "UNCERTAIN",
        }
        result = self._submit_market(
            pending,
            {
                "symbol": position.symbol,
                "side": "SELL",
                "type": "MARKET",
                "quantity": plan.quantity,
                "newClientOrderId": client_id,
                "newOrderRespType": "FULL",
            },
        )
        if result["status"] != "FILLED":
            raise TestnetExecutionError("Testnet SELL awaits reconciliation")
        try:
            return float(result.get("realized_pnl", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _apply_terminal_fill(self, pending: dict) -> None:
        if pending.get("applied"):
            return
        quantity = Decimal(str(pending.get("executed_qty", "0")))
        quote = Decimal(str(pending.get("cumulative_quote", "0")))
        fee_quote = Decimal(str(pending.get("commission_quote", "0")))
        fee_base = Decimal(str(pending.get("commission_base", "0")))
        if quantity <= 0 or quote <= 0:
            raise TestnetExecutionError("Filled Testnet order has no execution")
        average = quote / quantity
        if pending["side"] == "BUY":
            signal_data = pending.get("signal") or {}
            net_quantity = quantity - fee_base
            if net_quantity <= 0:
                raise TestnetExecutionError("Testnet BUY fee consumed fill")
            signal = Signal(**signal_data)
            cash = Decimal(str(self.db.cash()))
            debit = quote + fee_quote
            if debit > cash + Decimal("0.00000001"):
                raise TestnetExecutionError("Testnet fill exceeds local allocation")
            position = Position(
                symbol=signal.symbol,
                quantity=float(net_quantity),
                entry_price=float(average),
                stop_price=signal.stop_price,
                take_profit=signal.take_profit,
                high_water=float(average),
                atr=signal.atr,
                entry_fee=float(fee_quote),
                opened_at=datetime.now(UTC).isoformat(),
            )
            with self.db.transaction():
                if self.db.position(signal.symbol):
                    raise TestnetExecutionError("Duplicate local Testnet BUY")
                self.db.set_cash(float(cash - debit))
                self.db.upsert_position(position)
                self.db.record_trade(
                    signal.symbol,
                    "BUY",
                    float(net_quantity),
                    float(average),
                    float(fee_quote),
                    0.0,
                    "TESTNET " + str(pending.get("reason", "")),
                )
        else:
            original_data = pending.get("position") or {}
            original = Position(**original_data)
            current = self.db.position(original.symbol)
            if current is None:
                raise TestnetExecutionError("Local Testnet position missing during SELL reconciliation")
            sold = min(quantity, Decimal(str(current.quantity)))
            proceeds = quote - fee_quote
            pnl = (average - Decimal(str(current.entry_price))) * sold
            allocated_entry_fee = Decimal(str(current.entry_fee)) * sold / Decimal(str(current.quantity))
            pnl -= allocated_entry_fee + fee_quote
            remaining = Decimal(str(current.quantity)) - sold
            with self.db.transaction():
                self.db.set_cash(self.db.cash() + float(proceeds))
                if remaining <= Decimal("0.000000000001"):
                    self.db.delete_position(current.symbol)
                else:
                    self.db.upsert_position(
                        Position(
                            symbol=current.symbol,
                            quantity=float(remaining),
                            entry_price=current.entry_price,
                            stop_price=current.stop_price,
                            take_profit=current.take_profit,
                            high_water=current.high_water,
                            atr=current.atr,
                            entry_fee=max(0.0, current.entry_fee - float(allocated_entry_fee)),
                            opened_at=current.opened_at,
                        )
                    )
                    self.db.event("WARN", f"{current.symbol} Testnet close left exchange dust")
                self.db.record_trade(
                    current.symbol,
                    "SELL",
                    float(sold),
                    float(average),
                    float(fee_quote),
                    float(pnl),
                    "TESTNET " + str(pending.get("reason", "")),
                )
            pending["realized_pnl"] = float(pnl)
        pending["applied"] = True
        self._save_pending(pending)
