"""Explicit local provisioning utility; never run automatically.

Writes a new directory; refuses overwriting credentials. Outputs paths only.
Keep device.env on Windows and send server.env securely to the server.
"""
import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trader.remote_portal import password_hash, digest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Nueva contraseña privada (mínimo 14 caracteres): ")
    if password != getpass.getpass("Repite la contraseña: "):
        raise ValueError("Las contraseñas no coinciden")
    hashed = password_hash(password)
    from urllib.parse import urlsplit
    parts = urlsplit(args.origin)
    if parts.scheme != "https" or not parts.hostname or parts.path or parts.query or parts.fragment or parts.username:
        raise ValueError("Usa un origen HTTPS sin ruta")
    token = secrets.token_urlsafe(32)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, contents in {
        "server.env": f"PORTAL_ORIGIN={args.origin}\nPORTAL_DB=/var/lib/crypto-portal/portal.db\nPORTAL_PASSWORD_HASH={hashed}\nPORTAL_DEVICE_HASH={digest(token)}\n",
        "device.env": f"PORTAL_ORIGIN={args.origin}\nPORTAL_DEVICE_TOKEN={token}\n",
    }.items():
        path = args.output/name
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(contents)
        print(f"Creado: {path}")

if __name__ == "__main__":
    main()
