"""Real temporary-ledger producer to Worker contract, without a trading engine."""
import json
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.export_paper_snapshot import compatible_remote_projection
from trader.config import load_config
from trader.database import Database
from trader.domain import Position
from trader.futures_testnet_ledger import FuturesTestnetLedger
from trader.portal_snapshot import dashboard_snapshot


def make_dashboard(root, *, degraded=False):
    base = load_config()
    config = replace(base,
        bot=replace(base.bot, mode='paper', database_path=root / 'spot.db', kill_switch_path=root / 'spot-kill'),
        futures_testnet=replace(base.futures_testnet, database_path=root / 'futures.db', kill_switch_path=root / 'future-kill'),
        market_pulse=replace(base.market_pulse, kill_switch_path=root / 'pulse-kill'),
        research=replace(base.research, report_path=root / 'missing-research.json'))
    stamp = datetime.now(UTC).isoformat()
    spot = Database(config.bot.database_path)
    spot.initialize_cash(1000)
    spot.upsert_position(Position('BTCUSDT', 2, 98, 90, 115, 100, 2, .1, stamp))
    spot.record_market_snapshot({'BTCUSDT': 100})
    spot.record_equity(1000, 800, 200)
    future = FuturesTestnetLedger(config.futures_testnet.database_path)
    future.set_forward_position(dict(symbol='BTCUSDT', direction='SHORT', leverage=3,
        quantity=1, entry_price=100, stop_price=110, take_profit=80,
        liquidation_price=130, signal_score=85, opened_at=stamp))
    future.record_forward_equity(1000, 900, -2)
    future.set_setting('forward_position_metrics', {'at': stamp, 'positions': {
        'BTCUSDT': {'opened_at': stamp, 'quantity': 1, 'mark_price': 102, 'unrealized_pnl_usdt': -2}}})
    if degraded:
        with patch('trader.portfolio_guardian.build_guardian', side_effect=RuntimeError('private-data')):
            return dashboard_snapshot(config)
    return dashboard_snapshot(config)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        payload = make_dashboard(Path(directory), degraded='--degraded' in sys.argv)
        print(json.dumps(compatible_remote_projection(payload), allow_nan=False, separators=(',', ':')))
