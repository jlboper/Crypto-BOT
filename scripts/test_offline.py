"""Offline test runner: synthetic fixtures, temporary databases, loopback HTTP only."""
import os
import socket
import sys
import unittest
import json
import time
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
os.environ["OPENAI_API_KEY"] = ""
os.environ["BINANCE_API_KEY"] = ""
os.environ["BINANCE_API_SECRET"] = ""
os.environ["DASHBOARD_TOKEN"] = ""
original = socket.socket.connect
def offline_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("External network disabled by offline test runner")
    return original(sock, address)
socket.socket.connect = offline_connect
suite = unittest.defaultTestLoader.discover(str(root / "tests"))
started = time.monotonic()
result = unittest.TextTestRunner(verbosity=2).run(suite)
(root / "TEST_RESULTS.json").write_text(json.dumps({"at": datetime.now(UTC).isoformat(),
    "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
    "skipped": len(result.skipped), "passed": result.wasSuccessful(),
    "elapsed_seconds": round(time.monotonic()-started, 3), "python": sys.version.split()[0],
    "external_network": "blocked", "fixtures": "synthetic", "bot_started": False}, indent=2), encoding="utf-8")
raise SystemExit(0 if result.wasSuccessful() else 1)
