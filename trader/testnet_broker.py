"""Automatic Binance Spot Testnet broker for the unified trading engine.

This module can only write to https://testnet.binance.vision. It keeps a
separate local accounting database, journals an order intent before the POST,
and reconciles uncertain/partial responses by client order id before allowing
another write. There is deliberately no production host or LIVE mode here.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import secrets
import time

from .broker import PaperBroker
from .domain import Position, Signal
from .risk_control import profile_multiplier
from .testnet import plan_order
from .testnet_transport import signed_request, TestnetExecutionError, TERMINAL
from .native_protection import SpotNativeProtection


class BinanceTestnetBroker(PaperBroker):
    """Paper risk/accounting with actual Spot Testnet MARKET fills."""

    PENDING_KEY = "unified_testnet_pending_order"

    @property
    def native(self):
        return SpotNativeProtection(self)

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
        try:
            qty = Decimal(str(data.get("executedQty", "0")))
            quote = Decimal(str(data.get("cummulativeQuoteQty", "0")))
        except (InvalidOperation, TypeError, ValueError):
            raise TestnetExecutionError("Invalid unified Testnet fill") from None
        if not qty.is_finite() or not quote.is_finite() or qty < 0 or quote < 0:
            raise TestnetExecutionError("Invalid unified Testnet fill")
        commission_quote = Decimal("0")
        commission_base = Decimal("0")
        commission_other = []
        base_asset = expected.get("base_asset")
        fills = data.get("fills", [])
        if fills is not None and not isinstance(fills, list):
            raise TestnetExecutionError("Invalid unified Testnet fills")
        for fill in fills or []:
            if not isinstance(fill, dict):
                continue
            try:
                amount = Decimal(str(fill.get("commission", "0")))
            except (InvalidOperation, TypeError, ValueError):
                raise TestnetExecutionError("Invalid unified Testnet commission") from None
            if not amount.is_finite() or amount < 0:
                raise TestnetExecutionError("Invalid unified Testnet commission")
            if fill.get("commissionAsset") == "USDT":
                commission_quote += amount
            elif base_asset and fill.get("commissionAsset") == base_asset:
                commission_base += amount
            elif amount > 0:
                commission_other.append({"asset": str(fill.get("commissionAsset") or "")[:20],
                                         "amount": str(amount)})
        order_id = data.get("orderId")
        if order_id is not None and (not isinstance(order_id, int) or order_id <= 0):
            raise TestnetExecutionError("Invalid unified Testnet order id")
        return {
            "status": str(data["status"]),
            "executed_qty": str(qty),
            "cumulative_quote": str(quote),
            "commission_quote": str(commission_quote),
            "commission_base": str(commission_base),
            "commission_other": commission_other,
            "order_id": order_id,
        }

    @staticmethod
    def _account_balance(asset: str) -> Decimal:
        account = signed_request("GET", "/api/v3/account", {})
        if not isinstance(account, dict) or not isinstance(account.get("balances"), list):
            raise TestnetExecutionError("Invalid Spot Testnet account response")
        for row in account.get("balances", []):
            if row.get("asset") != asset:
                continue
            try:
                free = Decimal(str(row.get("free", "0")))
                locked = Decimal(str(row.get("locked", "0")))
            except (InvalidOperation, TypeError, ValueError):
                raise TestnetExecutionError(f"Invalid Testnet {asset} balance") from None
            if all(value.is_finite() and value >= 0 for value in (free, locked)):
                return free
        raise TestnetExecutionError(f"Testnet {asset} balance unavailable")

    def _normalize_fill_with_trades(self, response: dict, pending: dict) -> dict:
        normalized = self._safe_fill(response, pending)
        if (normalized["status"] in TERMINAL and Decimal(normalized["executed_qty"]) > 0
                and not response.get("fills")):
            order_id = normalized.get("order_id")
            if not isinstance(order_id, int):
                raise TestnetExecutionError("Terminal Testnet order missing order id for fee reconciliation")
            trades = signed_request("GET", "/api/v3/myTrades",
                                    {"symbol": pending["symbol"], "orderId": order_id})
            if not isinstance(trades, list) or not trades:
                raise TestnetExecutionError("Testnet trade fills unavailable for reconciliation")
            response = {**response, "fills": trades}
            normalized = self._safe_fill(response, pending)
        return normalized

    def reconcile_pending(self) -> bool:
        """Return True only when no unresolved exchange write remains."""
        self.native.reconcile_all()
        pending = self._pending()
        if not pending:
            return True
        response = signed_request(
            "GET",
            "/api/v3/order",
            {"symbol": pending["symbol"], "origClientOrderId": pending["client_order_id"]},
        )
        pending.update(self._normalize_fill_with_trades(response, pending))
        self._save_pending(pending)
        self._observe_response(pending)
        if pending["status"] in {"NEW", "PARTIALLY_FILLED"}:
            return False
        if pending["status"] not in TERMINAL:
            return False
        if Decimal(str(pending.get("executed_qty", "0"))) > 0:
            self._apply_terminal_fill(pending)
        self._save_pending(None)
        return True

    def _observe_entry(self, pending: dict, opportunity: dict | None) -> None:
        """Copy final BUY evidence to the fixed, non-blocking observer ingress."""
        if pending.get("side") != "BUY":
            return
        try:
            from .opportunity_observer import observe_entry_intent
            signal = pending.get("signal") or {}
            final_at = time.time()
            evidence = {"checks": ("NATIVE_QUANTITATIVE_CHECKS_PASSED",),
                "decision_at": final_at, "known_at": final_at,
                "source_digest": hashlib.sha256(json.dumps({key: signal.get(key) for key in
                    ("created_at", "price", "stop_price", "take_profit", "observed_price",
                     "observed_stop_price", "observed_take_profit")},
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "policy_digest": hashlib.sha256(json.dumps((self.risk.max_positions,
                    self.risk.max_total_exposure_pct, self.risk.max_position_pct,
                    self.risk.risk_per_trade_pct), separators=(",", ":")).encode()).hexdigest()}
            original = getattr(self, "_opportunity_review", None)
            if original:
                review, model, reviewed_at = original
                evidence["review_digest"] = hashlib.sha256(json.dumps((model, review.verdict,
                    review.confidence, review.risk_multiplier, reviewed_at), separators=(",", ":")).encode()).hexdigest()
                evidence["checks"] += ("INDIVIDUAL_AI_REVIEW_ACCEPTED",)
            observe_entry_intent(engine="SPOT", environment="SPOT_TESTNET",
                origin_ref=pending["client_order_id"], strategy_version="spot-final-entry-v1", at=final_at,
                legs=[{"symbol": pending["symbol"], "venue": "SPOT_TESTNET", "direction": "LONG",
                       "quantity": pending["planned_qty"], "reference_price": signal.get("price"),
                       "stop_price": signal.get("stop_price"), "take_profit": signal.get("take_profit"),
                       "fee_rate": self.settings.fee_rate, "slippage_rate": self.settings.slippage_rate}],
                # Native limits include positions predating this observer; no
                # frozen global baseline exists for a reservation budget yet.
                capital=(opportunity or {}).get("capital"), limits=None,
                evidence=evidence)
        except Exception:
            # Optional observation can lose evidence, never change a broker write.
            pass

    @staticmethod
    def _observe_response(pending: dict) -> None:
        if pending.get("side") != "BUY":
            return
        try:
            from .opportunity_observer import observe_entry_outcome
            status = pending["status"]
            state = {"PARTIALLY_FILLED": "PARTIAL", "CANCELED": "CANCELLED",
                     "EXPIRED": "CANCELLED", "EXPIRED_IN_MATCH": "CANCELLED"}.get(status, status)
            evidence = {}
            if "executed_qty" in pending:
                evidence["quantity"] = pending["executed_qty"]
            if "commission_quote" in pending and not pending.get("commission_other") and not Decimal(pending.get("commission_base", "0")):
                evidence["fees"] = pending["commission_quote"]
            observe_entry_outcome(engine="SPOT", environment="SPOT_TESTNET",
                origin_ref=pending["client_order_id"], at=time.time(), stage="EXCHANGE_RESPONSE",
                state=state if state in {"FILLED", "PARTIAL", "CANCELLED", "REJECTED"} else "UNKNOWN",
                complete=status in TERMINAL, evidence=evidence)
        except Exception:
            pass

    def _submit_market(self, pending: dict, fields: dict, *, opportunity: dict | None = None) -> dict:
        if self._pending():
            raise TestnetExecutionError("Unresolved unified Testnet order")
        self._save_pending(pending)  # durable receipt before the only POST
        self._observe_entry(pending, opportunity)
        try:
            response = signed_request("POST", "/api/v3/order", fields)
        except Exception:
            # Never retry a write. The next cycle/read-only reconciliation decides.
            self._observe_response(pending)
            raise
        pending.update(self._normalize_fill_with_trades(response, pending))
        self._save_pending(pending)
        self._observe_response(pending)
        if pending["status"] in TERMINAL:
            if Decimal(str(pending.get("executed_qty", "0"))) > 0:
                self._apply_terminal_fill(pending)
            self._save_pending(None)
        return pending

    def _validate_buy(self, signal: Signal, quantity: float) -> dict:
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
        # Values already used by native admission, copied only for observation.
        return {"equity": equity, "cash": cash}

    def buy(self, signal: Signal, quantity: float, reason: str) -> Position:
        self._validate_buy(signal, quantity)
        if not self.reconcile_pending():
            raise TestnetExecutionError("Testnet order still pending")
        self.native.ensure_all()
        from .exchange import BinanceClient

        client = BinanceClient(timeout=10)
        info = client.testnet_symbol_info(signal.symbol)
        base_asset = str(info.get("baseAsset", ""))
        reference = client.testnet_reference_price(signal.symbol)
        observed_stop = signal.observed_stop_price if signal.observed_stop_price is not None else signal.stop_price
        observed_take = signal.observed_take_profit if signal.observed_take_profit is not None else signal.take_profit
        if not (observed_stop < reference < observed_take and signal.stop_price < reference < signal.take_profit):
            raise TestnetExecutionError("Spot Testnet price moved outside signal protection range")
        execution_signal = signal.at_entry_price(reference)
        admitted_values = self._validate_buy(execution_signal, quantity)
        self.native.preflight_with_client(client, info, execution_signal.stop_price, execution_signal.take_profit)
        plan = plan_order(signal.symbol, "BUY", reference, info, quantity=quantity)
        if plan.status != "READY_FOR_MANUAL_REVIEW":
            raise TestnetExecutionError("Testnet filters reject engine quantity")
        quote_estimate = Decimal(plan.estimated_notional)
        available_usdt = self._account_balance("USDT")
        balance_observed_at = time.time()
        if available_usdt < quote_estimate:
            raise TestnetExecutionError("Insufficient Spot Testnet USDT")
        client_id = "cait-auto-" + secrets.token_hex(10)
        pending = {
            "client_order_id": client_id,
            "symbol": signal.symbol,
            "side": "BUY",
            "planned_qty": plan.quantity,
            "base_asset": base_asset,
            "reason": reason,
            # Keep the durable fill signal readable by the previous release.
            # Original admission evidence is additional journal metadata;
            # recovery needs only the already rebased execution plan.
            "signal": {key: value for key, value in execution_signal.to_dict().items()
                       if key not in {'observed_price', 'observed_stop_price', 'observed_take_profit'}},
            "entry_observation": {"price": execution_signal.observed_price,
                                  "stop_price": execution_signal.observed_stop_price,
                                  "take_profit": execution_signal.observed_take_profit},
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
            opportunity={"capital": {"available": str(available_usdt),
                "cash": admitted_values["cash"], "equity": admitted_values["equity"], "at": balance_observed_at}},
        )
        if result["status"] != "FILLED":
            raise TestnetExecutionError("Testnet BUY awaits reconciliation")
        position = self.db.position(signal.symbol)
        if position is None:
            raise TestnetExecutionError("Filled Testnet BUY missing local position")
        self.native.ensure(position)
        return position

    @staticmethod
    def execution_price(symbol: str) -> float:
        from .exchange import BinanceClient
        return BinanceClient(timeout=10).testnet_reference_price(symbol)

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
        native_pnl = self.native.reconcile(position.symbol, cancel=True)
        current = self.db.position(position.symbol)
        if current is None:
            return float(native_pnl or 0)
        position = current
        from .exchange import BinanceClient

        client = BinanceClient(timeout=10)
        info = client.testnet_symbol_info(position.symbol)
        base_asset = str(info.get("baseAsset", ""))
        available = min(Decimal(str(position.quantity)), self._account_balance(base_asset))
        if available <= 0:
            raise TestnetExecutionError("No free Spot Testnet balance available to close")
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

    def _apply_terminal_fill(self, pending: dict, *, native: bool = False) -> None:
        if pending.get("applied"):
            self._observe_ledger_commit(pending)
            return
        identity = pending.get("client_order_id")
        if not isinstance(identity, str) or not identity:
            raise TestnetExecutionError("Testnet fill missing durable order identity")
        try:
            with self.db.transaction() as db:
                receipt = db.execute("SELECT * FROM exchange_fill_receipts WHERE client_order_id=?", (identity,)).fetchone()
                if receipt:
                    if receipt["symbol"] != pending["symbol"] or receipt["side"] != pending["side"]:
                        raise TestnetExecutionError("Testnet fill receipt identity mismatch")
                    pending["applied"] = True
                    pending["realized_pnl"] = float(receipt["realized_pnl"])
                    if not native: self._save_pending(pending)
                else:
                    self._apply_terminal_fill_once(pending, native=native)
                    db.execute("INSERT INTO exchange_fill_receipts VALUES(?,?,?,?,?)", (
                        identity, pending["symbol"], pending["side"], float(pending.get("realized_pnl", 0)),
                        datetime.now(UTC).isoformat()))
        except BaseException:
            pending.pop("applied", None)
            raise
        # The transaction context has committed before optional evidence is sent.
        self._observe_ledger_commit(pending)

    @staticmethod
    def _observe_ledger_commit(pending):
        try:
            from .opportunity_contract import canonical
            from .opportunity_observer import observe_entry_outcome, observe_position_commit
            evidence=pending.get('_opportunity_commit')
            if type(evidence) is not dict:return
            proof=hashlib.sha256(canonical([pending['client_order_id'],pending['side'],evidence])).hexdigest()
            if pending['side']=='BUY':
                observe_entry_outcome(engine='SPOT',environment='SPOT_TESTNET',origin_ref=pending['client_order_id'],
                    at=time.time(),stage='LEDGER_COMMIT',state='OPENED',complete=True,
                    evidence={'position_digest':evidence['position_digest'],'quantity':evidence['quantity'],
                              'remaining_quantity':evidence['remaining_quantity'],'decision_digest':proof})
            else:
                observe_position_commit(engine='SPOT',environment='SPOT_TESTNET',position_ref=evidence['position_ref'],
                    at=time.time(),remaining_quantity=evidence['remaining_quantity'],quantity=evidence['quantity'],proof=proof)
        except Exception:
            pass

    def _apply_terminal_fill_once(self, pending: dict, *, native: bool = False) -> None:
        if pending.get("applied"):
            return
        quantity = Decimal(str(pending.get("executed_qty", "0")))
        quote = Decimal(str(pending.get("cumulative_quote", "0")))
        fee_quote = Decimal(str(pending.get("commission_quote", "0")))
        fee_base = Decimal(str(pending.get("commission_base", "0")))
        if quantity <= 0 or quote <= 0:
            raise TestnetExecutionError("Filled Testnet order has no execution")
        average = quote / quantity
        if pending.get("commission_other"):
            self.db.event("WARN", f"{pending.get('symbol')} Testnet fill used commission asset outside base/USDT")
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
            signal_entry = Decimal(str(signal.price))
            stop_ratio = Decimal(str(signal.stop_price)) / signal_entry
            take_ratio = Decimal(str(signal.take_profit)) / signal_entry
            anchored_stop = average * stop_ratio
            anchored_take = average * take_ratio
            if not (Decimal("0") < anchored_stop < average < anchored_take):
                raise TestnetExecutionError("Filled Spot Testnet protection levels are invalid")
            position = Position(
                symbol=signal.symbol,
                quantity=float(net_quantity),
                entry_price=float(average),
                stop_price=float(anchored_stop),
                take_profit=float(anchored_take),
                high_water=float(average),
                atr=signal.atr * float(average / signal_entry),
                entry_fee=float(fee_quote + fee_base * average),
                opened_at=datetime.now(UTC).isoformat(),
            )
            self._capture_opportunity_commit(pending,position,float(net_quantity),float(net_quantity))
            with self.db.connect():
                if self.db.position(signal.symbol):
                    raise TestnetExecutionError("Duplicate local Testnet BUY")
                self.db.set_cash(float(cash - debit))
                self.db.upsert_position(position)
                self.db.record_trade(
                    signal.symbol,
                    "BUY",
                    float(net_quantity),
                    float(average),
                    float(fee_quote + fee_base * average),
                    0.0,
                    "TESTNET " + str(pending.get("reason", "")),
                )
        else:
            original_data = pending.get("position") or {}
            original = Position(**original_data)
            current = self.db.position(original.symbol)
            if current is None:
                raise TestnetExecutionError("Local Testnet position missing during SELL reconciliation")
            sold = min(quantity + fee_base, Decimal(str(current.quantity)))
            proceeds = quote - fee_quote
            pnl = proceeds - Decimal(str(current.entry_price)) * sold
            allocated_entry_fee = Decimal(str(current.entry_fee)) * sold / Decimal(str(current.quantity))
            pnl -= allocated_entry_fee
            remaining = Decimal(str(current.quantity)) - sold
            self._capture_opportunity_commit(pending,current,float(sold),
                0.0 if remaining <= Decimal('0.000000000001') else float(remaining))
            with self.db.connect():
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
                    float(fee_quote + fee_base * average),
                    float(pnl),
                    "TESTNET " + str(pending.get("reason", "")),
                )
            pending["realized_pnl"] = float(pnl)
        pending["applied"] = True
        if not native: self._save_pending(pending)

    @staticmethod
    def _capture_opportunity_commit(pending,position,quantity,remaining):
        # This metadata is saved with the existing pending receipt transaction;
        # it cannot change quantity, order identity or financial accounting.
        try:
            from .opportunity_contract import position_digest,decimal_text
            reference=position.symbol+'|'+position.opened_at
            pending['_opportunity_commit']={'position_ref':reference,
                'position_digest':position_digest('SPOT','SPOT_TESTNET',reference),
                'quantity':decimal_text(quantity),'remaining_quantity':decimal_text(remaining)}
        except Exception:
            pass

    def protect(self, position: Position, price: float, atr_value: float):
        self.native.reconcile(position.symbol)
        current = self.db.position(position.symbol)
        if current is None:
            return None, "native exchange protection"
        updated, reason = super().protect(current, price, atr_value)
        if updated is not None:
            if price <= updated.stop_price:
                self.sell(updated, price, "protective stop")
                return None, "protective stop"
            # A definite rejection has no live exchange order to reconcile.
            # Keep local exits and valuation running; buy() still requires
            # ensure_all() and blocks entries until protection is repaired.
            record = self.native.records().get(updated.symbol, {})
            if record.get("state") != "REJECTED" or self.native.retryable_filter_rejection(record):
                self.native.ensure(updated)
        return updated, reason
