"""Offline signed packages, locked activation and durable rollback journal.

The trusted Ed25519 public key must be provisioned locally, outside packages.
This module never stops or starts processes and never executes downloaded hooks.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import time
import tomllib
import zipfile
import urllib.request
from urllib.parse import urlsplit
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from .runtime import single_instance

MAX_PACKAGE = 50 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
DIRECTORIES = {"trader", "tests", "web", "scripts", "portal_web"}
FILES = {"README.md", "RESEARCH_METHODOLOGY.md", "pyproject.toml", "UPDATE_NOTES.md"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def safe_name(name):
    if not isinstance(name, str) or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("unsafe package path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in name.split("/")):
        raise ValueError("unsafe package path")
    if name not in FILES and (len(path.parts) < 2 or path.parts[0] not in DIRECTORIES):
        raise ValueError("protected package path")
    reserved = {"CON", "PRN", "AUX", "NUL", *("COM"+str(i) for i in range(1,10)), *("LPT"+str(i) for i in range(1,10))}
    if any(p.split(".")[0].upper() in reserved or p.startswith(".env") or p == "__pycache__" for p in path.parts):
        raise ValueError("reserved package path")
    return path


def verify(package: Path, envelope: Path, public_key: Path, minimum_sequence=0, now=None):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if envelope.stat().st_size > 1024 * 1024 or package.stat().st_size > MAX_PACKAGE:
        raise ValueError("package size limit")
    signed = json.loads(envelope.read_text(encoding="utf-8"))
    manifest = signed["manifest"]
    Ed25519PublicKey.from_public_bytes(public_key.read_bytes()).verify(
        base64.b64decode(signed["signature"], validate=True), canonical(manifest))
    now = time.time() if now is None else now
    if manifest["app"] != "crypto-ai-trading-bot" or manifest["mode"] != "paper":
        raise ValueError("wrong application or mode")
    if type(manifest["sequence"]) is not int or manifest["sequence"] <= minimum_sequence:
        raise ValueError("replayed or downgraded update")
    if not now < manifest["expires"] <= now + 90 * 86400:
        raise ValueError("expired or excessive validity")
    if package.stat().st_size != manifest["size"] or hashlib.sha256(package.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("package digest mismatch")
    files = manifest["files"]
    if not isinstance(files, dict) or not files or len(files) > 2000:
        raise ValueError("invalid file manifest")
    names = set()
    with zipfile.ZipFile(package) as archive:
        if sum(i.file_size for i in archive.infolist()) > MAX_EXPANDED or len(archive.infolist()) > 2000:
            raise ValueError("expanded package limit")
        for entry in archive.infolist():
            name = entry.filename
            safe_name(name)
            if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or name.casefold() in names:
                raise ValueError("link, directory or duplicate entry")
            names.add(name.casefold())
            if name not in files or hashlib.sha256(archive.read(entry)).hexdigest() != files[name]:
                raise ValueError("file digest mismatch")
        if {i.filename for i in archive.infolist()} != set(files):
            raise ValueError("manifest file mismatch")
        for required in ("trader/__main__.py", "pyproject.toml"):
            if required not in files:
                raise ValueError("incomplete package")
        metadata = tomllib.loads(archive.read("pyproject.toml").decode())
        if metadata["project"]["version"] != manifest["version"]:
            raise ValueError("version mismatch")
    return manifest


class UpdateManager:
    def __init__(self, root: Path, public_key: Path, state_dir: Path | None = None):
        self.root, self.public_key = root.resolve(), public_key.resolve()
        self.state = state_dir or self.root / "data" / "updates"
        self.state.mkdir(parents=True, exist_ok=True)
        self.journal = self.state / "journal.json"
        self.sequence = self.state / "sequence.json"

    def stage(self, manifest_url: str):
        """Download to staging over HTTPS; no installation or engine shutdown."""
        from .remote_agent import NoRedirect
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        origin = urlsplit(manifest_url)
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.fragment:
            raise ValueError("HTTPS manifest required")
        opener = urllib.request.build_opener(NoRedirect())
        with single_instance(self.state / "stage.lock"):
            def download(url, maximum):
                with opener.open(url, timeout=30) as response:
                    payload = response.read(maximum+1)
                if len(payload) > maximum:
                    raise ValueError("download size limit")
                return payload
            envelope_bytes = download(manifest_url, 1024*1024)
            signed = json.loads(envelope_bytes)
            Ed25519PublicKey.from_public_bytes(self.public_key.read_bytes()).verify(
                base64.b64decode(signed["signature"], validate=True), canonical(signed["manifest"]))
            package_url = signed["manifest"]["package_url"]
            package_origin = urlsplit(package_url)
            if package_origin.scheme != "https" or package_origin.netloc != origin.netloc or package_origin.username or package_origin.fragment:
                raise ValueError("package origin mismatch")
            package = self.state / "staged.zip"
            envelope = self.state / "staged.zip.manifest.json"
            pending = self.state / "download.zip"
            pending_envelope = self.state / "download.json"
            pending.write_bytes(download(package_url, MAX_PACKAGE))
            pending_envelope.write_bytes(envelope_bytes)
            minimum = json.loads(self.sequence.read_text())["sequence"] if self.sequence.exists() else 0
            manifest = verify(pending, pending_envelope, self.public_key, minimum)
            pending.replace(package)
            pending_envelope.replace(envelope)
            return {"status": "staged_verified", "version": manifest["version"], "package": str(package)}

    def target(self, name):
        safe_name(name)
        path = self.root / name
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
                raise ValueError("linked install path")
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("install path escapes root")
        return path

    def locks(self):
        stack = ExitStack()
        try:
            with (self.root / "config.toml").open("rb") as handle:
                config = tomllib.load(handle)
            if config["bot"]["mode"] != "paper":
                raise ValueError("PAPER only")
            db_path = Path(config["bot"]["database_path"])
            if not db_path.is_absolute():
                db_path = self.root / db_path
            report = Path(config.get("research", {}).get("report_path", "data/research/latest.json"))
            if not report.is_absolute():
                report = self.root / report
            for lock in (db_path.parent / "engine.lock", db_path.parent / "remote.lock", report.parent / "research.lock"):
                stack.enter_context(single_instance(lock))
            return stack
        except BaseException:
            stack.close()
            raise

    def _recover(self):
        if not self.journal.exists():
            return False
        record = json.loads(self.journal.read_text())
        if record["phase"] == "committed":
            atomic_json(self.sequence, {"sequence": record["sequence"]})
            return False
        if record["phase"] != "applying":
            return False
        backup = self.state / "backup"
        for name, existed in record["previous"].items():
            target = self.target(name)
            if existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup / name, target)
            else:
                target.unlink(missing_ok=True)
        atomic_json(self.journal, {**record, "phase": "rolled_back"})
        return True

    def recover(self):
        with self.locks():
            return self._recover()

    def apply(self, package: Path, envelope: Path, health_check=None):
        with self.locks():
            self._recover()
            minimum = json.loads(self.sequence.read_text())["sequence"] if self.sequence.exists() else 0
            manifest = verify(package, envelope, self.public_key, minimum)
            with (self.root / "pyproject.toml").open("rb") as handle:
                old_version = tomllib.load(handle)["project"]["version"]
            def version(value):
                if not re.fullmatch(r"\d+\.\d+\.\d+", value):
                    raise ValueError("stable version required")
                return tuple(map(int, value.split(".")))
            if version(manifest["version"]) <= version(old_version):
                raise ValueError("version downgrade")
            backup = self.state / "backup"
            previous = {}
            for name in manifest["files"]:
                target = self.target(name)
                previous[name] = target.is_file()
                if target.exists() and not target.is_file():
                    raise ValueError("non-file target")
                if target.is_file():
                    saved = backup / name
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
            record = {"phase": "applying", "previous": previous, "sequence": manifest["sequence"]}
            atomic_json(self.journal, record)
            try:
                with zipfile.ZipFile(package) as archive:
                    for name in manifest["files"]:
                        payload = archive.read(name)
                        if hashlib.sha256(payload).hexdigest() != manifest["files"][name]:
                            raise ValueError("package changed after verification")
                        if name.endswith(".py"):
                            compile(payload, name, "exec")
                        target = self.target(name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(target.name + ".update-tmp")
                        temporary.write_bytes(payload)
                        temporary.replace(target)
                if health_check is not None and not health_check():
                    raise RuntimeError("update health check failed")
                atomic_json(self.journal, {**record, "phase": "committed"})
                atomic_json(self.sequence, {"sequence": manifest["sequence"]})
            except BaseException:
                self._recover()
                raise
            return {"version": manifest["version"], "status": "installed_offline", "runtime_health": "not_started"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify", "stage", "apply", "recover"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-url")
    args = parser.parse_args()
    manager = UpdateManager(args.root, args.public_key)
    if args.action == "stage":
        print(json.dumps(manager.stage(args.manifest_url)))
    elif args.action == "recover":
        print(json.dumps({"recovered": manager.recover()}))
    elif args.action == "verify":
        result = verify(args.package, args.manifest, args.public_key)
        print(json.dumps({"verified": True, "version": result["version"]}))
    else:
        print(json.dumps(manager.apply(args.package, args.manifest)))


if __name__ == "__main__":
    main()
