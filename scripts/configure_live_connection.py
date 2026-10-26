"""Owner-run local secret entry. Never accepts API values in command arguments."""
from __future__ import annotations
import argparse
import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveCredentials, LiveError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('SPOT_LIVE', 'FUTURES_LIVE'))
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--replace', action='store_true', help='Explicit replacement; never activates orders')
    args = parser.parse_args(argv)
    vault = LiveCredentialVault(ROOT/'data/live-preproduction/credentials.dpapi')
    try:
        if args.status:
            print(json.dumps(vault.status())); return 0
        if args.scope is None or not sys.stdin.isatty():
            raise LiveError('LOCAL_INTERACTIVE_SECRET_ENTRY_REQUIRED')
        existing = vault.read() if vault.store.path.exists() else {}
        if args.scope in existing and not args.replace:
            raise LiveError('EXPLICIT_CREDENTIAL_REPLACEMENT_REQUIRED')
        print('Entrada local protegida para '+args.scope+'. Conexión de solo lectura; órdenes deshabilitadas.')
        pair = LiveCredentials(getpass.getpass('API key dedicada (oculta): '),
                               getpass.getpass('API secret (oculto): '))
        existing[args.scope] = pair
        vault.configure(existing, replace=vault.store.path.exists())
        print(json.dumps(vault.status())); return 0
    except (LiveError, OSError, EOFError):
        print(json.dumps({'state': 'NOT_CONFIGURED', 'orders_enabled': False,
                          'error': 'LOCAL_CONFIGURATION_UNAVAILABLE'})); return 2


if __name__ == '__main__':
    raise SystemExit(main())
