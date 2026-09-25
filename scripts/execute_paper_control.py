"""Run exactly one authenticated PAPER control using the installed bot code."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.windows_agent import source_settings
from trader.database import Database
from trader.paper_controls import execute


def main():
    if len(sys.argv) != 2 or Path(sys.argv[1]).resolve(strict=True) != ROOT:
        raise ValueError('Installed source mismatch')
    request = json.loads(sys.stdin.read(512))
    if not isinstance(request, dict) or set(request) != {'action', 'payload'}:
        raise ValueError('Invalid control request')
    config = source_settings(ROOT)
    if (config.bot.database_path.parent / 'UPDATE_MAINTENANCE.json').exists():
        raise ValueError('Update maintenance in progress')
    result = execute(config, Database(config.bot.database_path), request['action'], request['payload'])
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('PAPER control: ' + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
