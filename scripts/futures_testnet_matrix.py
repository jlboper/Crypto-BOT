"""Run a bounded Futures Demo smoke matrix across supported symbols.

This script is TESTNET-only. It temporarily pauses the automatic Futures forward
entry loop, refuses to start if a forward position is already open, and runs
small reversible round trips sequentially. Every smoke case must close flat
before the next case begins.
"""
from __future__ import annotations

import json
from pathlib import Path

from trader.config import load_config
from trader.futures_testnet import FuturesTestnetLab


def main() -> int:
    config = load_config()
    if config.bot.mode != "testnet":
        raise SystemExit("Futures smoke matrix requires TESTNET mode")

    settings = config.futures_testnet
    lab = FuturesTestnetLab(settings)

    if lab.ledger.forward_position() is not None:
        raise SystemExit("Refusing matrix: automatic Futures forward position is open")

    kill = settings.kill_switch_path
    kill.parent.mkdir(parents=True, exist_ok=True)
    already_paused = kill.exists()
    if not already_paused:
        kill.write_text("temporary smoke matrix pause\n", encoding="utf-8")

    results: list[dict] = []
    try:
        readiness = lab.check()
        if not readiness.get("can_trade"):
            raise RuntimeError("Futures Demo account is not trade-ready")

        for symbol in lab.SYMBOLS:
            for leverage in (1, 2, 3):
                for direction in ("LONG", "SHORT"):
                    print(f"RUN {symbol} {direction} {leverage}x", flush=True)
                    result = lab.smoke(
                        symbol=symbol,
                        direction=direction,
                        leverage=leverage,
                    )
                    if not result.get("position_closed"):
                        raise RuntimeError(
                            f"Smoke case did not close flat: {symbol} {direction} {leverage}x"
                        )
                    results.append(result)
                    print(
                        f"OK  {symbol} {direction} {leverage}x "
                        f"entry={result.get('entry_price')} exit={result.get('exit_price')}",
                        flush=True,
                    )
    finally:
        if not already_paused and kill.exists():
            kill.unlink()

    summary = {
        "ok": True,
        "cases": len(results),
        "symbols": list(lab.SYMBOLS),
        "directions": ["LONG", "SHORT"],
        "leverages": [1, 2, 3],
        "all_closed": all(bool(row.get("position_closed")) for row in results),
        "results": results,
    }
    out = Path("data/futures-smoke-matrix-last.json")
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
