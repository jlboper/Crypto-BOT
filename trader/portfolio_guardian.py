"""Bounded read-only diagnostics over existing, credential-free portal evidence.

This module has no database, filesystem, network, broker or trading dependencies.
Guardian observes separate ledgers; it cannot reserve funds, veto an entry, change
limits or delay a protective close. Nominal stop distance excludes execution costs,
gaps and funding and must never be compared with an inclusive stop-risk budget.
"""
from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime


MAX_SCOPES = 4
MAX_ASSETS = 40
MAX_ALERTS = 20
MAX_OVERLAPS = 10
MAX_BYTES = 15_000
_SYMBOL = re.compile(r"^[A-Z0-9]{2,24}USDT$")
_LIMITATIONS = [
    "SEPARATE_ENVIRONMENTS_NO_FINANCIAL_TOTAL",
    "LEDGER_INVENTORY_IS_NOT_COMPLETE_EXCHANGE_ACCOUNT_RECONCILIATION",
    "NOMINAL_STOP_DISTANCE_EXCLUDES_COSTS_GAPS_AND_FUNDING",
    "NATIVE_PROTECTION_IS_NOT_A_GUARANTEED_LOSS_BOUND",
    "RESERVATIONS_NOT_INTEGRATED_NO_ADMISSION_OR_VETO",
    "CROSS_SCOPE_OVERLAP_IS_NOT_A_VERIFIED_HEDGE",
    "FUNDING_LIQUIDATION_NOT_OBSERVED",
    "CORRELATION_DRAWDOWN_NOT_COMPUTED",
]


def _number(value, *, minimum=None):
    if type(value) not in (int, float):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(result) or minimum is not None and result < minimum:
        return None
    return result


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _now(value=None):
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC)
    if type(value) in (float, int) and math.isfinite(value):
        return datetime.fromtimestamp(value, UTC)
    parsed = _time(value)
    if parsed is None:
        raise ValueError("Guardian requires an explicit valid UTC instant")
    return parsed


