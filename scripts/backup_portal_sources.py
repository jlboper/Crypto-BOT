"""Allowlisted code-only checkpoint. Never includes data, credentials or dependencies."""
import hashlib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
destination = root / "before-unified-portals.zip"
folders = ("trader", "scripts", "tests", "web", "portal_web", "cloudflare/src", "cloudflare/public", "cloudflare/tests", "cloudflare/migrations", "cloudflare/scripts")
with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
    for folder in folders:
        for path in (root / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".ps1", ".js", ".mjs", ".html", ".css", ".sql", ".png", ".ico", ".svg", ".webmanifest"}:
                archive.write(path, path.relative_to(root))
    for name in ("config.toml", "pyproject.toml", "cloudflare/wrangler.jsonc", "cloudflare/package.json", "cloudflare/pnpm-lock.yaml"):
        archive.write(root / name, name)
print("Source backup SHA256: " + hashlib.sha256(destination.read_bytes()).hexdigest())
