"""Bounded, owner-triggered Binance Spot Testnet execution. Never targets mainnet."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

from .exchange import BinanceClient
from .runtime import single_instance
from .testnet import plan_order
from .update_manager import atomic_json

HOST = 'https://testnet.binance.vision'
SYMBOL = 'BTCUSDT'
TERMINAL = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED', 'EXPIRED_IN_MATCH'}


class TestnetExecutionError(ValueError):
    pass


def _signed(method: str, endpoint: str, fields: dict) -> dict:
    if (method, endpoint) not in {('GET', '/api/v3/account'), ('GET', '/api/v3/order'),
                                   ('POST', '/api/v3/order')}:
        raise TestnetExecutionError('Testnet endpoint blocked')
    key, secret = os.getenv('BINANCE_API_KEY', ''), os.getenv('BINANCE_API_SECRET', '')
    if not key or not secret:
        raise TestnetExecutionError('Testnet credentials unavailable')
    values = {**fields, 'timestamp': int(time.time() * 1000), 'recvWindow': 5000}
    query = urllib.parse.urlencode(values)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    encoded = f'{query}&signature={signature}'
    url = HOST + endpoint + ('?' + encoded if method == 'GET' else '')
    request = urllib.request.Request(url, data=encoded.encode() if method == 'POST' else None,
        method=method, headers={'X-MBX-APIKEY': key, 'Content-Type': 'application/x-www-form-urlencoded'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        type('NoRedirect', (urllib.request.HTTPRedirectHandler,),
                                             {'redirect_request': lambda *args: None})())
    try:
        with opener.open(request, timeout=10) as response:
            result = json.loads(response.read(65537))
    except urllib.error.HTTPError as error:
        raise TestnetExecutionError('Testnet HTTP ' + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise TestnetExecutionError('Testnet response uncertain; reconcile before another action') from None
    if not isinstance(result, dict):
        raise TestnetExecutionError('Invalid Testnet response')
    return result


def _safe_order(data: dict, expected_id: str, expected_side: str) -> dict:
    if (data.get('symbol') != SYMBOL or data.get('clientOrderId') != expected_id or
            data.get('side') != expected_side or data.get('status') not in TERMINAL | {'NEW', 'PARTIALLY_FILLED'}):
        raise TestnetExecutionError('Order identity or status mismatch')
    qty, quote = Decimal(str(data['executedQty'])), Decimal(str(data['cummulativeQuoteQty']))
    if qty < 0 or quote < 0 or not qty.is_finite() or not quote.is_finite():
        raise TestnetExecutionError('Invalid executed quantity')
    return {'client_order_id': expected_id, 'side': expected_side, 'status': data['status'],
            'executed_qty': str(qty), 'cumulative_quote': str(quote)}


def _balance(asset: str) -> Decimal:
    account = _signed('GET', '/api/v3/account', {})
    for row in account.get('balances', []):
        if row.get('asset') == asset:
            amount = Decimal(str(row['free']))
            if not amount.is_finite() or amount < 0:
                break
            return amount
    raise TestnetExecutionError('Testnet balance unavailable')


def _summary(orders: list) -> dict:
    """Conservative derived state; a corrupt ledger must never unlock a write."""
    owned = Decimal('0')
    spent = Decimal('0')
    received = Decimal('0')
    gross = Decimal('0')
    cycles = 0
    for row in orders:
        if not isinstance(row, dict) or row.get('symbol') != SYMBOL or row.get('side') not in {'BUY','SELL'}:
            raise TestnetExecutionError('Invalid Testnet ledger')
        qty = Decimal(str(row.get('executed_qty','0')))
        quote = Decimal(str(row.get('cumulative_quote','0')))
        if not qty.is_finite() or not quote.is_finite() or qty < 0 or quote < 0:
            raise TestnetExecutionError('Invalid Testnet ledger quantity')
        if row['side'] == 'BUY':
            owned += qty
            spent += quote
        else:
            owned -= qty
            received += quote
            if owned < 0:
                raise TestnetExecutionError('Testnet sale exceeds owned quantity')
            if owned == 0 and spent > 0:
                gross += received - spent
                cycles += 1
                spent = received = Decimal('0')
    today = time.strftime('%Y-%m-%d', time.gmtime())
    pending = any(row.get('status') not in TERMINAL for row in orders)
    bought_today = any(row['side']=='BUY' and row.get('created_day')==today for row in orders)
    return {'position_qty':str(owned), 'closed_cycles':cycles,
            'gross_closed_quote_usdt':str(gross), 'can_buy':not pending and owned==0 and not bought_today,
            'can_close':not pending and owned>0, 'needs_reconciliation':pending,
            'entry_today':bought_today}


def execute(source: Path, action: str, payload: dict) -> dict:
    if action not in {'testnet_buy', 'testnet_close', 'testnet_reconcile', 'testnet_audit'} or payload != {}:
        raise TestnetExecutionError('Invalid Testnet request')
    source = source.resolve(strict=True)
    from .config import load_config
    config = load_config(source / 'config.toml')
    if config.bot.mode != 'paper' or (config.bot.database_path.parent / 'UPDATE_MAINTENANCE.json').exists():
        raise TestnetExecutionError('PAPER maintenance or mode mismatch')
    state_path = source / 'data/testnet-execution.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with single_instance(source / 'data/testnet-execution.lock'):
        state = json.loads(state_path.read_text()) if state_path.exists() else {'orders': []}
        orders = state['orders']
        if not isinstance(orders, list) or len(orders) > 100:
            raise TestnetExecutionError('Testnet history requires review')
        summary = _summary(orders)
        unresolved = next((order for order in orders if order.get('status') not in TERMINAL), None)
        if action == 'testnet_audit':
            if unresolved:
                raise TestnetExecutionError('Reconcile uncertain order before auditing')
            audit_path = source/'data/testnet-audit.json'
            # A failed read cannot leave an older "verified" flag in effect.
            atomic_json(audit_path, {'status':'requires_review',
                        'last_order_id':orders[-1]['client_order_id'] if orders else None,
                        'checked_at':time.time()})
            account = _signed('GET', '/api/v3/account', {})
            balances = {}
            for asset in ('BTC','USDT'):
                row = next((r for r in account.get('balances',[]) if r.get('asset')==asset), None)
                if row is None:
                    raise TestnetExecutionError('Incomplete Testnet account response')
                free = Decimal(str(row['free']))
                locked = Decimal(str(row['locked']))
                if not all(value.is_finite() and value >= 0 for value in (free,locked)):
                    raise TestnetExecutionError('Invalid Testnet account balance')
                balances[asset] = {'free':str(free), 'locked':str(locked)}
            verified = True
            for row in orders[-10:]:
                received = _safe_order(_signed('GET', '/api/v3/order',
                    {'symbol':SYMBOL, 'origClientOrderId':row['client_order_id']}),
                    row['client_order_id'],row['side'])
                if (received['status'] != row.get('status') or
                        any(Decimal(received[key]) != Decimal(str(row.get(key))) for key in
                            ('executed_qty', 'cumulative_quote'))):
                    verified = False
            audit = {'status':'verified' if verified else 'requires_review',
                     'orders_checked':min(len(orders),10), 'complete_history':len(orders)<=10,
                     'last_order_id':orders[-1]['client_order_id'] if orders else None,
                     'balances':balances, 'checked_at':time.time()}
            atomic_json(audit_path,audit)
            return {'ok':True, **audit}
        if action == 'testnet_reconcile':
            if not unresolved:
                return {'ok': True, 'status': 'reconciled', 'order': orders[-1] if orders else None}
            target = unresolved
            response = _signed('GET', '/api/v3/order', {'symbol': SYMBOL, 'origClientOrderId': target['client_order_id']})
            target.update(_safe_order(response, target['client_order_id'], target['side']))
            atomic_json(state_path, state)
            return {'ok': True, 'status': target['status'], 'order': target}
        if unresolved:
            raise TestnetExecutionError('Unresolved Testnet order; reconcile first')
        owned = Decimal(summary['position_qty'])
        audit_file = source/'data/testnet-audit.json'
        if audit_file.exists() and json.loads(audit_file.read_text()).get('status')=='requires_review':
            raise TestnetExecutionError('Testnet order mismatch requires manual review')
        if action == 'testnet_buy':
            if owned > 0:
                raise TestnetExecutionError('Testnet position already open')
            # Single BTC/USDT trade, max 25 test USDT; never automatically enter.
            today = time.strftime('%Y-%m-%d', time.gmtime())
            if any(order['side'] == 'BUY' and order['created_day'] == today for order in orders):
                raise TestnetExecutionError('One Testnet entry per UTC day')
            client = BinanceClient(timeout=10)
            plan = plan_order(SYMBOL, 'BUY', client.testnet_reference_price(SYMBOL),
                              client.testnet_symbol_info(SYMBOL), quote_amount=25)
            if plan.status != 'READY_FOR_MANUAL_REVIEW' or Decimal(plan.estimated_notional) > 25:
                raise TestnetExecutionError('Testnet filters reject limited order')
            if _balance('USDT') < Decimal('25'):
                raise TestnetExecutionError('Insufficient Testnet USDT')
            quantity = plan.quantity
            side = 'BUY'
        else:
            if owned <= 0:
                raise TestnetExecutionError('No reconciled Testnet position to close')
            client = BinanceClient(timeout=10)
            available = min(owned, _balance('BTC'))
            plan = plan_order(SYMBOL, 'SELL', client.testnet_reference_price(SYMBOL),
                              client.testnet_symbol_info(SYMBOL), quantity=str(available))
            if plan.status != 'READY_FOR_MANUAL_REVIEW' or Decimal(plan.quantity) <= 0:
                raise TestnetExecutionError('Testnet filters reject close')
            quantity = plan.quantity
            side = 'SELL'
        order_id = 'cait-' + secrets.token_hex(12)
        entry = {'client_order_id': order_id, 'side': side, 'symbol': SYMBOL,
                 'planned_qty': quantity, 'status': 'UNCERTAIN', 'created_day': time.strftime('%Y-%m-%d', time.gmtime())}
        orders.append(entry)
        atomic_json(state_path, state)  # Durable receipt BEFORE the only POST; never retry on uncertainty.
        order_fields = {'symbol': SYMBOL, 'side': side, 'type': 'MARKET',
                        'newClientOrderId': order_id, 'newOrderRespType': 'FULL'}
        order_fields.update({'quoteOrderQty': '25'} if side == 'BUY' else {'quantity': quantity})
        response = _signed('POST', '/api/v3/order', order_fields)
        entry.update(_safe_order(response, order_id, side))
        atomic_json(state_path, state)
        return {'ok': True, 'status': entry['status'], 'order': entry}


def public_status(source: Path) -> dict:
    path = source / 'data/testnet-execution.json'
    if not path.is_file():
        return {'mode':'SPOT_TESTNET', 'orders': [], 'next_step':'Primera operación limitada pendiente',
                **_summary([]), 'audit':None}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data.get('orders'),list) or len(data['orders'])>100:
            raise TestnetExecutionError('Invalid Testnet history')
        summary = _summary(data['orders'])
        rows = data['orders'][-5:]
        audit_path = source/'data/testnet-audit.json'
        audit = json.loads(audit_path.read_text()) if audit_path.is_file() else None
        if audit is not None and audit.get('last_order_id') != (rows[-1]['client_order_id'] if rows else None):
            audit = None
        return {'mode':'SPOT_TESTNET', 'orders': [{k: row.get(k) for k in
            ('client_order_id','side','symbol','status','executed_qty','cumulative_quote','created_day')} for row in rows],
            'next_step': 'Conciliar si aparece estado incierto; nunca se reenvía una orden',
            **summary, 'audit':audit}
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return {'mode':'SPOT_TESTNET','orders':[],'next_step':'Historial local requiere revisión; acciones bloqueadas',
                'position_qty':None,'closed_cycles':0,'gross_closed_quote_usdt':None,
                'can_buy':False,'can_close':False,'needs_reconciliation':False,'entry_today':False,'audit':None}
