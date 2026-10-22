"""Synthetic closed preparation fixture; no engine, database, keys or network."""
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trader.live_preparation import evaluate_live_preparation

def make_preparation():
    return evaluate_live_preparation({}, {'schema': 1, 'amount_usd': '100'}, now=datetime.now(UTC))

if __name__ == '__main__':
    print(json.dumps(make_preparation(), allow_nan=False))
