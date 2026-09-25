"""Refresh independent agent modules from a committed signed PAPER install.

The calling Windows task wrapper must stop the outbound agent first. No trading
engine, database, credential or scheduled-task definition is changed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import tomllib
from pathlib import Path


MODULES = ("scripts/windows_agent.py", "trader/remote_agent.py", "trader/remote_paper_controls.py")


def _regular(path: Path, root: Path) -> bool:
    return (path.is_file() and not path.is_symlink() and
            not any(parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction())
                    for parent in path.parents if parent != root and parent.is_relative_to(root)) and
            path.resolve().is_relative_to(root.resolve()))


def refresh(source: Path, agent_root: Path, *, apply: bool = False) -> dict:
    source, agent_root = source.resolve(strict=True), agent_root.resolve(strict=True)
    if source == agent_root:
        raise ValueError("Independent supervisor required")
    journal = agent_root / "data/remote-updates/journal.json"
    sequence = agent_root / "data/remote-updates/sequence.json"
    trusted = agent_root / "data/trusted-update.pub"
    if not all(_regular(path, agent_root) for path in (journal, sequence, trusted)):
        raise ValueError("Committed signed installation record unavailable")
    record = json.loads(journal.read_text(encoding="utf-8"))
    committed = json.loads(sequence.read_text(encoding="utf-8"))
    with (source / "config.toml").open("rb") as stream:
        mode = tomllib.load(stream)["bot"]["mode"]
    with (source / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    if (mode != "paper" or record.get("phase") != "committed" or record.get("version") != version or
            type(record.get("sequence")) is not int or record["sequence"] != committed.get("sequence") or
            re.fullmatch(r"[0-9a-f]{64}", record.get("release_id", "")) is None):
        raise ValueError("Signed installation not committed for this PAPER version")
    files = record.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("Invalid signed file inventory")
    replacements = []
    for name in MODULES:
        expected = files.get(name)
        origin, target = source / name, agent_root / name
        if (not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None or
                not _regular(origin, source) or
                (target.exists() and not _regular(target, agent_root)) or
                not target.parent.is_dir() or target.parent.is_symlink() or
                not target.parent.resolve().is_relative_to(agent_root) or
                hashlib.sha256(origin.read_bytes()).hexdigest() != expected):
            raise ValueError("Agent source is not the committed signed code")
        replacements.append((origin, target, expected))
    if not apply:
        return {"status": "refresh_available", "version": version,
                "release_id": record["release_id"],
                "changes": [origin.relative_to(source).as_posix() for origin, target, digest in replacements
                            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest]}
    if not _regular(agent_root / "data/REMOTE_STOP", agent_root):
        raise ValueError("Outbound agent stop marker required")
    changed = [(origin, target, digest) for origin, target, digest in replacements
               if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest]
    if not changed:
        return {"status": "already_current", "version": version}
    backup = agent_root / "data/agent-refresh" / record["release_id"]
    if backup.exists():
        raise ValueError("Existing backup requires review before another refresh")
    backup.mkdir(parents=True)
    saved = []
    replaced = []
    try:
        for origin, target, digest in changed:
            copy = backup / origin.relative_to(source)
            copy.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.copy2(target, copy)
                saved.append((target, copy))
        for origin, target, digest in changed:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".agent-refresh-", delete=False) as handle:
                temporary = Path(handle.name)
            try:
                shutil.copyfile(origin, temporary)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                    raise ValueError("Signed module changed during copy")
                temporary.replace(target)
                replaced.append(target)
            finally:
                temporary.unlink(missing_ok=True)
        return {"status": "refreshed", "version": version, "release_id": record["release_id"],
                "modules": list(MODULES), "backup": str(backup)}
    except BaseException:
        for target in reversed(replaced):
            backup_file = next((copy for prior, copy in saved if prior == target), None)
            if backup_file is None:
                target.unlink(missing_ok=True)
            else:
                shutil.copy2(backup_file, target)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent PAPER supervisor refresh")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--agent-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(refresh(args.source, args.agent_root, apply=args.apply)))
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
