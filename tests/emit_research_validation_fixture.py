"""Emit a synthetic closed research-summary fixture; never read operating data."""
import json
from datetime import UTC, datetime
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_research_validation import fixture
from trader.research_validation import build_validation_summary


if __name__ == '__main__':
    now = time.time()
    report = fixture()
    at = datetime.fromtimestamp(now-1, UTC).isoformat()
    report['generated_at'] = at
    report['market_pulse_observation']['captured_at'] = at
    report['quant_observation']['captured_at'] = at
    print(json.dumps(build_validation_summary(report, now=now), ensure_ascii=True, separators=(',',':')))
