"""Opt-in outbound-only companion. Does not construct or start a trading engine."""
from __future__ import annotations

import json
import os
import random
import sqlite3
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .config import load_config
from .runtime import single_instance


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects forbidden")


class RemoteAgent:
    def __init__(self, config, origin: str, token: str, *, state_directory=None):
        if config.bot.mode.lower() != "paper":
            raise ValueError("Remote agent requires PAPER")
        parts = urlsplit(origin)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.path or parts.query or parts.fragment:
            raise ValueError("Canonical HTTPS origin required")
        if len(token) < 32:
            raise ValueError("Provision a dedicated device token")
        self.config, self.origin, self.token = config, origin, token
        self.state_directory = Path(state_directory) if state_directory else config.bot.database_path.parent
        self.state = self.state_directory / "remote-state.json"
        self.opener = urllib.request.build_opener(NoRedirect())
        self.last_error = None
        self.dashboard_provider = None
        self.jobs = None
        self.update_provider = None
        self.restore_provider = None

    def snapshot(self):
        # Read-only SQLite connection never initializes or modifies the engine database.
        path = self.config.bot.database_path.resolve()
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            row = db.execute("SELECT equity,cash,exposure,created_at FROM equity ORDER BY id DESC LIMIT 1").fetchone()
            positions = [dict(p) for p in db.execute("SELECT symbol,quantity,entry_price,stop_price,take_profit FROM positions LIMIT 100")]
            return {"mode": "PAPER", "equity": row["equity"] if row else None,
                "cash": row["cash"] if row else None, "exposure": row["exposure"] if row else None,
                "last_cycle_at": row["created_at"] if row else None, "positions": positions,
                "killed": self.config.bot.kill_switch_path.exists(), "ai_model": self.config.ai.model,
                "update_state": "manual_signed_install_only"}
        finally:
            db.close()

    def _last_id(self):
        if not self.state.exists():
            return 0
        return int(json.loads(self.state.read_text())["last_id"])

    def apply(self, command, now=None):
        now = time.time() if now is None else now
        identifier, action, expires = command["id"], command["action"], command["expires"]
        if type(identifier) is not int or identifier <= 0 or action not in {"kill", "resume"}:
            raise ValueError("Invalid remote command")
        if type(expires) not in (float, int) or not now < expires <= now+125:
            raise ValueError("Expired or invalid remote command")
        previous = self._last_id()
        if identifier <= previous:
            return identifier
        kill = self.config.bot.kill_switch_path
        kill.parent.mkdir(parents=True, exist_ok=True)
        if action == "kill":
            # Exclusive creation preserves a local/automatic halt and its ownership.
            try:
                with kill.open("x", encoding="utf-8") as handle:
                    handle.write("remote pause\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                pass
        else:
            if kill.exists():
                if kill.read_text(encoding="utf-8") != "remote pause\n":
                    raise ValueError("Local pause requires local release")
                kill.unlink(missing_ok=True)
        # Desired-state actions are safe to retry after a crash before this checkpoint.
        self.state_directory.mkdir(parents=True, exist_ok=True)
        temporary = self.state.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"last_id": identifier}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.state)
        return identifier

    def sync(self):
        last = self._last_id()
        payload = {"snapshot": self.snapshot(), "acks": [last] if last else []}
        if self.update_provider:
            payload['snapshot']['bot_update'] = self.update_provider()
        if self.restore_provider:
            payload['snapshot']['bot_restore'] = self.restore_provider()
        if self.dashboard_provider:
            payload["snapshot"]["dashboard"] = self.dashboard_provider()
        if self.jobs:
            payload["job_results"] = self.jobs.results()
        request = urllib.request.Request(self.origin + "/v1/device/sync",
            data=json.dumps(payload, allow_nan=False).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token,
                     "User-Agent": "CryptoPaperPortalAgent/0.6.2", "Accept": "application/json"})
        with self.opener.open(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Oversized response")
        decoded = json.loads(raw)
        commands = decoded["commands"]
        if not isinstance(commands, list) or len(commands) > 50:
            raise ValueError("Invalid commands")
        for command in sorted(commands, key=lambda c: c["id"]):
            self.apply(command)
        jobs = decoded.get('jobs',[])
        if not isinstance(jobs,list) or len(jobs)>1:
            raise ValueError('Invalid jobs')
        if self.jobs:
            for job in jobs:
                self.jobs.accept(job)

    def run(self, *, stop=None, validate=None, report=None):
        failures = 0
        with single_instance(self.state_directory / "remote.lock"):
            while not (stop and stop()):
                try:
                    if validate:
                        validate()
                    self.sync()
                    failures = 0
                    self.last_error = None
                except Exception as error:
                    failures = min(failures+1, 5)
                    self.last_error = type(error).__name__
                    if isinstance(error, urllib.error.HTTPError):
                        self.last_error += ":" + str(error.code)
                    # Never log response bodies, URLs with secrets, or credentials.
                if report:
                    report(failures == 0)
                deadline = time.monotonic() + min(300, 30 * 2**failures) + random.uniform(0, 3)
                while time.monotonic() < deadline:
                    if stop and stop():
                        return
                    time.sleep(min(1, max(0, deadline-time.monotonic())))


if __name__ == "__main__":
    config = load_config()
    RemoteAgent(config, os.environ["PORTAL_ORIGIN"], os.environ["PORTAL_DEVICE_TOKEN"]).run()
