#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"

echo "Crypto-BOT portable bootstrap"
echo "Root: $ROOT"

"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), sys.version'
[ -d .venv ] || "$PYTHON" -m venv .venv

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[portal,updates]'

mkdir -p data logs backup

if [ ! -f .env.local ]; then
  cp .env.example .env.local
  echo "WARNING: .env.local created from template. Add secrets locally before enabling AI/Testnet."
else
  echo "Existing .env.local preserved."
fi

.venv/bin/python scripts/portability_check.py --root "$ROOT"

echo "Bootstrap complete. Review .env.local and restore only the intended persistent state before starting the engine."
