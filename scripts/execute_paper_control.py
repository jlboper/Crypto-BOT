"""Run exactly one authenticated PAPER control using the installed bot code."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.windows_agent import source_settings
from trader.database import Database
from trader.paper_controls import execute
from trader.update_manager import atomic_json


def main():
    if len(sys.argv) != 2 or Path(sys.argv[1]).resolve(strict=True) != ROOT:
        raise ValueError('Installed source mismatch')
    request = json.loads(sys.stdin.read(512))
    if not isinstance(request, dict) or set(request) != {'action', 'payload'}:
        raise ValueError('Invalid control request')
    config = source_settings(ROOT)
    if (config.bot.database_path.parent / 'UPDATE_MAINTENANCE.json').exists():
        raise ValueError('Update maintenance in progress')
    if request['action'] in {'testnet_buy', 'testnet_close', 'testnet_reconcile', 'testnet_audit'}:
        from trader.testnet_execution import execute as testnet_execute
        result = testnet_execute(ROOT, request['action'], request['payload'])
    elif request['action'] in {'ai_model', 'restart_engine'}:
        from trader.operational_controls import execute as operational_control
        result = operational_control(ROOT, request['action'], request['payload'])
    else:
        result = execute(config, Database(config.bot.database_path), request['action'], request['payload'])
    if request['action'] in {'ai_model','restart_engine','testnet_buy','testnet_close','testnet_reconcile','testnet_audit'}:
        atomic_json(ROOT / 'data/operation-last.json', {'action': request['action'],
                    'status': 'completed', 'at': time.time(), 'result': result})
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        try:
            atomic_json(ROOT / 'data/operation-last.json', {'status':'failed',
                         'at':time.time(), 'reason':type(error).__name__})
        except (OSError, ValueError):
            pass
        print('PAPER control: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
