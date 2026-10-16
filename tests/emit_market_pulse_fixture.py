"""Synthetic producer fixture, without touching any operating ledger or credential."""
import json
import sys
import tempfile
import sqlite3
import time
from copy import deepcopy
from contextlib import closing
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trader.config import load_config
from trader.portal_snapshot import market_pulse_projection
from trader.market_pulse import MarketPulseService, PulseConfig, market_pulse_control, market_pulse_snapshot
from trader.market_pulse_news import iso
from dataclasses import replace


def legacy_sell_projection(root, config):
    """Exercise real temporary ledger history and a real protective Shadow exit."""
    now = time.time() - 2
    observer = MarketPulseService(root, config=PulseConfig(symbols=('BTCUSDT', 'ETHUSDT', 'SOLUSDT')),
        clock=lambda: now, kill_switch_path=config.market_pulse.kill_switch_path)
    observer._initialize()
    for symbol, window in observer.windows.items():
        metrics = dict(symbol=symbol, price=100., change_1m_pct=.8, change_5m_pct=1.4,
            relative_volume=2.2, anomaly_z=3., momentum=.8, acceleration=.2, volatility_pct=.15,
            spread_bps=4., depth_quote=100_000., imbalance=.1, liquidity_change_pct=0., fresh=True,
            complete=True, at=iso(now))
        window.metrics = Mock(return_value=metrics)
        window.bid, window.ask, window.book_at = 99.98, 100.02, now
        window.bid_quote = window.ask_quote = 50_000.
    first = observer.evaluate(now)
    assert len(first['positions']) == 3
    # Reproduce persisted pre-0.10.34 evidence by removing only the new optional
    # ranking keys from this synthetic ledger; no operating file is accessed.
    with closing(sqlite3.connect(observer.path)) as ledger, ledger:
        for identity, encoded in ledger.execute('SELECT id,data FROM pulse_decisions').fetchall():
            decision = json.loads(encoded)
            for key in ('selection_rank', 'selection_pool', 'selection_rule'):
                decision['evidence'].pop(key, None)
            ledger.execute('UPDATE pulse_decisions SET data=? WHERE id=?', (json.dumps(decision), identity))
    market_pulse_control(root, 'pause', kill_switch_path=config.market_pulse.kill_switch_path)
    stop = observer._positions['BTCUSDT']['stop']
    observer.windows['BTCUSDT'].bid = stop - 1
    observer._protective_check('BTCUSDT', stop - 1, now + 1)
    observer.evaluate(now + 1)
    return market_pulse_projection(config)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = load_config()
        config = replace(config, bot=replace(config.bot, database_path=root / 'spot.db'),
            market_pulse=replace(config.market_pulse, kill_switch_path=root / 'pulse-kill'))
        if '--legacy-sell' in sys.argv:
            print(json.dumps(legacy_sell_projection(root, config), allow_nan=False))
            return
        if '--initialized' in sys.argv or '--ten-assets' in sys.argv:
            class SyntheticReviewer:
                def health(self):
                    return {'daily_cap': 6, 'used_today': 0, 'min_interval_seconds': 300,
                            'max_output_tokens': 250, 'max_input_bytes': 4800}
            observer = MarketPulseService(root, reviewer=SyntheticReviewer(),
                kill_switch_path=config.market_pulse.kill_switch_path)
            observer._initialize()
            observer.evaluate()
        if '--ten-assets' in sys.argv:
            raw = market_pulse_snapshot(root, kill_switch_path=config.market_pulse.kill_switch_path)
            symbols = ('BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT',
                       'TRXUSDT', 'ZECUSDT', 'HYPEUSDT', 'DOGEUSDT', 'LINKUSDT')
            row = deepcopy(raw['market'][0])
            row.update(price=100, fresh=True, complete=True)
            raw['market'] = [dict(row, symbol=symbol) for symbol in symbols]
            raw['positions'] = [dict(symbol=symbol, quantity=.1, entry_price=100, mark_price=101,
                stop=99, target=102, opened_at=raw['at'], unrealized_pnl=.08, environment='SHADOW')
                for symbol in symbols[:3]]
            raw['performance']['benchmark_buy_hold'] = {symbol: 1.25 for symbol in symbols}
            raw['news_providers'] = [dict(id=f'provider-{i}', name=f'Synthetic public source {i}',
                url=f'https://example.com/news/{i}', kind='editorial', state='STANDBY',
                last_update=None, last_error=None) for i in range(5)]
            raw['universe'] = {'selection': 'OWNER_APPROVED_LIQUID_TOP10',
                'selected_at': raw['at'], 'source': 'Binance public exchangeInfo and 24h quote volume'}
            decision = deepcopy(raw['decisions'][0])
            decision.update(favorable=['Evidence ' + 'ñ' * 70] * 6, risks=['Risk ' + 'ñ' * 70] * 6)
            raw['decisions'] = [dict(decision, id=f'synthetic-{i}') for i in range(16)]
            raw['opportunities'] = [{key: value for key, value in item.items() if key != 'evidence'}
                                    for item in raw['decisions'][:12]]
            raw['events'] = [dict(id=f'event-{i}', published_at=raw['at'], received_at=raw['at'],
                symbol=symbols[i % 10], source='Synthetic public source', url='https://example.com/news/1',
                title='Hypothetical ' + 'ñ' * 160, impact='uncertain', credibility=.5, kind='report',
                decision='REJECT', reason='Synthetic fixture', market_reaction_pct=None) for i in range(12)]
            with patch('trader.market_pulse.market_pulse_snapshot', return_value=raw):
                print(json.dumps(market_pulse_projection(config), allow_nan=False))
        else:
            print(json.dumps(market_pulse_projection(config), allow_nan=False))


if __name__ == '__main__':
    main()
