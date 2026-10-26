"""Offline test runner: synthetic fixtures, temporary databases, loopback HTTP only."""
import os
import socket
import sys
import unittest
import json
import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parent.parent
def source_hashes():
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for directory in ("trader", "scripts", "tests") for path in (root/directory).glob("*.py")}
source_before = source_hashes()
sys.path.insert(0, str(root))
os.environ["OPENAI_API_KEY"] = ""
os.environ["BINANCE_API_KEY"] = ""
os.environ["BINANCE_API_SECRET"] = ""
os.environ["BINANCE_FUTURES_TESTNET_API_KEY"] = ""
os.environ["BINANCE_FUTURES_TESTNET_API_SECRET"] = ""
os.environ["BINANCE_LIVE_SPOT_API_KEY"] = ""
os.environ["BINANCE_LIVE_SPOT_API_SECRET"] = ""
os.environ["BINANCE_LIVE_FUTURES_API_KEY"] = ""
os.environ["BINANCE_LIVE_FUTURES_API_SECRET"] = ""
os.environ["MARKET_PULSE_SEC_CONTACT"] = ""
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
source_after = source_hashes()
unchanged = source_before == source_after
(root / "TEST_RESULTS.json").write_text(json.dumps({"at": datetime.now(UTC).isoformat(),
    "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
    "skipped": len(result.skipped), "passed": result.wasSuccessful() and unchanged,
    "elapsed_seconds": round(time.monotonic()-started, 3), "python": sys.version.split()[0],
    "external_network": "blocked", "fixtures": "synthetic", "bot_started": False,
    "source_unchanged": unchanged, "source_hashes": source_after if unchanged else {}}, indent=2), encoding="utf-8")
raise SystemExit(0 if result.wasSuccessful() and unchanged else 1)
