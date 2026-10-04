"""Read-only compatibility gate before returning to code without native orders."""
import json
import sqlite3
import tomllib
from contextlib import closing


def require_native_compatible(root, target):
    module = target / "trader/native_protection.py"
    native_supported = module.is_file() and "NATIVE_PROTECTION_PROTOCOL = 1" in module.read_text(encoding="utf-8")
    forward = target / "trader/futures_forward.py"
    trials_supported = forward.is_file() and "FUTURES_LEVERAGE_TRIAL_PROTOCOL = 1" in forward.read_text(encoding="utf-8")
    portfolio_supported = forward.is_file() and "FUTURES_PORTFOLIO_PROTOCOL = 1" in forward.read_text(encoding="utf-8")
    if native_supported and trials_supported and portfolio_supported: return
    config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    bot = config["bot"]
    paths = {bot.get("testnet_database_path", "data/testnet-trader.db"),
             bot.get("futures_testnet_database_path", "data/futures-testnet.db")}
    for name in paths:
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Native compatibility database must remain inside installation")
        if not path.exists(): continue
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as connection:
                if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone():
                    continue
                if not trials_supported:
                    position_table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_position'").fetchone()
                    if position_table and connection.execute("SELECT 1 FROM forward_position WHERE leverage > 1 LIMIT 1").fetchone():
                        raise RuntimeError("Code without Futures leverage trials cannot resume with a 2x/3x position")
                    plan = connection.execute("SELECT value FROM settings WHERE key='forward_open_plan'").fetchone()
                    if plan and int((json.loads(plan[0]) or {}).get('leverage', 1)) > 1:
                        raise RuntimeError("Code without Futures leverage trials cannot resume with a pending 2x/3x plan")
                if not portfolio_supported:
                    old_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}
                    table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_position'").fetchone()
                    symbols = [r[0] for r in connection.execute("SELECT symbol FROM forward_position")] if table else []
                    plan_row = connection.execute("SELECT value FROM settings WHERE key='forward_open_plan'").fetchone()
                    plan = (json.loads(plan_row[0]) or {}) if plan_row else {}
                    if len(symbols) > 3 or any(s not in old_symbols for s in symbols) or (plan.get("symbol") and plan["symbol"] not in old_symbols):
                        raise RuntimeError("Code without Futures portfolio support cannot resume expanded positions or plan")
                if native_supported: continue
                rows = connection.execute("SELECT value FROM settings WHERE key IN ('spot_native_protection','forward_native_protection')")
                if any(json.loads(value or "{}") for (value,) in rows):
                    raise RuntimeError("Code without native protection cannot resume while native order reconciliation remains pending")
        except sqlite3.Error:
            raise RuntimeError("Native protection compatibility could not be verified") from None
