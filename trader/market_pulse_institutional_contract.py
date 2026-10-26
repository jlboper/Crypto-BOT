"""Closed optional portal contract for public institutional context only."""
from __future__ import annotations

from datetime import datetime
import json
import re

from .market_pulse_institutional import (PROVIDERS, LIMITATIONS, valid_observation)


def _stamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(timespec="milliseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def valid_institutional_context(value):
    try:
        if (type(value) is not dict or set(value) != {"schema", "mode", "execution_enabled", "at", "providers", "observations", "limitations"}
                or type(value["schema"]) is not int or value["schema"] != 1 or value["mode"] != "CONTEXT_ONLY"
                or value["execution_enabled"] is not False or not _stamp(value["at"])
                or len(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))) > 8000
                or type(value["providers"]) is not list or len(value["providers"]) > 2
                or type(value["observations"]) is not list or len(value["observations"]) > 6
                or type(value["limitations"]) is not list or not 1 <= len(value["limitations"]) <= 8
                or len(set(value["limitations"])) != len(value["limitations"])
                or any(type(code) is not str or code not in LIMITATIONS for code in value["limitations"])):
            return False
        seen = set()
        for provider in value["providers"]:
            if (type(provider) is not dict or set(provider) != {"id", "name", "url", "state", "last_update", "last_error"}
                    or provider["id"] not in PROVIDERS or provider["id"] in seen
                    or (provider["name"], provider["url"]) != PROVIDERS[provider["id"]]
                    or provider["state"] not in {"STANDBY", "READY", "ERROR", "DISABLED"}
                    or provider["last_error"] not in {None, "SEC_CONTACT_REQUIRED", "INSTITUTIONAL_HTTP_ERROR", "INSTITUTIONAL_UNAVAILABLE"}
                    or provider["last_update"] is not None and (not _stamp(provider["last_update"]) or provider["last_update"] > value["at"])):
                return False
            seen.add(provider["id"])
        ids, proofs = set(), set()
        for row in value["observations"]:
            if (not valid_observation(row) or row["id"] in ids
                    or any(not _stamp(row[key]) for key in ("as_of", "available_at", "received_at"))
                    or row["received_at"] > value["at"] or len(row["title"].encode("utf-16-le"))//2 > 180
                    or len(set(row["limitations"])) != len(row["limitations"])):
                return False
            proof = (row["provider"], row["symbol"], row["evidence_digest"])
            if proof in proofs:
                return False
            ids.add(row["id"])
            proofs.add(proof)
        return True
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return False
