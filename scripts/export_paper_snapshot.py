"""Read-only PAPER dashboard projection from the currently installed bot."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.windows_agent import source_settings
from trader.portal_snapshot import dashboard_snapshot


def compatible_remote_projection(payload):
    """Preserve the deployed portal schema; new finance stays local until release."""
    payload.get('paper_scorecard', {}).pop('financial', None)
    futures = payload.get('futures_forward', {})
    futures.get('scorecard', {}).pop('financial', None)
    positions = list(futures.get('positions') or [])
    if isinstance(futures.get('position'), dict):
        positions.append(futures['position'])
    for position in positions:
        for key in ('mark_price', 'unrealized_pnl_usdt', 'priced_at', 'unrealized_after_accrued_costs_usdt'):
            position.pop(key, None)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    source = parser.parse_args().source.resolve(strict=True)
    if source != ROOT:
        raise ValueError('Installed source mismatch')
    config = source_settings(source)
    payload = dashboard_snapshot(config, source / 'data/research/latest.json')
    print(json.dumps(compatible_remote_projection(payload), allow_nan=False, separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Projection unavailable: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
