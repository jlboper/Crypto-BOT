"""Pure bounded sizing hypotheses, without accounts, orders or financial approval.

All prices, budgets, rates and exchange filters must be supplied explicitly.
100 USDT is a possible fixture, never a funded balance or a default allocation.
These checks cover only the listed mathematical rules, not all Binance filters,
native protection, fee-asset settlement or contract margin/liquidation behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Context, Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext
import hashlib
import json


MAX_INPUT_CHARACTERS = 80
MAX_INPUT_DIGITS = 48
MIN_INPUT_EXPONENT = -30
MAX_INPUT_EXPONENT = 18
MAX_INPUT_VALUE = Decimal("1e18")
PRECISION = 256
VENUES = ("SPOT_SIMULATION", "LINEAR_FUTURES_SIMULATION")


@dataclass(frozen=True)
class OrderCostScenario:
    venue: str
    quote_asset: str
    direction: str
    available_capital: Decimal | str | int | None
    risk_budget: Decimal | str | int | None
    max_notional: Decimal | str | int | None
    reference_price: Decimal | str | int | None
    stop_price: Decimal | str | int | None
    leverage: Decimal | str | int | None
    approved_max_leverage: Decimal | str | int | None
    entry_fee_rate: Decimal | str | int | None
    exit_fee_rate: Decimal | str | int | None
    entry_slippage_rate: Decimal | str | int | None
    exit_slippage_rate: Decimal | str | int | None
    lot_step: Decimal | str | int | None
    min_qty: Decimal | str | int | None
    min_notional: Decimal | str | int | None
    max_qty: Decimal | str | int | None
    tick_size: Decimal | str | int | None


SCENARIO_KEYS = tuple(row.name for row in fields(OrderCostScenario))
DECIMAL_KEYS = SCENARIO_KEYS[3:]


class ScenarioInputError(ValueError):
    pass


def _decimal(value):
    if type(value) is int:
        if value.bit_length() > 256:
            raise ScenarioInputError("INPUT_DECIMAL_BOUNDS")
        value = str(value)
    if type(value) is str:
        if not 1 <= len(value) <= MAX_INPUT_CHARACTERS or value.strip() != value:
            raise ScenarioInputError("INPUT_DECIMAL_BOUNDS")
        try:
            value = Decimal(value)
        except InvalidOperation:
            raise ScenarioInputError("INVALID_DECIMAL_INPUT") from None
    if type(value) is not Decimal or not value.is_finite():
        raise ScenarioInputError("INVALID_DECIMAL_INPUT")
    parts = value.as_tuple()
    if (value.is_signed() or len(parts.digits) > MAX_INPUT_DIGITS
            or not MIN_INPUT_EXPONENT <= parts.exponent <= MAX_INPUT_EXPONENT
            or value > MAX_INPUT_VALUE):
        raise ScenarioInputError("INPUT_DECIMAL_BOUNDS")
    return value


def _text(value):
    if value is None:
        return None
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result or "0"


def _step(value, step, rounding):
    return (value/step).to_integral_value(rounding=rounding)*step


def _base():
    return {"schema": 1, "mode": "HYPOTHETICAL_SIMULATION", "state": "UNKNOWN",
        "venue": None, "quote_asset": "USDT", "direction": None,
        "reason_codes": [], "scenario_digest": None,
        "feasible_hypothesis": False, "execution_enabled": False,
        "promotion_allowed": False, "financial_authorization": False,
        "risk_change_allowed": False, "live_implemented": False,
        "quantity": None, "reference_tick_price": None, "entry_scenario_price": None,
        "stop_trigger_price": None, "stop_scenario_price": None,
        "notional_budget_basis_price": None, "min_notional_basis_price": None,
        "estimated_entry_notional": None, "conservative_notional": None,
        "filter_min_notional_value": None, "stop_risk_per_unit": None,
        "estimated_stop_risk": None, "estimated_entry_fee": None,
        "estimated_exit_fee_at_stop": None, "estimated_total_fees_at_stop": None,
        "estimated_adverse_price_cost": None, "conservative_capital_required": None,
        "capital_model": None,
        "limitations": ["ONLY_EXPLICIT_LISTED_FILTERS_NOT_ALL_EXCHANGE_RULES",
            "NO_ACCOUNT_OR_FILTER_SOURCE_CERTIFICATION", "NO_NATIVE_PROTECTION_VERIFICATION",
            "FEE_ASSET_SETTLEMENT_NOT_MODELED", "NO_USD_USDT_CONVERSION",
            "NO_SHARED_CAPITAL_RESERVATION_OR_SIMULTANEOUS_FUNDING_CLAIM",
            "SCENARIO_RISK_NOT_MAXIMUM_LOSS_GUARANTEE"]}


def evaluate_order_costs(scenario: OrderCostScenario):
    """Size downward within every explicitly supplied bound, or reject.

    Entry/stop ticks and assumed slippage are adverse to the proposed direction.
    Minimum-notional qualification uses the lower reference/scenario entry price;
    a pessimistic price must never be used to manufacture minimum eligibility.
    Capital sizing uses the higher price and full round-trip fee reserves. Futures
    initial margin is a simulation proxy, not a calibrated exchange requirement.
    """
    result = _base()
    if type(scenario) is not OrderCostScenario:
        result.update(state="REJECTED_HYPOTHESIS", reason_codes=["TYPED_SCENARIO_REQUIRED"])
        return result
    if (any(type(getattr(scenario,key)) is not str for key in ("venue","quote_asset","direction"))
            or scenario.venue not in VENUES or scenario.quote_asset != "USDT" or scenario.direction not in {"LONG", "SHORT"}):
        result.update(state="REJECTED_HYPOTHESIS", reason_codes=["UNSUPPORTED_SIMULATION_SCOPE"])
        return result
    result.update(venue=scenario.venue, direction=scenario.direction)
    result["capital_model"] = ("SPOT_PRINCIPAL_PLUS_ROUNDTRIP_FEE_RESERVE" if scenario.venue == "SPOT_SIMULATION"
        else "SIM_NOT_CONTRACT_CALIBRATED")
    if scenario.venue == "LINEAR_FUTURES_SIMULATION":
        result["limitations"] += ["FUNDING_NOT_MODELED", "LIQUIDATION_AND_MAINTENANCE_MARGIN_NOT_CALIBRATED",
                                   "BASIS_GAPS_AND_EXECUTION_DISCONTINUITY_NOT_BOUNDED"]
    if any(getattr(scenario, key) is None for key in DECIMAL_KEYS if key != "max_qty"):
        result["reason_codes"] = ["EXPLICIT_BUDGET_PRICE_COST_OR_FILTER_UNKNOWN"]
        return result
    try:
        values = {key: _decimal(getattr(scenario, key)) for key in DECIMAL_KEYS
                  if getattr(scenario, key) is not None}
        for key in ("reference_price", "stop_price", "leverage", "approved_max_leverage", "lot_step", "tick_size"):
            if values[key] <= 0:
                raise ScenarioInputError("POSITIVE_PRICE_LEVERAGE_OR_INCREMENT_REQUIRED")
        for key in ("entry_fee_rate", "exit_fee_rate", "entry_slippage_rate", "exit_slippage_rate"):
            if not 0 <= values[key] < 1:
                raise ScenarioInputError("INVALID_COST_RATE")
        if (scenario.venue == "LINEAR_FUTURES_SIMULATION"
                and any(values[key] != values[key].to_integral_value()
                        for key in ("leverage", "approved_max_leverage"))):
            raise ScenarioInputError("INTEGER_FUTURES_LEVERAGE_REQUIRED")
        if (values["leverage"] < 1 or values["leverage"] > values["approved_max_leverage"]
                or scenario.venue == "SPOT_SIMULATION" and (values["leverage"] != 1 or values["approved_max_leverage"] != 1)):
            raise ScenarioInputError("LEVERAGE_OUTSIDE_EXPLICIT_SIMULATION_POLICY")
        if "max_qty" in values and (values["max_qty"] <= 0 or values["max_qty"] < values["min_qty"]):
            raise ScenarioInputError("INCONSISTENT_QUANTITY_FILTERS")
        if ((scenario.direction == "LONG" and values["stop_price"] >= values["reference_price"])
                or (scenario.direction == "SHORT" and values["stop_price"] <= values["reference_price"])):
            raise ScenarioInputError("INVALID_STOP_DIRECTION")
        if scenario.venue == "SPOT_SIMULATION" and scenario.direction != "LONG":
            raise ScenarioInputError("SPOT_SHORT_NOT_SUPPORTED")
        digest_input = {"venue":scenario.venue,"quote_asset":scenario.quote_asset,"direction":scenario.direction,
                        **{key:_text(value) for key,value in values.items()},
                        "max_qty":_text(values.get("max_qty"))}
        result["scenario_digest"] = hashlib.sha256(json.dumps(digest_input,sort_keys=True,separators=(",", ":")).encode("ascii")).hexdigest()
        with localcontext(Context(prec=PRECISION,rounding=ROUND_HALF_EVEN,Emin=-999,Emax=999)):
            long = scenario.direction == "LONG"
            entry_round, exit_round = ((ROUND_CEILING, ROUND_FLOOR) if long else (ROUND_FLOOR, ROUND_CEILING))
            reference = _step(values["reference_price"], values["tick_size"], entry_round)
            stop = _step(values["stop_price"], values["tick_size"], exit_round)
            entry = _step(reference*(1+values["entry_slippage_rate"] if long else 1-values["entry_slippage_rate"]),
                          values["tick_size"], entry_round)
            exit_price = _step(stop*(1-values["exit_slippage_rate"] if long else 1+values["exit_slippage_rate"]),
                               values["tick_size"], exit_round)
            if min(reference, stop, entry, exit_price) <= 0:
                raise ScenarioInputError("TICK_ROUNDING_ZERO_OR_INVALID_PRICE")
            unit_entry_fee = entry*values["entry_fee_rate"]
            unit_exit_fee = exit_price*values["exit_fee_rate"]
            unit_risk = abs(entry-exit_price)+unit_entry_fee+unit_exit_fee
            budget_price = max(values["reference_price"],reference,entry)
            minimum_price = min(values["reference_price"],reference,entry)
            fee_reserve = budget_price*values["entry_fee_rate"]+max(stop,exit_price)*values["exit_fee_rate"]
            capital_unit = budget_price/values["leverage"]+fee_reserve
            bounds = {"CAPITAL_LIMIT":values["available_capital"]/capital_unit,
                      "RISK_LIMIT":values["risk_budget"]/unit_risk,
                      "NOTIONAL_LIMIT":values["max_notional"]/budget_price}
            if "max_qty" in values:
                bounds["MAX_QUANTITY_FILTER"] = values["max_qty"]
            quantity = _step(min(bounds.values()),values["lot_step"],ROUND_FLOOR)
            # Defend an exact grid boundary against any finite-context division
            # rounding. Corrections only decrease size, never budget or risk.
            for _ in range(2):
                if (quantity*capital_unit <= values["available_capital"] and quantity*unit_risk <= values["risk_budget"]
                        and quantity*budget_price <= values["max_notional"]):
                    break
                quantity = max(Decimal(0),quantity-values["lot_step"])
            if (quantity*capital_unit > values["available_capital"] or quantity*unit_risk > values["risk_budget"]
                    or quantity*budget_price > values["max_notional"]):
                raise ScenarioInputError("NUMERIC_BUDGET_BOUNDARY_UNRESOLVED")
            result.update(quantity=_text(quantity), reference_tick_price=_text(reference),
                entry_scenario_price=_text(entry), stop_trigger_price=_text(stop), stop_scenario_price=_text(exit_price),
                notional_budget_basis_price=_text(budget_price), min_notional_basis_price=_text(minimum_price),
                estimated_entry_notional=_text(quantity*entry), conservative_notional=_text(quantity*budget_price),
                filter_min_notional_value=_text(quantity*minimum_price), stop_risk_per_unit=_text(unit_risk),
                estimated_stop_risk=_text(quantity*unit_risk), estimated_entry_fee=_text(quantity*unit_entry_fee),
                estimated_exit_fee_at_stop=_text(quantity*unit_exit_fee),
                estimated_total_fees_at_stop=_text(quantity*(unit_entry_fee+unit_exit_fee)),
                estimated_adverse_price_cost=_text(quantity*(abs(entry-values["reference_price"])+abs(exit_price-values["stop_price"]))),
                conservative_capital_required=_text(quantity*capital_unit))
            reasons = []
            if quantity <= 0:
                reasons.append("NO_QUANTITY_WITHIN_EXPLICIT_BUDGETS")
            if quantity < values["min_qty"]:
                reasons.append("MIN_QUANTITY_EXCEEDS_SAFE_SIZE")
            if quantity*minimum_price < values["min_notional"]:
                reasons.append("MIN_NOTIONAL_EXCEEDS_SAFE_SIZE")
            if reasons:
                result.update(state="REJECTED_HYPOTHESIS",reason_codes=reasons)
            else:
                result.update(state="FEASIBLE_HYPOTHESIS",feasible_hypothesis=True,
                              reason_codes=["EXPLICIT_MATHEMATICAL_RULES_SATISFIED_ONLY"])
            return result
    except (ScenarioInputError, InvalidOperation, ArithmeticError) as error:
        result.update(state="REJECTED_HYPOTHESIS",reason_codes=[str(error) if type(error) is ScenarioInputError else "DECIMAL_CALCULATION_FAILED"])
        return result
