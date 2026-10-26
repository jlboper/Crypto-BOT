"""One bounded observation thread inside the existing supervised process.

All sources are explicit read-only SQLite paths. No wallet/ledger constructor,
exchange transport, credential loading, model or trading executor is imported.
Only the new cohort database is writable; failures never control trading.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
import math
from pathlib import Path
import queue
import re
import sqlite3
import threading
import time

from .operational_cohort import (AUTHORITY, FLAGS, SCOPES, FINGERPRINT_KEYS, OperationalCohortStore,
                                 canonical, digest, epoch, iso)

QUEUE_CAPACITY = 64
SOURCE_READ_SECONDS = .25
MAX_PROPOSAL_BYTES = 4096
_ACTIVE_PATHS = set()
_ACTIVE_LOCK = threading.Lock()


@dataclass(frozen=True)
class SourceSpec:
    engine: str
    environment: str
    database_path: Path
    max_age_seconds: int = 900

    def __post_init__(self):
        if self.engine not in SCOPES or self.environment not in SCOPES[self.engine]:
            raise ValueError("OBSERVATION_SCOPE_REQUIRED")
        if type(self.max_age_seconds) is not int or not 60 <= self.max_age_seconds <= 86400:
            raise ValueError("SOURCE_FRESHNESS_REQUIRED")
        object.__setattr__(self, "database_path", Path(self.database_path).resolve())


TABLES = {
    "SPOT": ("equity", "created_at", "positions", "trades", "created_at"),
    "FUTURES": ("forward_equity", "created_at", "forward_position", "forward_trades", "closed_at"),
    "AI_MARKET_PULSE": ("pulse_observations", "at", "pulse_positions", "pulse_trades", "closed"),
    "QUANT_ARBITRAGE": ("quant_equity", "at", "quant_positions", "quant_trades", "closed"),
}


def _timestamp(value):
    if type(value) in (int, float):
        return epoch(value)
    if type(value) is str and len(value) <= 40:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
            raise ValueError("EXPLICIT_UTC_REQUIRED")
        return epoch(dt.timestamp())
    raise ValueError("UTC_TIME_REQUIRED")


def _readonly(spec):
    db = sqlite3.connect(spec.database_path.as_uri() + "?mode=ro", uri=True, timeout=.1)
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    deadline = time.monotonic() + SOURCE_READ_SECONDS
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return db


def capture_source(spec, *, now):
    """Current local evidence, not complete account reconciliation or balance.

    Count/last-cut queries are scoped to known identifiers, with query_only and
    a progress deadline. Raw JSON settings/news/order/account IDs never leave
    the source, and source files cannot be created by a missing-path read.
    """
    at = epoch(now)
    result = {"schema": 1, "engine": spec.engine, "environment": spec.environment,
        "captured_at": iso(at), "state": "UNAVAILABLE", "source_at": None,
        "position_count": None, "trade_row_count": None, "source_digest": None,
        "reason_codes": ["SOURCE_UNAVAILABLE"], **{flag: False for flag in FLAGS}}
    table, timestamp, positions, trades, _ = TABLES[spec.engine]
    try:
        with closing(_readonly(spec)) as db:
            db.execute("BEGIN")
            latest = db.execute(f"SELECT {timestamp} FROM {table} ORDER BY {timestamp} DESC LIMIT 1").fetchone()
            pos = db.execute(f"SELECT COUNT(*) FROM {positions}").fetchone()[0]
            closed = db.execute(f"SELECT COUNT(*) FROM {trades}").fetchone()[0]
            # A digest of currently visible financial columns captures changes
            # without leaking arbitrary stored text, identifiers or JSON.
            if spec.engine == "SPOT":
                rows = db.execute("SELECT substr(symbol,1,33),quantity,entry_price,stop_price,take_profit FROM positions ORDER BY symbol LIMIT 257").fetchall()
            elif spec.engine == "FUTURES":
                rows = db.execute("SELECT substr(symbol,1,33),substr(direction,1,8),leverage,quantity,entry_price,stop_price,take_profit FROM forward_position ORDER BY symbol LIMIT 257").fetchall()
            else:
                rows = [(pos,)]  # Shadow JSON is intentionally not propagated.
            if len(rows) > 256 or type(pos) is not int or type(closed) is not int:
                raise ValueError("SOURCE_LIMIT")
            if spec.engine in {"SPOT", "FUTURES"}:
                for row in rows:
                    if type(row[0]) is not str or not re.fullmatch(r"[A-Z0-9]{2,32}", row[0]):
                        raise ValueError("SOURCE_SYMBOL")
                    if spec.engine == "FUTURES" and row[1] not in {"LONG", "SHORT"}:
                        raise ValueError("SOURCE_DIRECTION")
                    numbers = row[2:] if spec.engine == "FUTURES" else row[1:]
                    if any(type(number) not in (int, float) or not math.isfinite(number) or not 0 < number <= 1e18 for number in numbers):
                        raise ValueError("SOURCE_NUMBER")
        source_at = _timestamp(latest[0]) if latest else None
        fresh = source_at is not None and 0 <= at-source_at <= spec.max_age_seconds
        result.update(position_count=pos, trade_row_count=closed,
                      source_at=iso(source_at) if source_at else None,
                      source_complete=fresh, state="OBSERVED_LOCAL" if fresh else "STALE_OR_EMPTY",
                      reason_codes=["LOCAL_SNAPSHOT_ONLY" if fresh else "SOURCE_STALE_OR_EMPTY"],
                      source_digest=digest({"source_at": source_at, "positions": rows, "trade_rows": closed}))
    except (sqlite3.Error, OSError, ValueError, OverflowError, TypeError):
        pass  # Closed diagnostics only; never echo SQL paths or provider text.
    return result


def audit_legacy_source(spec, *, now, max_rows=100_000):
    """Inspect existing timestamps without backdating a prospective cohort.

    A local span and row gaps are observable. Strategy continuity, account
    cashflows, complete costs and semantic fingerprints of old decisions stay
    unknown unless separately retained evidence proves them.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 100_000:
        raise ValueError("ROW_LIMIT_REQUIRED")
    at = epoch(now)
    result = {"engine": spec.engine, "environment": spec.environment, "state": "UNAVAILABLE",
              "observed_rows": 0, "first_at": None, "last_at": None, "local_span_days": None,
              "max_gap_seconds": None, "truncated": False, "qualified_days": None,
              "costs_complete": None, "cashflows_complete": None,
              "semantic_continuity": "UNKNOWN", "financial_qualification": "UNKNOWN",
              "backfilled": False, "reset_required": False, **AUTHORITY}
    table, timestamp, *_ = TABLES[spec.engine]
    try:
        with closing(_readonly(spec)) as db:
            rows = db.execute(f"SELECT {timestamp} FROM {table} ORDER BY {timestamp} LIMIT ?", (max_rows+1,)).fetchall()
        result["truncated"] = len(rows) > max_rows
        values = sorted(_timestamp(row[0]) for row in rows[:max_rows])
        if any(value > at for value in values):
            result["state"] = "FUTURE_SOURCE_TIMESTAMPS"
            return result
        if values:
            result.update(state="LEGACY_LOCAL_EVIDENCE", observed_rows=len(values), first_at=iso(values[0]),
                last_at=iso(values[-1]), local_span_days=(values[-1]-values[0])/86400,
                max_gap_seconds=max((right-left for left, right in zip(values, values[1:])), default=0))
        else:
            result["state"] = "NO_LEGACY_ROWS"
    except (sqlite3.Error, OSError, ValueError, OverflowError, TypeError):
        pass
    return result


