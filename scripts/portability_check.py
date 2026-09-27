#!/usr/bin/env python3
"""Read-only portability preflight for Crypto-BOT."""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import shutil
import sys
import tomllib

MIN_PYTHON = (3, 11)
REQUIRED = (
    "pyproject.toml",
    "config.toml",
    ".env.example",
    "trader/__init__.py",
    "trader/__main__.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None)
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve() if args.root else Path(__file__).resolve().parents[1]

    failures = 0
    print(f"Crypto-BOT portability preflight\nRoot: {root}\nOS: {platform.platform()}\nPython: {sys.version.split()[0]}")

    if sys.version_info[:2] < MIN_PYTHON:
        print("[FAIL] Python >= 3.11 required")
        failures += 1
    else:
        print("[OK] Python >= 3.11")

    for rel in REQUIRED:
        if (root / rel).exists():
            print(f"[OK] {rel}")
        else:
            print(f"[FAIL] missing {rel}")
            failures += 1

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            with pyproject.open("rb") as fh:
                version = tomllib.load(fh).get("project", {}).get("version", "unknown")
            print(f"[OK] project version: {version}")
        except Exception as exc:
            print(f"[FAIL] pyproject parse: {type(exc).__name__}")
            failures += 1

    print("[OK] git available" if shutil.which("git") else "[WARN] git not found; ZIP migration is possible but less convenient")
    print("[OK] .env.local exists (contents not inspected)" if (root / ".env.local").exists()
          else "[WARN] .env.local missing; create it locally from .env.example")

    for rel in ("data", "logs", "backup"):
        print(f"[OK] {rel}/ exists" if (root / rel).exists() else f"[WARN] {rel}/ missing; bootstrap/runtime can create it")

    print("Preflight finished with no blocking issues." if not failures else f"Preflight finished with {failures} blocking issue(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
