from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

from .backtest import run_backtest
from .config import load_config
from .dashboard import DashboardServer
from .database import Database
from .engine import TradingEngine
from .exchange import BinanceClient
from .monitoring import activity_status, position_metrics
from .research import execute_research, report_without_trades
from .runtime import single_instance
from .runtime_control import RuntimeControl


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Safety-first crypto AI swing bot")
    root.add_argument("--config", default=None, help="Path to config.toml")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("once", help="Run one complete paper-trading cycle")
    commands.add_parser("run", help="Run continuously with the local dashboard")
    commands.add_parser("dashboard", help="Run only the local dashboard")
    backtest = commands.add_parser("backtest", help="Backtest one Binance symbol")
    backtest.add_argument("symbol", nargs="?", default="BTCUSDT")
    backtest.add_argument("--limit", type=int, default=2000, choices=range(100, 10001), metavar="100-10000")
    research = commands.add_parser("research", help="Run the multi-asset Research Lab")
    research.add_argument("--symbols", nargs="+", default=None, help="USDT symbols; BTCUSDT is always included")
    research.add_argument("--limit", type=int, default=None, choices=range(100, 10001), metavar="100-10000")
    research.add_argument("--train-bars", type=int, default=None)
    research.add_argument("--test-bars", type=int, default=None)
    commands.add_parser("status", help="Print a safe local status summary")
    commands.add_parser("kill", help="Activate the emergency kill switch")
    commands.add_parser("resume", help="Clear the emergency kill switch")
    commands.add_parser("check-testnet", help="Verify Binance Spot Testnet credentials without placing an order")
    return root


def main() -> None:
    args = parser().parse_args()
    config = load_config(args.config)
    control = RuntimeControl(config.bot.database_path.parent, os.environ.get("CRYPTO_UPDATE_TOKEN"))
    if args.command in {"once", "run", "dashboard", "research", "status", "resume"}:
        if args.command != "run" and control.token is not None:
            raise RuntimeError("Candidate handshake only supports run")
        control.guard_start()
    if args.command == "once":
        with single_instance(config.bot.database_path.parent / "engine.lock"):
            control.guard_start()
            print(json.dumps(TradingEngine(config).cycle(), indent=2))
    elif args.command == "run":
        lock_path = config.bot.database_path.parent / "engine.lock"
        try:
            with single_instance(lock_path):
                # Recheck after taking the lock to close the maintenance/start race.
                control.guard_start()
                engine = TradingEngine(config)
                dashboard = DashboardServer(config, engine.db)
                try:
                    dashboard.runtime_token = control.token
                    thread = dashboard.start_thread()
                    metadata = tomllib.loads((Path(__file__).resolve().parent.parent/'pyproject.toml').read_text())
                    control.ready(metadata['project']['version'], dashboard_ready=thread.is_alive())
                    control.await_activation()
                    print(f"PAPER dashboard: http://{config.dashboard.host}:{config.dashboard.port}")
                    engine.run_forever(control.should_stop)
                finally:
                    dashboard.close()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc
    elif args.command == "dashboard":
        with single_instance(config.bot.database_path.parent / "engine.lock"):
            control.guard_start()
            db = Database(config.bot.database_path)
            print(f"PAPER dashboard: http://{config.dashboard.host}:{config.dashboard.port}")
            DashboardServer(config, db).serve_forever()
    elif args.command == "backtest":
        exchange = BinanceClient()
        candles = exchange.historical_candles(args.symbol.upper(), config.bot.timeframe, args.limit)
        result = run_backtest(args.symbol.upper(), candles, config)
        print(json.dumps(report_without_trades(result), indent=2))
    elif args.command == "research":
        lock_path = config.research.report_path.parent / "research.lock"
        try:
            with single_instance(lock_path):
                control.guard_start()
                report = execute_research(
                    config,
                    symbols=args.symbols,
                    history_candles=args.limit,
                    train_bars=args.train_bars,
                    test_bars=args.test_bars,
                )
        except RuntimeError as exc:
            print("Research Lab is already running", file=sys.stderr)
            raise SystemExit(2) from exc
        print(json.dumps({
            "generated_at": report["generated_at"],
            "mode": report["mode"],
            "summary": report["summary"],
            "report_path": str(config.research.report_path),
        }, indent=2))
    elif args.command == "status":
        db = Database(config.bot.database_path)
        db.initialize_cash(config.paper.initial_cash_usdt)
        latest = db.recent("equity", 1)
        latest_equity = latest[0] if latest else None
        prices, prices_at = db.market_snapshot()
        positions = [
            position_metrics(position, prices.get(position.symbol, position.entry_price), config.paper)
            for position in db.positions()
        ]
        print(json.dumps({
            "mode": "paper",
            "kill_switch": config.bot.kill_switch_path.exists(),
            "cash": db.cash(),
            "positions": positions,
            "latest_equity": latest_equity,
            "activity": activity_status(
                latest_equity.get("created_at") if latest_equity else None,
                config.bot.cycle_seconds,
            ),
            "market_prices_count": len(prices),
            "prices_at": prices_at,
        }, indent=2))
    elif args.command == "kill":
        config.bot.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        config.bot.kill_switch_path.write_text("manual kill switch\n", encoding="utf-8")
        print("Kill switch ACTIVE")
    elif args.command == "resume":
        config.bot.kill_switch_path.unlink(missing_ok=True)
        print("Kill switch cleared")
    elif args.command == "check-testnet":
        try:
            print(json.dumps(BinanceClient().verify_testnet_credentials(), indent=2))
        except Exception as exc:
            print(f"Testnet verification failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
