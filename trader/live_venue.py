"""Retained production venue checks; no observation commissions execution.

Grids, price references, current order counts and leverage brackets use actual
GET responses. Undocumented semantics stay explicit and never become permission.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re
import time

from .live_transport import LiveError, LiveHTTPError, LiveReadOnlyTransport, SYMBOL


def _number(value, zero=False, signed=False):
    if type(value) not in {str, int} or len(str(value)) > 64:
        raise LiveError('VENUE_DECIMAL_UNKNOWN')
    try:
        out = Decimal(value)
        if (not out.is_finite() or not signed and out < 0 or not zero and out == 0
                or abs(out) >= Decimal('1e18') or out.as_tuple().exponent < -18):
            raise ValueError()
        return out
    except (ValueError, InvalidOperation):
        raise LiveError('VENUE_DECIMAL_UNKNOWN') from None


def _ceil(value):
    return int(value.to_integral_value(rounding=ROUND_CEILING))


class LiveVenueReader:
    def __init__(self, transport, *, retain, clock=time.time):
        if type(transport) is not LiveReadOnlyTransport or not callable(retain):
            raise LiveError('READ_ONLY_RETAINED_VENUE_REQUIRED')
        self.transport, self.retain, self.clock = transport, retain, clock

    def _get(self, environment, endpoint, params=None):
        began = self.clock()
        raw = self.transport.get(environment, endpoint, params or {})
        receipt = self.retain({'environment':environment, 'endpoint':endpoint, 'params':params or {},
            'request_started_at':began, 'received_at':self.clock(), 'response':raw})
        if (type(receipt) is not dict or type(receipt.get('sha256')) is not str
                or not re.fullmatch('[0-9a-f]{64}', receipt['sha256'])):
            raise LiveError('ENCRYPTED_ORIGINAL_VENUE_RECEIPT_REQUIRED')
        return raw

    def _fresh_time(self, stamp):
        if type(stamp) is not int or stamp <= 0 or not -2 <= self.clock() - stamp / 1000 <= 30:
            raise LiveError('VENUE_REFERENCE_STALE_OR_FUTURE')

    @staticmethod
    def _rows(value, *, identity, symbol=None):
        if type(value) is not list or len(value) > 10000:
            raise LiveError('VENUE_CURRENT_ORDER_ROWS_UNKNOWN')
        seen = set()
        for row in value:
            if (type(row) is not dict or type(row.get(identity)) is not int or row[identity] < 0
                    or row[identity] in seen or type(row.get('symbol')) is not str
                    or symbol is not None and row['symbol'] != symbol):
                raise LiveError('VENUE_CURRENT_ORDER_ROWS_UNKNOWN')
            seen.add(row[identity])
        return value

    def _spot_references(self, symbol, filters):
        needs = any(kind in filters for kind in ('MIN_NOTIONAL','NOTIONAL','PERCENT_PRICE','PERCENT_PRICE_BY_SIDE'))
        if not needs:
            return {}, []
        began = self.clock()
        try:
            reference = self._get('SPOT_LIVE', '/api/v3/referencePrice', {'symbol':symbol})
        except LiveHTTPError as error:
            # Only the documented -2043 establishes that no reference has ever
            # existed. Network failures and other rejections are not absence.
            if error.provider_code != -2043 or error.http_status != 400:
                raise
            retained = self.retain({'environment':'SPOT_LIVE', 'endpoint':'/api/v3/referencePrice',
                'params':{'symbol':symbol}, 'request_started_at':began, 'received_at':self.clock(),
                'error':{'http_status':400,'provider_code':-2043}})
            if type(retained) is not dict or not re.fullmatch('[0-9a-f]{64}', str(retained.get('sha256',''))):
                raise LiveError('ENCRYPTED_ORIGINAL_VENUE_RECEIPT_REQUIRED')
            reference = {'symbol':symbol, 'referencePrice':None, 'absence_provider_code':-2043}
        if type(reference) is not dict or reference.get('symbol') != symbol or 'referencePrice' not in reference:
            raise LiveError('VENUE_REFERENCE_PRICE_UNKNOWN')
        if reference['referencePrice'] is not None:
            _number(reference['referencePrice'])
            self._fresh_time(reference.get('timestamp'))
            average = None
        else:
            average = self._get('SPOT_LIVE', '/api/v3/avgPrice', {'symbol':symbol})
            if (type(average) is not dict or type(average.get('mins')) is not int
                    or not 0 <= average['mins'] <= 1440):
                raise LiveError('VENUE_AVERAGE_PRICE_UNKNOWN')
            _number(average.get('price'))
            self._fresh_time(average.get('closeTime'))
        reasons = []
        if average is not None and any(
                type(rule.get('avgPriceMins')) is not int or rule['avgPriceMins'] != average['mins']
                for kind, rule in filters.items() if kind in {'MIN_NOTIONAL','NOTIONAL','PERCENT_PRICE','PERCENT_PRICE_BY_SIDE'}):
            reasons.append('VENUE_AVERAGE_INTERVAL_MISMATCH')
        execution = self._get('SPOT_LIVE', '/api/v3/executionRules', {'symbol':symbol})
        rules = execution.get('symbolRules') if type(execution) is dict else None
        if (type(rules) is not list or len(rules) > 1
                or any(type(row) is not dict or row.get('symbol') != symbol or type(row.get('rules')) is not list for row in rules)):
            raise LiveError('VENUE_EXECUTION_RULES_UNKNOWN')
        active_rules = rules[0]['rules'] if rules else []
        if len(active_rules) > 16 or any(type(r) is not dict or r.get('ruleType') != 'PRICE_RANGE' for r in active_rules):
            reasons.append('UNSUPPORTED_VENUE_EXECUTION_RULE')
        return {'reference':reference, 'average':average, 'execution_rules':active_rules}, reasons

    def _account_constraints(self, environment, symbol, filters, exchange_filters):
        spot = environment == 'SPOT_LIVE'
        needed = any(kind in filters for kind in ('MAX_NUM_ORDERS','MAX_NUM_ALGO_ORDERS','MAX_NUM_ORDER_LISTS','MAX_POSITION')) or bool(exchange_filters) or not spot
        if not needed:
            return {}, []
        orders = self._rows(self._get(environment, '/api/v3/openOrders' if spot else '/fapi/v1/openOrders',
            {} if exchange_filters else {'symbol':symbol}), identity='orderId', symbol=None if exchange_filters else symbol)
        symbol_orders = [r for r in orders if r['symbol'] == symbol]
        if spot:
            kinds = {'LIMIT','LIMIT_MAKER','MARKET','STOP_LOSS','STOP_LOSS_LIMIT','TAKE_PROFIT','TAKE_PROFIT_LIMIT'}
            if any(r.get('type') not in kinds for r in orders):
                raise LiveError('VENUE_CURRENT_ORDER_TYPE_UNKNOWN')
            algo = [r for r in orders if r['type'] in {'STOP_LOSS','STOP_LOSS_LIMIT','TAKE_PROFIT','TAKE_PROFIT_LIMIT'}]
            lists = self._rows(self._get(environment, '/api/v3/openOrderList'), identity='orderListId')
            balance = None
            if 'MAX_POSITION' in filters:
                raw = self._get(environment, '/api/v3/account')
                rows = raw.get('balances') if type(raw) is dict else None
                balances = [r for r in rows if type(r) is dict and r.get('asset') == symbol[:-4]] if type(rows) is list else []
                if len(balances) != 1:
                    raise LiveError('VENUE_CURRENT_BASE_BALANCE_UNKNOWN')
                balance = format(_number(balances[0].get('free'), True) + _number(balances[0].get('locked'), True), 'f')
        else:
            algo = self._rows(self._get(environment, '/fapi/v1/openAlgoOrders', {'symbol':symbol}), identity='algoId', symbol=symbol)
            lists, balance = [], None
        counts = {'orders':len(symbol_orders) + (len(algo) if not spot else 0),
            'algo':sum(r['symbol'] == symbol for r in algo), 'lists':sum(r['symbol'] == symbol for r in lists),
            'exchange_orders':len(orders), 'exchange_algo':len(algo), 'exchange_lists':len(lists)}
        reasons = []
        additions = {'MAX_NUM_ORDERS':('orders',3,'maxNumOrders'), 'MAX_NUM_ALGO_ORDERS':('algo',1 if spot else 2,'maxNumAlgoOrders'),
            'MAX_NUM_ORDER_LISTS':('lists',1 if spot else 0,'maxNumOrderLists')}
        for kind, (field, addition, key) in additions.items():
            if kind in filters:
                limit = filters[kind].get(key, filters[kind].get('limit'))
                if type(limit) is not int or not 1 <= limit <= 100000:
                    raise LiveError('VENUE_ORDER_LIMIT_UNKNOWN')
                if counts[field] + addition > limit:
                    reasons.append('INSUFFICIENT_' + kind + '_HEADROOM')
        exchange_limits = {'EXCHANGE_MAX_NUM_ORDERS':('exchange_orders',3,'maxNumOrders'),
            'EXCHANGE_MAX_NUM_ALGO_ORDERS':('exchange_algo',1,'maxNumAlgoOrders'),
            'EXCHANGE_MAX_NUM_ORDER_LISTS':('exchange_lists',1,'maxNumOrderLists'),
            'EXCHANGE_MAX_NUM_ICEBERG_ORDERS':(None,0,'maxNumIcebergOrders')}
        for rule in exchange_filters:
            if type(rule) is not dict or rule.get('filterType') not in exchange_limits:
                reasons.append('UNSUPPORTED_EXCHANGE_FILTER')
                continue
            field, addition, key = exchange_limits[rule['filterType']]
            limit = rule.get(key)
            if type(limit) is not int or limit < 0:
                raise LiveError('VENUE_ORDER_LIMIT_UNKNOWN')
            if field is not None and counts[field] + addition > limit:
                reasons.append('INSUFFICIENT_' + rule['filterType'] + '_HEADROOM')
        return {'orders':symbol_orders, 'algo_orders':algo, 'counts':counts, 'base_balance':balance}, reasons

    def _futures_references(self, symbol):
        mark = self._get('FUTURES_LIVE', '/fapi/v1/premiumIndex', {'symbol':symbol})
        if type(mark) is not dict or mark.get('symbol') != symbol:
            raise LiveError('VENUE_MARK_PRICE_UNKNOWN')
        _number(mark.get('markPrice'))
        _number(mark.get('indexPrice'))
        self._fresh_time(mark.get('time'))
        raw = self._get('FUTURES_LIVE', '/fapi/v1/leverageBracket', {'symbol':symbol})
        matches = raw if type(raw) is list else [raw]
        if len(matches) != 1 or type(matches[0]) is not dict or matches[0].get('symbol') != symbol:
            raise LiveError('VENUE_USER_LEVERAGE_BRACKETS_UNKNOWN')
        brackets = matches[0].get('brackets')
        if type(brackets) is not list or not 1 <= len(brackets) <= 64:
            raise LiveError('VENUE_USER_LEVERAGE_BRACKETS_UNKNOWN')
        previous = Decimal(0)
        for row in brackets:
            if (type(row) is not dict or type(row.get('initialLeverage')) is not int
                    # This is the venue's advertised tier ceiling, not the
                    # configured or owner-approved leverage. Live BTC tiers
                    # exceed the old 125 ceiling; the plan/policy cap below
                    # still governs every entry independently.
                    or not 1 <= row['initialLeverage'] <= 10000
                    or _number(row.get('notionalFloor'), True) != previous):
                raise LiveError('VENUE_USER_LEVERAGE_BRACKETS_UNKNOWN')
            cap = _number(row.get('notionalCap'))
            if cap <= previous:
                raise LiveError('VENUE_USER_LEVERAGE_BRACKETS_UNKNOWN')
            previous = cap
        positions = self._get('FUTURES_LIVE', '/fapi/v3/positionRisk', {'symbol':symbol})
        if (type(positions) is not list or len(positions) > 2
                or any(type(r) is not dict or r.get('symbol') != symbol or r.get('positionSide') != 'BOTH' for r in positions)):
            raise LiveError('VENUE_CURRENT_FUTURES_POSITION_UNKNOWN')
        if len({r['positionSide'] for r in positions}) != len(positions):
            raise LiveError('VENUE_CURRENT_FUTURES_POSITION_UNKNOWN')
        signed_amount = sum((_number(r.get('positionAmt'), True, True) for r in positions), Decimal(0))
        return {'mark':mark, 'brackets':brackets, 'position_quantity':format(abs(signed_amount), 'f'),
            'signed_position_quantity':format(signed_amount, 'f')}

    def capture(self, environment, symbol):
        if environment not in {'SPOT_LIVE', 'FUTURES_LIVE'} or type(symbol) is not str or not SYMBOL.fullmatch(symbol):
            raise LiveError('VENUE_SCOPE_SYMBOL_REQUIRED')
        began = self.clock()
        spot = environment == 'SPOT_LIVE'
        prefix = '/api/v3' if spot else '/fapi/v1'
        rawtime = self._get(environment, prefix + '/time')
        server = rawtime.get('serverTime') if type(rawtime) is dict else None
        if type(server) is not int or abs(server / 1000 - self.clock()) > 2:
            raise LiveError('VENUE_SERVER_CLOCK_UNVERIFIED')
        info = self._get(environment, prefix + '/exchangeInfo', {'symbol':symbol} if spot else {})
        symbols = info.get('symbols') if type(info) is dict else None
        rows = [r for r in symbols if type(r) is dict and r.get('symbol') == symbol] if type(symbols) is list else []
        if len(rows) != 1 or rows[0].get('status') != 'TRADING' or rows[0].get('quoteAsset') != 'USDT':
            raise LiveError('VENUE_SYMBOL_NOT_TRADING')
        row, reasons = rows[0], []
        required_types = {'MARKET', 'LIMIT_MAKER', 'STOP_LOSS_LIMIT'} if spot else {'MARKET', 'STOP_MARKET', 'TAKE_PROFIT_MARKET'}
        if (type(row.get('orderTypes')) is not list or not required_types <= set(row['orderTypes'])
                or spot and row.get('ocoAllowed') is not True):
            reasons.append('VENUE_PROTECTION_ORDER_TYPES_UNAVAILABLE')
        filters = row.get('filters')
        if (type(filters) is not list or not 1 <= len(filters) <= 64
                or any(type(f) is not dict or type(f.get('filterType')) is not str for f in filters)):
            raise LiveError('VENUE_FILTER_SCHEMA_UNKNOWN')
        by_type = {f['filterType']:f for f in filters}
        if len(by_type) != len(filters) or not {'PRICE_FILTER', 'LOT_SIZE', 'MARKET_LOT_SIZE'} <= by_type.keys():
            raise LiveError('VENUE_FILTER_SCHEMA_UNKNOWN')
        if not {'MIN_NOTIONAL', 'NOTIONAL'} & by_type.keys():
            reasons.append('VENUE_NOTIONAL_FILTER_UNAVAILABLE')
        # Validate the base filter schemas even in diagnostic mode.
        for kind, keys in (('PRICE_FILTER', ('minPrice','maxPrice','tickSize')),
                           ('LOT_SIZE', ('minQty','maxQty','stepSize')),
                           ('MARKET_LOT_SIZE', ('minQty','maxQty','stepSize'))):
            for key in keys:
                _number(by_type[kind].get(key), True)
        depth = self._get(environment, prefix + '/depth', {'symbol':symbol, 'limit':20})
        if type(depth) is not dict or type(depth.get('lastUpdateId')) is not int:
            raise LiveError('VENUE_ORDER_BOOK_UNKNOWN')
        books = []
        for side in ('bids', 'asks'):
            levels = depth.get(side)
            if (type(levels) is not list or not 1 <= len(levels) <= 20
                    or any(type(level) is not list or len(level) != 2 for level in levels)):
                raise LiveError('VENUE_ORDER_BOOK_UNKNOWN')
            parsed = [(_number(p), _number(q)) for p, q in levels]
            prices = [p for p, q in parsed]
            if prices != sorted(set(prices), reverse=side == 'bids'):
                raise LiveError('VENUE_ORDER_BOOK_UNKNOWN')
            books.append(parsed)
        if books[0][0][0] >= books[1][0][0]:
            raise LiveError('VENUE_ORDER_BOOK_CROSSED')
        commission = self._get(environment, '/api/v3/account/commission' if spot else '/fapi/v1/commissionRate', {'symbol':symbol})
        if type(commission) is not dict or commission.get('symbol') != symbol:
            raise LiveError('VENUE_ACCOUNT_FEE_UNKNOWN')
        if spot:
            rate = Decimal(0)
            for group in ('standardCommission', 'specialCommission', 'taxCommission'):
                rates = commission.get(group)
                if type(rates) is not dict:
                    raise LiveError('VENUE_ACCOUNT_FEE_UNKNOWN')
                # Ignore discounts conservatively; include special/tax and
                # side-specific rates instead of assuming a fixed fee tier.
                rate += max(_number(rates.get('maker'), True), _number(rates.get('taker'), True)) + max(
                    _number(rates.get('buyer'), True), _number(rates.get('seller'), True))
            config = {'leverage':1, 'marginType':'CASH', 'oneWay':True}
        else:
            rate = max(_number(commission.get('makerCommissionRate'), True), _number(commission.get('takerCommissionRate'), True))
            configs = self._get(environment, '/fapi/v1/symbolConfig', {'symbol':symbol})
            matches = [r for r in configs if type(r) is dict and r.get('symbol') == symbol] if type(configs) is list else []
            mode = self._get(environment, '/fapi/v1/positionSide/dual')
            if len(matches) != 1 or type(mode) is not dict or type(mode.get('dualSidePosition')) is not bool:
                raise LiveError('VENUE_CURRENT_CONFIGURATION_UNKNOWN')
            config = {**matches[0], 'oneWay':mode['dualSidePosition'] is False}
            if type(config.get('leverage')) is not int or not 1 <= config['leverage'] <= 125:
                raise LiveError('VENUE_LEVERAGE_UNKNOWN')
            _number(config.get('maxNotionalValue'))
            if config.get('marginType') != 'ISOLATED' or config['oneWay'] is not True:
                reasons.append('EXISTING_ISOLATED_ONE_WAY_REQUIRED')
        known = {'PRICE_FILTER','LOT_SIZE','MARKET_LOT_SIZE','MIN_NOTIONAL','NOTIONAL','PERCENT_PRICE','PERCENT_PRICE_BY_SIDE',
            'MAX_NUM_ORDERS','MAX_NUM_ALGO_ORDERS','MAX_NUM_ORDER_LISTS','MAX_POSITION','ICEBERG_PARTS','MAX_NUM_ICEBERG_ORDERS',
            'TRAILING_DELTA','MAX_NUM_ORDER_AMENDS','POSITION_RISK_CONTROL'}
        if set(by_type) - known:
            reasons.append('UNKNOWN_ACTIVE_SYMBOL_FILTER')
        exchange_filters = info.get('exchangeFilters', [])
        if type(exchange_filters) is not list or len(exchange_filters) > 64:
            raise LiveError('VENUE_EXCHANGE_FILTER_SCHEMA_UNKNOWN')
        if 'POSITION_RISK_CONTROL' in by_type:
            # The live metadata reports NONE but the official common-definition
            # and changelog still do not specify its meaning. Recognize the
            # field without interpreting an undocumented enum as permission.
            reasons.append('POSITION_RISK_CONTROL_SEMANTICS_UNCONFIRMED')
        if 'MAX_NUM_ORDER_AMENDS' in by_type:
            amends = by_type['MAX_NUM_ORDER_AMENDS'].get('maxNumOrderAmends')
            if type(amends) is not int or not 0 <= amends <= 100000:
                raise LiveError('VENUE_ORDER_AMEND_LIMIT_UNKNOWN')
            # No permitted intent uses PUT/amend. New orders start at zero
            # amendments; this filter is explicitly inapplicable to this plan.
        for kind in ('MIN_NOTIONAL', 'NOTIONAL'):
            rule = by_type.get(kind)
            if rule is not None:
                minutes = rule.get('avgPriceMins', 0)
                if type(minutes) is not int or not 0 <= minutes <= 1440:
                    raise LiveError('VENUE_NOTIONAL_REFERENCE_UNKNOWN')
                if kind == 'NOTIONAL':
                    _number(rule.get('minNotional'))
                    _number(rule.get('maxNotional'))
                    if any(type(rule.get(k)) is not bool for k in ('applyMinToMarket','applyMaxToMarket')):
                        raise LiveError('VENUE_NOTIONAL_REFERENCE_UNKNOWN')
                else:
                    _number(rule.get('minNotional', rule.get('notional')))
                    if spot and type(rule.get('applyToMarket')) is not bool:
                        raise LiveError('VENUE_NOTIONAL_REFERENCE_UNKNOWN')
        account, account_reasons = self._account_constraints(environment, symbol, by_type, exchange_filters)
        reasons.extend(account_reasons)
        if spot:
            references, reference_reasons = self._spot_references(symbol, by_type)
            reasons.extend(reference_reasons)
        else:
            references = self._futures_references(symbol)
        value = {'environment':environment, 'symbol':symbol, 'observed_at':began, 'received_at':self.clock(),
            'server_time':server / 1000, 'filters':filters, 'depth':depth, 'commission':commission,
            'fee_bps':_ceil(rate * 10000), 'configuration':config, 'references':references,
            'account_constraints':account, 'reasons':sorted(set(reasons)),
            'nonapplicable_filters':sorted(k for k in by_type if k in {'ICEBERG_PARTS','MAX_NUM_ICEBERG_ORDERS','TRAILING_DELTA','MAX_NUM_ORDER_AMENDS'})}
        value['evidence_digest'] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        return value

    @staticmethod
    def summary(cut):
        return {'environment':cut['environment'], 'symbol':cut['symbol'], 'observed_at':cut['observed_at'],
            'state':'BLOCKED' if cut['reasons'] else 'STRUCTURAL_FILTERS_OBSERVED', 'execution_enabled':False,
            'filter_count':len(cut['filters']), 'evidence_digest':cut['evidence_digest'], 'reasons':cut['reasons'],
            'nonapplicable_filters':cut.get('nonapplicable_filters', []),
            'dynamic_references_observed':bool(cut.get('references')),
            'current_order_counts_observed':bool(cut.get('account_constraints'))}

    def validate(self, plan, now):
        from .live_strategy_adapter import PreparedStrategyEntry
        if type(plan) is not PreparedStrategyEntry:
            raise LiveError('EXACT_PREPARED_VENUE_PLAN_REQUIRED')
        cut = self.capture(plan.proposal.scope.environment, plan.proposal.symbol)
        if (cut['reasons'] or not cut['observed_at'] <= cut['received_at'] <= self.clock() < plan.decision.expires_at
                or self.clock() - cut['observed_at'] > plan.policy.max_data_age_seconds
                or not 0 <= self.clock() - now <= plan.policy.max_data_age_seconds):
            return False
        config = cut['configuration']
        try:
            leverage = int(config['leverage']) * 1000
        except (ValueError, TypeError, KeyError):
            raise LiveError('VENUE_LEVERAGE_UNKNOWN') from None
        if leverage != plan.decision.leverage_milli or leverage > plan.policy.max_leverage_milli or cut['fee_bps'] > plan.venue.fee_bps:
            return False
        bid, ask = (_number(cut['depth'][side][0][0]) for side in ('bids', 'asks'))
        reference = _number(plan.decision.reference_price)
        if _ceil((ask - bid) * 10000 / reference) > plan.venue.spread_bps:
            return False
        long = plan.decision.direction == 'LONG'
        quote = ask if long else bid
        if abs(quote - reference) * 10000 > reference * plan.venue.slippage_bps:
            return False
        stop = _number(plan.decision.stop_price)
        if long and bid <= stop or not long and ask >= stop:
            return False
        eligible = [(_number(p), _number(q)) for p, q in cut['depth']['asks' if long else 'bids']
            if abs(_number(p) - reference) * 10000 <= reference * plan.venue.slippage_bps]
        if sum((q for p, q in eligible), Decimal(0)) < _number(plan.decision.quantity):
            return False
        filters = {f['filterType']:f for f in cut['filters']}
        spot = cut['environment'] == 'SPOT_LIVE'
        references, account = cut['references'], cut['account_constraints']

        def effective_reference(rule):
            if not spot:
                self._fresh_time(references['mark']['time'])
                return _number(references['mark']['markPrice'])
            current = references['reference']
            if current['referencePrice'] is not None:
                self._fresh_time(current['timestamp'])
                return _number(current['referencePrice'])
            average = references['average']
            if average['mins'] != rule['avgPriceMins']:
                raise LiveError('VENUE_AVERAGE_INTERVAL_MISMATCH')
            self._fresh_time(average['closeTime'])
            return _number(average['price'])

        if not spot:
            mark = effective_reference({})
            pending = Decimal(0)
            for order in [*account['orders'], *account['algo_orders']]:
                if order.get('closePosition') in (True, 'true') or order.get('reduceOnly') in (True, 'true'):
                    continue
                if order.get('reduceOnly') not in (False, 'false'):
                    raise LiveError('VENUE_PENDING_POSITION_RISK_UNKNOWN')
                quantity = _number(order.get('origQty', order.get('quantity')), True)
                executed = _number(order.get('executedQty', '0'), True)
                if executed > quantity:
                    raise LiveError('VENUE_PENDING_POSITION_RISK_UNKNOWN')
                pending += quantity - executed
            gross = (_number(references['position_quantity'], True) + pending + _number(plan.decision.quantity)) * mark
            bracket = next((r for r in references['brackets']
                if _number(r['notionalFloor'], True) <= gross < _number(r['notionalCap'])), None)
            if bracket is None or leverage > bracket['initialLeverage'] * 1000 or gross > _number(config['maxNotionalValue']):
                return False
        if 'MAX_POSITION' in filters:
            held = _number(account['base_balance'], True)
            pending = Decimal(0)
            for order in account['orders']:
                if order.get('side') not in {'BUY','SELL'}:
                    raise LiveError('VENUE_PENDING_POSITION_RISK_UNKNOWN')
                if order['side'] == 'BUY':
                    quantity = _number(order.get('origQty'), True)
                    executed = _number(order.get('executedQty'), True)
                    if executed > quantity:
                        raise LiveError('VENUE_PENDING_POSITION_RISK_UNKNOWN')
                    pending += quantity - executed
            if held + pending + _number(plan.decision.quantity) > _number(filters['MAX_POSITION'].get('maxPosition')):
                return False

        def grid(value, rule, lo, hi, step):
            minimum, maximum, tick = (_number(rule[k], True) for k in (lo, hi, step))
            return ((minimum == 0 or value >= minimum) and (maximum == 0 or value <= maximum)
                and (tick == 0 or (value - (Decimal(0) if spot else minimum)) % tick == 0))
        intents = [plan.intent, *plan.protection_factory(plan.proposal, plan.intent, None, self.clock()).intents]
        for intent in intents:
            fields = dict(intent.fields)
            quantity, kind = _number(fields['quantity']), fields.get('type')
            if not grid(quantity, filters['LOT_SIZE'], 'minQty', 'maxQty', 'stepSize'):
                return False
            if kind == 'MARKET' and not grid(quantity, filters['MARKET_LOT_SIZE'], 'minQty', 'maxQty', 'stepSize'):
                return False
            prices = [_number(fields[k]) for k in ('price','triggerPrice','abovePrice','belowStopPrice','belowPrice') if k in fields]
            for price in prices:
                if not grid(price, filters['PRICE_FILTER'], 'minPrice', 'maxPrice', 'tickSize'):
                    return False
            order_prices = [_number(fields[k]) for k in ('price','abovePrice','belowPrice') if k in fields]
            for price in order_prices:
                if 'PERCENT_PRICE' in filters:
                    rule = filters['PERCENT_PRICE']
                    anchor = effective_reference(rule)
                    lower, upper = _number(rule.get('multiplierDown')), _number(rule.get('multiplierUp'))
                    if lower > upper:
                        raise LiveError('VENUE_PERCENT_PRICE_RANGE_UNKNOWN')
                    if spot and not anchor * lower <= price <= anchor * upper:
                        return False
                    if not spot and (fields['side'] == 'BUY' and price > anchor * upper
                            or fields['side'] == 'SELL' and price < anchor * lower):
                        return False
                if 'PERCENT_PRICE_BY_SIDE' in filters:
                    rule = filters['PERCENT_PRICE_BY_SIDE']
                    anchor = effective_reference(rule)
                    prefix = 'bid' if fields['side'] == 'BUY' else 'ask'
                    lower, upper = (_number(rule.get(prefix + key)) for key in ('MultiplierDown','MultiplierUp'))
                    if lower > upper:
                        raise LiveError('VENUE_PERCENT_PRICE_RANGE_UNKNOWN')
                    if not anchor * lower <= price <= anchor * upper:
                        return False
            if spot and references:
                current = references['reference']
                if current['referencePrice'] is not None:
                    self._fresh_time(current['timestamp'])
                    anchor = _number(current['referencePrice'])
                    for rule in references['execution_rules']:
                        prefix = 'bid' if fields['side'] == 'BUY' else 'ask'
                        for price in order_prices or [quote if intent.purpose == 'ENTRY' else reference]:
                            low, high = rule.get(prefix + 'LimitMultDown'), rule.get(prefix + 'LimitMultUp')
                            if low is not None and price < anchor * _number(low):
                                return False
                            if high is not None and price > anchor * _number(high):
                                return False
            for price in order_prices or [None]:
                market = price is None
                notional = Decimal(0) if market else quantity * price
                if 'MIN_NOTIONAL' in filters:
                    rule = filters['MIN_NOTIONAL']
                    if not market or not spot or rule.get('applyToMarket') is True:
                        notional = quantity * (effective_reference(rule) if market else price)
                        if notional < _number(rule.get('minNotional', rule.get('notional'))):
                            return False
                if 'NOTIONAL' in filters:
                    rule = filters['NOTIONAL']
                    if not market or rule.get('applyMinToMarket') is True or rule.get('applyMaxToMarket') is True:
                        notional = quantity * (effective_reference(rule) if market else price)
                    if not market or rule.get('applyMinToMarket') is True:
                        if notional < _number(rule.get('minNotional')):
                            return False
                    if not market or rule.get('applyMaxToMarket') is True:
                        if notional > _number(rule.get('maxNotional')):
                            return False
        return True

    def validate_reduction(self, intent, position, now):
        """Validate a retained, owned MARKET reduction using fresh GET originals.

        This is a filter check, not authority or proof of ownership. The runtime
        must independently reconcile the entry, native coverage and own exits
        again after this callback. Never increase quantity to satisfy a filter.
        """
        from .live_execution_runtime import ConfirmedPosition
        from .live_transport import LiveOrderIntent
        if type(intent) is not LiveOrderIntent or type(position) is not ConfirmedPosition:
            raise LiveError('EXACT_OWNED_REDUCTION_REQUIRED')
        fields = dict(intent.fields)
        spot = intent.scope == 'SPOT_LIVE'
        if (intent.purpose != 'CLOSE' or intent.method != 'POST'
                or intent.endpoint != ('/api/v3/order' if spot else '/fapi/v1/order')
                or fields.get('type') != 'MARKET' or intent.scope != position.scope.environment
                or fields.get('symbol') != position.symbol or position.direction not in {'LONG','SHORT'}
                or spot and position.direction != 'LONG'
                or fields.get('side') != ('SELL' if position.direction == 'LONG' else 'BUY')
                or not spot and (fields.get('reduceOnly') != 'true' or fields.get('positionSide') != 'BOTH')):
            return False
        current = self.clock()
        if (type(now) not in {int,float} or type(position.observed_at) not in {int,float}
                or not 0 <= current - now <= 30 or not 0 <= current - position.observed_at <= 30
                or int(current * 1000) >= intent.expires_utc_ms):
            return False
        quantity, owned = _number(fields.get('quantity')), _number(position.quantity)
        if quantity > owned:
            return False
        cut = self.capture(intent.scope, position.symbol)
        if (cut['reasons'] or not cut['observed_at'] <= cut['received_at'] <= self.clock()
                or self.clock() - current > 30 or self.clock() * 1000 >= intent.expires_utc_ms):
            return False
        filters = {row['filterType']:row for row in cut['filters']}
        for kind in ('LOT_SIZE','MARKET_LOT_SIZE'):
            rule = filters[kind]
            low, high, step = (_number(rule[key], True) for key in ('minQty','maxQty','stepSize'))
            if (low and quantity < low or high and quantity > high
                    or step and (quantity - (Decimal(0) if spot else low)) % step):
                return False
        levels = cut['depth']['bids' if fields['side'] == 'SELL' else 'asks']
        if sum((_number(row[1]) for row in levels), Decimal(0)) < quantity:
            return False
        references = cut['references']
        if spot:
            # Binance's Commission Rates FAQ specifies SELL commissions in the
            # received quote asset, or the configured discount asset. BNBUSDT
            # with an enabled BNB discount can debit base and must be rejected.
            # https://developers.binance.com/en/docs/products/spot/faqs/commission_faq
            discount = cut['commission'].get('discount')
            if (type(discount) is not dict
                    or any(type(discount.get(key)) is not bool for key in ('enabledForAccount','enabledForSymbol'))
                    or type(discount.get('discountAsset')) is not str
                    or not re.fullmatch(r'[A-Z0-9]{1,20}', discount['discountAsset'])):
                return False
            _number(discount.get('discount'), True)
            standard = cut['commission']['standardCommission']
            standard_rate = _number(standard['taker'], True) + _number(standard['seller'], True)
            if (standard_rate and discount['enabledForAccount'] and discount['enabledForSymbol']
                    and discount['discountAsset'] == position.symbol[:-4]):
                return False
            account = self._get(intent.scope, '/api/v3/account')
            balances = account.get('balances') if type(account) is dict else None
            base = [row for row in balances if type(row) is dict and row.get('asset') == position.symbol[:-4]] if type(balances) is list else []
            if len(base) != 1:
                return False
            free, locked = _number(base[0].get('free'), True), _number(base[0].get('locked'), True)
            if free + locked != owned or free < quantity:
                return False
        else:
            signed = _number(references['signed_position_quantity'], True, True)
            if (abs(signed) != owned or (signed > 0) != (position.direction == 'LONG')
                    or cut['configuration']['oneWay'] is not True or cut['configuration']['marginType'] != 'ISOLATED'):
                return False

        def anchor(rule):
            if not spot:
                self._fresh_time(references['mark']['time'])
                return _number(references['mark']['markPrice'])
            reference = references['reference']
            if reference['referencePrice'] is not None:
                self._fresh_time(reference['timestamp'])
                return _number(reference['referencePrice'])
            average = references['average']
            if average['mins'] != rule['avgPriceMins']:
                raise LiveError('VENUE_AVERAGE_INTERVAL_MISMATCH')
            self._fresh_time(average['closeTime'])
            return _number(average['price'])

        if 'MIN_NOTIONAL' in filters:
            rule = filters['MIN_NOTIONAL']
            if (not spot or rule.get('applyToMarket') is True) and quantity * anchor(rule) < _number(rule.get('minNotional',rule.get('notional'))):
                return False
        if 'NOTIONAL' in filters:
            rule = filters['NOTIONAL']
            if rule.get('applyMinToMarket') is True or rule.get('applyMaxToMarket') is True:
                notional = quantity * anchor(rule)
                if (rule.get('applyMinToMarket') is True and notional < _number(rule['minNotional'])
                        or rule.get('applyMaxToMarket') is True and notional > _number(rule['maxNotional'])):
                    return False
        if spot and references['reference']['referencePrice'] is not None:
            reference = anchor({})
            prefix = 'bid' if fields['side'] == 'BUY' else 'ask'
            for rule in references['execution_rules']:
                low, high = rule.get(prefix+'LimitMultDown'), rule.get(prefix+'LimitMultUp')
                for price, _ in levels:
                    price = _number(price)
                    if low is not None and price < reference * _number(low) or high is not None and price > reference * _number(high):
                        return False
        return (self.clock() - current <= 30 and self.clock() * 1000 < intent.expires_utc_ms)
