"""Run exactly one authenticated supervised control using installed bot code."""
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
    if request['action'] in {'ai_model', 'restart_engine', 'execution_mode', 'testnet_smoke'}:
        from trader.operational_controls import execute as operational_control
        result = operational_control(ROOT, request['action'], request['payload'])
    else:
        result = execute(config, Database(config.bot.database_path), request['action'], request['payload'])
    if request['action'] in {'ai_model','restart_engine','execution_mode','testnet_smoke'}:
        atomic_json(ROOT / 'data/operation-last.json', {'action': request['action'],
                    'status': 'completed', 'at': time.time(), 'result': result})
    print(json.dumps(result, allow_nan=False))


def _safe_failure(error: Exception) -> str:
    message = str(error)
    if message == 'Binance Spot Testnet credentials cannot trade':
        return 'BINANCE_TESTNET_CANNOT_TRADE'
    if message == 'Healthy installed trading motor required':
        return 'ENGINE_NOT_HEALTHY'
    if message in {'Maintenance already in progress', 'Update maintenance in progress'}:
        return 'MAINTENANCE_BUSY'
    if message == 'Trading motor did not stop cooperatively':
        return 'ENGINE_STOP_TIMEOUT'
    if message == 'New motor did not pass supervised health':
        return 'ENGINE_START_HEALTH_FAILED'
    if message == 'Local credential file unavailable':
        return 'LOCAL_ENV_UNAVAILABLE'
    if message == 'Testnet smoke test requires TESTNET mode':
        return 'TESTNET_SMOKE_REQUIRES_TESTNET'
    if message == 'Testnet smoke test found no isolated symbol':
        return 'TESTNET_SMOKE_NO_ISOLATED_SYMBOL'
    if message == 'Testnet smoke test requires no pending order':
        return 'TESTNET_SMOKE_PENDING_ORDER'
    if message == 'Testnet smoke allocation too small':
        return 'TESTNET_SMOKE_ALLOCATION_TOO_SMALL'
    if message == 'Testnet smoke reconciliation incomplete':
        return 'TESTNET_SMOKE_RECONCILIATION_INCOMPLETE'
    if type(error).__name__ == 'TestnetExecutionError':
        return 'BINANCE_TESTNET_EXECUTION_FAILED'
    if type(error).__name__ == 'ExchangeError':
        return 'BINANCE_TESTNET_CONNECTION_OR_AUTH_FAILED'
    return type(error).__name__.upper()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = _safe_failure(error)
        try:
            atomic_json(ROOT / 'data/operation-last.json', {'status':'failed',
                         'at':time.time(), 'reason':code})
        except (OSError, ValueError):
            pass
        print(json.dumps({'ok': False, 'reason': code}, separators=(',', ':')))
        raise SystemExit(1) from None
