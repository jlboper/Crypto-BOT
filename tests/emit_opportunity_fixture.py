"""Real observer projection using only new synthetic DBs and bounded local events."""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_opportunity(*, variant='ready', at=None):
    from trader.opportunity_observer import (
        OpportunityObserverService, opportunity_snapshot,
        observe_entry_intent, observe_entry_outcome,
    )
    variants = {'ready', 'not-started', 'idle', 'stale', 'partial', 'unavailable', 'full', 'mixed', 'ai-allow', 'ai-reduce', 'capital-unknown', 'clock-regression'}
    if variant not in variants:
        raise ValueError('Unknown synthetic observer fixture')
    instant = math.floor(time.time()*1000)/1000 if at is None else float(at)
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        root = Path(temporary)/'observer'
        if variant == 'not-started':
            result = opportunity_snapshot(root, now=instant)
            if root.exists():
                raise AssertionError('Absent observer projection created files')
            return result
        if variant == 'unavailable':
            root.mkdir()
            path = root/'opportunity-shadow.db'
            raw = b'synthetic invalid SQLite'
            path.write_bytes(raw)
            result = opportunity_snapshot(root, now=instant)
            if result['state'] != 'UNAVAILABLE' or path.read_bytes() != raw:
                raise AssertionError('Invalid synthetic observer DB changed')
            return result
        service = OpportunityObserverService(root, clock=lambda: instant)
        try:
            if not service.start():
                raise AssertionError('Synthetic observer did not start')
            deadline = time.monotonic()+3
            while opportunity_snapshot(root, now=instant)['freshness']['state'] != 'FRESH':
                if time.monotonic() >= deadline:
                    raise AssertionError('Synthetic observer heartbeat unavailable')
                time.sleep(.005)
            if variant == 'capital-unknown':
                # Deliberately malformed capital below the normalizing producer
                # exercises the model's defensive branch, never an adapter claim.
                from trader.opportunity_contract import build_intent, OpportunityEvent, canonical
                event = build_intent(engine='SPOT', environment='SPOT_TESTNET', origin_ref='synthetic-defensive-capital',
                    strategy_version='synthetic-defensive-v1', at=instant-1,
                    legs=[{'symbol': 'ADAUSDT', 'venue': 'SPOT_TESTNET', 'direction': 'LONG', 'quantity': '1',
                        'reference_price': '100', 'stop_price': '95', 'take_profit': '110', 'fee_rate': '0.001', 'slippage_rate': '0.0005'}],
                    capital={'cash': '1000', 'equity': '1000', 'available': '1000', 'at': instant-2},
                    limits={'gross_limit': '500', 'capital_limit': '500', 'stop_risk_limit': '50', 'max_positions': 4},
                    evidence={'market_at': instant-2, 'received_at': instant-1.5, 'known_at': instant-1.5, 'decision_at': instant-1})
                payload = event.payload()
                payload['capital']['cash'] = 'invalid-fixed-decimal'
                raw = canonical(payload)
                service._consume(OpportunityEvent(raw, hashlib.sha256(raw).hexdigest()))
            elif variant != 'idle':
                for index, (engine, environment, symbol) in enumerate((
                    ('SPOT', 'SPOT_TESTNET', 'BTCUSDT'), ('FUTURES', 'FUTURES_DEMO', 'ETHUSDT'),
                    ('AI_MARKET_PULSE', 'SHADOW', 'SOLUSDT'), ('QUANT_ARBITRAGE', 'SHADOW', 'BTCUSDT'),
                )):
                    when = instant-10+index
                    legs = [{'symbol': symbol, 'venue': 'FUTURES_DEMO' if engine == 'FUTURES' else 'SPOT_REFERENCE',
                        'direction': 'LONG', 'quantity': '1', 'reference_price': '100', 'stop_price': '95',
                        'take_profit': '110', 'fee_rate': '0.001', 'slippage_rate': '0.0005',
                        'gross_notional': '100', 'margin': '20' if engine == 'FUTURES' else None}]
                    if engine == 'QUANT_ARBITRAGE':
                        legs.append({**legs[0], 'venue': 'FUTURES_REFERENCE', 'direction': 'SHORT',
                            'stop_price': '105', 'take_profit': '90', 'margin': '20'})
                    checks = ['NATIVE_QUANTITATIVE_CHECKS_PASSED']
                    if engine == 'SPOT' and variant in {'ai-allow', 'ai-reduce'}:
                        checks.extend(['INDIVIDUAL_AI_REVIEW_ACCEPTED',
                            'INDIVIDUAL_AI_REVIEW_ALLOW' if variant == 'ai-allow' else 'INDIVIDUAL_AI_REVIEW_REDUCE'])
                    if not observe_entry_intent(engine=engine, environment=environment, origin_ref='synthetic-'+engine,
                        strategy_version='synthetic-observation-v1', at=when, legs=legs,
                        capital={'cash': '1000', 'equity': '1000', 'available': '1000', 'at': when-1},
                        limits={'gross_limit': '500', 'capital_limit': '500', 'stop_risk_limit': '50', 'max_positions': 4},
                        evidence={'market_at': when-1, 'received_at': when-.5, 'known_at': when-.5,
                            'decision_at': when, 'source_digest': 'a'*64, 'review_digest': 'b'*64,
                            'policy_digest': 'c'*64, 'checks': checks}):
                        raise AssertionError('Synthetic intent queue rejected')
                if variant == 'mixed':
                    if not observe_entry_intent(engine='SPOT', environment='PAPER', origin_ref='synthetic-paper',
                        strategy_version='synthetic-observation-v1', at=instant-5,
                        legs=[{'symbol': 'ETHUSDT', 'venue': 'PAPER', 'direction': 'LONG', 'quantity': '1',
                               'reference_price': '100', 'stop_price': '95', 'take_profit': '110'}]):
                        raise AssertionError('Synthetic PAPER intent queue rejected')
                for fields in (
                    {'engine': 'SPOT', 'environment': 'SPOT_TESTNET', 'origin_ref': 'synthetic-SPOT',
                     'at': instant-3, 'stage': 'EXCHANGE_RESPONSE', 'state': 'UNKNOWN', 'complete': False},
                    {'engine': 'QUANT_ARBITRAGE', 'environment': 'SHADOW', 'origin_ref': 'synthetic-QUANT_ARBITRAGE',
                     'at': instant-2, 'stage': 'LEDGER_COMMIT', 'state': 'CLOSED', 'complete': True},
                ):
                    if not observe_entry_outcome(**fields, evidence={'quantity': '1', 'fees': '0.2',
                        'response_digest': 'd'*64, 'decision_digest': 'e'*64}):
                        raise AssertionError('Synthetic outcome queue rejected')
                service._queue.join()
            if variant in {'partial', 'full'}:
                service._errors = 1
                service._last_error = 'RETENTION_FULL' if variant == 'full' else 'OBSERVATION_FAILED'
                service._flush_health()
            if variant == 'clock-regression':
                instant -= 100
                service._flush_health(heartbeat=True)
            result = opportunity_snapshot(root, now=instant+16 if variant == 'stale' else instant)
            expected = {'ready': 'OBSERVING', 'mixed': 'OBSERVING', 'ai-allow': 'OBSERVING', 'ai-reduce': 'OBSERVING', 'capital-unknown': 'OBSERVING', 'clock-regression': 'PARTIAL', 'idle': 'IDLE', 'stale': 'STALE',
                        'partial': 'PARTIAL', 'full': 'PARTIAL'}[variant]
            if result['state'] != expected:
                raise AssertionError('Real synthetic observer returned unexpected state')
            return result
        finally:
            service.stop()


def contract_codes():
    """Read only fixed producer/model codes; no runtime, config or DB is opened."""
    from trader import opportunity_shadow, opportunity_observer
    from trader.opportunity_contract import CHECKS
    reasons = set()
    for module in (opportunity_shadow, opportunity_observer):
        tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            value = node.args[0].value
            named = isinstance(node.func, ast.Name) and node.func.id in {'_assessment', '_unknown'}
            appended = isinstance(node.func, ast.Attribute) and node.func.attr == 'append'
            if (named or appended) and isinstance(value, str) and value.isupper():
                reasons.add(value)
    return {'checks': sorted(CHECKS), 'reasons': sorted(reasons)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=('ready', 'not-started', 'idle', 'stale', 'partial', 'unavailable', 'full', 'mixed', 'ai-allow', 'ai-reduce', 'capital-unknown', 'clock-regression'), default='ready')
    parser.add_argument('--contract-codes', action='store_true')
    args = parser.parse_args()
    value = contract_codes() if args.contract_codes else make_opportunity(variant=args.variant)
    print(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')))