class PreproductionObserverService:
    def __init__(self, data_dir, *, sources, semantic_config, clock=time.time,
                 cadence_seconds=300, max_receipt_delay_seconds=60,
                 max_records=200_000, max_bytes=256*1024*1024):
        if type(sources) not in (tuple, list) or not 1 <= len(sources) <= 4 or any(type(item) is not SourceSpec for item in sources):
            raise ValueError("EXPLICIT_SOURCES_REQUIRED")
        if len({(item.engine, item.environment) for item in sources}) != len(sources):
            raise ValueError("DUPLICATE_SOURCE_SCOPE")
        self.sources = tuple(sources)
        if type(semantic_config) is not dict or set(semantic_config) != {item.engine for item in sources}:
            raise ValueError("EXPLICIT_SEMANTIC_FINGERPRINTS_REQUIRED")
        self.semantic_config = {key: dict(value) for key, value in semantic_config.items()}
        if any(set(value) != set(FINGERPRINT_KEYS) or any(type(item) is not str or not re.fullmatch(r"[0-9a-f]{64}", item) for item in value.values()) for value in self.semantic_config.values()):
            raise ValueError("EXPLICIT_SEMANTIC_FINGERPRINTS_REQUIRED")
        for source in self.sources:
            self.semantic_config[source.engine]["configuration"] = digest({
                "supplied_configuration": self.semantic_config[source.engine].get("configuration"),
                "source_max_age_seconds": source.max_age_seconds, "local_capture_schema": 1})
        self.clock, self.cadence, self.delay = clock, cadence_seconds, max_receipt_delay_seconds
        self.store = OperationalCohortStore(Path(data_dir)/"operational-cohorts.sqlite3", clock=clock,
                                            max_records=max_records, max_bytes=max_bytes)
        if self.store.path.resolve() in {item.database_path for item in sources}:
            raise ValueError("DEDICATED_COHORT_DATABASE_REQUIRED")
        self._registrations, self._last_tick = {}, None
        self._queue = queue.Queue(maxsize=QUEUE_CAPACITY)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._tick_lock = threading.Lock()
        self._initialized = False
        self._errors = self._dropped = 0
        self._last_error = None
        self._owns_path = False

    def initialize(self):
        self.store.initialize()
        now = epoch(self.clock())
        for source in self.sources:
            self._registrations[(source.engine, source.environment)] = self.store.register(
                source.engine, source.environment, self.semantic_config[source.engine],
                cadence_seconds=self.cadence, max_receipt_delay_seconds=self.delay, now=now)
        self._initialized = True

    def record_proposal(self, payload):
        """No SQL, callback, model or wait on the producer/entry thread.

        Persist only a canonical digest and trusted scope/time, not arbitrary
        opportunity content. The existing opportunity journal retains details.
        """
        try:
            pending, nodes = [(payload, 0)], 0
            while pending:
                item, depth = pending.pop()
                nodes += 1
                if nodes > 256 or depth > 8:
                    raise ValueError()
                if type(item) is dict:
                    if any(type(key) is not str or len(key) > 96 for key in item):
                        raise ValueError()
                    pending.extend((child, depth+1) for child in item.values())
                elif type(item) in (list, tuple):
                    pending.extend((child, depth+1) for child in item)
                elif type(item) is str and len(item) > 2048:
                    raise ValueError()
                elif item is not None and type(item) not in (str, int, float, bool):
                    raise ValueError()
            if type(payload) is not dict or len(canonical(payload)) > MAX_PROPOSAL_BYTES:
                raise ValueError()
            scope = (payload.get("engine"), payload.get("environment"))
            if scope not in {(source.engine, source.environment) for source in self.sources}:
                raise ValueError()
            proposal_at = epoch(payload.get("at"))
            if proposal_at > epoch(self.clock()):
                raise ValueError()
            self._queue.put_nowait((scope, proposal_at, digest(payload)))
            return True
        except (ValueError, TypeError, OverflowError, queue.Full):
            self._dropped += 1
            return False

    def tick(self):
        if not self._tick_lock.acquire(blocking=False):
            return False
        try:
            if not self._initialized:
                self.initialize()
            now = epoch(self.clock())
            if self._last_tick is not None and now < self._last_tick:
                raise ValueError("CLOCK_REGRESSION")
            # Align captures with UTC cadence boundaries, not the arbitrary
            # process start second. Otherwise a restart at :03 would remain
            # outside a :00 receipt-delay window forever.
            if self._last_tick is None or int(now // self.cadence) > int(self._last_tick // self.cadence):
                for source in self.sources:
                    captured = capture_source(source, now=now)
                    received_at = epoch(self.clock())
                    self.store.observe(self._registrations[(source.engine, source.environment)], captured, now=received_at)
                self._last_tick = now
            now = epoch(self.clock())
            for _ in range(QUEUE_CAPACITY):
                try:
                    scope, proposal_at, value_hash = self._queue.get_nowait()
                except queue.Empty:
                    break
                payload = {"proposal_digest": value_hash, "proposal_at": iso(proposal_at),
                           **{flag: False for flag in FLAGS}}
                self.store.observe(self._registrations[scope], payload, now=now,
                                   identity="proposal:"+value_hash, kind="PROPOSAL")
            return True
        except (ValueError, sqlite3.Error, OSError, KeyError, TypeError):
            self._errors += 1
            self._last_error = "OBSERVATION_FAILED"
            return False
        finally:
            self._tick_lock.release()

    def _run(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(1)

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            path = self.store.path.resolve()
            with _ACTIVE_LOCK:
                if path in _ACTIVE_PATHS and not self._owns_path:
                    self._last_error = "ALREADY_SUPERVISED"
                    return False
                _ACTIVE_PATHS.add(path)
                self._owns_path = True
            try:
                if not self._initialized:
                    self.initialize()
            except (ValueError, sqlite3.Error, OSError, KeyError, TypeError):
                self._errors += 1
                self._last_error = "INITIALIZATION_FAILED"
                with _ACTIVE_LOCK:
                    _ACTIVE_PATHS.discard(path)
                    self._owns_path = False
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="preproduction-observer", daemon=True)
            self._thread.start()
            return True

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        if self._owns_path and (self._thread is None or not self._thread.is_alive()):
            with _ACTIVE_LOCK:
                _ACTIVE_PATHS.discard(self.store.path.resolve())
                self._owns_path = False

    def snapshot(self):
        try:
            result = self.store.snapshot(now=self.clock())
        except (sqlite3.Error, OSError, ValueError, TypeError):
            result = {"schema": 1, "state": "UNAVAILABLE", "scopes": [], **AUTHORITY}
        result["health"] = {"worker_alive": bool(self._thread and self._thread.is_alive()),
            "queue_depth": self._queue.qsize(), "queue_capacity": QUEUE_CAPACITY,
            "errors": self._errors, "dropped": self._dropped, "last_error": self._last_error}
        return result
