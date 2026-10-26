"""Emit a synthetic closed DTO; never initializes operating state."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_preproduction_status import fixture
print(json.dumps(fixture(), ensure_ascii=True))
