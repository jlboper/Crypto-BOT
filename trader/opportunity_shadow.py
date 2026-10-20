"""Pure, non-authoritative arithmetic for captured entry intentions.

No account identity is verified here. A hypothetical reservation is evidence
about a separate observation scenario, never financial admission or execution.
Capital and available-cash checks include both entry and exit cost estimates;
gross exposure and nominal stop distance never net opposite legs. Stop distance
is not a bound on gap losses, funding or actual execution costs.

``max_positions`` counts observed proposal reservations, not verified account
positions. The caller must isolate reservations by engine and environment and
retain uncertain reservations until an explicit, evidenced terminal event.
"""

from decimal import Context, Decimal, localcontext
import math
import re


_ENGINES = {"SPOT", "FUTURES", "AI_MARKET_PULSE", "QUANT_ARBITRAGE"}
_ENVIRONMENTS = {"SPOT_TESTNET", "FUTURES_DEMO", "PAPER", "SHADOW"}
_VENUES = {"SPOT_TESTNET", "FUTURES_DEMO", "SPOT_REFERENCE",
           "FUTURES_REFERENCE", "SPOT", "FUTURES", "PAPER"}
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]{0,31})(?:\.[0-9]{1,32})?\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{2,32}\Z")
_ZERO = Decimal("0")
_TWO = Decimal("2")


def _decimal(value):
    # Bounded fixed-point text only: bool, floats, exponents and NaN are invalid.
    if type(value) is not str or not _NUMBER.fullmatch(value):
        return None
    number = Decimal(value)
    if number.is_zero() and value.startswith("-"):
        return None
    return number


def _text(value):
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _epoch(value):
    return (type(value) in (int, float) and 0 < value < 253402300800
            and math.isfinite(value))


def _assessment(reason, hypothetical="UNKNOWN", *, gross=None, capital=None,
                costs=None, nominal=None, risk=None):
    return {"state": "UNKNOWN", "reason": reason,
            "hypothetical_state": hypothetical,
            "gross_notional": _text(gross), "committed_capital": _text(capital),
            "estimated_costs": _text(costs), "nominal_stop_risk": _text(nominal),
            "stop_risk": _text(risk), "account_identity": "UNKNOWN",
            "real_admission": "NOT_EVALUABLE"}


def _causality(payload):
    evidence = payload.get("evidence")
    if type(evidence) is not dict:
        return "EVIDENCE_TIMESTAMP_UNKNOWN", None
    times = {key: evidence.get(key) for key in
             ("market_at", "received_at", "known_at", "decision_at")}
    if any(not _epoch(value) for value in times.values()):
        return "EVIDENCE_TIMESTAMP_UNKNOWN", None
    decision = times["decision_at"]
    if any(value > payload["at"] for value in times.values()):
        return "EVIDENCE_AFTER_CAPTURE", decision
    if any(times[key] > decision for key in ("market_at", "received_at", "known_at")):
        return "EVIDENCE_AFTER_DECISION", decision
    # Provider timestamps may lead local receipt by up to five seconds, but may
    # never move evidence from after the decision into its available context.
    if times["market_at"] > times["received_at"] + 5:
        return "MARKET_RECEIPT_CLOCK_DIVERGENCE", decision
    return None, decision


def evaluate_intent(payload: dict, reservations: list[dict] = ()) -> dict:
    """Evaluate a normalized, schema-1 ENTRY_INTENT without side effects.

    All monetary inputs must be fixed-point decimal strings or absent/None.
    Missing evidence is UNKNOWN; a demonstrable numerical breach or observed
    asset conflict is REJECTED_UNVERIFIED. Unknown or invalid evidence causality
    always makes the historical hypothesis UNKNOWN, retaining arithmetic only.
    Even a complete, passing scenario is
    only RESERVED_UNVERIFIED with state UNKNOWN and real admission unevaluable.
    Output metrics refer only to this intention, not a merged account balance.
    """
    if (type(payload) is not dict or type(payload.get("schema")) is not int
            or payload.get("schema") != 1 or payload.get("kind") != "ENTRY_INTENT"
            or type(payload.get("engine")) is not str or payload["engine"] not in _ENGINES
            or type(payload.get("environment")) is not str or payload["environment"] not in _ENVIRONMENTS
            or payload.get("account_identity") != "UNKNOWN"
            or not _epoch(payload.get("at"))):
        return _assessment("INVALID_INTENT")
    legs = payload.get("legs")
    if type(legs) is not list or not 1 <= len(legs) <= 4:
        return _assessment("INVALID_LEGS")
    if type(reservations) not in (list, tuple) or len(reservations) > 256:
        return _assessment("INVALID_RESERVATIONS")
    # A new decimal context makes results independent of the caller's precision.
    # Bounds above guarantee exactness for sums/products of up to four legs.
    with localcontext(Context(prec=256)):
        return _evaluate(payload, legs, reservations)