def _iso(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else None


def _fresh(value, now, maximum):
    instant = _time(value)
    return instant is not None and -5 <= (now - instant).total_seconds() <= maximum


def _dict(value):
    return value if isinstance(value, dict) else {}


def _latest(value):
    return _dict(value[-1]) if isinstance(value, list) and value else {}


def _positive(value):
    number = _number(value, minimum=0)
    return number if number is not None and number > 0 else None


def _safe_sum(values):
    try:
        value = math.fsum(values)
        return value if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _cycle_seconds(status):
    value = _number(status.get("cycle_seconds"), minimum=1)
    return min(value, 86_400) if value is not None else 300


def quant_not_started(now=None):
    """An identity scaffold, never a Quant engine, wallet or performance sample."""
    return {
        "schema": 1, "engine": "QUANT_ARBITRAGE", "mode": "SHADOW",
        "state": "NOT_STARTED", "initialized": False, "enabled": False,
        "execution_enabled": False, "controls_available": False,
        "at": _iso(_now(now)), "updated_at": None,
        "freshness": {"state": "UNAVAILABLE", "age_seconds": None},
        "positions": [],
        "performance": {"initial_capital": None, "equity": None,
                        "net_pnl": None, "closed_trades": None},
        "strategies": [{"id": "FUNDING_CARRY", "state": "NOT_STARTED"},
                       {"id": "STATISTICAL_ARBITRAGE", "state": "NOT_STARTED"}],
        "promotion_allowed": False,
    }


def engine_catalog(dashboard=None):
    """Stable identities/capabilities; no claim of current engine liveness."""
    mode = _dict(_dict(dashboard).get("status")).get("mode")
    return [
        {"id": "SPOT", "name": "Spot Bot", "environment": "SPOT_TESTNET" if mode == "TESTNET" else "PAPER" if mode == "PAPER" else "UNKNOWN", "role": "TREND", "state": "OBSERVED_EXTERNALLY"},
        {"id": "FUTURES", "name": "Futures Bot", "environment": "FUTURES_DEMO", "role": "LONG_SHORT", "state": "OBSERVED_EXTERNALLY"},
        {"id": "AI_MARKET_PULSE", "name": "AI Market Pulse", "environment": "SHADOW", "role": "EVENTS", "state": "OBSERVED_EXTERNALLY"},
        {"id": "QUANT_ARBITRAGE", "name": "Quant Arbitrage", "environment": "SHADOW", "role": "CARRY_STATISTICAL_RESEARCH", "state": "NOT_STARTED"},
    ]


def _base(now, state):
    return {
        "schema": 1, "engine": "PORTFOLIO_GUARDIAN", "mode": "OBSERVER",
        "state": state, "at": _iso(now), "controls_enabled": False,
        "can_veto": False, "execution_enabled": False,
        "scopes": [],
        "reservations": {"state": "NOT_INTEGRATED", "reserved_usdt": None,
                         "reserved_stop_risk_usdt": None},
        "risk_quality": {"correlation": "UNKNOWN", "daily_loss": "UNKNOWN",
                         "weekly_loss": "UNKNOWN", "drawdown": "UNKNOWN"},
        "overlaps": [], "alerts": [],
        "truncation": {"assets_omitted": 0, "alerts_omitted": 0, "overlaps_omitted": 0},
        "limitations": list(_LIMITATIONS),
    }


def guardian_unavailable(now=None):
    """Safe complete fallback for callers isolating optional Observer failures."""
    instant = _now(now)
    result = _base(instant, "DEGRADED")
    for identifier, environment in (("SPOT", "UNKNOWN"), ("FUTURES", "FUTURES_DEMO"),
                                    ("AI_MARKET_PULSE", "SHADOW"), ("QUANT_ARBITRAGE", "SHADOW")):
        scope, _ = _scope(identifier, environment, None, now=instant)
        scope["capital"] = _capital(None, None, None, None, instant, 30, False)
        if identifier == "QUANT_ARBITRAGE":
            scope["state"] = "NOT_STARTED"
        result["scopes"].append(scope)
    result["alerts"] = [{"code": "GUARDIAN_UNAVAILABLE", "severity": "WARNING",
                         "scope": None, "symbol": None}]
    return result


def _capital(equity, cash, available, at, now, maximum, marks_current):
    fresh = _fresh(at, now, maximum)
    observed_equity = _number(equity, minimum=0) if fresh and marks_current else None
    return {"equity_usdt": observed_equity,
            "cash_usdt": _number(cash, minimum=0) if fresh else None,
            "available_usdt": _number(available, minimum=0) if fresh else None,
            "at": _iso(_time(at)), "state": "FRESH" if observed_equity is not None else "UNKNOWN"}


def _native(native, symbol, applicable):
    if not applicable:
        return "NOT_APPLICABLE"
    state = _dict(_dict(_dict(native).get("positions")).get(symbol)).get("status")
    return state if isinstance(state, str) and state in {"ARMED", "PENDING", "ERROR", "UNAVAILABLE", "RECONCILING"} else "UNKNOWN"


def _scope(identifier, environment, rows, *, now, source_at=None, maximum=600,
           fresh_source=False, initialized=False, mark_key="mark_price", stop_key="stop_price",
           price_at=None, native=None, native_applicable=False, pulse_market=None):
    observed = initialized and isinstance(rows, list)
    rows = rows if observed else []
    total = len(rows) if observed else None
    overflow = max(0, len(rows) - MAX_ASSETS)
    result = {"id": identifier, "engine": identifier, "environment": environment,
              "inventory_scope": "LEDGER_ONLY", "state": "UNAVAILABLE",
              "position_count": total, "unpriced_positions": None,
              "gross_usdt": None, "net_usdt": None,
              "known_gross_usdt": None, "known_net_usdt": None,
              "nominal_stop_risk_usdt": None,
              "capital": {}, "limits": {"gross_usdt": None, "stop_risk_usdt": None},
              "budget_status": {"gross": "UNKNOWN", "stop_risk": "UNKNOWN"},
              "observed_budget": {"gross_usdt": None, "stop_risk_usdt": None, "at": None},
              "assets": [], "assets_omitted": overflow}
    alerts, gross, signed, risks, unpriced = [], [], [], [], overflow
    symbols_seen = set()
    unknown_risk = bool(overflow)
    if not observed:
        return result, alerts
    for row in rows[:MAX_ASSETS]:
        row = _dict(row)
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            unpriced += 1
            unknown_risk = True
            alerts.append(("INVALID_POSITION", "WARNING", None))
            continue
        if symbol in symbols_seen:
            unpriced += 1
            unknown_risk = True
            alerts.append(("DUPLICATE_POSITION", "WARNING", symbol))
            continue
        symbols_seen.add(symbol)
        direction = row.get("direction") if identifier == "FUTURES" else "LONG"
        direction = direction if isinstance(direction, str) else None
        quantity = _positive(row.get("quantity"))
        mark = _positive(row.get(mark_key))
        stamp = row.get("priced_at", price_at)
        current = fresh_source and _fresh(stamp, now, maximum)
        if pulse_market is not None:
            market = pulse_market.get(symbol, {})
            current = current and market.get("fresh") is True and _fresh(market.get("at"), now, maximum)
        if direction not in {"LONG", "SHORT"}:
            quantity = None
        notional = quantity * mark if quantity is not None and mark is not None and current else None
        notional = _number(notional, minimum=0)
        mark = mark if notional is not None else None
        signed_value = notional * (-1 if direction == "SHORT" else 1) if notional is not None else None
        stop = _positive(row.get(stop_key))
        risk = None
        if notional is not None and stop is not None:
            distance = mark - stop if direction == "LONG" else stop - mark
            if distance > 0:
                risk = _number(quantity * distance, minimum=0)
            else:
                alerts.append(("PROTECTIVE_THRESHOLD_CROSSED", "WARNING", symbol))
        if risk is None:
            unknown_risk = True
        else:
            risks.append(risk)
        protection = _native(native, symbol, native_applicable)
        if native_applicable and protection != "ARMED":
            alerts.append(("NATIVE_PROTECTION_UNCONFIRMED", "WARNING", symbol))
        if notional is None:
            unpriced += 1
            alerts.append(("POSITION_VALUE_UNKNOWN", "WARNING", symbol))
        else:
            gross.append(notional)
            signed.append(signed_value)
        result["assets"].append({"symbol": symbol, "direction": direction if direction in {"LONG", "SHORT"} else "UNKNOWN",
                                 "quantity": quantity, "mark_price": mark,
                                 "notional_usdt": notional, "signed_notional_usdt": signed_value,
                                 "stop_price": stop, "nominal_stop_risk_usdt": risk,
                                 "priced_at": _iso(_time(stamp)), "native_protection": protection,
                                 "state": "FRESH" if notional is not None else "UNKNOWN",
                                 "concentration_pct": None})
    known = bool(gross) or (not rows and fresh_source)
    result["unpriced_positions"] = unpriced
    result["known_gross_usdt"] = _safe_sum(gross) if known else None
    result["known_net_usdt"] = _safe_sum(signed) if known else None
    complete = fresh_source and not unpriced and len(result["assets"]) == len(rows)
    if complete and (result["known_gross_usdt"] is None or result["known_net_usdt"] is None):
        complete = False
        alerts.append(("AGGREGATE_VALUE_UNKNOWN", "WARNING", None))
    if complete:
        result["gross_usdt"] = result["known_gross_usdt"]
        result["net_usdt"] = result["known_net_usdt"]
        result["nominal_stop_risk_usdt"] = _safe_sum(risks) if not unknown_risk else None
        if result["gross_usdt"] is not None and result["gross_usdt"] > 0:
            for asset in result["assets"]:
                asset["concentration_pct"] = asset["notional_usdt"] / result["gross_usdt"] * 100
    result["state"] = "FRESH" if complete else "PARTIAL"
    if not fresh_source:
        alerts.append(("SOURCE_STALE_OR_UNAVAILABLE", "WARNING", None))
    return result, alerts


def _budget(scope, gross_limit, stop_limit, budget, now, maximum):
    gross_limit, stop_limit = _positive(gross_limit), _positive(stop_limit)
    scope["limits"].update(gross_usdt=gross_limit, stop_risk_usdt=stop_limit)
    if gross_limit is not None and scope["gross_usdt"] is not None:
        scope["budget_status"]["gross"] = "EXCEEDED" if scope["gross_usdt"] > gross_limit else "WITHIN"
    budget = _dict(budget)
    at = budget.get("at")
    scope["observed_budget"]["at"] = _iso(_time(at))
    if _fresh(at, now, maximum):
        observed_gross = _number(budget.get("notional_usdt"), minimum=0)
        observed_stop = _number(budget.get("stop_loss_usdt"), minimum=0)
        scope["observed_budget"].update(gross_usdt=observed_gross, stop_risk_usdt=observed_stop)
        # This is the existing engine's cost-inclusive observed budget, not
        # Guardian's separate nominal stop-distance calculation.
        if observed_stop is not None and stop_limit is not None:
            scope["budget_status"]["stop_risk"] = "OBSERVED_EXCEEDED" if observed_stop > stop_limit else "OBSERVED_WITHIN"


def _bounded(result):
    # Preserve scoped aggregates and freshness while thinning only display rows.
    while sum(len(scope["assets"]) for scope in result["scopes"]) > MAX_ASSETS:
        scope = max(result["scopes"], key=lambda item: len(item["assets"]))
        scope["assets"].pop()
        scope["assets_omitted"] += 1
    while len(json.dumps(result, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()) >= MAX_BYTES - 128:
        scope = max(result["scopes"], key=lambda item: len(item["assets"]))
        if scope["assets"]:
            scope["assets"].pop()
            scope["assets_omitted"] += 1
        elif result["overlaps"]:
            result["overlaps"].pop()
            result["truncation"]["overlaps_omitted"] += 1
        else:
            return guardian_unavailable(result["at"])
    result["truncation"]["assets_omitted"] = sum(scope["assets_omitted"] for scope in result["scopes"])
    return result


def build_guardian(dashboard, now=None):
    """Build non-authoritative diagnostics; inputs are never mutated.

    An initialized, fresh empty ledger can have zero observed exposure. Missing,
    stale, malformed or truncated inventories cannot become a zero portfolio.
    Account identity/common reservation participation is deliberately unverified.
    """
    instant = _now(now)
    dashboard = _dict(dashboard)
    result = _base(instant, "PARTIAL")
    status = _dict(dashboard.get("status"))
    maximum = max(_cycle_seconds(status) * 1.5, _cycle_seconds(status) + 120)
    score = _dict(dashboard.get("paper_scorecard"))
    quote_at = score.get("prices_at")
    spot_equity = _latest(dashboard.get("equity"))
    spot_at = quote_at if dashboard.get("positions") else spot_equity.get("created_at")
    mode = status.get("mode") if isinstance(status.get("mode"), str) else None
    spot, spot_alerts = _scope("SPOT", "SPOT_TESTNET" if mode == "TESTNET" else "PAPER" if mode == "PAPER" else "UNKNOWN",
        dashboard.get("positions"), now=instant, source_at=spot_at, maximum=maximum,
        fresh_source=_fresh(spot_at, instant, maximum), initialized=mode in {"TESTNET", "PAPER"},
        mark_key="market_price", price_at=quote_at, native=status.get("native_protection"), native_applicable=mode == "TESTNET")
    spot["capital"] = _capital(spot_equity.get("equity"), spot_equity.get("cash"), None,
        spot_equity.get("created_at"), instant, maximum, spot["state"] == "FRESH")
    fraction = _number(_dict(status.get("risk", dashboard.get("risk"))).get("max_total_exposure_pct"), minimum=0)
    equity = spot["capital"]["equity_usdt"]
    gross_limit = equity * fraction if equity is not None and fraction is not None and fraction <= 1 else None
    _budget(spot, gross_limit, None, {}, instant, maximum)

    futures = _dict(dashboard.get("futures_forward"))
    f_state = futures.get("state") if isinstance(futures.get("state"), str) else None
    futures_rows = futures.get("positions")
    if not isinstance(futures_rows, list) and isinstance(futures.get("position"), dict):
        futures_rows = [futures["position"]]
    future_equity = _latest(futures.get("equity"))
    budget = _dict(futures.get("portfolio_budget"))
    f_at = _dict(futures.get("cycle_diagnostic")).get("at") or future_equity.get("created_at") or budget.get("at")
    initialized = (bool(futures) and isinstance(futures_rows, list)
                   and futures.get("initialized") is not False
                   and f_state not in {"NOT_STARTED", "UNAVAILABLE"})
    f_scope, f_alerts = _scope("FUTURES", "FUTURES_DEMO", futures_rows, now=instant,
        source_at=f_at, maximum=600, fresh_source=_fresh(f_at, instant, 600), initialized=initialized,
        native=futures.get("native_protection"), native_applicable=True)
    if f_state == "NOT_STARTED":
        f_scope["state"] = "NOT_STARTED"
    wallet = _number(future_equity.get("wallet_balance"), minimum=0)
    pnl = _number(future_equity.get("unrealized_pnl"))
    f_equity = _safe_sum([wallet, pnl]) if wallet is not None and pnl is not None else None
    f_scope["capital"] = _capital(f_equity, None, future_equity.get("available_balance"),
        future_equity.get("created_at"), instant, 600, f_scope["state"] == "FRESH")
    guardrails = _dict(futures.get("guardrails"))
    _budget(f_scope, guardrails.get("forward_total_notional_usdt", budget.get("notional_limit_usdt")),
            guardrails.get("forward_total_stop_loss_usdt", budget.get("stop_loss_limit_usdt")), budget, instant, 600)

    pulse = _dict(dashboard.get("market_pulse"))
    p_state = pulse.get("state") if isinstance(pulse.get("state"), str) else None
    market_rows = pulse.get("market")
    markets = {row["symbol"]: row for row in market_rows[:10]
               if isinstance(row, dict) and isinstance(row.get("symbol"), str)} if isinstance(market_rows, list) else {}
    p_at = pulse.get("updated_at")
    p_fresh = _dict(pulse.get("freshness")).get("state") == "FRESH" and _fresh(p_at, instant, 30)
    p_scope, p_alerts = _scope("AI_MARKET_PULSE", "SHADOW", pulse.get("positions"), now=instant,
        source_at=p_at, maximum=30, fresh_source=p_fresh,
        initialized=(pulse.get("mode") == "SHADOW" and p_state not in {None, "NOT_STARTED"}
                     and _positive(_dict(pulse.get("performance")).get("initial_capital")) is not None
                     and _time(p_at) is not None
                     and _dict(pulse.get("health")).get("last_error") != "SHADOW_LEDGER_UNAVAILABLE"),
        stop_key="stop", price_at=p_at, pulse_market=markets)
    if p_state == "NOT_STARTED":
        p_scope["state"] = "NOT_STARTED"
    perf = _dict(pulse.get("performance"))
    p_scope["capital"] = _capital(perf.get("equity"), perf.get("cash"), None,
        p_at, instant, 30, p_scope["state"] == "FRESH")
    # Effective Pulse caps can be lower than nominal defaults. Do not invent them.
    _budget(p_scope, _dict(pulse.get("limits")).get("gross_usdt"),
            _dict(pulse.get("limits")).get("stop_risk_usdt"), {}, instant, 30)

    q_scope, _ = _scope("QUANT_ARBITRAGE", "SHADOW", None, now=instant)
    q_scope["state"] = "NOT_STARTED"
    q_scope["capital"] = _capital(None, None, None, None, instant, 30, False)
    result["scopes"] = [spot, f_scope, p_scope, q_scope]
    alert_rows = []
    for scope, alerts in ((spot, spot_alerts), (f_scope, f_alerts), (p_scope, p_alerts)):
        for code, severity, symbol in alerts:
            alert_rows.append({"code": code, "severity": severity, "scope": scope["id"], "symbol": symbol})
        for metric in ("gross", "stop_risk"):
            if scope["budget_status"][metric] in {"EXCEEDED", "OBSERVED_EXCEEDED"}:
                alert_rows.append({"code": "GROSS_LIMIT_EXCEEDED" if metric == "gross" else "OBSERVED_STOP_RISK_LIMIT_EXCEEDED",
                                   "severity": "WARNING", "scope": scope["id"], "symbol": None})
    # Observe overlapping ledgers without netting their financially separate books.
    by_symbol = {}
    for scope in result["scopes"]:
        for asset in scope["assets"]:
            by_symbol.setdefault(asset["symbol"], []).append((scope["id"], asset["direction"]))
    overlaps = [{"symbol": symbol, "scopes": [item[0] for item in members],
                 "directions": [item[1] for item in members], "classification": "CROSS_SCOPE_OBSERVATION"}
                for symbol, members in sorted(by_symbol.items()) if len({item[0] for item in members}) > 1]
    result["overlaps"] = overlaps[:MAX_OVERLAPS]
    result["truncation"]["overlaps_omitted"] = max(0, len(overlaps) - MAX_OVERLAPS)
    unique = []
    seen = set()
    for alert in alert_rows:
        identity = (alert["code"], alert["scope"], alert["symbol"])
        if identity not in seen:
            seen.add(identity)
            unique.append(alert)
    priority = {"GROSS_LIMIT_EXCEEDED": 0, "OBSERVED_STOP_RISK_LIMIT_EXCEEDED": 0,
                "PROTECTIVE_THRESHOLD_CROSSED": 1, "NATIVE_PROTECTION_UNCONFIRMED": 2,
                "INVALID_POSITION": 3, "DUPLICATE_POSITION": 3,
                "SOURCE_STALE_OR_UNAVAILABLE": 4, "AGGREGATE_VALUE_UNKNOWN": 4,
                "POSITION_VALUE_UNKNOWN": 5}
    unique.sort(key=lambda alert: (priority.get(alert["code"], 6), alert["scope"], alert["symbol"] or ""))
    result["alerts"] = unique[:MAX_ALERTS]
    result["truncation"]["alerts_omitted"] = max(0, len(unique) - MAX_ALERTS)
    result["state"] = "OBSERVING" if all(scope["state"] == "FRESH" for scope in result["scopes"][:3]) else "PARTIAL"
    return _bounded(result)
