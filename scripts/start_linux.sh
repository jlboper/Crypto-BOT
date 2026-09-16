#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env.local ]; then
  cp .env.example .env.local
  echo "Created .env.local. Add credentials there before enabling AI/Testnet."
fi
python3 -m trader run

