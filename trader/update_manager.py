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
import sqlite3
import stat
import time
import tempfile
import tomllib
import zipfile
import urllib.request
from urllib.parse import urlsplit
from contextlib import ExitStack, closing
from pathlib import Path, PurePosixPath

from .runtime import single_instance

MAX_PACKAGE = 50 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
DIRECTORIES = {"trader", "tests", "web", "scripts", "portal_web"}
FILES = {"README.md", "RESEARCH_METHODOLOGY.md", "pyproject.toml", "UPDATE_NOTES.md", "config.toml"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def release_id(manifest):
    """Bind consent to every signed field, including version, URL and expiry."""
    return hashlib.sha256(canonical(manifest)).hexdigest()


def public_bytes(path):
    value = path.read_bytes()
    if len(value) == 64 and re.fullmatch(b'[a-f0-9]{64}', value):
        return bytes.fromhex(value.decode())
    return value


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix="."+path.name,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic()+1
        while True:
            try:
                temporary.replace(path)
                break
            except PermissionError as error:
                # A short-lived reader can deny replace on Windows; retain the
                # old complete document until replacement succeeds.
                if os.name != "nt" or getattr(error, "winerror", None) not in {5, 32, 33} or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    Ed25519PublicKey.from_public_bytes(public_bytes(public_key)).verify(
        base64.b64decode(signed["signature"], validate=True), canonical(manifest))
    now = time.time() if now is None else now
    if manifest["app"] != "crypto-ai-trading-bot" or manifest["mode"] not in {"paper", "testnet"}:
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
        if "config.toml" in files:
            release_config = tomllib.loads(archive.read("config.toml").decode())
            configured_mode = str(release_config.get("bot", {}).get("mode", "")).lower()
            if configured_mode != manifest["mode"]:
                raise ValueError("release mode mismatch")
    return manifest


class UpdateManager:
    def __init__(self, root: Path, public_key: Path, state_dir: Path | None = None):
        self.root, self.public_key = root.resolve(), public_key.resolve()
        self.state = state_dir or self.root / "data" / "updates"
        self.state.mkdir(parents=True, exist_ok=True)
        self.journal = self.state / "journal.json"
        self.sequence = self.state / "sequence.json"
        # Shared by installers even if their staging directories differ.
        self.transaction_lock = self.root / "data" / "update-transaction.lock"

    def stage(self, manifest_url: str, *, allow_current: bool = False):
        """Download and verify a signed release without installing it.

        Installation callers remain strictly monotonic. Discovery may allow
        exactly the already-committed sequence so "check for updates" can
        report an up-to-date installation without treating it as a replay.
        """
        from .remote_agent import NoRedirect
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        origin = urlsplit(manifest_url)
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.fragment:
            raise ValueError("HTTPS manifest required")
        opener = urllib.request.build_opener(NoRedirect())
        with single_instance(self.state / "stage.lock"):
            def download(url, maximum):
                request = urllib.request.Request(url, headers={"User-Agent": "CryptoAITraderUpdateManager/1"})
                with opener.open(request, timeout=30) as response:
                    payload = response.read(maximum+1)
                if len(payload) > maximum:
                    raise ValueError("download size limit")
                return payload
            envelope_bytes = download(manifest_url, 1024*1024)
            signed = json.loads(envelope_bytes)
            Ed25519PublicKey.from_public_bytes(public_bytes(self.public_key)).verify(
                base64.b64decode(signed["signature"], validate=True), canonical(signed["manifest"]))
            package_url = signed["manifest"]["package_url"]
            package_origin = urlsplit(package_url)
            github_package = re.fullmatch(r'https://raw\.githubusercontent\.com/jlboper/Crypto-BOT/bot-releases/packages/[a-f0-9]{40}\.zip', package_url) is not None
            if package_origin.scheme != "https" or (package_origin.netloc != origin.netloc and not github_package) or package_origin.username or package_origin.fragment:
                raise ValueError("package origin mismatch")
            package = self.state / "staged.zip"
            envelope = self.state / "staged.zip.manifest.json"
            pending = self.state / "download.zip"
            pending_envelope = self.state / "download.json"
            pending.write_bytes(download(package_url, MAX_PACKAGE))
            pending_envelope.write_bytes(envelope_bytes)
            minimum = json.loads(self.sequence.read_text())["sequence"] if self.sequence.exists() else 0
            verification_minimum = minimum - 1 if allow_current and minimum > 0 else minimum
            manifest = verify(pending, pending_envelope, self.public_key, verification_minimum)
            if manifest["sequence"] < minimum:
                raise ValueError("replayed or downgraded update")
            pending.replace(package)
            pending_envelope.replace(envelope)
            return {"status": "staged_current" if manifest["sequence"] == minimum and minimum > 0 else "staged_verified", "version": manifest["version"],
                    "release_id": release_id(manifest), "sequence": manifest["sequence"],
                    "expires": manifest['expires'], "commit": manifest.get('commit'), "package": str(package)}

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

    def database_path(self):
        with (self.root / "config.toml").open("rb") as handle:
            config = tomllib.load(handle)
        mode = str(config["bot"].get("mode", "paper")).lower()
        for name in (".env.local", ".env"):
            env_file = self.root / name
            if not env_file.is_file():
                continue
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "EXECUTION_MODE":
                    mode = value.strip().strip('"').strip("'").lower()
                    break
            break
        if mode not in {"paper", "testnet"}:
            raise ValueError("unsupported execution mode for database backup")
        database_setting = (config["bot"].get("testnet_database_path", "data/testnet-trader.db")
                            if mode == "testnet" else config["bot"]["database_path"])
        path = self.root / database_setting
        if not path.resolve().is_relative_to(self.root) or path.resolve() == self.root:
            raise ValueError("database must remain inside installation")
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
                raise ValueError("linked database path")
        return path

    def invalidate_bytecode(self, name):
        path = self.target(name)
        if path.suffix != '.py':
            return
        cache = path.parent/'__pycache__'
        if cache.is_symlink() or (hasattr(cache, 'is_junction') and cache.is_junction()):
            raise ValueError('linked bytecode cache')
        if cache.is_dir():
            for compiled in cache.iterdir():
                if compiled.name.startswith(path.stem+'.') and compiled.suffix == '.pyc':
                    compiled.unlink()

    @staticmethod
    def copy_database(source, destination):
        """SQLite backup includes WAL and restores transactionally, not file-copy."""
        deadline = time.monotonic() + 30
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError("database backup deadline exceeded")
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True, timeout=30)) as reader:
            with closing(sqlite3.connect(destination, timeout=30)) as writer:
                reader.backup(writer, pages=256, progress=progress)
                if writer.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("database integrity check failed")

    def locks(self):
        stack = ExitStack()
        try:
            stack.enter_context(single_instance(self.transaction_lock))
            stack.enter_context(single_instance(self.state / "stage.lock"))
            with (self.root / "config.toml").open("rb") as handle:
                config = tomllib.load(handle)
            db_path = self.database_path()
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
        if record["phase"] not in {"applying", "pending_health"}:
            return False
        backup = self.state / "backup"
        if "database_existed" in record:
            database = self.database_path()
            if str(database.relative_to(self.root)) != record["database_path"]:
                raise ValueError("database configuration changed during update")
            if record["database_existed"]:
                self.copy_database(self.state / "database-before.sqlite", database)
            elif database.exists():
                # Only a supervisor with all writer locks may reach recovery.
                database.unlink()
                database.with_name(database.name+"-wal").unlink(missing_ok=True)
                database.with_name(database.name+"-shm").unlink(missing_ok=True)
        for name, existed in record["previous"].items():
            target = self.target(name)
            if existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup / name, target)
            else:
                target.unlink(missing_ok=True)
            self.invalidate_bytecode(name)
        atomic_json(self.journal, {**record, "phase": "rolled_back"})
        return True

    def restore_offer(self):
        """Advertise only the exact previous code captured during a signed install.

        A successful restore keeps the committed sequence, so an older signed
        release never becomes eligible as a new update.
        """
        if not self.journal.exists():
            return None
        record = json.loads(self.journal.read_text())
        previous = record.get('previous')
        hashes = record.get('previous_hashes')
        if (record.get('phase') != 'committed' or not isinstance(previous, dict)
                or not isinstance(hashes, dict) or not previous.get('pyproject.toml')
                or not previous.get('trader/runtime_control.py') or not record.get('old_version')):
            return None
        if set(hashes) != {name for name, existed in previous.items() if existed}:
            return None
        current = tomllib.loads((self.root/'pyproject.toml').read_text())['project']['version']
        if current != record['version']:
            return None
        for name, digest in record['files'].items():
            target = self.target(name)
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                return None
        for name, digest in hashes.items():
            source = self.state/'backup'/name
            if (not source.is_file() or source.is_symlink()
                    or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
                return None
        prior = tomllib.loads((self.state/'backup/pyproject.toml').read_text())['project']['version']
        if prior != record['old_version']:
            return None
        identifier = hashlib.sha256(canonical({'current_release':record['release_id'],
            'previous_version':prior,'previous_hashes':hashes})).hexdigest()
        return {'restore_id':identifier, 'version':prior, 'current_version':current,
                'current_release_id':record['release_id']}

    def snapshot_current(self):
        """Make a verified code-only escape hatch before changing installed files."""
        with self.locks():
            offer = self.restore_offer()
            if offer is None:
                raise ValueError('Previous code is no longer eligible for restoration')
            current = self.state/'restore-current'
            temporary = Path(tempfile.mkdtemp(prefix='restore-current-', dir=self.state))
            try:
                for name in json.loads(self.journal.read_text())['files']:
                    target = self.target(name)
                    saved = temporary/name
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target,saved)
                if current.exists():
                    shutil.rmtree(current)
                temporary.replace(current)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            return offer

    def swap_previous(self, approved):
        with self.locks():
            offer = self.restore_offer()
            if offer is None or offer['restore_id'] != approved:
                raise ValueError('Approved restore target changed')
            record = json.loads(self.journal.read_text())
            for name, existed in record['previous'].items():
                target = self.target(name)
                if existed:
                    saved = self.state/'backup'/name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved,target)
                else:
                    target.unlink(missing_ok=True)
                self.invalidate_bytecode(name)

    def rollback_restore(self):
        """Reinstate the current code without touching active ledger balances or trades."""
        with self.locks():
            record = json.loads(self.journal.read_text())
            snapshot = self.state/'restore-current'
            for name,digest in record['files'].items():
                saved = snapshot/name
                if not saved.is_file() or saved.is_symlink() or hashlib.sha256(saved.read_bytes()).hexdigest()!=digest:
                    raise ValueError('Cannot verify current code recovery snapshot')
            for name in record['files']:
                target = self.target(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshot/name,target)
                self.invalidate_bytecode(name)

    def finish_restore(self, approved):
        """Close the one-time offer after previous code has passed health checks."""
        with single_instance(self.transaction_lock):
            record = json.loads(self.journal.read_text())
            if record.get('phase') == 'restored' and record.get('restore_id') == approved:
                return
            if record.get('phase') != 'committed':
                raise ValueError('No committed installation to restore')
            hashes = record['previous_hashes']
            identifier = hashlib.sha256(canonical({'current_release':record['release_id'],
                'previous_version':record['old_version'],'previous_hashes':hashes})).hexdigest()
            if identifier != approved:
                raise ValueError('Restoration identifier changed')
            for name, digest in hashes.items():
                target = self.target(name)
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError('Restored code changed before completion')
            for name, existed in record['previous'].items():
                if not existed and self.target(name).exists():
                    raise ValueError('Restored code contains unexpected file')
            atomic_json(self.journal,{**record,'phase':'restored','restore_id':approved})

    def recover(self):
        with self.locks():
            return self._recover()

    def commit_pending(self, expected_release, health_check):
        """Commit after an external supervisor proves runtime health.

        Never roll back files beneath a running process. On failure the caller
        must stop that process and call recover(), which requires engine locks.
        """
        with single_instance(self.transaction_lock):
            record = json.loads(self.journal.read_text())
            if record.get("phase") != "pending_health" or record.get("release_id") != expected_release:
                raise ValueError("pending release mismatch")
            for name, digest in record["files"].items():
                if hashlib.sha256(self.target(name).read_bytes()).hexdigest() != digest:
                    raise ValueError("installed file changed before commit")
            if health_check() is not True:
                raise RuntimeError("runtime health check failed; stop candidate before recovery")
            atomic_json(self.journal, {**record, "phase": "committed"})
            atomic_json(self.sequence, {"sequence": record["sequence"]})
            return {"status": "committed", "release_id": expected_release, "version": record["version"]}

    def apply(self, package: Path, envelope: Path, health_check=None, *,
              expected_release=None, defer_commit=False):
        if defer_commit and (expected_release is None or health_check is not None):
            raise ValueError("supervised activation requires exact approval and external health check")
        with self.locks():
            minimum = json.loads(self.sequence.read_text())["sequence"] if self.sequence.exists() else 0
            manifest = verify(package, envelope, self.public_key, minimum)
            if expected_release is not None and release_id(manifest) != expected_release:
                raise ValueError("approved release changed")
            # Check consent before recovery or any changes to installed files.
            self._recover()
            minimum = json.loads(self.sequence.read_text())["sequence"] if self.sequence.exists() else 0
            if manifest["sequence"] <= minimum:
                raise ValueError("replayed or downgraded update")
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
            previous_hashes = {}
            for name in manifest["files"]:
                target = self.target(name)
                previous[name] = target.is_file()
                if target.exists() and not target.is_file():
                    raise ValueError("non-file target")
                if target.is_file():
                    saved = backup / name
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                    previous_hashes[name] = hashlib.sha256(saved.read_bytes()).hexdigest()
            record = {"phase": "applying", "previous": previous, "sequence": manifest["sequence"],
                      "release_id": release_id(manifest), "version": manifest["version"], "files": manifest["files"],
                      "old_version":old_version, "previous_hashes":previous_hashes}
            if defer_commit:
                database = self.database_path()
                record.update(database_path=str(database.relative_to(self.root)), database_existed=database.is_file())
                if database.exists() and not database.is_file():
                    raise ValueError("non-file database")
                if database.is_file():
                    self.copy_database(database, self.state / "database-before.sqlite")
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
                        self.invalidate_bytecode(name)
                if health_check is not None and not health_check():
                    raise RuntimeError("update health check failed")
                atomic_json(self.journal, {**record, "phase": "pending_health" if defer_commit else "committed"})
                if not defer_commit:
                    atomic_json(self.sequence, {"sequence": manifest["sequence"]})
            except BaseException:
                self._recover()
                raise
            return {"version": manifest["version"], "release_id": release_id(manifest),
                    "status": "pending_health" if defer_commit else "installed_offline", "runtime_health": "not_started"}


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
