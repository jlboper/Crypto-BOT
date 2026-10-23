"""Explicit Testnet/Demo GET audit, separate from the supervised trading process."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.account_inventory import (InventoryError, TestnetReadOnlyTransport,
                                      capture_inventory, read_local_positions)


def source_inputs(source):
    """Read only the four existing Testnet credentials; never print or copy them."""
    source = source.resolve(strict=True)
    config = tomllib.loads((source/"config.toml").read_text(encoding="utf-8"))
    names = {"BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_FUTURES_TESTNET_API_KEY",
             "BINANCE_FUTURES_TESTNET_API_SECRET", "EXECUTION_MODE"}
    values = {name: os.environ[name] for name in names if os.environ.get(name)}
    for name in (".env.local", ".env"):
        path = source/name
        if not path.is_file():
            continue
        if path.is_symlink() or path.stat().st_size > 65536:
            raise InventoryError("SOURCE_CONFIGURATION_UNAVAILABLE")
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            key = key.strip()
            if sep and key in names and key not in values:
                values[key] = value.strip().strip("\"'")
    if values.get("EXECUTION_MODE", config["bot"]["mode"]).lower() != "testnet":
        raise InventoryError("SOURCE_TESTNET_REQUIRED")
    credentials = {}
    for scope, prefix in (("SPOT_TESTNET", "BINANCE"), ("FUTURES_DEMO", "BINANCE_FUTURES_TESTNET")):
        pair = tuple(values.get(prefix+suffix, "") for suffix in ("_API_KEY", "_API_SECRET"))
        if all(pair):
            credentials[scope] = pair
    paths = []
    for value in (config["bot"]["testnet_database_path"], config["bot"]["futures_testnet_database_path"]):
        path = (source/value).resolve()
        if path == source or not path.is_relative_to(source):
            raise InventoryError("SOURCE_PATH_OUTSIDE_INSTALLATION")
        paths.append(path)
    return credentials, paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--symbols", required=True, help="1..4 explicit USDT symbols; history is only their latest 24h first page")
    args = parser.parse_args(argv)
    try:
        symbols = tuple(args.symbols.split(","))
        if not 1 <= len(symbols) <= 4:
            raise InventoryError("BOUNDED_SYMBOL_SCOPE_REQUIRED")
        credentials, paths = source_inputs(args.source)
        local = read_local_positions(*paths)
        transport = TestnetReadOnlyTransport(credentials, max_calls=60)
        report = capture_inventory(transport, local, symbols=symbols)
        # New folder for every explicit audit. Never overwrite financial state.
        output = args.output_dir.resolve()/((datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))+"-"+uuid.uuid4().hex)
        output.mkdir(parents=True, exist_ok=False)
        with (output/"inventory.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, allow_nan=False, indent=2)
        print(json.dumps({"schema": 1, "mode": report["mode"], "at": report["at"],
            "calls": report["calls"], "execution_enabled": False, "complete_exchange_inventory": False,
            "accounts": [{k: row[k] for k in ("environment", "state", "identity", "quantity_check",
                "local_positions", "exchange_positions", "open_orders", "conditional_orders")} for row in report["accounts"]],
            "market_input_count": len(report["market_inputs"]), "report": str(output/"inventory.json")}))
        return 0 if all(row["state"] == "OBSERVED" for row in report["accounts"]) else 1
    except Exception:
        print(json.dumps({"schema": 1, "state": "UNAVAILABLE", "error": "READ_ONLY_AUDIT_UNAVAILABLE",
                          "execution_enabled": False, "financial_authorization": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
