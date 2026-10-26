"""Emit a synthetic context DTO, never contact CFTC, SEC or Binance."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_institutional_contract import fixture
print(json.dumps(fixture(), ensure_ascii=True))
