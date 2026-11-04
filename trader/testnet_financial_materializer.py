"""Pure diagnostics from retained Testnet sources; never a financial bundle.

Only ``summary`` is public. The caller must encrypt ``details`` beside the
originals. Observed cuts are not historical boundaries, local virtual cash is
not an exchange wallet, and matching snapshots never establish continuous
protection or account-wide history. This adapter performs no I/O or requests.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, localcontext
import re

from .account_inventory import HOSTS, SYMBOL
from .financial_evidence import AUTHORITY, FLAGS, _time, digest
from .migration_evidence import register_forward_cohort

UNIT_SCALE = 8
SCALE = 10 ** UNIT_SCALE
MAX_UNITS = 10 ** 24
MAX_SOURCES = 1024
MAX_ROWS = 10000
_HASH = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_ID = re.compile(r"[0-9]{1,40}\Z", re.ASCII)
_LABEL = re.compile(r"[A-Z0-9_]{1,64}\Z", re.ASCII)
_CLIENT = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z", re.ASCII)
_GAPS = {
    'ALL_ACCOUNT_SOURCE_COVERAGE_UNPROVEN',
    'EXACT_BOUNDARY_RECONSTRUCTION_REQUIRED',
    'LEDGER_FILL_IDENTITY_MAPPING_REQUIRED',
    'PROTECTION_INTERVALS_UNPROVEN',
    'CASHFLOW_SOURCE_COVERAGE_UNPROVEN',
}


class _Invalid(ValueError):
    pass


def _number(value, *, signed=False, positive=False, legacy=False):
    """Exact decimal display to unit8; no quantize, float arithmetic or rounding."""
    if type(value) not in ((str, int, float) if legacy else (str, int)):
        raise _Invalid('INVALID_EXACT_DECIMAL_SOURCE')
    if len(str(value)) > 80:
        raise _Invalid('INVALID_EXACT_DECIMAL_SOURCE')
    try:
        with localcontext() as context:
            context.prec = 100
            amount = Decimal(str(value))
            # Reject before arithmetic: Decimal context underflow can otherwise
            # turn a positive source into zero before the exact-unit check.
            if amount.is_finite() and not -18 <= amount.as_tuple().exponent <= 18:
                raise _Invalid('DECIMAL_SOURCE_EXPONENT_OUT_OF_RANGE')
            if (not amount.is_finite() or amount.copy_abs() > Decimal('1e16')
                    or not signed and amount < 0 or positive and amount <= 0):
                raise _Invalid('INVALID_EXACT_DECIMAL_SOURCE')
            scaled = amount * SCALE
            if scaled != scaled.to_integral_value():
                raise _Invalid('DECIMAL_NOT_EXACT_AT_UNIT8')
            units = int(scaled)
            if abs(units) > MAX_UNITS:
                raise _Invalid('FINANCIAL_UNIT_LIMIT')
            return units
    except InvalidOperation:
        raise _Invalid('INVALID_EXACT_DECIMAL_SOURCE') from None


def _native_id(value, *, positive=False):
    if type(value) not in (str, int) or not _ID.fullmatch(str(value)):
        raise _Invalid('NATIVE_RECORD_ID_REQUIRED')
    result = str(int(value))
    if positive and result == '0':
        raise _Invalid('NATIVE_RECORD_ID_REQUIRED')
    return result


def _stamp(value):
    if type(value) is not int or not 0 <= value <= 253402300799999:
        raise _Invalid('EXCHANGE_EVENT_TIME_REQUIRED')
    return value


def _rows(value, *, limit=MAX_ROWS):
    if type(value) is not list or len(value) > limit or any(type(row) is not dict for row in value):
        raise _Invalid('BOUNDED_SOURCE_ROWS_REQUIRED')
    return value


def _asset(value):
    # Financial inventory can contain opaque/mixed-case/CJK assets. They stay
    # private and never become trading symbols, paths, endpoints or UI content.
    if type(value) is not str or not 1 <= len(value) <= 32 or not value.isalnum():
        raise _Invalid('SOURCE_ASSET_REQUIRED')
    return value


def _observed_amount(value, gaps, *, signed=False):
    """Keep a valid original decimal even when unit8 cannot represent it."""
    if type(value) not in (str,int) or len(str(value)) > 80:
        gaps.add('INVALID_EXACT_DECIMAL_SOURCE'); return None,None
    try:
        amount = Decimal(str(value))
        # Bound the original exponent before any later fixed-point formatting.
        if amount.is_finite() and not -18 <= amount.as_tuple().exponent <= 18:
            gaps.add('DECIMAL_SOURCE_EXPONENT_OUT_OF_RANGE'); return None,None
        if (not amount.is_finite() or amount.copy_abs() > Decimal('1e16')
                or not signed and amount < 0):
            raise InvalidOperation()
    except InvalidOperation:
        gaps.add('INVALID_EXACT_DECIMAL_SOURCE'); return None,None
    try:
        return _number(value,signed=signed),str(value)
    except _Invalid as error:
        gaps.add(str(error)); return None,str(value)


def _symbol(value):
    if type(value) is not str or not SYMBOL.fullmatch(value):
        raise _Invalid('SOURCE_SYMBOL_REQUIRED')
    return value


def _utc_ms(value):
    instant = _time(value)
    # datetime.timestamp() would introduce float rounding at boundaries.
    from datetime import UTC, datetime
    delta = instant - datetime(1970, 1, 1, tzinfo=UTC)
    microseconds = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    if microseconds % 1000:
        raise _Invalid('SUBMILLISECOND_WINDOW_BOUNDARY_UNREPRESENTABLE')
    return microseconds // 1000


def _identity(scope, sources, gaps):
    found = set()
    endpoint = '/api/v3/account' if scope == 'SPOT_TESTNET' else '/fapi/v3/balance'
    cuts = [source for source in sources if source.get('endpoint') == endpoint and 'failure' not in source]
    for source in cuts:
        raw = source.get('response')
        if scope == 'SPOT_TESTNET':
            uid = raw.get('uid') if type(raw) is dict else None
            if type(uid) not in (str, int) or not re.fullmatch(r'[0-9]{1,30}', str(uid)):
                gaps.add('TESTNET_REPORTED_ACCOUNT_IDENTITY_MISSING'); continue
            found.add(digest({'environment':scope, 'reported_uid':str(uid)}))
        else:
            if type(raw) is not list or not raw or any(type(row) is not dict for row in raw):
                gaps.add('TESTNET_REPORTED_ACCOUNT_IDENTITY_MISSING'); continue
            aliases = {row.get('accountAlias') for row in raw if type(row.get('accountAlias')) is str
                       and 1 <= len(row['accountAlias']) <= 128}
            if len(aliases) != 1 or any(row.get('accountAlias') not in aliases for row in raw):
                gaps.add('TESTNET_REPORTED_ACCOUNT_IDENTITY_MISSING'); continue
            found.add(digest({'environment':scope, 'reported_account_alias':next(iter(aliases))}))
    if len(found) > 1:
        raise _Invalid('TESTNET_REPORTED_ACCOUNT_CHANGED')
    if not found or not cuts:
        gaps.add('TESTNET_REPORTED_ACCOUNT_IDENTITY_MISSING')
    return next(iter(found)) if found else None


def _fill(row, scope, account, requested_symbol, start, end, gaps):
    symbol = _symbol(row.get('symbol'))
    if symbol != requested_symbol:
        raise _Invalid('FILL_QUERY_SYMBOL_MISMATCH')
    trade_id, order_id = _native_id(row.get('id')), _native_id(row.get('orderId'), positive=True)
    at = _stamp(row.get('time'))
    if not start <= at < end:
        raise _Invalid('FILL_OUTSIDE_HALF_OPEN_WINDOW')
    if scope == 'SPOT_TESTNET':
        if type(row.get('isBuyer')) is not bool:
            raise _Invalid('FILL_SIDE_REQUIRED')
        side, position_side = ('BUY' if row['isBuyer'] else 'SELL'), 'LONG'
    else:
        side, position_side = row.get('side'), row.get('positionSide')
        if side not in ('BUY', 'SELL') or position_side not in ('BOTH', 'LONG', 'SHORT'):
            raise _Invalid('FILL_SIDE_REQUIRED')
        if position_side != 'BOTH':
            gaps.add('HEDGE_POSITION_MODE_REQUIRES_EXACT_EPISODE_MAPPING')
    qty = _number(row.get('qty'), positive=True)
    quote = _number(row.get('quoteQty'), positive=True)
    price = _number(row['price'],positive=True) if 'price' in row else None
    if price is None:
        gaps.add('FILL_PRICE_MISSING')
    fee, fee_asset = _number(row.get('commission')), _asset(row.get('commissionAsset'))
    fee_quote = fee if fee_asset == 'USDT' else None
    fraction = None
    if fee_asset == symbol[:-4]:
        numerator = fee * quote
        fraction = {'numerator':numerator, 'denominator':qty}
        if numerator % qty == 0:
            fee_quote = numerator // qty
        else:
            gaps.add('FEE_QUOTE_VALUATION_NOT_EXACT_UNIT8')
    elif fee_asset != 'USDT':
        gaps.add('THIRD_ASSET_FEE_VALUATION_UNPROVEN')
    realized = None
    if scope == 'FUTURES_DEMO':
        if 'realizedPnl' in row:
            realized = _number(row['realizedPnl'], signed=True)
        else:
            gaps.add('FILL_REALIZED_PNL_MISSING')
    ref = digest({'environment':scope, 'account_ref':account, 'symbol':symbol, 'trade_id':trade_id})
    client = row.get('clientOrderId')
    if client is not None and (type(client) is not str or not _CLIENT.fullmatch(client)):
        raise _Invalid('CLIENT_ORDER_ID_INVALID')
    return {'ref':ref, 'symbol':symbol, 'trade_id':trade_id, 'order_id':order_id,
            'client_order_id':client, 'at_ms':at, 'side':side, 'position_side':position_side,
            'quantity_units':qty, 'quote_units':quote, 'price_units':price, 'fee_asset':fee_asset, 'fee_units':fee,
            'fee_quote_units':fee_quote, 'fee_quote_exact_fraction':fraction,
            'realized_pnl_units':realized, 'ownership_verified':False, 'episode_ref':None}


def _income(row, scope, account, start, end, gaps):
    kind = row.get('incomeType')
    if type(kind) is not str or not _LABEL.fullmatch(kind):
        raise _Invalid('INCOME_TYPE_REQUIRED')
    tran_id, at, asset = _native_id(row.get('tranId')), _stamp(row.get('time')), _asset(row.get('asset'))
    if not start <= at < end:
        raise _Invalid('INCOME_OUTSIDE_HALF_OPEN_WINDOW')
    symbol = row.get('symbol', '')
    if symbol != '':
        _symbol(symbol)
    amount = _number(row.get('income'), signed=True)
    if kind == 'COMMISSION' and amount > 0:
        raise _Invalid('COMMISSION_INCOME_SIGN_CONTRADICTION')
    if asset != 'USDT':
        gaps.add('NON_USDT_WALLET_FLOW_UNSUPPORTED')
    if kind not in {'COMMISSION', 'REALIZED_PNL', 'FUNDING_FEE', 'TRANSFER'}:
        gaps.add('INCOME_CLASSIFICATION_REQUIRED')
    trade_id = row.get('tradeId')
    if trade_id not in (None, ''):
        trade_id = _native_id(trade_id)
    else:
        trade_id = None
    ref = digest({'environment':scope, 'account_ref':account, 'income_type':kind, 'transaction_id':tran_id})
    return {'ref':ref, 'income_type':kind, 'transaction_id':tran_id, 'symbol':symbol,
            'trade_id':trade_id, 'at_ms':at, 'asset':asset, 'amount_units':amount}


def _account_cut(source, scope, source_ref, gaps):
    endpoint, raw = source['endpoint'], source['response']
    result = {'source_ref':source_ref, 'endpoint':endpoint, 'started_ms':source['started_ms'],
              'received_ms':source['received_ms'], 'observed_only':True,
              'historical_boundary_verified':False, 'assets':[], 'positions':[],
              'unrecognized_position_rows':[]}
    if scope == 'SPOT_TESTNET':
        if type(raw) is not dict:
            raise _Invalid('ACCOUNT_CUT_SHAPE_INVALID')
        balances = _rows(raw.get('balances'))
        for row in balances:
            try:
                asset = _asset(row.get('asset'))
            except _Invalid as error:
                gaps.add(str(error)); continue
            free, free_text = _observed_amount(row.get('free'),gaps)
            locked, locked_text = _observed_amount(row.get('locked'),gaps)
            total_text = None
            if free_text is not None and locked_text is not None:
                with localcontext() as context:
                    context.prec=100
                    total_text = format(Decimal(free_text)+Decimal(locked_text),'f')
            result['assets'].append({'asset':asset,
                'wallet_units':free+locked if free is not None and locked is not None else None,
                'wallet_decimal':total_text,'free_units':free,'free_decimal':free_text,
                'locked_units':locked,'locked_decimal':locked_text})
    else:
        balances = _rows(raw if endpoint == '/fapi/v3/balance' else raw.get('assets') if type(raw) is dict else None)
        for row in balances:
            try:
                asset = _asset(row.get('asset'))
            except _Invalid as error:
                gaps.add(str(error)); continue
            wallet, wallet_text = _observed_amount(row.get('balance') if endpoint.endswith('/balance') else row.get('walletBalance'),gaps,signed=True)
            result['assets'].append({'asset':asset, 'wallet_units':wallet,'wallet_decimal':wallet_text})
        if endpoint == '/fapi/v3/account':
            for row in _rows(raw.get('positions')):
                try:
                    symbol = _symbol(row.get('symbol'))
                except _Invalid:
                    gaps.add('ACCOUNT_POSITION_SYMBOL_OUTSIDE_USDT_SCOPE')
                    result['unrecognized_position_rows'].append({'source_row_ref':digest(row)})
                    continue
                amount, amount_text = _observed_amount(row.get('positionAmt'),gaps,signed=True)
                side = row.get('positionSide', 'BOTH')
                if side not in {'BOTH', 'LONG', 'SHORT'}:
                    raise _Invalid('ACCOUNT_POSITION_SIDE_INVALID')
                if side != 'BOTH':
                    gaps.add('HEDGE_POSITION_MODE_REQUIRES_EXACT_EPISODE_MAPPING')
                result['positions'].append({'symbol':symbol, 'position_side':side,
                                             'signed_quantity_units':amount,'signed_quantity_decimal':amount_text})
    if len({row['asset'] for row in result['assets']}) != len(result['assets']):
        raise _Invalid('DUPLICATE_ACCOUNT_ASSET')
    if len({(row['symbol'],row['position_side']) for row in result['positions']}) != len(result['positions']):
        raise _Invalid('DUPLICATE_ACCOUNT_POSITION')
    return result


def _local_cut(raw, scope, gaps):
    if type(raw) is not dict or raw.get('environment') != scope:
        raise _Invalid('LOCAL_LEDGER_SCOPE_INVALID')
    _time(raw.get('at'))
    result = {'at':raw['at'], 'scope':'LOCAL_LEDGER_ONLY', 'positions':[], 'trades':[],
              'equity':None, 'native_snapshot_present':raw.get('native_protection') is not None,
              'independent_fill_identity_verified':False}
    for kind in ('positions','trades'):
        for row in _rows(raw.get(kind)):
            normalized = {'symbol':_symbol(row.get('symbol')), 'source_row_ref':digest(row),
                          'exact_original_decimal_source':True}
            if 'id' in row:
                normalized['local_id'] = _native_id(row['id'],positive=True)
            for name in ('quantity','entry_price','exit_price','price','fee','entry_fee','realized_pnl','gross_pnl'):
                if name not in row:
                    continue
                if type(row[name]) is float:
                    gaps.add('LEGACY_FLOAT_PRECISION_UNPROVEN')
                    normalized['exact_original_decimal_source'] = False
                normalized[name+'_decimal'] = str(row[name]) if type(row[name]) in (str,int,float) else None
                try:
                    normalized[name+'_units'] = _number(row[name], signed=name in {'realized_pnl','gross_pnl'},
                                                         positive=name=='quantity', legacy=True)
                except _Invalid as error:
                    gaps.add(str(error)); normalized[name+'_units'] = None
            for name in ('opened_at','closed_at','created_at'):
                if name in row:
                    _time(row[name].replace('+00:00','Z') if type(row[name]) is str else row[name])
                    normalized[name] = row[name]
            if 'direction' in row:
                if row['direction'] not in {'LONG','SHORT'}:
                    raise _Invalid('LOCAL_POSITION_DIRECTION_INVALID')
                normalized['direction'] = row['direction']
            elif scope == 'FUTURES_DEMO' and kind == 'positions':
                raise _Invalid('LOCAL_POSITION_DIRECTION_INVALID')
            result[kind].append(normalized)
    equity = raw.get('latest_equity')
    if equity is not None:
        if type(equity) is not dict:
            raise _Invalid('LOCAL_EQUITY_SHAPE_INVALID')
        observed = {'semantics':'ALLOCATED_VIRTUAL_CASH' if scope == 'SPOT_TESTNET' else 'OBSERVED_WALLET_CUT'}
        for name in ('cash','wallet_balance','available_balance','unrealized_pnl'):
            if name in equity:
                if type(equity[name]) is float:
                    gaps.add('LEGACY_FLOAT_PRECISION_UNPROVEN')
                try:
                    observed[name+'_units'] = _number(equity[name],signed=True,legacy=True)
                except _Invalid as error:
                    gaps.add(str(error)); observed[name+'_units'] = None
        observed['source_at'] = equity.get('created_at')
        result['equity'] = observed
    if result['trades']:
        gaps.add('LEDGER_FEES_AGGREGATED_NO_FILL_IDENTITY' if scope == 'SPOT_TESTNET'
                 else 'LEDGER_FUTURES_NET_COSTS_UNAVAILABLE')
    return result


def _comparisons(scope, cuts, local, symbols, gaps):
    account = [cut for cut in cuts if cut['endpoint'] == ('/api/v3/account' if scope == 'SPOT_TESTNET' else '/fapi/v3/account')]
    if not account:
        gaps.add('EXCHANGE_ACCOUNT_CUT_UNAVAILABLE'); return []
    latest = max(account,key=lambda cut:cut['received_ms'])
    values = []
    for symbol in symbols:
        positions = [row for row in local['positions'] if row['symbol'] == symbol]
        local_units = sum(row.get('quantity_units') or 0 for row in positions)
        local_known = all(row.get('quantity_units') is not None for row in positions)
        if scope == 'FUTURES_DEMO':
            local_units = sum((1 if row.get('direction') == 'LONG' else -1) * (row.get('quantity_units') or 0)
                              for row in positions)
            matching = [row for row in latest['positions'] if row['symbol'] == symbol]
            exchange_units = (sum(row['signed_quantity_units'] for row in matching)
                              if all(row['signed_quantity_units'] is not None for row in matching) else None)
        else:
            matching = [row for row in latest['assets'] if row['asset'] == symbol[:-4]]
            exchange_units = matching[0]['wallet_units'] if matching else None
        equal = local_known and exchange_units is not None and exchange_units == local_units
        values.append({'symbol':symbol, 'local_quantity_units':local_units if local_known else None,
                       'exchange_quantity_units':exchange_units, 'observed_units_equal':equal,
                       'reconciliation_verified':False,
                       'semantics':'ACCOUNT_INVENTORY_VS_LOCAL_ALLOCATED' if scope=='SPOT_TESTNET' else 'SIGNED_OBSERVED_QUANTITY'})
        if local_known and exchange_units is not None and not equal:
            gaps.add('OBSERVED_POSITION_QUANTITY_DIFFERENCE')
    # Even equal quantities are not simultaneous cuts or an ownership proof.
    gaps.add('OBSERVED_CUTS_ARE_NOT_AT_COMMON_BOUNDARY')
    return values


def reconcile_testnet_sources(packet):
    """Return a private normalized diagnostic and a safe, non-authoritative summary.

    This return value is deliberately incompatible with canonical bundle input.
    Duplicate native IDs are deduped; contradictory versions are excluded from
    aggregates and reject this diagnostic. No source completeness is inferred
    from an empty or short history page.
    """
    gaps, fatal = set(_GAPS), False
    summary = {'state':'DIAGNOSTIC_REJECTED', 'source_scope':'BOUNDED_SYMBOLS',
               'financial_window_complete':False, 'canonical_bundle_produced':False,
               'counts':{}, 'reason_codes':[], **{name:False for name in FLAGS}, **AUTHORITY}
    details = {'unit_scale':UNIT_SCALE, 'normalized_fills':[], 'normalized_income':[],
               'observed_account_cuts':[], 'ledger_observations':{}, 'comparisons':[],
               'history_queries':[], 'rejected_records':[]}
    try:
        if type(packet) is not dict or type(packet.get('schema')) is not int or packet['schema'] != 1:
            raise _Invalid('TESTNET_SOURCE_PACKET_REQUIRED')
        scope = packet.get('environment')
        if scope not in HOSTS or packet.get('source_scope') != 'BOUNDED_SYMBOLS':
            raise _Invalid('BOUNDED_TESTNET_SOURCE_SCOPE_REQUIRED')
        if any(type(packet.get(name)) is not dict for name in
               ('registration','original','baseline','closing_ledger')):
            raise _Invalid('NESTED_TESTNET_SOURCE_OBJECT_REQUIRED')
        reg, original = packet['registration'], packet['original']
        cohort = register_forward_cohort(reg)
        if (cohort.environment != scope or original.get('cohort_digest') != cohort.digest
                or original.get('environment') != scope or original.get('fingerprints') != reg['fingerprints']):
            raise _Invalid('TESTNET_COHORT_BINDING_INVALID')
        start, end = _utc_ms(original['interval_start']), _utc_ms(original['interval_end'])
        if not start < end:
            raise _Invalid('HALF_OPEN_FINANCIAL_WINDOW_REQUIRED')
        details['window'] = {'start':original['interval_start'], 'end':original['interval_end'],
                             'start_ms':start, 'end_ms':end, 'cohort_digest':cohort.digest,
                             'original_receipt_digest':digest(original)}
        symbols = packet.get('symbol_universe')
        if (type(symbols) is not list or not 1 <= len(symbols) <= 100 or len(set(symbols)) != len(symbols)
                or any(type(symbol) is not str or not SYMBOL.fullmatch(symbol) for symbol in symbols)):
            raise _Invalid('EXPLICIT_BOUNDED_SYMBOL_UNIVERSE_REQUIRED')
        sources, refs = packet.get('sources'), packet.get('source_refs')
        if (type(sources) is not list or not 1 <= len(sources) <= MAX_SOURCES
                or type(refs) is not list or len(refs) != len(sources)):
            raise _Invalid('BOUNDED_RETAINED_SOURCE_REFERENCES_REQUIRED')
        for source, ref in zip(sources,refs):
            if (type(source) is not dict or type(ref) is not dict or ref.get('sha256') != digest(source)
                    or type(ref.get('encrypted_sha256')) is not str or not _HASH.fullmatch(ref['encrypted_sha256'])
                    or source.get('environment') != scope or source.get('host') != HOSTS[scope]):
                raise _Invalid('RETAINED_SOURCE_BINDING_INVALID')
            if _stamp(source.get('started_ms')) > _stamp(source.get('received_ms')):
                raise _Invalid('SOURCE_OBSERVATION_TIME_INVALID')
        account = _identity(scope,sources,gaps)
        details['account_ref'] = account
        fills, income, conflicts = {}, {}, set()
        observed_rows = 0
        trade_endpoint = '/api/v3/myTrades' if scope == 'SPOT_TESTNET' else '/fapi/v1/userTrades'
        queried_symbols = set(); income_queried = False
        for source, ref in zip(sources,refs):
            source_ref, endpoint = ref['sha256'], source.get('endpoint')
            if 'failure' in source:
                gaps.add('TESTNET_GET_SOURCE_UNAVAILABLE'); continue
            try:
                if endpoint in ('/api/v3/account','/fapi/v3/account','/fapi/v3/balance'):
                    expected = {'/api/v3/account'} if scope=='SPOT_TESTNET' else {'/fapi/v3/account','/fapi/v3/balance'}
                    if endpoint not in expected:
                        raise _Invalid('SOURCE_ENDPOINT_ENVIRONMENT_MISMATCH')
                    details['observed_account_cuts'].append(_account_cut(source,scope,source_ref,gaps)); continue
                if endpoint not in (trade_endpoint, '/fapi/v1/income'):
                    # Open orders are retained observations, never protection intervals.
                    allowed = {'/api/v3/openOrders','/api/v3/openOrderList'} if scope=='SPOT_TESTNET' else {'/fapi/v1/openOrders','/fapi/v1/openAlgoOrders'}
                    if endpoint not in allowed:
                        raise _Invalid('SOURCE_ENDPOINT_ENVIRONMENT_MISMATCH')
                    continue
                if endpoint == '/fapi/v1/income' and scope != 'FUTURES_DEMO':
                    raise _Invalid('SOURCE_ENDPOINT_ENVIRONMENT_MISMATCH')
                params, rows = source.get('params'), _rows(source.get('response'),limit=1000)
                if (type(params) is not dict or type(params.get('startTime')) is not int
                        or type(params.get('endTime')) is not int
                        or not start <= params['startTime'] <= params['endTime'] < end):
                    raise _Invalid('HISTORY_QUERY_WINDOW_MISMATCH')
                if type(params.get('limit')) is not int or not 1 <= params['limit'] <= 1000:
                    raise _Invalid('BOUNDED_HISTORY_QUERY_REQUIRED')
                full = len(rows) >= params['limit']
                if full:
                    gaps.add('TESTNET_HISTORY_PAGE_REQUIRES_SPLIT')
                details['history_queries'].append({'source_ref':source_ref,'endpoint':endpoint,
                    'symbol':params.get('symbol'), 'rows':len(rows), 'full_page':full,
                    'start_ms':params['startTime'],'end_ms_inclusive':params['endTime'],
                    'account_scope_complete':False, 'pagination_exhaustion_verified':False})
                observed_rows += len(rows)
                if observed_rows > MAX_ROWS:
                    raise _Invalid('NORMALIZED_RECORD_LIMIT')
                if endpoint == trade_endpoint:
                    symbol = _symbol(params.get('symbol'))
                    if symbol not in symbols:
                        raise _Invalid('FILL_QUERY_OUTSIDE_DECLARED_UNIVERSE')
                    queried_symbols.add(symbol)
                else:
                    income_queried = True
                for index,row in enumerate(rows):
                    try:
                        at = _stamp(row.get('time'))
                        if not params['startTime'] <= at <= params['endTime']:
                            raise _Invalid('EVENT_OUTSIDE_REQUESTED_HISTORY_SLICE')
                        normalized = (_fill(row,scope,account,symbol,start,end,gaps) if endpoint==trade_endpoint
                                      else _income(row,scope,account,start,end,gaps))
                        target = fills if endpoint==trade_endpoint else income
                        key = normalized['ref']
                        if key in conflicts:
                            continue
                        if key in target and target[key] != normalized:
                            target.pop(key); conflicts.add(key); fatal=True
                            gaps.add('DUPLICATE_NATIVE_ID_CONTRADICTION')
                        else:
                            target[key] = normalized
                    except _Invalid as error:
                        gaps.add(str(error))
                        details['rejected_records'].append({'source_ref':source_ref, 'row_index':index,'reason_code':str(error)})
            except _Invalid as error:
                gaps.add(str(error))
                details['rejected_records'].append({'source_ref':source_ref,'reason_code':str(error)})
                if str(error) == 'NORMALIZED_RECORD_LIMIT':
                    fatal=True; break
        if queried_symbols != set(symbols):
            gaps.add('DECLARED_SYMBOL_HISTORY_QUERY_MISSING')
        if scope=='FUTURES_DEMO' and not income_queried:
            gaps.add('FUTURES_INCOME_SOURCE_MISSING')
        details['normalized_fills'] = sorted(fills.values(),key=lambda row:(row['at_ms'],row['symbol'],int(row['trade_id'])))
        details['normalized_income'] = sorted(income.values(),key=lambda row:(row['at_ms'],row['income_type'],int(row['transaction_id'])))
        totals = defaultdict(int); fees = defaultdict(int); cash = defaultdict(int)
        spot_inventory = defaultdict(int); spot_cash = 0
        for row in details['normalized_fills']:
            totals[row['symbol']+':'+row['side']] += row['quantity_units']
            fees[row['fee_asset']] += row['fee_units']
            if scope == 'SPOT_TESTNET':
                sign = 1 if row['side'] == 'BUY' else -1
                spot_inventory[row['symbol']] += sign * row['quantity_units']
                if row['fee_asset'] == row['symbol'][:-4]:
                    spot_inventory[row['symbol']] -= row['fee_units']
                spot_cash -= sign * row['quote_units']
                if row['fee_asset'] == 'USDT':
                    spot_cash -= row['fee_units']
        for row in details['normalized_income']:
            cash[row['income_type']+':'+row['asset']] += row['amount_units']
        details['known_totals'] = {'fill_quantity_by_symbol_side_units':dict(sorted(totals.items())),
                                  'fill_fees_by_asset_units':dict(sorted(fees.items())),
                                  'income_by_kind_asset_units':dict(sorted(cash.items())),
                                  'scope':'RETAINED_VALID_ROWS_ONLY', 'not_account_complete':True}
        if scope == 'SPOT_TESTNET':
            details['known_totals']['spot_net_inventory_delta_by_symbol_units'] = dict(sorted(spot_inventory.items()))
            details['known_totals']['spot_fill_cash_delta_usdt_units'] = spot_cash
        if scope=='FUTURES_DEMO':
            commission = cash.get('COMMISSION:USDT',0)
            comparable = all(row['fee_asset']=='USDT' for row in fills.values())
            details['commission_comparison'] = {'fill_fee_units':fees.get('USDT',0),
                'income_commission_units':commission, 'observed_totals_equal':comparable and commission == -fees.get('USDT',0),
                'coverage_verified':False}
            if comparable and commission != -fees.get('USDT',0):
                gaps.add('FUTURES_OBSERVED_COMMISSION_DIFFERENCE')
        local = {}
        for label,raw in (('baseline',packet.get('baseline',{}).get('ledger')),('closing',packet.get('closing_ledger'))):
            try:
                local[label] = _local_cut(raw,scope,gaps)
            except (_Invalid,ValueError,TypeError) as error:
                gaps.add(str(error) if type(error) is _Invalid else 'LOCAL_LEDGER_SOURCE_INVALID')
        details['ledger_observations'] = local
        if 'closing' in local:
            details['comparisons'] = _comparisons(scope,details['observed_account_cuts'],local['closing'],symbols,gaps)
        summary.update(state='DIAGNOSTIC_REJECTED' if fatal else 'BOUNDED_SOURCE_DIAGNOSTIC',
            counts={'retained_sources':len(sources),'normalized_fills':len(fills),'normalized_income':len(income),
                    'observed_account_cuts':len(details['observed_account_cuts']),
                    'rejected_records':len(details['rejected_records']),'contradictory_native_ids':len(conflicts)})
    except (_Invalid,ValueError,TypeError,KeyError,OverflowError,RecursionError) as error:
        # Closed codes only; provider bodies, rows, identifiers and amounts stay private.
        gaps.add(str(error) if type(error) is _Invalid else 'TESTNET_SOURCE_PACKET_INVALID')
    summary['reason_codes'] = sorted(gaps)
    return {'schema':1, 'kind':'TESTNET_SOURCE_RECONCILIATION_DIAGNOSTIC_V1',
            'summary':summary, 'details':details}


materialize_testnet_sources = reconcile_testnet_sources
