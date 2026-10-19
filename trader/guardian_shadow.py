"""Bounded, append-only Guardian SHADOW LEVEL 0 observer.

The caller is the existing supervised engine;
this service never creates an executor, reserves capital or controls another bot.
Optional injected context is a separately frozen annotation, never authority or
an input to the deterministic assessment. Default context/API budget is zero.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
import threading
import time
import uuid
import zlib

from .guardian_capture import capture_guardian, _read_only
from .guardian_intelligence import build_intelligence

DB_NAME = "guardian-shadow.db"
PROTOCOL = 1
MAX_CAPTURE = 65536
MAX_REPORT = 12000
MAX_ANNOTATION = 6144
MAX_SNAPSHOT = 12000
_HASH = re.compile(r"^[a-f0-9]{64}$")
_OWNERS = {}
_OWNERS_LOCK = threading.RLock()
_ERROR_CODES = frozenset(("RETENTION_FULL","JOURNAL_STORAGE_FULL","GUARDIAN_COHORT_CONFIG_MISMATCH",
    "INVALID_FROZEN_JSON","FROZEN_VALUE_TOO_LARGE","INVALID_CAPTURE_IDENTITY","CAPTURE_CAUSALITY_ERROR",
    "INVALID_CAPTURE_SOURCES","INVALID_CAPTURE_BARS","INVALID_ASSESSMENT_IDENTITY","LEASE_LOST",
    "GUARDIAN_OBSERVATION_FAILED","GUARDIAN_OBSERVER_LOOP_FAILED"))
_AI_REASONS = frozenset(("AI_DISABLED_OR_UNAVAILABLE","MODEL_PRICING_NOT_VERIFIED","ASSESSMENT_STALE_OR_FUTURE",
    "AI_BUDGET_OR_INTERVAL","AI_FAILED","AI_CONTEXT_TIMEOUT","AI_PRIOR_CONTEXT_RUNNING","AI_OBSERVER_STOPPED",
    "AI_CONTEXT_INVALID","AI_HEALTH_UNAVAILABLE","AI_BUDGET_CONFIGURATION","INSUFFICIENT_VERIFIED_CONTEXT",
    "AI_AUTH_FAILED","AI_ACCESS_DENIED","AI_REQUEST_INVALID","AI_QUOTA_EXHAUSTED","AI_RATE_LIMITED",
    "AI_RATE_LIMIT_UNKNOWN","AI_SERVER_ERROR","AI_HTTP_ERROR","AI_TRANSPORT_FAILED",
    "AI_RESPONSE_TOO_LARGE","AI_RESPONSE_INVALID","AI_RESPONSE_INCOMPLETE","AI_RESPONSE_REFUSED",
    "AI_COMMENTARY_INVALID"))


@dataclass(frozen=True)
class GuardianShadowConfig:
    enabled: bool = True
    mode: str = "SHADOW"
    autonomy_level: int = 0
    evaluation_interval: float = 60.
    lease_seconds: float = 160.
    heartbeat_seconds: float = 5.
    max_records: int = 129600
    max_corpus_bytes: int = 512*1024*1024
    context_max_calls_per_day: int = 0
    context_timeout_seconds: float = 10.

    def __post_init__(self):
        if (type(self.enabled) is not bool or self.mode!="SHADOW" or type(self.autonomy_level) is not int or self.autonomy_level!=0
                or self.evaluation_interval!=60 or self.lease_seconds!=160 or self.heartbeat_seconds!=5):
            raise ValueError("Guardian supports only fixed SHADOW LEVEL 0 observation")
        if (type(self.max_records) is not int or not 1<=self.max_records<=129600
                or type(self.max_corpus_bytes) is not int or not 32768<=self.max_corpus_bytes<=512*1024*1024
                or type(self.context_max_calls_per_day) is not int or not 0<=self.context_max_calls_per_day<=2
                or type(self.context_timeout_seconds) not in (int,float) or not math.isfinite(self.context_timeout_seconds)
                or not .05<=self.context_timeout_seconds<=10):
            raise ValueError("Invalid bounded Guardian observation budget")


class ShadowError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _dump(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _time(value):
    if type(value) in (int,float) and math.isfinite(value) and 0<value<=253402300799:
        return float(value)
    if isinstance(value,str) and len(value)<=48:
        try:
            instant=datetime.fromisoformat(value.replace("Z","+00:00"))
            return _time(instant.timestamp()) if instant.tzinfo is not None else None
        except (ValueError,OverflowError,OSError):
            pass
    return None


def _iso(value):
    stamp=_time(value)
    return datetime.fromtimestamp(stamp,UTC).isoformat() if stamp is not None else None


def _pack(value,maximum):
    try:
        raw=_dump(value).encode()
    except (ValueError,TypeError,RecursionError,OverflowError):
        raise ShadowError("INVALID_FROZEN_JSON") from None
    if len(raw)>maximum:
        raise ShadowError("FROZEN_VALUE_TOO_LARGE")
    compressed=zlib.compress(raw,6)
    return ("ZLIB",compressed,len(raw)) if len(compressed)<len(raw) else ("RAW",raw,len(raw))


def _unpack(codec,payload,maximum):
    if not isinstance(payload,bytes) or len(payload)>maximum:
        raise ShadowError("INVALID_FROZEN_PAYLOAD")
    if codec=="ZLIB":
        decoder=zlib.decompressobj()
        raw=decoder.decompress(payload,maximum+1)
        if len(raw)>maximum or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
            raise ShadowError("DECOMPRESSION_LIMIT")
    elif codec=="RAW":
        raw=payload
    else:
        raise ShadowError("INVALID_FROZEN_CODEC")
    try:
        result=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if _dump(result).encode()!=raw:
            raise ValueError()
        return result
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError):
        raise ShadowError("INVALID_FROZEN_JSON") from None


@contextmanager
def _writer(path):
    db=sqlite3.connect(path,timeout=.25)
    try:
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        # SQLite's page ceiling belongs to each connection. Reapply the frozen
        # journal cap on every writer, not only the initialization connection.
        try:
            row=db.execute("SELECT value FROM guardian_meta WHERE key='cohort'").fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error):
                raise
            row=None  # New, separate Guardian journal awaiting initialization.
        if row:
            ceiling=json.loads(row[0])["settings"]["max_corpus_bytes"]
            if type(ceiling) is not int or not 32768<=ceiling<=512*1024*1024:
                raise ShadowError("GUARDIAN_COHORT_CONFIG_MISMATCH")
            page_size=db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count={max(8,ceiling//page_size)}")
        with db:
            yield db
    finally:
        db.close()


def _get(db,key,fallback=None):
    row=db.execute("SELECT value FROM guardian_meta WHERE key=?",(key,)).fetchone()
    return row[0] if row else fallback


def _set(db,key,value):
    db.execute("INSERT INTO guardian_meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)))


def _record_hash(row):
    value = {key:row[key] for key in ("id","cutoff","committed","capture_digest","report_digest","annotation_digest","previous_digest")}
    # SQLite REAL returns floats even if the injected clock supplied an int.
    # Canonicalize before both write and read to keep durable digests stable.
    for key in ("cutoff", "committed"):
        value[key] = float(value[key])
    return _digest(value)


def _validate_capture(value,now):
    if not isinstance(value,dict) or value.get("execution_enabled") is not False or value.get("promotion_allowed") is not False:
        raise ShadowError("INVALID_CAPTURE_IDENTITY")
    cutoff,captured=_time(value.get("cutoff_at")),_time(value.get("captured_at"))
    if cutoff is None or captured is None or abs(cutoff-captured)>.00001 or cutoff>now:
        raise ShadowError("CAPTURE_CAUSALITY_ERROR")
    metadata=value.get("source_metadata")
    if not isinstance(metadata,dict) or set(metadata)!={"spot","futures","pulse","quant"}:
        raise ShadowError("INVALID_CAPTURE_SOURCES")
    for source in metadata.values():
        if not isinstance(source,dict) or source.get("state") not in {"FRESH","STALE","UNKNOWN"}:
            raise ShadowError("INVALID_CAPTURE_SOURCES")
        for field in ("available_at","captured_at"):
            if source.get(field) is not None and (_time(source[field]) is None or _time(source[field])>cutoff):
                raise ShadowError("CAPTURE_CAUSALITY_ERROR")
    bars=value.get("btc_closed_bars")
    if not isinstance(bars,list) or len(bars)>121:
        raise ShadowError("INVALID_CAPTURE_BARS")
    for row in bars:
        if not isinstance(row,dict) or any(_time(row.get(field)) is None or _time(row[field])>cutoff for field in ("at","received_at","known_at")):
            raise ShadowError("CAPTURE_CAUSALITY_ERROR")
    _pack(value,MAX_CAPTURE)
    return cutoff


def _validate_report(value,capture_digest,cutoff):
    if (not isinstance(value,dict) or value.get("schema")!=1 or value.get("engine")!="GUARDIAN_INTELLIGENCE"
            or value.get("mode")!="SHADOW" or type(value.get("autonomy_level")) is not int or value["autonomy_level"]!=0
            or any(value.get(flag) is not False for flag in ("controls_enabled","can_veto","execution_enabled","reservations_enabled","promotion_allowed"))
            or value.get("evidence",{}).get("source_digest")!=capture_digest
            or _time(value.get("at")) is None or abs(_time(value["at"])-cutoff)>.001
            or _time(value.get("cutoff_at")) is None or abs(_time(value["cutoff_at"])-cutoff)>.001):
        raise ShadowError("INVALID_ASSESSMENT_IDENTITY")
    _pack(value,MAX_REPORT)


def _ai_unavailable(reason):
    return {"state":"UNAVAILABLE","reason":reason if reason in _AI_REASONS else "AI_FAILED",
            "advisory_only":True,"controls_enabled":False,"execution_enabled":False}


def _annotation(value,report,now):
    """Accept only the reviewed advisory protocol, retaining historical identity."""
    if (not isinstance(value,dict) or value.get("advisory_only") is not True
            or value.get("controls_enabled") is not False or value.get("execution_enabled") is not False):
        raise ShadowError("INVALID_CONTEXT_ANNOTATION")
    if value.get("state")=="UNAVAILABLE":
        if set(value)!={"state","reason","advisory_only","execution_enabled","controls_enabled"}:
            raise ShadowError("INVALID_CONTEXT_ANNOTATION")
        return _ai_unavailable(value.get("reason"))
    fields={"state","at","assessment_id","model","advisory_only","execution_enabled","controls_enabled","commentary","usage"}
    cached=value.get("state")=="CACHED_HISTORICAL"
    if (value.get("state") not in {"COMPLETED","CACHED_HISTORICAL"} or set(value)!=fields|({"cache_age_seconds"} if cached else set())
            or not isinstance(value.get("assessment_id"),str) or not _HASH.fullmatch(value["assessment_id"])
            or not isinstance(value.get("model"),str) or not re.fullmatch(r"gpt-[A-Za-z0-9._-]{1,70}",value["model"])
            or _time(value.get("at")) is None or _time(value["at"])>now
            or not cached and (value["assessment_id"]!=report["assessment_id"] or _time(value["at"])<_time(report["at"])-.001)):
        raise ShadowError("INVALID_CONTEXT_ANNOTATION")
    if cached and (type(value["cache_age_seconds"]) not in (int,float) or not math.isfinite(value["cache_age_seconds"])
                   or not 0<=value["cache_age_seconds"]<=900 or _time(value["at"])>_time(report["at"])):
        raise ShadowError("INVALID_CONTEXT_ANNOTATION")
    commentary,usage=value["commentary"],value["usage"]
    if (not isinstance(commentary,dict) or set(commentary)!={"summary","posture","cautions","evidence_ids"}
            or not isinstance(commentary["summary"],str) or not 1<=len(commentary["summary"])<=280
            or commentary["posture"] not in {"OBSERVE","REVIEW_DATA","REVIEW_CONCENTRATION","REVIEW_PROTECTION"}
            or not isinstance(commentary["cautions"],list) or len(commentary["cautions"])>4
            or any(not isinstance(v,str) or len(v)>120 for v in commentary["cautions"])
            or not isinstance(commentary["evidence_ids"],list) or not 1<=len(commentary["evidence_ids"])<=4
            or any(v!=value["assessment_id"] for v in commentary["evidence_ids"])):
        raise ShadowError("INVALID_CONTEXT_ANNOTATION")
    if not isinstance(usage,dict) or set(usage)!={"input_tokens","output_tokens","cached_tokens","estimated_cost_usd","pricing_verified_at"}:
        raise ShadowError("INVALID_CONTEXT_ANNOTATION")
    if (any(v is not None and (type(v) is not int or not 0<=v<=100000) for v in (usage["input_tokens"],usage["output_tokens"],usage["cached_tokens"]))
            or usage["cached_tokens"] is not None and (usage["input_tokens"] is None or usage["cached_tokens"]>usage["input_tokens"])
            or usage["estimated_cost_usd"] is not None and (type(usage["estimated_cost_usd"]) not in (int,float) or not math.isfinite(usage["estimated_cost_usd"]) or not 0<=usage["estimated_cost_usd"]<=1)
            or not isinstance(usage["pricing_verified_at"],str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",usage["pricing_verified_at"])):
        raise ShadowError("INVALID_CONTEXT_ANNOTATION")
    result=json.loads(_dump(value))
    result["commentary"]["summary"]=re.sub(r"[\x00-\x1f]"," ",commentary["summary"])
    result["commentary"]["cautions"]=[re.sub(r"[\x00-\x1f]"," ",v) for v in commentary["cautions"]]
    _pack(result,MAX_ANNOTATION)
    return result


class GuardianShadowService:
    def __init__(self,data_dir,*,app_config,config=None,capture_fn=None,analyze_fn=None,context_hook=None,clock=time.time,monotonic=time.monotonic):
        self.data_dir=Path(data_dir)
        self.path=self.data_dir/DB_NAME
        self.app_config,self.config=app_config,config or GuardianShadowConfig()
        self.capture_fn,self.analyze_fn=capture_fn or capture_guardian,analyze_fn or build_intelligence
        if context_hook is not None and not callable(context_hook):
            raise ValueError("Context hook must be explicitly injected and callable")
        self.context_hook,self.clock,self.monotonic=context_hook,clock,monotonic
        self._owner=f"{os.getpid()}:{uuid.uuid4().hex}"
        self._stop=threading.Event()
        self._tick_lock=threading.Lock()
        self._thread=self._context_thread=None
        self._initialized=False

    def initialize(self):
        self.data_dir.mkdir(parents=True,exist_ok=True)
        with _writer(self.path) as db:
            # Own separate journal only. Do not set WAL or touch engine DBs.
            db.executescript("""
              CREATE TABLE IF NOT EXISTS guardian_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS guardian_records(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,
                cutoff REAL NOT NULL,committed REAL NOT NULL,capture_digest TEXT NOT NULL UNIQUE,
                report_digest TEXT NOT NULL,annotation_digest TEXT NOT NULL,previous_digest TEXT NOT NULL,record_digest TEXT NOT NULL,
                capture_codec TEXT NOT NULL,capture BLOB NOT NULL,capture_bytes INTEGER NOT NULL,
                report_codec TEXT NOT NULL,report BLOB NOT NULL,report_bytes INTEGER NOT NULL,
                annotation_codec TEXT NOT NULL,annotation BLOB NOT NULL,annotation_bytes INTEGER NOT NULL,stored_bytes INTEGER NOT NULL);
              CREATE TRIGGER IF NOT EXISTS guardian_records_no_update BEFORE UPDATE ON guardian_records BEGIN SELECT RAISE(ABORT,'guardian evidence is append-only'); END;
              CREATE TRIGGER IF NOT EXISTS guardian_records_no_delete BEFORE DELETE ON guardian_records BEGIN SELECT RAISE(ABORT,'guardian evidence is append-only'); END;
            """)
            db.execute("BEGIN IMMEDIATE")
            cohort=_dump({"protocol":PROTOCOL,"settings":asdict(self.config)})
            saved=_get(db,"cohort")
            if saved is not None and saved!=cohort:
                raise ShadowError("GUARDIAN_COHORT_CONFIG_MISMATCH")
            if saved is None:
                for key,value in {"cohort":cohort,"records":0,"stored_bytes":0,"errors":0,"last_error":"",
                                  "started_at":self.clock(),"heartbeat_at":"","last_success_at":"","context_day":"","context_calls":0}.items():
                    _set(db,key,value)
            page_size=db.execute("PRAGMA page_size").fetchone()[0]
            pages=max(8,self.config.max_corpus_bytes//page_size)
            db.execute(f"PRAGMA max_page_count={pages}")
        self._initialized=True
        return True

    def _owned(self,db,now):
        return _get(db,"lease_owner")==self._owner and float(_get(db,"lease_until","0"))>now

    def _lease(self):
        now=self.clock()
        with _writer(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            owner,until=_get(db,"lease_owner"),float(_get(db,"lease_until","0"))
            if owner and owner!=self._owner and until>now:
                return False
            _set(db,"lease_owner",self._owner)
            _set(db,"lease_until",now+self.config.lease_seconds)
            _set(db,"heartbeat_at",now)
            return True

    def _error(self,code):
        code=code if code in _ERROR_CODES else "GUARDIAN_OBSERVATION_FAILED"
        try:
            with _writer(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                if self._owned(db,self.clock()) and not self._stop.is_set():
                    _set(db,"last_error",code)
                    _set(db,"errors",int(_get(db,"errors","0"))+1)
        except (sqlite3.Error,OSError,ValueError):
            pass  # Observability errors cannot escape to the financial engine.

    def _context(self,report):
        if self.context_hook is None or self.config.context_max_calls_per_day==0:
            return _ai_unavailable("AI_DISABLED_OR_UNAVAILABLE")
        if (not any(scope.get('data_state') == 'FRESH' for scope in report.get('scopes', []))
                and report.get('regime', {}).get('state') == 'INSUFFICIENT_DATA'):
            # No source to interpret: persist the deterministic unknowns rather
            # than spending a request on an empty context.
            return _ai_unavailable('INSUFFICIENT_VERIFIED_CONTEXT')
        if self._context_thread is not None and self._context_thread.is_alive():
            return _ai_unavailable("AI_PRIOR_CONTEXT_RUNNING")
        has_health=callable(getattr(self.context_hook,"health",None))
        health=None
        if has_health:
            try:
                health=self.context_hook.health()
                if (not isinstance(health,dict) or type(health.get("daily_cap")) is not int or not 0<=health["daily_cap"]<=self.config.context_max_calls_per_day
                        or type(health.get("used_today")) is not int or not 0<=health["used_today"]<=2
                        or type(health.get("available")) is not bool):
                    return _ai_unavailable("AI_BUDGET_CONFIGURATION")
            except Exception:
                return _ai_unavailable("AI_HEALTH_UNAVAILABLE")
        with _writer(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if not self._owned(db,self.clock()) or self._stop.is_set():
                raise ShadowError("LEASE_LOST")
            day=datetime.fromtimestamp(self.clock(),UTC).date().isoformat()
            calls=int(_get(db,"context_calls","0")) if _get(db,"context_day")==day else 0
            if has_health:
                _set(db,"ai_health_day",day)
                _set(db,"ai_used_today",health["used_today"])
                _set(db,"ai_daily_cap",health["daily_cap"])
                _set(db,"ai_health_pending",0)
                if not health["available"] or health["daily_cap"]==0:
                    return _ai_unavailable("AI_DISABLED_OR_UNAVAILABLE")
                # The reviewed hook checks its durable API claim budget itself;
                # allow its historical-cache lookup even after that API cap.
                if calls>=1440:
                    return _ai_unavailable("AI_BUDGET_OR_INTERVAL")
            elif calls>=self.config.context_max_calls_per_day:
                return _ai_unavailable("AI_BUDGET_OR_INTERVAL")
            _set(db,"context_day",day)
            _set(db,"context_calls",calls+1)
            if has_health:
                _set(db,"ai_health_pending",1)
        channel=queue.Queue(maxsize=1)
        # The reviewed hook sanitizes the numeric report into its own <=4096 B
        # request. No raw capture, news text, credentials or previous reasons.
        payload=json.loads(_dump(report))
        def invoke():
            try:
                value=_annotation(self.context_hook(payload),report,self.clock())
            except Exception:
                value=_ai_unavailable("AI_CONTEXT_INVALID")
            try:
                channel.put_nowait(value)
            except queue.Full:
                pass
        self._context_thread=threading.Thread(target=invoke,name="guardian-untrusted-context",daemon=True)
        self._context_thread.start()
        deadline=time.monotonic()+self.config.context_timeout_seconds
        while not self._stop.is_set() and time.monotonic()<deadline:
            try:
                value=channel.get(timeout=min(.05,max(.001,deadline-time.monotonic())))
                if has_health:
                    try:
                        latest=self.context_hook.health()
                        if (isinstance(latest,dict) and type(latest.get("used_today")) is int and 0<=latest["used_today"]<=2
                                and latest.get("daily_cap")==health["daily_cap"]):
                            with _writer(self.path) as db:
                                db.execute("BEGIN IMMEDIATE")
                                if self._owned(db,self.clock()) and not self._stop.is_set():
                                    _set(db,"ai_health_day",datetime.fromtimestamp(self.clock(),UTC).date().isoformat())
                                    _set(db,"ai_used_today",latest["used_today"])
                                    _set(db,"ai_health_pending",0)
                    except Exception:
                        pass
                return value
            except queue.Empty:
                pass
        return _ai_unavailable("AI_OBSERVER_STOPPED" if self._stop.is_set() else "AI_CONTEXT_TIMEOUT")

    def tick(self):
        if not self.config.enabled or self._stop.is_set():
            return {"state":"STOPPED"}
        if not self._tick_lock.acquire(blocking=False):
            return {"state":"TICK_ALREADY_RUNNING"}
        try:
            if not self._initialized:
                self.initialize()
            if not self._lease():
                return {"state":"LEASE_HELD_BY_ANOTHER_OBSERVER"}
            with _writer(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                if not self._owned(db,self.clock()) or self._stop.is_set():
                    raise ShadowError("LEASE_LOST")
                if (int(_get(db,"records","0"))>=self.config.max_records
                        or int(_get(db,"stored_bytes","0"))>=self.config.max_corpus_bytes
                        or _get(db,"last_error") in {"RETENTION_FULL","JOURNAL_STORAGE_FULL"}):
                    _set(db,"last_error","RETENTION_FULL")
                    return {"state":"RETENTION_FULL"}
            capture=self.capture_fn(self.app_config)
            cutoff=_validate_capture(capture,self.clock())
            capture_digest=_digest(capture)
            with _writer(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                if not self._owned(db,self.clock()) or self._stop.is_set():
                    raise ShadowError("LEASE_LOST")
                existing=db.execute("SELECT id,report_digest FROM guardian_records WHERE capture_digest=?",(capture_digest,)).fetchone()
                if existing:
                    return {"state":"ALREADY_RECORDED","id":existing["id"]}
            report=self.analyze_fn(json.loads(_dump(capture)),now=cutoff)
            _validate_report(report,capture_digest,cutoff)
            report_digest=_digest(report)
            annotation=self._context(report)
            capture_codec,capture_blob,capture_size=_pack(capture,MAX_CAPTURE)
            report_codec,report_blob,report_size=_pack(report,MAX_REPORT)
            annotation_codec,annotation_blob,annotation_size=_pack(annotation,MAX_ANNOTATION)
            annotation_digest=_digest(annotation)
            stored=len(capture_blob)+len(report_blob)+len(annotation_blob)+1024
            with _writer(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                # Every blocking capture/model/hook precedes this lease check.
                now=self.clock()
                if not self._owned(db,now) or self._stop.is_set():
                    raise ShadowError("LEASE_LOST")
                existing=db.execute("SELECT id FROM guardian_records WHERE capture_digest=?",(capture_digest,)).fetchone()
                if existing:
                    return {"state":"ALREADY_RECORDED","id":existing["id"]}
                count,used=int(_get(db,"records","0")),int(_get(db,"stored_bytes","0"))
                if count>=self.config.max_records or used+stored>self.config.max_corpus_bytes:
                    _set(db,"last_error","RETENTION_FULL")
                    return {"state":"RETENTION_FULL"}
                previous=db.execute("SELECT record_digest FROM guardian_records ORDER BY sequence DESC LIMIT 1").fetchone()
                row={"id":capture_digest,"cutoff":cutoff,"committed":now,"capture_digest":capture_digest,
                     "report_digest":report_digest,"annotation_digest":annotation_digest,"previous_digest":previous[0] if previous else "0"*64}
                digest=_record_hash(row)
                db.execute("""INSERT INTO guardian_records(id,cutoff,committed,capture_digest,report_digest,annotation_digest,previous_digest,record_digest,
                  capture_codec,capture,capture_bytes,report_codec,report,report_bytes,annotation_codec,annotation,annotation_bytes,stored_bytes)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  tuple(row[key] for key in ("id","cutoff","committed","capture_digest","report_digest","annotation_digest","previous_digest"))+
                  (digest,capture_codec,capture_blob,capture_size,report_codec,report_blob,report_size,annotation_codec,annotation_blob,annotation_size,stored))
                _set(db,"records",count+1)
                _set(db,"stored_bytes",used+stored)
                _set(db,"last_success_at",cutoff)
                _set(db,"last_error","")
                _set(db,"heartbeat_at",now)
                _set(db,"lease_until",now+self.config.lease_seconds)
            return {"state":"RECORDED","id":capture_digest,"report_digest":report_digest}
        except (Exception,) as error:
            code=error.code if isinstance(error,ShadowError) and error.code in _ERROR_CODES else "JOURNAL_STORAGE_FULL" if isinstance(error,sqlite3.Error) and getattr(error,"sqlite_errorcode",None)==sqlite3.SQLITE_FULL else "GUARDIAN_OBSERVATION_FAILED"
            if self._initialized:
                self._error(code)
            return {"state":code}
        finally:
            self._tick_lock.release()

    def _run(self):
        next_tick=0.
        try:
            while not self._stop.is_set():
                try:
                    if self.monotonic()>=next_tick:
                        self.tick()
                        next_tick=self.monotonic()+self.config.evaluation_interval
                    elif self._initialized:
                        self._lease()
                except Exception:
                    self._error("GUARDIAN_OBSERVER_LOOP_FAILED")
                self._stop.wait(self.config.heartbeat_seconds)
        finally:
            self._release()
            with _OWNERS_LOCK:
                key=str(self.path.resolve())
                if _OWNERS.get(key) is self:
                    del _OWNERS[key]

    def start(self):
        if not self.config.enabled:
            return False
        key=str(self.path.resolve())
        with _OWNERS_LOCK:
            if self._thread is not None and self._thread.is_alive():
                return True
            if key in _OWNERS and _OWNERS[key] is not self:
                return False
            self.initialize()
            _OWNERS[key]=self
            self._stop.clear()
            self._thread=threading.Thread(target=self._run,name="guardian-shadow-level-0",daemon=True)
            self._thread.start()
        return True

    def _release(self):
        if not self._initialized:
            return
        try:
            with _writer(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                if _get(db,"lease_owner")==self._owner:
                    _set(db,"lease_until",0)
                    _set(db,"lease_owner","")
        except (sqlite3.Error,OSError,ValueError):
            pass

    def stop(self,timeout=2.):
        self._stop.set()
        thread=self._thread
        if thread is not None and thread.ident is not None and thread is not threading.current_thread():
            thread.join(max(0,min(3.,timeout)))
        # A blocked tick must not surrender its lease while still running. Its
        # eventual append rechecks stop/owner; a successor may recover at expiry.
        if (thread is None or not thread.is_alive()) and not self._tick_lock.locked():
            self._release()
        return (thread is None or not thread.is_alive()) and not self._tick_lock.locked()

    def replay(self,record_id):
        return replay_guardian(self.data_dir,record_id,analyze_fn=self.analyze_fn)


def _read_record(db,record_id):
    if not isinstance(record_id,str) or not _HASH.fullmatch(record_id):
        raise ShadowError("INVALID_RECORD_ID")
    row=db.execute("SELECT * FROM guardian_records WHERE id=? LIMIT 1",(record_id,)).fetchone()
    if row is None:
        raise ShadowError("RECORD_UNAVAILABLE")
    row=dict(row)
    capture=_unpack(row["capture_codec"],row["capture"],MAX_CAPTURE)
    report=_unpack(row["report_codec"],row["report"],MAX_REPORT)
    annotation=_unpack(row["annotation_codec"],row["annotation"],MAX_ANNOTATION)
    if any(_digest(value)!=row[key] for value,key in ((capture,"capture_digest"),(report,"report_digest"),(annotation,"annotation_digest"))) or _record_hash(row)!=row["record_digest"]:
        raise ShadowError("FROZEN_DIGEST_MISMATCH")
    previous=db.execute("SELECT record_digest FROM guardian_records WHERE sequence<? ORDER BY sequence DESC LIMIT 1",(row["sequence"],)).fetchone()
    if row["previous_digest"]!=(previous[0] if previous else "0"*64):
        raise ShadowError("JOURNAL_CHAIN_MISMATCH")
    cutoff=_validate_capture(capture,row["committed"])
    _validate_report(report,row["capture_digest"],cutoff)
    if _annotation(annotation,report,row["committed"])!=annotation:
        raise ShadowError("INVALID_FROZEN_ANNOTATION")
    return row,capture,report,annotation


def replay_guardian(data_dir,record_id,*,analyze_fn=None):
    """RO deterministic replay. Context is verified as frozen, never regenerated."""
    try:
        with _read_only(Path(data_dir)/DB_NAME) as db:
            row,capture,recorded,annotation=_read_record(db,record_id)
        cutoff=_validate_capture(capture,row["committed"])
        recalculated=(analyze_fn or build_intelligence)(capture,now=cutoff)
        _validate_report(recalculated,row["capture_digest"],cutoff)
        matched=_digest(recalculated)==row["report_digest"]
        return {"state":"MATCH" if matched else "MISMATCH","id":row["id"],"causal_cutoff_valid":True,
                "capture_digest":row["capture_digest"],"report_digest":row["report_digest"],
                "annotation_digest":row["annotation_digest"],"annotation_replayed":False,
                "annotation_state":"FROZEN_NOT_REGENERATED","execution_enabled":False}
    except Exception as error:
        return {"state":"UNAVAILABLE","reason":error.code if isinstance(error,ShadowError) else "REPLAY_UNAVAILABLE",
                "causal_cutoff_valid":False,"execution_enabled":False}


def guardian_shadow_snapshot(data_dir,*,now=None):
    """Bounded RO metadata + last frozen assessment; absent DB creates nothing."""
    instant=time.time() if now is None else _time(now)
    if instant is None:
        raise ValueError("Invalid Guardian snapshot time")
    result={"schema":1,"engine":"GUARDIAN_INTELLIGENCE","mode":"SHADOW","autonomy_level":0,
            "execution_enabled":False,"can_veto":False,"controls_enabled":False,"reservations_enabled":False,"promotion_allowed":False,
            "state":"NOT_STARTED","at":_iso(instant),"updated_at":None,
            "freshness":{"state":"UNAVAILABLE","age_seconds":None},"report":None,"ai":None,"journal":[],
            "health":{"last_error":None,"errors":None,"heartbeat_at":None,"lease_state":"UNAVAILABLE","lease_expires_at":None,
                      "records":None,"compressed_corpus_bytes":None,"max_records":None,"max_corpus_bytes":None,
                      "capacity_state":"UNKNOWN","capacity_fraction":None,"ai_calls_today":None,"ai_daily_limit":0}}
    path=Path(data_dir)/DB_NAME
    if not path.is_file():
        return result
    try:
        with _read_only(path) as db:
            cohort=json.loads(_get(db,"cohort"))
            config=GuardianShadowConfig(**cohort["settings"])
            if cohort.get("protocol")!=PROTOCOL:
                raise ShadowError("UNSUPPORTED_GUARDIAN_PROTOCOL")
            count,stored=int(_get(db,"records")),int(_get(db,"stored_bytes"))
            if not 0<=count<=config.max_records or not 0<=stored<=config.max_corpus_bytes:
                raise ShadowError("INVALID_RETENTION_COUNTER")
            fraction=max(count/config.max_records,stored/config.max_corpus_bytes)
            raw_error=_get(db,"last_error") or None
            last_error=raw_error if raw_error in _ERROR_CODES else "GUARDIAN_OBSERVATION_FAILED" if raw_error else None
            day=datetime.fromtimestamp(instant,UTC).date().isoformat()
            until=float(_get(db,"lease_until","0"))
            owner=_get(db,"lease_owner")
            heartbeat = _get(db,"heartbeat_at")
            result["health"]={"last_error":last_error,"errors":int(_get(db,"errors","0")),"heartbeat_at":_iso(float(heartbeat)) if heartbeat else None,
                              "lease_state":"ACTIVE" if owner and until>instant else "EXPIRED" if owner else "RELEASED" if _get(db,"heartbeat_at") else "NONE",
                              "lease_expires_at":_iso(until),"records":count,"compressed_corpus_bytes":stored,
                              "max_records":config.max_records,"max_corpus_bytes":config.max_corpus_bytes,
                              "capacity_state":"FULL" if fraction>=1 or last_error in {"RETENTION_FULL","JOURNAL_STORAGE_FULL"} else "WARNING" if fraction>=.8 else "AVAILABLE",
                              "capacity_fraction":fraction,
                              "ai_calls_today":None if _get(db,"ai_health_pending")=="1" else int(_get(db,"ai_used_today","0")) if _get(db,"ai_health_day")==day else int(_get(db,"context_calls","0")) if _get(db,"context_day")==day else 0,
                              "ai_daily_limit":int(_get(db,"ai_daily_cap")) if _get(db,"ai_health_day")==day else config.context_max_calls_per_day}
            if (not 0<=result["health"]["ai_daily_limit"]<=2 or result["health"]["ai_calls_today"] is not None
                    and not 0<=result["health"]["ai_calls_today"]<=2):
                raise ShadowError("INVALID_AI_HEALTH_COUNTER")
            latest=db.execute("SELECT id FROM guardian_records ORDER BY sequence DESC LIMIT 1").fetchone()
            if latest:
                row,capture,report,annotation=_read_record(db,latest[0])
                age=instant-row["cutoff"]
                fresh=0<=age<=90
                result.update(state=report["state"] if fresh and last_error is None else "STALE" if age>90 else "DEGRADED",
                              updated_at=_iso(row["cutoff"]),freshness={"state":"FRESH" if fresh else "STALE" if age>90 else "UNAVAILABLE","age_seconds":age if age>=0 else None},
                              report=report,ai=annotation)
                result["journal"]=[{"id":item["id"],"cutoff_at":_iso(item["cutoff"]),"committed_at":_iso(item["committed"]),
                                    "report_digest":item["report_digest"]} for item in db.execute("SELECT id,cutoff,committed,report_digest FROM guardian_records ORDER BY sequence DESC LIMIT 3")]
            else:
                result["state"]="DEGRADED" if last_error else "INITIALIZED"
        if len(_dump(result).encode())>MAX_SNAPSHOT:
            result.update(ai=None,journal=[])
        if len(_dump(result).encode())>MAX_SNAPSHOT:
            result["report"]=None
            result["health"]["last_error"]="ASSESSMENT_EXCEEDS_SUMMARY_BUDGET"
            result["state"]="DEGRADED"
        if len(_dump(result).encode())>MAX_SNAPSHOT:
            raise ShadowError("SNAPSHOT_SIZE_LIMIT")
        return result
    except Exception:
        result.update(state="DEGRADED",report=None,ai=None,journal=[],updated_at=None,
                      freshness={"state":"UNAVAILABLE","age_seconds":None},
                      health={**{key:None for key in result["health"]},"last_error":"GUARDIAN_JOURNAL_UNAVAILABLE", "lease_state":"UNAVAILABLE", "capacity_state":"UNKNOWN","ai_daily_limit":0})
        return result
