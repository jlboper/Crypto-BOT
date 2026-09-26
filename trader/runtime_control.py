"""Local maintenance handshake; candidate engines cannot trade before commit."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .update_manager import atomic_json


class RuntimeControl:
    def __init__(self, directory: Path, token=None):
        self.directory = Path(directory)
        self.maintenance = self.directory / "UPDATE_MAINTENANCE.json"
        self.activation = self.directory / "UPDATE_ACTIVATION.json"
        self.status = self.directory / "engine-runtime.json"
        self.token = token

    def guard_start(self):
        if self.token is not None:
            if re.fullmatch(r"[0-9a-f]{64}", self.token) is None:
                raise RuntimeError("Invalid candidate handshake")
            request = json.loads(self.maintenance.read_text())
            if request.get("token") != self.token or request.get("phase") != "candidate":
                raise RuntimeError("Candidate is not authorized to start")
        elif self.maintenance.exists():
            raise RuntimeError("Update maintenance in progress; startup blocked")

    def ready(self, version, *, dashboard_ready, mode="paper"):
        if dashboard_ready is not True:
            raise RuntimeError("Dashboard did not start")
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_json(self.status, {"protocol": 1, "pid": os.getpid(), "version": version,
                    "token": self.token, "phase": "candidate" if self.token else "running",
                    "mode": mode, "dashboard_ready": True})

    def await_activation(self, timeout=120, sleep=time.sleep):
        if self.token is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.maintenance.exists():
                request = json.loads(self.maintenance.read_text())
                if request.get("token") != self.token or request.get("phase") != "candidate":
                    raise RuntimeError("Candidate activation cancelled")
            else:
                approval = json.loads(self.activation.read_text())
                if approval.get("token") != self.token:
                    raise RuntimeError("Activation does not match candidate")
                record = json.loads(self.status.read_text())
                atomic_json(self.status, {**record, "phase": "running"})
                return
            sleep(0.1)
        raise TimeoutError("Candidate activation deadline exceeded")

    def should_stop(self):
        return self.maintenance.exists()