def _evaluate(payload, legs, reservations):
    missing = []
    causality, decision_at = _causality(payload)
    gross_parts, capital_parts, cost_parts, nominal_parts = [], [], [], []
    symbols = set()
    for leg in legs:
        if (type(leg) is not dict or type(leg.get("symbol")) is not str
                or not _SYMBOL.fullmatch(leg["symbol"])
                or type(leg.get("venue")) is not str or leg["venue"] not in _VENUES
                or leg.get("direction") not in ("LONG", "SHORT")):
            return _assessment("INVALID_LEG")
        symbols.add(leg["symbol"])
        quantity, price = _decimal(leg.get("quantity")), _decimal(leg.get("reference_price"))
        if quantity is None or not quantity or price is None or price <= 0:
            missing.append("QUANTITY_OR_PRICE_UNKNOWN")
            gross_parts.append(None)
            capital_parts.append(None)
            cost_parts.append(None)
            nominal_parts.append(None)
            continue
        quantity = abs(quantity)
        gross = quantity * price
        gross_parts.append(gross)
        if leg.get("gross_notional") is not None:
            stated = _decimal(leg["gross_notional"])
            if stated is None or stated != gross:
                missing.append("GROSS_EVIDENCE_INCONSISTENT")
        futures = payload["engine"] == "FUTURES" or leg["venue"].startswith("FUTURES")
        margin = _decimal(leg.get("margin"))
        if leg.get("margin") is not None and (margin is None or margin <= 0):
            missing.append("MARGIN_UNKNOWN")
            capital_parts.append(None)
        elif margin is not None:
            capital_parts.append(margin)
        elif futures:
            missing.append("MARGIN_UNKNOWN")
            capital_parts.append(None)
        else:
            capital_parts.append(gross)
        fee, slippage = _decimal(leg.get("fee_rate")), _decimal(leg.get("slippage_rate"))
        if fee is None or slippage is None or not 0 <= fee <= 1 or not 0 <= slippage <= 1:
            missing.append("COST_EVIDENCE_UNKNOWN")
            cost_parts.append(None)
        else:
            cost_parts.append(_TWO * gross * (fee + slippage))
        stop = _decimal(leg.get("stop_price"))
        long = leg["direction"] == "LONG"
        if stop is None or stop <= 0 or (stop >= price if long else stop <= price):
            missing.append("STOP_EVIDENCE_UNKNOWN")
            nominal_parts.append(None)
        else:
            nominal_parts.append(quantity * abs(price - stop))
        if leg.get("take_profit") is not None:
            target = _decimal(leg["take_profit"])
            if target is None or target <= 0 or (target <= price if long else target >= price):
                missing.append("TARGET_EVIDENCE_INCONSISTENT")

    def complete_sum(parts):
        return None if None in parts else sum(parts, _ZERO)

    gross, capital = complete_sum(gross_parts), complete_sum(capital_parts)
    costs, nominal = complete_sum(cost_parts), complete_sum(nominal_parts)
    risk = None if nominal is None or costs is None else nominal + costs
    metrics = {"gross": gross, "capital": capital, "costs": costs,
               "nominal": nominal, "risk": risk}
    prior = {key: _ZERO for key in ("gross", "capital", "costs", "stop_risk")}
    seen = set()
    active_count, conflict = 0, False
    for reservation in reservations:
        if type(reservation) is not dict:
            missing.append("RESERVATION_EVIDENCE_UNKNOWN")
            continue
        origin = reservation.get("origin_digest")
        if type(origin) is not str or not 1 <= len(origin) <= 128 or origin in seen:
            missing.append("RESERVATION_EVIDENCE_UNKNOWN")
            continue
        seen.add(origin)
        if origin == payload.get("origin_digest"):
            continue
        active_count += 1
        prior_symbols = reservation.get("symbols")
        if (type(prior_symbols) is not list or not 1 <= len(prior_symbols) <= 4
                or any(type(symbol) is not str or not _SYMBOL.fullmatch(symbol)
                       for symbol in prior_symbols)):
            missing.append("RESERVATION_SYMBOLS_UNKNOWN")
        elif symbols.intersection(prior_symbols):
            conflict = True
        for key in prior:
            value = _decimal(reservation.get(key))
            if value is None or value < 0:
                missing.append("RESERVATION_EVIDENCE_UNKNOWN")
            else:
                # Known values are lower bounds for rejection only. Missing
                # values always prevent a hypothetical successful reservation.
                prior[key] += value

    limits = payload.get("limits")
    if type(limits) is not dict:
        limits = {}
    caps = {}
    for key in ("gross_limit", "capital_limit", "stop_risk_limit"):
        value = _decimal(limits.get(key))
        if value is None or value < 0:
            missing.append("LIMIT_EVIDENCE_UNKNOWN")
            value = None
        caps[key] = value
    max_positions = limits.get("max_positions")
    if type(max_positions) is not int or not 0 <= max_positions <= 1000000:
        missing.append("LIMIT_EVIDENCE_UNKNOWN")
        max_positions = None
    account = payload.get("capital")
    if type(account) is not dict:
        account = {}
    available = _decimal(account.get("available"))
    if any(account.get(key) is not None and _decimal(account[key]) is None
           for key in ("cash", "equity")):
        missing.append("CAPITAL_EVIDENCE_UNKNOWN")
    capital_at = account.get("at")
    if available is None:
        missing.append("AVAILABLE_CAPITAL_UNKNOWN")
    if not _epoch(capital_at):
        missing.append("CAPITAL_TIMESTAMP_UNKNOWN")
        available = None
    elif capital_at > payload["at"]:
        missing.append("CAPITAL_EVIDENCE_FUTURE")
        causality = causality or "CAPITAL_EVIDENCE_FUTURE"
        available = None
    elif decision_at is not None and capital_at > decision_at:
        missing.append("CAPITAL_EVIDENCE_AFTER_DECISION")
        causality = causality or "CAPITAL_EVIDENCE_AFTER_DECISION"
        available = None
    elif decision_at is not None and decision_at - capital_at > 90:
        missing.append("CAPITAL_EVIDENCE_STALE")
        available = None
    breaches = []
    if conflict:
        breaches.append("OBSERVED_ASSET_CONFLICT")
    if max_positions is not None and active_count + 1 > max_positions:
        breaches.append("POSITION_LIMIT_EXCEEDED")
    lower_gross = sum((part for part in gross_parts if part is not None), _ZERO)
    lower_capital = sum((part for part in capital_parts if part is not None), _ZERO)
    lower_costs = sum((part for part in cost_parts if part is not None), _ZERO)
    lower_risk = sum((part for part in nominal_parts if part is not None), _ZERO) + lower_costs
    if caps["gross_limit"] is not None and lower_gross + prior["gross"] > caps["gross_limit"]:
        breaches.append("GROSS_LIMIT_EXCEEDED")
    if caps["stop_risk_limit"] is not None and lower_risk + prior["stop_risk"] > caps["stop_risk_limit"]:
        breaches.append("STOP_RISK_LIMIT_EXCEEDED")
    allocated = lower_capital + lower_costs + prior["capital"] + prior["costs"]
    if caps["capital_limit"] is not None and allocated > caps["capital_limit"]:
        breaches.append("CAPITAL_LIMIT_EXCEEDED")
    if available is not None and allocated > available:
        breaches.append("AVAILABLE_CAPITAL_EXCEEDED")
    if causality:
        return _assessment(causality, **metrics)
    if breaches:
        return _assessment(breaches[0], "REJECTED_UNVERIFIED", **metrics)
    if missing:
        return _assessment(missing[0], **metrics)
    return _assessment("ACCOUNT_IDENTITY_UNVERIFIED", "RESERVED_UNVERIFIED", **metrics)
