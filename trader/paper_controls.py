"""The same validated PAPER mutations for the local dashboard and Windows agent."""
import math
import re
import time

from .broker import PaperBroker
from .exchange import BinanceClient
from .risk_control import PROFILES


def execute(config, db, action, payload):
    if config.bot.mode not in {'paper', 'testnet'}:
        raise ValueError('Unsupported execution mode')
    if not isinstance(payload, dict):
        raise ValueError('Invalid PAPER request')
    if action == 'risk_profile':
        if set(payload) != {'profile'} or payload['profile'] not in PROFILES:
            raise ValueError('Unknown risk profile')
        with db.transaction():
            db.set_setting('paper_risk_profile', payload['profile'])
            db.event('INFO', 'PAPER risk profile: ' + payload['profile'])
        return {'ok': True, 'profile': payload['profile']}
    if action != 'paper_close':
        raise ValueError('Unknown PAPER action')
    if config.bot.mode != 'paper':
        raise ValueError('Simulated PAPER close is blocked in Testnet mode')
    if (set(payload) != {'symbol', 'opened_at', 'reference_price'} or
            not isinstance(payload['symbol'], str) or
            re.fullmatch(r'[A-Z0-9]{2,24}USDT', payload['symbol']) is None or
            not isinstance(payload['opened_at'], str) or len(payload['opened_at']) > 64 or
            type(payload['reference_price']) not in (int, float) or
            not math.isfinite(payload['reference_price']) or payload['reference_price'] <= 0):
        raise ValueError('Invalid position identity')
    held = db.position(payload['symbol'])
    if held is None or held.opened_at != payload['opened_at']:
        raise ValueError('Position changed; reload')
    quote = BinanceClient(timeout=10).latest_prices({held.symbol})[held.symbol]
    if abs(quote / payload['reference_price'] - 1) > .02:
        raise ValueError('Price moved more than 2%; reload position')
    pnl = PaperBroker(db, config.paper, config.risk).sell(
        held, quote, 'manual PAPER close', manual_cooldown_until=time.time() + 86400)
    db.event('INFO', held.symbol + ' manual PAPER close; 24h entry cooldown')
    return {'ok': True, 'symbol': held.symbol, 'realized_pnl_usdt': pnl}
