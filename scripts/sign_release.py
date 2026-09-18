"""Sign an already built release ZIP with an offline Ed25519 private PEM key."""
import argparse
import base64
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trader.update_manager import canonical, safe_name
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import getpass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--package-url", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Contraseña de la clave privada de firma: ").encode()
    key = load_pem_private_key(args.private_key.read_bytes(), password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 required")
    with zipfile.ZipFile(args.package) as archive:
        files = {}
        for name in archive.namelist():
            safe_name(name)
            files[name] = hashlib.sha256(archive.read(name)).hexdigest()
    manifest = {"app": "crypto-ai-trading-bot", "mode": "paper", "version": args.version,
        "sequence": args.sequence, "expires": int(time.time())+14*86400,
        "size": args.package.stat().st_size, "sha256": hashlib.sha256(args.package.read_bytes()).hexdigest(),
        "files": files, "package_url": args.package_url,
        "runtime_protocol": 1 if "trader/runtime_control.py" in files else 0}
    target = args.package.with_name(args.package.name + ".manifest.json")
    with target.open("x", encoding="utf-8") as handle:
        json.dump({"manifest": manifest, "signature": base64.b64encode(key.sign(canonical(manifest))).decode()}, handle)
    print(f"Manifiesto firmado: {target}")

if __name__ == "__main__":
    main()
