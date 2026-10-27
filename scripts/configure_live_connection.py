"""Owner-run system-generated HMAC64 entry; never secret command arguments."""
from __future__ import annotations
import argparse
import getpass
import json
from pathlib import Path
import re
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.live_credentials import LiveCredentialVault
from trader.live_transport import LiveCredentials, LiveError


class ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally includes unknown option values in its diagnostic.
        # An owner can accidentally paste a key there; never repeat the input.
        self.exit(2, json.dumps({'state':'BLOCKED','orders_enabled':False,
                                'error':'INVALID_LOCAL_CONFIGURATION_ARGUMENTS'})+'\n')


def hidden_hmac_input(prompt):
    """Bound the selected system-generated HMAC format without echo fallback.

    Never trim, truncate or deduplicate credential content. Reject invalid input
    before a vault write and let the owner copy the value again.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        for _ in range(4):
            value = getpass.getpass(prompt)
            if not value:
                raise EOFError()
            if re.fullmatch(r'[A-Za-z0-9]{64}', value, re.ASCII):
                print('Longitud y formato verificados: 64 caracteres; contenido oculto.')
                return value
            print('Entrada de '+str(len(value))+' caracteres: este asistente HMAC espera 64 alfanumericos.')
            print('Valor no guardado. Copia solo el valor desde Binance, pega una vez y pulsa Enter.')
    raise LiveError('HMAC_INPUT_ATTEMPTS_EXHAUSTED')


def main(argv=None):
    parser = ClosedArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('SPOT_LIVE', 'FUTURES_LIVE'))
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--replace', action='store_true', help='Explicit replacement; never activates orders')
    args = parser.parse_args(argv)
    vault = LiveCredentialVault(ROOT/'data/live-preproduction/credentials.dpapi',
        connection_cache_path=ROOT/'data/live-preproduction/connection-status.json')
    interactive = args.scope is not None and sys.stdin.isatty()
    try:
        if args.status:
            print(json.dumps(vault.status())); return 0
        if not interactive:
            raise LiveError('LOCAL_INTERACTIVE_SECRET_ENTRY_REQUIRED')
        existing = vault.read() if vault.store.path.exists() else {}
        if args.scope in existing and not args.replace:
            raise LiveError('EXPLICIT_CREDENTIAL_REPLACEMENT_REQUIRED')
        print('Entrada local protegida para '+args.scope+'. Conexión de solo lectura; órdenes deshabilitadas.')
        pair = LiveCredentials(hidden_hmac_input('API key dedicada (oculta): '),
                               hidden_hmac_input('API secret (oculto): '))
        vault.configure_scope(args.scope, pair, replace=args.replace)
        print(json.dumps(vault.status())); return 0
    except (LiveError, OSError, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print(json.dumps({'state': 'CONFIGURATION_NOT_CONFIRMED', 'orders_enabled': False,
                          'error': 'LOCAL_CONFIGURATION_UNAVAILABLE'})); return 2
    finally:
        if interactive and not args.status:
            print('Finalizado. Cierra esta ventana; no pegues credenciales en el prompt.')


if __name__ == '__main__':
    raise SystemExit(main())
