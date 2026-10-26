"""Prepared LIVE runtime compatibility, separate from financial authorization.

No package field or environment variable authorizes capital. LIVE requires both
an explicit requested mode and the protected local owner authority. Ordinary
Testnet/PAPER operation does not depend on that optional authority's availability.
"""
from __future__ import annotations

from pathlib import Path

PREPARED_LIVE_PROTOCOL = 1
LIVE_SPOT_DATABASE = "data/live/spot-trader.db"
LIVE_FUTURES_DATABASE = "data/live/futures-trader.db"
LIVE_SPOT_CAPITAL_DATABASE = "data/live/central-admission-spot.sqlite3"
LIVE_FUTURES_CAPITAL_DATABASE = "data/live/central-admission-futures.sqlite3"
LIVE_SPOT_KILL = "data/live/SPOT_KILL"
LIVE_FUTURES_KILL = "data/live/FUTURES_KILL"
LIVE_ENTRY_HALT = "data/live/ENTRY_HALT"
LIVE_DATABASES = (LIVE_SPOT_DATABASE,LIVE_FUTURES_DATABASE,LIVE_SPOT_CAPITAL_DATABASE,LIVE_FUTURES_CAPITAL_DATABASE)


def owner_mode_authorized(source, *, require_ready=True):
    try:
        from .live_authorization import operating_mode_authorized
        return operating_mode_authorized(Path(source),require_ready=require_ready) is True
    except Exception:
        return False


def require_runtime_mode(source, mode, *, require_ready=True):
    if mode in {"paper","testnet"}: return mode
    if mode != "live" or not owner_mode_authorized(source,require_ready=require_ready):
        raise ValueError("LIVE requires protected active owner approval and validated readiness")
    return mode


def runtime_mode_allowed(source, mode, *, require_ready=False):
    try: return require_runtime_mode(source,mode,require_ready=require_ready)==mode
    except (TypeError,ValueError): return False


def confined_live_path(source, relative):
    source=Path(source).resolve()
    if relative not in {*LIVE_DATABASES,LIVE_SPOT_KILL,LIVE_FUTURES_KILL,LIVE_ENTRY_HALT}:
        raise ValueError("Unknown prepared LIVE state path")
    target=source/relative
    for path in (target,*target.parents):
        if path==source: break
        if path.is_symlink() or (hasattr(path,"is_junction") and path.is_junction()):
            raise ValueError("Linked LIVE state path")
    if not target.resolve().is_relative_to(source): raise ValueError("LIVE state escaped installation")
    return target


def live_capabilities(source):
    """Small non-secret summary. No keys, policy values or proofs are returned."""
    return {"prepared_live_protocol":PREPARED_LIVE_PROTOCOL,"default_activation":False,
            "protected_owner_mode_authorized":owner_mode_authorized(source),
            "separate_live_ledgers":True,"single_supervised_engine_required":True}
