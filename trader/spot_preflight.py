"""Read-only estimate of Spot MARKET quantity compatibility; never places orders."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def market_quantity_preflight(symbol_info: dict | None, quantity: float, spot_price: float) -> tuple[str, list[str]]:
    """Check public filters. Spot price is only a proxy for MARKET notional rules.

    A passing estimate does not check account balance, weighted average price,
    exchange availability or the eventual fill. PAPER trades remain unchanged.
    """
    if not isinstance(symbol_info, dict) or not isinstance(symbol_info.get('filters'), list):
        return 'unknown', ['RULES_UNAVAILABLE']
    try:
        qty, price = Decimal(str(quantity)), Decimal(str(spot_price))
        if not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0:
            return 'unknown', ['INVALID_INPUT']
        filters = {item['filterType']: item for item in symbol_info['filters']
                   if isinstance(item, dict) and isinstance(item.get('filterType'), str)}
        if 'LOT_SIZE' not in filters:
            return 'unknown', ['LOT_SIZE_UNAVAILABLE']
        reasons = []
        for kind in ('LOT_SIZE', 'MARKET_LOT_SIZE'):
            rule = filters.get(kind)
            if rule is None:
                continue
            minimum, maximum, step = (Decimal(str(rule[key])) for key in ('minQty', 'maxQty', 'stepSize'))
            if minimum > 0 and qty < minimum:
                reasons.append(f'{kind}_MIN')
            if maximum > 0 and qty > maximum:
                reasons.append(f'{kind}_MAX')
            if step > 0 and qty % step != 0:
                reasons.append(f'{kind}_STEP')
        notional = qty * price
        minimum_rule = filters.get('MIN_NOTIONAL')
        if minimum_rule and minimum_rule.get('applyToMarket') is True:
            minimum = Decimal(str(minimum_rule['minNotional']))
            if minimum > 0 and notional < minimum:
                reasons.append('MIN_NOTIONAL_ESTIMATE')
        band = filters.get('NOTIONAL')
        if band:
            if band.get('applyMinToMarket') is True:
                minimum = Decimal(str(band['minNotional']))
                if minimum > 0 and notional < minimum:
                    reasons.append('NOTIONAL_MIN_ESTIMATE')
            if band.get('applyMaxToMarket') is True:
                maximum = Decimal(str(band['maxNotional']))
                if maximum > 0 and notional > maximum:
                    reasons.append('NOTIONAL_MAX_ESTIMATE')
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return 'unknown', ['RULES_INVALID']
    return ('incompatible' if reasons else 'estimated_compatible', reasons)
