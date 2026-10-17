"""Event-driven public-market observation in the existing supervised process.

Market Pulse has no broker, authenticated Binance client, order endpoint or
promotion path. Its SHADOW wallet is hypothetical and financially separate.
The initial deterministic rules are preregistered hypotheses, not fitted or
statistically optimal weights. AI can interpret a bounded event; numeric gates
and protective simulation never depend on an AI/network review completing.
"""
from __future__ import annotations

import hashlib
import json
import math
import queue
import sqlite3
import statistics
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .market_pulse_news import clean_text, iso, normalize_event, timestamp, validate_review
from .market_pulse_transport import BinancePublicStream, PublicRateLimitError, rest_recovery
from .market_pulse_universe import DEFAULT_SYMBOLS, UNIVERSE_METADATA


RULE_VERSION = "pulse-v1"
OWNER_PAUSE = "owner pause\n"
DB_NAME = "market-pulse.db"
_OWNERS: dict[str, object] = {}
_OWNERS_LOCK = threading.Lock()
_EVIDENCE_KEYS = ("market", "event_id", "rule_version", "published_at", "received_at", "decision_at",
                  "btc_change_1m_pct", "btc_change_5m_pct", "estimated_cost_bps", "confirmations",
                  "selection_rank", "selection_pool", "selection_rule")
_EVENT_KEYS = ("id", "published_at", "received_at", "symbol", "source", "url", "title", "impact",
               "credibility", "kind", "decision", "reason", "market_reaction_pct")
LIMITATIONS = ["Initial score weights and thresholds are unvalidated hypotheses.",
               "SHADOW fills are conservative simulations, never exchange executions.",
               "Insufficient independent forward/OOS evidence; no strategy promotion.",
               "Decision replay uses frozen contemporaneous evidence; no retrospective news reconstruction.",
               "Top-five depth is partial liquidity; gaps and execution impact may exceed assumptions."]


@dataclass(frozen=True)
class PulseConfig:
    enabled: bool = True
    mode: str = "SHADOW"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    windows_seconds: tuple[int, int] = (60, 300)
    initial_capital: float = 1000.0
    risk_per_trade: float = 0.0025
    max_exposure_fraction: float = 0.15
    max_position_fraction: float = 0.05
    max_positions: int = 3
    fee_bps: float = 10.0
    slippage_bps: float = 10.0
    evaluation_interval: float = 5.0
    stale_seconds: float = 15.0
    news_interval: float = 60.0

    def __post_init__(self) -> None:
        if self.mode != "SHADOW":
            raise ValueError("Market Pulse execution is locked to SHADOW; promotion requires separate authorization")
        if (not self.symbols or len(set(self.symbols)) != len(self.symbols) or len(self.symbols) > 10
                or any(symbol not in DEFAULT_SYMBOLS for symbol in self.symbols)):
            raise ValueError("Market Pulse requires the reviewed bounded universe")
        if len(self.windows_seconds) != 2 or not 15 <= self.windows_seconds[0] < self.windows_seconds[1] <= 600:
            raise ValueError("Market Pulse windows out of bounded range")
        numeric = (self.initial_capital, self.risk_per_trade, self.max_exposure_fraction,
                   self.max_position_fraction, self.fee_bps, self.slippage_bps,
                   self.evaluation_interval, self.stale_seconds, self.news_interval)
        if any(isinstance(value, bool) or not math.isfinite(value) for value in numeric):
            raise ValueError("Market Pulse requires finite numeric settings")
        if not (0 < self.initial_capital <= 1_000_000 and 0 < self.risk_per_trade <= 0.0025
                and 0 < self.max_exposure_fraction <= 0.15 and 0 < self.max_position_fraction <= 0.05
                and 1 <= self.max_positions <= 3 and 0 <= self.fee_bps <= 100
                and 0 <= self.slippage_bps <= 100 and 1 <= self.evaluation_interval <= 60
                and 1 <= self.stale_seconds <= 30 and self.news_interval >= 60):
            raise ValueError("Market Pulse conservative limits exceeded")


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _number(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean market number rejected")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Invalid market number")
    return result


@contextmanager
def _connect(path: Path, readonly: bool = False):
    if readonly:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        db.execute("PRAGMA query_only=ON")
    else:
        db = sqlite3.connect(path, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def _meta(db: sqlite3.Connection, key: str, fallback: str = "") -> str:
    row = db.execute("SELECT value FROM pulse_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else fallback


def _set(db: sqlite3.Connection, key: str, value: object) -> None:
    db.execute("INSERT INTO pulse_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, str(value)))


class MarketWindow:
    """At most 601 one-second buckets, regardless of trade arrival rate."""
    def __init__(self, symbol: str, config: PulseConfig) -> None:
        self.symbol, self.config = symbol, config
        self.buckets: deque[list[float]] = deque(maxlen=601)
        self.last_id: int | None = None
        self.last_trade_at: float | None = None
        self.last_received_at: float | None = None
        self.gap_at: float | None = None
        self.book_at: float | None = None
        self.bid = self.ask = self.depth_quote = self.imbalance = None
        self.bid_quote = self.ask_quote = None
        self.depths: deque[tuple[float, float]] = deque(maxlen=61)
        self.latency_ms = None

    def trade(self, data: dict, received_at: float) -> bool:
        trade_id = int(data["a"])
        price, quantity = _number(data["p"], positive=True), _number(data["q"], positive=True)
        traded_at = _number(data["T"], positive=True) / 1000
        emitted_at = _number(data.get("E", data["T"]), positive=True) / 1000
        if traded_at > received_at + 5 or emitted_at > received_at + 5:
            raise ValueError("Future market event rejected")
        if received_at - traded_at > self.config.stale_seconds:
            self.gap_at = received_at
            return False
        if self.last_id is not None and trade_id <= self.last_id:
            return False
        if self.last_trade_at is not None and traded_at < self.last_trade_at:
            self.gap_at = received_at
            return False
        if self.last_id is not None and trade_id != self.last_id + 1:
            self.gap_at = received_at
        self.last_id, self.last_trade_at, self.last_received_at = trade_id, traded_at, received_at
        self.latency_ms = max(0, (received_at - emitted_at) * 1000)
        second, quote = int(traded_at), price * quantity
        if self.buckets and self.buckets[-1][0] == second:
            bucket = self.buckets[-1]
            bucket[2], bucket[3] = price, bucket[3] + quote
            bucket[4], bucket[5] = min(bucket[4], price), max(bucket[5], price)
        else:
            self.buckets.append([second, price, price, quote, price, price])
        while self.buckets and self.buckets[0][0] < second - self.config.windows_seconds[1] - 2:
            self.buckets.popleft()
        return True

    def trade_fresh(self, now: float) -> bool:
        # Public exchange timestamps may lead the Windows clock by the same
        # bounded five seconds accepted at ingestion. Local receipt still has
        # to precede the decision and expire independently of provider time.
        return bool(self.last_trade_at is not None and self.last_received_at is not None
                    and -5 <= now - self.last_trade_at <= self.config.stale_seconds
                    and 0 <= now - self.last_received_at <= self.config.stale_seconds)

    def depth(self, data: dict, received_at: float) -> None:
        bids, asks = data.get("bids"), data.get("asks")
        if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
            raise ValueError("Incomplete depth snapshot")
        bids = [(_number(row[0], positive=True), _number(row[1], positive=True)) for row in bids[:5]]
        asks = [(_number(row[0], positive=True), _number(row[1], positive=True)) for row in asks[:5]]
        if any(bids[i][0] <= bids[i + 1][0] for i in range(len(bids) - 1)) or any(asks[i][0] >= asks[i + 1][0] for i in range(len(asks) - 1)):
            raise ValueError("Unsorted depth snapshot")
        if bids[0][0] >= asks[0][0]:
            raise ValueError("Crossed depth snapshot")
        bid_value, ask_value = sum(p * q for p, q in bids), sum(p * q for p, q in asks)
        # Far ladder levels do not support a fill near the displayed best price.
        # Only liquidity inside the already modeled slippage band contributes
        # to hypothetical taker capacity; the full top-five totals stay diagnostic.
        band = self.config.slippage_bps / 10000
        self.bid_quote = sum(p * q for p, q in bids if p >= bids[0][0] * (1 - band))
        self.ask_quote = sum(p * q for p, q in asks if p <= asks[0][0] * (1 + band))
        self.bid, self.ask, self.depth_quote = bids[0][0], asks[0][0], bid_value + ask_value
        self.imbalance = (bid_value - ask_value) / self.depth_quote
        self.book_at = received_at
        if not self.depths or int(self.depths[-1][0]) != int(received_at):
            self.depths.append((received_at, self.depth_quote))

    def metrics(self, now: float) -> dict:
        short, long = self.config.windows_seconds
        rows = [b for b in self.buckets if now - long - 2 <= b[0] <= now]
        price = rows[-1][2] if rows else None
        fresh = bool(rows and self.trade_fresh(now) and self.book_at is not None
                     and 0 <= now - rows[-1][0] <= self.config.stale_seconds
                     and 0 <= now - self.book_at <= self.config.stale_seconds)
        # Liquid initial assets need broad time coverage and no unresolved trade-ID gap.
        complete = bool(rows and rows[0][0] <= now - long and len(rows) >= long * 0.80
                        and (self.gap_at is None or now - self.gap_at > long))
        short_rows = [b for b in rows if b[0] > now - short]
        baseline = [b for b in rows if now - long <= b[0] <= now - short]
        def change(seconds: int) -> float | None:
            past = [b for b in rows if b[0] <= now - seconds]
            return (price / past[-1][2] - 1) * 100 if past and price else None
        changes = [math.log(rows[i][2] / rows[i - 1][2]) for i in range(1, len(rows))]
        deviation = statistics.pstdev(changes) if len(changes) >= 20 else None
        change_short = change(short)
        relative = (sum(b[3] for b in short_rows) / short) / (sum(b[3] for b in baseline) / (long - short)) if baseline and sum(b[3] for b in baseline) > 0 else None
        anomaly = (math.log1p(change_short / 100) - statistics.mean(changes) * short) / (deviation * math.sqrt(short)) if change_short is not None and deviation and deviation > 1e-10 else None
        half_rows = [b for b in rows if b[0] <= now - short / 2]
        half_change = (price / half_rows[-1][2] - 1) * 100 if half_rows and price else None
        depth_old = [d for d in self.depths if d[0] <= now - 30]
        return {"symbol": self.symbol, "price": price, "change_1m_pct": change_short,
                "change_5m_pct": change(long), "relative_volume": relative, "anomaly_z": anomaly,
                "momentum": change_short, "acceleration": half_change * 2 - change_short if half_change is not None and change_short is not None else None,
                "volatility_pct": deviation * math.sqrt(short) * 100 if deviation is not None else None,
                "spread_bps": (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 10000 if self.bid and self.ask else None,
                "depth_quote": self.depth_quote, "imbalance": self.imbalance,
                "liquidity_change_pct": (self.depth_quote / depth_old[-1][1] - 1) * 100 if depth_old and self.depth_quote else None,
                "fresh": fresh, "complete": complete, "at": iso(self.last_received_at)}


def score_opportunity(market: dict, btc: dict | None, event: dict | None, *, cost_bps: float = 40) -> dict:
    """Pure, reproducible rules. Confidence describes evidence, not probability."""
    favorable, risks, score, confirmations = [], [], 0, 0
    change = market.get("change_1m_pct")
    long_change = market.get("change_5m_pct")
    volume = market.get("relative_volume")
    anomaly = market.get("anomaly_z")
    if change is not None and long_change is not None and 0.15 <= change <= 1.0 and 0 < long_change <= 2:
        score += 25
        confirmations += 1
        favorable.append("Positive short-window momentum")
    if volume is not None and volume >= 1.8:
        score += 25
        confirmations += 1
        favorable.append("Relative traded volume at least 1.8x baseline")
    if anomaly is not None and 2 <= anomaly <= 8:
        score += 15
        favorable.append("Statistically unusual short-window move")
    if btc and btc.get("fresh") and btc.get("complete") and btc.get("change_1m_pct") is not None and btc["change_1m_pct"] > -0.25:
        score += 10
        favorable.append("BTC context does not contradict momentum")
    else:
        risks.append("BTC context missing, incomplete or adverse")
    if market.get("spread_bps") is not None and market["spread_bps"] <= 10 and (market.get("depth_quote") or 0) >= 10_000:
        score += 10
        confirmations += 1
        favorable.append("Spread and partial depth meet initial liquidity gates")
    else:
        risks.append("Insufficient liquidity or excessive spread")
    if event and event.get("_admissible") is True:
        if event.get("impact") == "positive" and event.get("credibility", 0) >= 0.8 and event.get("kind") != "rumor":
            score += 15
            favorable.append("Recent credible event agrees with market direction")
        elif event.get("impact") == "negative":
            risks.append("Negative event conflicts with long entry")
        elif event.get("kind") == "rumor":
            risks.append("Rumor does not provide independent confirmation")
    if not market.get("fresh"):
        risks.append("Stale or absent trade/depth data")
    if not market.get("complete"):
        risks.append("Incomplete short-window baseline or unresolved data gap")
    if change is not None and (change > 1.0 or (long_change is not None and long_change > 2)):
        risks.append("Move already extended; avoid chasing")
    if (market.get("volatility_pct") or 0) > 1.5:
        risks.append("Excessive realized short-window volatility")
    if market.get("liquidity_change_pct") is not None and market["liquidity_change_pct"] < -40:
        risks.append("Abrupt partial-depth liquidity deterioration")
    if change is not None and change * 100 <= cost_bps + (market.get("spread_bps") or 0):
        risks.append("Observed move does not cover round-trip cost hypothesis")
    action = "REJECT" if risks else "BUY" if score >= 65 and confirmations >= 3 else "WAIT FOR CONFIRMATION" if score >= 40 else "HOLD"
    return {"score": min(100, score), "confidence": min(0.95, confirmations / 4), "action": action,
            "favorable": favorable[:6], "risks": risks[:6],
            "reason": "; ".join(risks[:2])[:240] if risks else "Independent price, participation and liquidity gates passed" if action == "BUY" else "Waiting for independent quantitative confirmation",
            "confirmations": confirmations}


class MarketPulseService:
    def __init__(self, data_dir: Path | str, *, config: PulseConfig | None = None,
                 reviewer: Callable | None = None, clock: Callable = time.time,
                 stream_factory: Callable | None = None, rest_fetcher: Callable | None = None,
                 news_fetcher: Callable | None = None, kill_switch_path: Path | str | None = None) -> None:
        self.config, self.clock = config or PulseConfig(), clock
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / DB_NAME
        self.kill_switch_path = Path(kill_switch_path) if kill_switch_path else self.data_dir / "MARKET_PULSE_PAUSED"
        self.stream_factory, self.rest_fetcher = stream_factory or BinancePublicStream, rest_fetcher or rest_recovery
        self.news_fetcher, self.reviewer = news_fetcher, reviewer
        self.windows = {symbol: MarketWindow(symbol, self.config) for symbol in self.config.symbols}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = self._aux_thread = self._stream = None
        self._review_queue: queue.Queue = queue.Queue(maxsize=8)
        self._queued_reviews: set[str] = set()
        self._positions: dict[str, dict] = {}
        self._started = self.clock()
        self._last_tick = self._last_rest = self._last_journal = 0.0
        self._rest_index = 0
        self._lease_valid_until = 0.0
        self._owner = uuid.uuid4().hex
        self._health = {"latency_ms": None, "reconnects": 0, "errors": 0, "last_error": None,
                        "ws_messages": 0, "rest_calls": 0, "news_calls": 0, "ai_reviews": 0,
                        "ai_errors": 0, "buffer_seconds": self.config.windows_seconds[1] + 2,
                        "uptime_seconds": 0}
        self._sources = {"binance_ws": {"state": "CONNECTING", "last_update": None},
                         "binance_rest": {"state": "STANDBY", "last_update": None},
                         "news": {"state": "READY" if news_fetcher else "DISABLED", "last_update": None}}

    def _initialize(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with _connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pulse_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pulse_events(id TEXT PRIMARY KEY,published REAL NOT NULL,received REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pulse_decisions(id TEXT PRIMARY KEY,at REAL NOT NULL,symbol TEXT NOT NULL,action TEXT NOT NULL,score REAL NOT NULL,data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS pulse_decisions_at ON pulse_decisions(at);
                CREATE INDEX IF NOT EXISTS pulse_opportunities_at ON pulse_decisions(at) WHERE score>=40;
                CREATE TABLE IF NOT EXISTS pulse_positions(symbol TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pulse_trades(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,opened REAL NOT NULL,closed REAL NOT NULL,net_pnl REAL NOT NULL,costs REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pulse_observations(at INTEGER NOT NULL,symbol TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(at,symbol));
            """)
            if not _meta(db, "initial_capital"):
                for key, value in {"initial_capital": self.config.initial_capital, "cash": self.config.initial_capital,
                                   "peak_equity": self.config.initial_capital, "drawdown_pct": 0,
                                   "started_at": self.clock(), "costs": 0, "paused": "", "entries": 0,
                                   "decisions": 0, "opportunities": 0, "accepted": 0, "rejected": 0,
                                   "events_analyzed": 0, "closed_trades": 0, "wins": 0,
                                   "gross_profit": 0, "gross_loss": 0}.items():
                    _set(db, key, value)
            elif float(_meta(db, "initial_capital")) != self.config.initial_capital:
                raise ValueError("Existing Shadow capital cannot be silently reset by configuration")
            saved = _meta(db, "hypotheses")
            current = _json(asdict(self.config))
            if saved and saved != current:
                prior, following = json.loads(saved), json.loads(current)
                previous_symbols = prior.pop("symbols", [])
                next_symbols = following.pop("symbols", [])
                previous_poll, next_poll = prior.pop("news_interval", 300), following.pop("news_interval", 60)
                # Only the reviewed additive observation/polling expansion is compatible.
                # Financial hypotheses and held assets must remain identical/present.
                if (prior != following or not set(previous_symbols).issubset(next_symbols)
                        or tuple(next_symbols) != DEFAULT_SYMBOLS
                        or previous_poll not in (60, 300) or next_poll != 60):
                    raise ValueError("Shadow hypotheses changed; a separately reviewed cohort is required")
                history = json.loads(_meta(db, "hypothesis_history", "[]"))
                history.append({"at": iso(self.clock()), "previous": json.loads(saved),
                                "next": json.loads(current), "reason": "Reviewed prospective universe expansion; prior evidence retained"})
                _set(db, "hypothesis_history", _json(history))
            _set(db, "hypotheses", current)
            self._positions = {row["symbol"]: json.loads(row["data"]) for row in db.execute("SELECT symbol,data FROM pulse_positions")}

    def start(self) -> bool:
        if not self.config.enabled:
            return False
        key = str(self.path.resolve())
        with _OWNERS_LOCK:
            if self._thread is not None and self._thread.is_alive():
                return True
            if self._aux_thread is not None and self._aux_thread.is_alive():
                return False
            if key in _OWNERS and _OWNERS[key] is not self:
                return False
            self._initialize()
            _OWNERS[key] = self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="market-pulse-shadow", daemon=True)
        self._thread.start()
        if self.news_fetcher or self.reviewer:
            self._aux_thread = threading.Thread(target=self._auxiliary, name="market-pulse-events", daemon=True)
            self._aux_thread.start()
        return True

    def stop(self, timeout: float = 3) -> None:
        self._stop.set()
        stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        for thread in (self._thread, self._aux_thread):
            if thread and thread.ident is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0, min(3, timeout)))
        with _OWNERS_LOCK:
            key = str(self.path.resolve())
            if (_OWNERS.get(key) is self and not (self._thread and self._thread.is_alive())
                    and not (self._aux_thread and self._aux_thread.is_alive())):
                _OWNERS.pop(key, None)

    def _error(self, code: str) -> None:
        with self._lock:
            self._health["errors"] += 1
            self._health["last_error"] = code

    def _lease(self, now: float) -> bool:
        with self._lock, _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            owner, until = _meta(db, "lease_owner"), float(_meta(db, "lease_until", "0"))
            if owner and owner != self._owner and until > now:
                self._lease_valid_until = 0.0
                return False
            if owner != self._owner:
                # A waiting successor must read the ledger as it exists at
                # takeover, rather than reuse its pre-lease startup cache.
                self._positions = {row["symbol"]: json.loads(row["data"])
                                   for row in db.execute("SELECT symbol,data FROM pulse_positions")}
                for window in self.windows.values():
                    window.gap_at = now
            _set(db, "lease_owner", self._owner)
            _set(db, "lease_until", now + 20)
        self._lease_valid_until = now + 20
        return True

    def _run(self) -> None:
        backoff, next_connect, lease_at, connected_at = 1.0, 0.0, 0.0, 0.0
        try:
            while not self._stop.is_set():
                now = self.clock()
                if now >= lease_at:
                    if not self._lease(now):
                        self._error("ANOTHER_PULSE_OBSERVER_OWNS_LEASE")
                        self._stop.wait(2)
                        continue
                    lease_at = now + 5
                if self._stream is None and now >= next_connect:
                    try:
                        self._stream = self.stream_factory(self.config.symbols)
                        self._sources["binance_ws"]["state"] = "CONNECTED"
                        connected_at = self.clock()
                    except Exception:
                        self._error("PUBLIC_WS_CONNECT_FAILED")
                        self._sources["binance_ws"]["state"] = "DISCONNECTED"
                        next_connect, backoff = now + backoff, min(60, backoff * 2)
                if self._stream is not None:
                    try:
                        message = self._stream.receive()
                        if message is not None:
                            if self.clock() >= self._lease_valid_until and not self._lease(self.clock()):
                                raise RuntimeError("Observer lease expired during public read")
                            self.ingest_message(message, received_at=self.clock())
                        last = timestamp(self._sources["binance_ws"]["last_update"])
                        if self.clock() - (last or connected_at) > self.config.stale_seconds * 2:
                            raise ConnectionError("PUBLIC_WS_STALE")
                        if last is not None and self.clock() - connected_at > 60:
                            backoff = 1
                    except Exception:
                        try:
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None
                        self._health["reconnects"] += 1
                        self._sources["binance_ws"]["state"] = "DISCONNECTED"
                        self._error("PUBLIC_WS_INTERRUPTED")
                        for window in self.windows.values():
                            window.gap_at = self.clock()
                        next_connect, backoff = self.clock() + backoff, min(60, backoff * 2)
                else:
                    if now - self._last_rest >= 30:
                        self.recover_market(now)
                    self._stop.wait(0.25)
                if self.clock() - self._last_tick >= self.config.evaluation_interval:
                    if not self._lease(self.clock()):
                        lease_at = 0
                        continue
                    lease_at = self.clock() + 5
                    self.evaluate(self.clock(), project=False)
        except Exception:
            # A third-observer failure never escapes into the operating engine.
            self._error("PULSE_OBSERVER_STOPPED")
        finally:
            self._stop.set()
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            try:
                with _connect(self.path) as db:
                    if _meta(db, "lease_owner") == self._owner:
                        _set(db, "lease_until", 0)
            except Exception:
                pass

    def ingest_message(self, message: dict, *, received_at: float | None = None) -> bool:
        now = self.clock() if received_at is None else received_at
        data = message.get("data", message)
        if not isinstance(data, dict):
            raise ValueError("Invalid market message")
        stream = message.get("stream", "")
        symbol = data.get("s") or str(stream).split("@", 1)[0].upper()
        if symbol not in self.windows:
            return False
        with self._lock:
            window = self.windows[symbol]
            if data.get("e") == "aggTrade" or ("a" in data and "p" in data and "T" in data):
                accepted = window.trade(data, now)
                if accepted:
                    self._protective_check(symbol, _number(data["p"], positive=True), now)
            elif "bids" in data and "asks" in data:
                window.depth(data, now)
                accepted = True
            else:
                return False
            if accepted:
                self._health["ws_messages"] += 1
                self._health["latency_ms"] = window.latency_ms
                self._sources["binance_ws"]["last_update"] = iso(now)
            return accepted

    def recover_market(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        self._last_rest = now
        self._sources["binance_rest"]["state"] = "RECOVERY"
        # One rotating asset per pass bounds public REST waits to one pair of
        # three-second requests, independent of the observation-universe size.
        symbols = tuple(self.windows)
        symbol = symbols[self._rest_index % len(symbols)]
        self._rest_index = (self._rest_index + 1) % len(symbols)
        for symbol in (symbol,):
            window = self.windows[symbol]
            if self._stop.is_set():
                break
            try:
                self._health["rest_calls"] += 2
                trades, depth = self.rest_fetcher(symbol, window.last_id)
                if self._stop.is_set():
                    return
                if not self._lease(self.clock()):
                    self._sources["binance_rest"]["state"] = "ERROR"
                    self._error("PULSE_LEASE_LOST_DURING_RECOVERY")
                    return
                with self._lock:
                    for trade in trades[:1000]:
                        trade = dict(trade, s=symbol, e="aggTrade")
                        # REST page has trade time but no exchange emission time.
                        if window.trade(trade, self.clock()):
                            self._protective_check(symbol, _number(trade["p"], positive=True), self.clock())
                    window.depth(depth, self.clock())
                    if trades and self.clock() - _number(trades[-1].get("T", 0)) / 1000 > self.config.stale_seconds:
                        # A bounded recovery page may be too old to catch a busy
                        # market up. Restart at recent public trades, mark the
                        # gap and warm up; never pretend that page was complete.
                        window.last_id, window.gap_at = None, self.clock()
                self._sources["binance_rest"]["last_update"] = iso(self.clock())
            except PublicRateLimitError as exc:
                self._last_rest = self.clock() + exc.retry_after
                self._sources["binance_rest"]["state"] = "ERROR"
                self._error("PUBLIC_REST_RATE_LIMIT")
                break
            except Exception:
                self._sources["binance_rest"]["state"] = "ERROR"
                self._error("PUBLIC_REST_RECOVERY_FAILED")

    def ingest_event(self, raw: dict, *, received_at: float | None = None) -> int:
        now = self.clock() if received_at is None else received_at
        rows = normalize_event(raw, now, self.config.symbols)
        inserted = 0
        with self._lock, _connect(self.path) as db:
            for event in rows:
                result = db.execute("INSERT OR IGNORE INTO pulse_events(id,published,received,data) VALUES(?,?,?,?)",
                                    (event["id"], timestamp(event["published_at"]), now, _json(event)))
                if not result.rowcount:
                    continue
                inserted += 1
                _set(db, "events_analyzed", int(_meta(db, "events_analyzed", "0")) + 1)
                window = self.windows.get(event["symbol"])
                if window is None:  # Macro context is retained, never an asset order signal.
                    continue
                market = window.metrics(now)
                # Promise/ambiguity prefilter precedes AI. Never review every tick/headline.
                if (self.reviewer and event.get("_admissible") is True and market["fresh"]
                        and (abs(market.get("change_1m_pct") or 0) >= 0.1 or (market.get("relative_volume") or 0) >= 1.5)):
                    self._queue_review(event, market)
        return inserted

    def _queue_review(self, event: dict, market: dict) -> None:
        if event["id"] in self._queued_reviews:
            return
        priority = (score_opportunity(market, self.windows["BTCUSDT"].metrics(self.clock())
                    if "BTCUSDT" in self.windows else None, event)["score"],
                    event.get("credibility", 0), timestamp(event.get("published_at")) or 0)
        item = {"event": dict(event), "metrics": dict(market), "priority": priority}
        try:
            self._review_queue.put_nowait(item)
            self._queued_reviews.add(event["id"])
        except queue.Full:
            # Replace only a lower-priority pending event; active reviews are separate.
            with self._review_queue.mutex:
                pending = self._review_queue.queue
                if not pending:
                    return
                lowest = min(pending, key=lambda value: value.get("priority", (0, 0, 0)))
                if priority > lowest.get("priority", (0, 0, 0)):
                    pending.remove(lowest)
                    self._queued_reviews.discard(lowest["event"]["id"])
                    pending.append(item)
                    self._queued_reviews.add(event["id"])

    def _auxiliary(self) -> None:
        next_news = 0.0
        while not self._stop.is_set():
            now = self.clock()
            if self.news_fetcher and now >= next_news:
                next_news = now + self.config.news_interval
                try:
                    self._health["news_calls"] += 1
                    rows = self.news_fetcher()
                    if not isinstance(rows, list):
                        raise ValueError("Invalid news feed")
                    for event in rows[:24]:
                        if isinstance(event, dict):
                            self.ingest_event(event)
                    self._sources["news"] = {"state": "READY", "last_update": iso(self.clock())}
                except Exception:
                    self._sources["news"]["state"] = "ERROR"
                    self._error("NEWS_PROVIDER_UNAVAILABLE")
            try:
                with self._review_queue.mutex:
                    pending = self._review_queue.queue
                    if pending:
                        best = max(pending, key=lambda value: value.get("priority", (0, 0, 0)))
                        pending.remove(best)
                        pending.appendleft(best)
                item = self._review_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.reviewer:
                try:
                    if ((timestamp(item["event"].get("published_at")) or 0) < self.clock() - 1800
                            or item["event"].get("_admissible") is not True):
                        self._review_queue.task_done()
                        self._queued_reviews.discard(item["event"]["id"])
                        continue
                    # Dedicated event worker: review cannot delay market stops.
                    review = self.reviewer(item)
                    if review is not None:  # Independent budget/rate gate may decline a call.
                        self._health["ai_reviews"] += 1
                        review = validate_review(review)
                        with self._lock, _connect(self.path) as db:
                            row = db.execute("SELECT data FROM pulse_events WHERE id=?", (item["event"]["id"],)).fetchone()
                            if row:
                                event = json.loads(row[0])
                                event["impact"] = review["impact"]
                                event["reason"] = review["reason"]
                                event["_reviewed_at"] = iso(self.clock())
                                event["_review_confidence"] = review["confidence"]
                                # The model cannot upgrade provenance/credibility or a rumor.
                                db.execute("UPDATE pulse_events SET data=? WHERE id=?", (_json(event), event["id"]))
                except Exception:
                    self._health["ai_errors"] += 1
                    self._error("EVENT_REVIEW_INVALID_OR_UNAVAILABLE")
            self._review_queue.task_done()
            self._queued_reviews.discard(item["event"]["id"])

    def _latest_event(self, db: sqlite3.Connection, symbol: str, now: float) -> dict | None:
        for row in db.execute("SELECT data FROM pulse_events WHERE published>=? AND received<=? ORDER BY received DESC LIMIT 24", (now - 1800, now)):
            event = json.loads(row[0])
            if (event.get("_admissible") is True and event["symbol"] == symbol
                    and (timestamp(event["published_at"]) or now + 1) <= now
                    and (timestamp(event.get("_reviewed_at")) or 0) <= now):
                return event
        return None

    def _protective_check(self, symbol: str, price: float, now: float) -> None:
        position = self._positions.get(symbol)
        if not position:
            return
        window = self.windows[symbol]
        # No fictional fill during stale prices or absent book.
        if window.book_at is None or now - window.book_at > self.config.stale_seconds:
            return
        pending = position.get("_pending_exit")
        if pending:
            self._close_position(symbol, min(price, window.bid, pending["reference_price"]), now, pending["reason"])
        elif price <= position["stop"]:
            self._close_position(symbol, min(price, window.bid, position["stop"]), now, "STOP")
        elif price >= position["target"] and window.bid >= position["target"]:
            self._close_position(symbol, position["target"], now, "TARGET")

    def _close_position(self, symbol: str, price: float, now: float, reason: str) -> None:
        position = self._positions.get(symbol)
        if not position:
            return
        quantity = position["quantity"]
        bid_quote = self.windows[symbol].bid_quote or 0
        if quantity * price > bid_quote * 0.005:
            # Preserve the position/protective intent until current bid-side
            # liquidity can support a conservative simulated full exit. A
            # large ask book does not prove executable sell-side liquidity.
            if self._health["last_error"] != "SHADOW_EXIT_LIQUIDITY_UNCERTAIN":
                self._error("SHADOW_EXIT_LIQUIDITY_UNCERTAIN")
            if "_pending_exit" not in position:
                position["_pending_exit"] = {"reason": reason, "reference_price": price,
                                             "triggered_at": iso(now)}
                with _connect(self.path) as db:
                    db.execute("UPDATE pulse_positions SET data=? WHERE symbol=?", (_json(position), symbol))
            return
        fill = price * (1 - self.config.slippage_bps / 10000)
        proceeds = quantity * fill
        fee = proceeds * self.config.fee_bps / 10000
        net = proceeds - fee - position["entry_value"] - position["entry_fee"]
        costs = position["entry_fee"] + fee + position["entry_slippage"] + quantity * (price - fill)
        trade_id = hashlib.sha256((position["id"] + "|close").encode()).hexdigest()
        decision = {"id": trade_id, "at": iso(now), "symbol": symbol, "score": 0, "confidence": 1.0,
                    "action": "SELL", "favorable": [], "risks": [], "reason": "Protective hypothetical " + reason,
                    "evidence": {"market": self.windows[symbol].metrics(now), "event_id": None, "rule_version": RULE_VERSION,
                                 "published_at": None, "received_at": None, "decision_at": iso(now), "btc_change_1m_pct": None,
                                 "btc_change_5m_pct": None, "estimated_cost_bps": 2 * (self.config.fee_bps + self.config.slippage_bps), "confirmations": 0,
                                 "_protective": {"stop": position["stop"], "target": position["target"], "exit_reference": price, "reason": reason}}}
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM pulse_positions WHERE symbol=?", (symbol,)).fetchone():
                self._positions.pop(symbol, None)
                return
            trade = dict(position, closed_at=iso(now), exit_price=fill, net_pnl=net, costs=costs,
                         exit_reason=reason, environment="SHADOW")
            db.execute("INSERT INTO pulse_trades VALUES(?,?,?,?,?,?,?)",
                       (trade_id, symbol, timestamp(position["opened_at"]), now, net, costs, _json(trade)))
            db.execute("INSERT INTO pulse_decisions VALUES(?,?,?,?,?,?)", (trade_id, now, symbol, "SELL", 0, _json(decision)))
            db.execute("DELETE FROM pulse_positions WHERE symbol=?", (symbol,))
            _set(db, "cash", float(_meta(db, "cash")) + proceeds - fee)
            _set(db, "costs", float(_meta(db, "costs", "0")) + fee + quantity * (price - fill))
            for key in ("decisions", "closed_trades"):
                _set(db, key, int(_meta(db, key, "0")) + 1)
            if net > 0:
                _set(db, "wins", int(_meta(db, "wins", "0")) + 1)
                _set(db, "gross_profit", float(_meta(db, "gross_profit", "0")) + net)
            elif net < 0:
                _set(db, "gross_loss", float(_meta(db, "gross_loss", "0")) - net)
        self._positions.pop(symbol, None)

    def evaluate(self, now: float | None = None, *, project: bool = True) -> dict | None:
        now = self.clock() if now is None else now
        with self._lock:
            self._last_tick = now
            markets = [window.metrics(now) for window in self.windows.values()]
            btc = next((market for market in markets if market["symbol"] == "BTCUSDT"), None)
            for symbol, position in list(self._positions.items()):
                window = self.windows[symbol]
                if window.trade_fresh(now):
                    self._protective_check(symbol, window.buckets[-1][2], now)
            with _connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                paused = bool(_meta(db, "paused") or self.kill_switch_path.exists())
                cash = float(_meta(db, "cash"))
                exposure = 0.0
                mark_complete = True
                for symbol, position in self._positions.items():
                    market = next(m for m in markets if m["symbol"] == symbol)
                    if market["fresh"] and market["price"]:
                        position["mark_price"] = market["price"]
                        db.execute("UPDATE pulse_positions SET data=? WHERE symbol=?", (_json(position), symbol))
                    else:
                        mark_complete = False
                    exposure += position["quantity"] * position["mark_price"]
                exit_cost_rate = (self.config.fee_bps + self.config.slippage_bps) / 10000
                equity = cash + exposure * (1 - exit_cost_rate)
                peak = max(equity, float(_meta(db, "peak_equity")))
                _set(db, "peak_equity", peak)
                _set(db, "drawdown_pct", max(float(_meta(db, "drawdown_pct", "0")), (1 - equity / peak) * 100))
                costs = 2 * (self.config.fee_bps + self.config.slippage_bps)
                candidates = [(market, self._latest_event(db, market["symbol"], now)) for market in markets]
                ranked = [(market, event, score_opportunity(market, btc, event, cost_bps=costs)) for market, event in candidates]
                ranked.sort(key=lambda item: (-item[2]["score"], -item[2]["confidence"], -(item[0].get("depth_quote") or 0), item[0]["symbol"]))
                for rank, (market, event, result) in enumerate(ranked, 1):
                    symbol = market["symbol"]
                    if symbol in self._positions:
                        result.update(action="HOLD", reason="Existing hypothetical position remains under protective monitoring")
                    elif result["action"] == "BUY" and paused:
                        result.update(action="REJECT", reason="Market Pulse new entries paused")
                        result["risks"].append("Independent owner/safety pause")
                    elif result["action"] == "BUY" and (not mark_complete or len(self._positions) >= self.config.max_positions):
                        result.update(action="REJECT", reason="Shadow portfolio capacity or mark freshness gate")
                    bucket = int(now // (30 if result["action"] in {"BUY", "REJECT", "WAIT FOR CONFIRMATION"} else 60))
                    identity = hashlib.sha256(f"{RULE_VERSION}|{symbol}|{bucket}|{result['action']}|{event['id'] if event else ''}".encode()).hexdigest()
                    evidence = {"market": market, "event_id": event["id"] if event else None,
                                "rule_version": RULE_VERSION, "published_at": event["published_at"] if event else None,
                                "received_at": event["received_at"] if event else None, "decision_at": iso(now),
                                "btc_change_1m_pct": btc.get("change_1m_pct") if btc else None,
                                "btc_change_5m_pct": btc.get("change_5m_pct") if btc else None,
                                "estimated_cost_bps": costs + (market["spread_bps"] or 0), "confirmations": result.pop("confirmations"),
                                "_event": event, "_btc": btc, "_cost_bps": costs}
                    evidence.update(selection_rank=rank, selection_pool=len(ranked), selection_rule="QUANTITATIVE_SCORE_THEN_CONFIDENCE_LIQUIDITY")
                    decision = dict(result, id=identity, at=iso(now), symbol=symbol, evidence=evidence)
                    if db.execute("SELECT 1 FROM pulse_decisions WHERE id=?", (identity,)).fetchone():
                        continue
                    if result["action"] == "BUY":
                        window = self.windows[symbol]
                        price = window.ask * (1 + self.config.slippage_bps / 10000)
                        stop_fraction = min(0.02, max(0.006, (market["volatility_pct"] or 0) / 100 * 2))
                        loss_per_unit = price * (stop_fraction + 2 * (self.config.fee_bps + self.config.slippage_bps) / 10000 + (market["spread_bps"] or 0) / 10000)
                        available = max(0, equity * self.config.max_exposure_fraction - exposure)
                        quantity = min(equity * self.config.risk_per_trade / loss_per_unit,
                                       equity * self.config.max_position_fraction / price,
                                       available / price, cash / (price * (1 + self.config.fee_bps / 10000)))
                        # Partial book depth cannot imply infinite affordable execution.
                        quantity = min(quantity, (window.ask_quote or 0) * 0.005 / price)
                        if quantity * price < 5 or stop_fraction * 2 * 10000 <= evidence["estimated_cost_bps"]:
                            decision.update(action="REJECT", reason="Hypothetical size or net reward fails conservative cost/risk gates")
                            decision["risks"].append("Cost-aware sizing blocked")
                        else:
                            entry_value = quantity * price
                            entry_fee = entry_value * self.config.fee_bps / 10000
                            position = {"id": identity, "symbol": symbol, "quantity": quantity, "entry_price": price,
                                        "mark_price": market["price"], "stop": price * (1 - stop_fraction),
                                        "target": price * (1 + 2 * stop_fraction), "opened_at": iso(now),
                                        "entry_value": entry_value, "entry_fee": entry_fee,
                                        "entry_slippage": quantity * (price - window.ask), "environment": "SHADOW",
                                        "estimated_risk": quantity * loss_per_unit}
                            db.execute("INSERT INTO pulse_positions VALUES(?,?)", (symbol, _json(position)))
                            cash -= entry_value + entry_fee
                            exposure += entry_value
                            _set(db, "cash", cash)
                            _set(db, "costs", float(_meta(db, "costs", "0")) + entry_fee + position["entry_slippage"])
                            _set(db, "entries", int(_meta(db, "entries", "0")) + 1)
                            self._positions[symbol] = position
                    db.execute("INSERT INTO pulse_decisions VALUES(?,?,?,?,?,?)",
                               (identity, now, symbol, decision["action"], decision["score"], _json(decision)))
                    _set(db, "decisions", int(_meta(db, "decisions", "0")) + 1)
                    for key, increment in (("opportunities", decision["score"] >= 65),
                                           ("accepted", decision["action"] == "BUY"),
                                           ("rejected", decision["action"] == "REJECT")):
                        if increment:
                            _set(db, key, int(_meta(db, key, "0")) + 1)
                    if event:
                        event["decision"], event["reason"] = decision["action"], decision["reason"]
                        event["market_reaction_pct"] = market["change_1m_pct"]
                        db.execute("UPDATE pulse_events SET data=? WHERE id=?", (_json(event), event["id"]))
                    # One-minute checkpoints allow conservative benchmarks/restart context.
                    db.execute("INSERT OR IGNORE INTO pulse_observations VALUES(?,?,?)", (int(now // 60) * 60, symbol, _json(market)))
                self._health["uptime_seconds"] = max(0, now - self._started)
                if self.reviewer and callable(getattr(self.reviewer, "health", None)):
                    try:
                        ai_health = self.reviewer.health()
                        for source, target in (("daily_cap", "ai_daily_cap"), ("used_today", "ai_used_today"),
                                               ("min_interval_seconds", "ai_min_interval_seconds"),
                                               ("max_output_tokens", "ai_max_output_tokens"),
                                               ("max_input_bytes", "ai_max_input_bytes")):
                            value = ai_health.get(source)
                            if type(value) in {float, int} and math.isfinite(value) and value >= 0:
                                self._health[target] = value
                    except Exception:
                        self._health["last_error"] = "EVENT_REVIEW_BUDGET_UNAVAILABLE"
                equity_after = cash + sum(p["quantity"] * p["mark_price"] for p in self._positions.values()) * (1 - exit_cost_rate)
                _set(db, "drawdown_pct", max(float(_meta(db, "drawdown_pct", "0")), (1 - equity_after / peak) * 100))
                _set(db, "updated_at", now)
                _set(db, "market", _json(markets))
                _set(db, "health", _json(self._health))
                _set(db, "sources", _json(self._sources))
                if callable(getattr(self.news_fetcher, "health", None)):
                    _set(db, "news_providers", _json(self.news_fetcher.health()))
            return self.snapshot(now=now) if project else None

    def snapshot(self, *, now: float | None = None) -> dict:
        return market_pulse_snapshot(self.data_dir, now=self.clock() if now is None else now,
                                     kill_switch_path=self.kill_switch_path)


def _empty_snapshot(now: float) -> dict:
    return {"schema": 1, "engine": "AI_MARKET_PULSE", "mode": "SHADOW", "state": "NOT_STARTED",
            "at": iso(now), "updated_at": None, "freshness": {"state": "UNAVAILABLE", "age_seconds": None},
            "execution_enabled": False,
            "sources": {"binance_ws": {"state": "DISCONNECTED", "last_update": None},
                        "binance_rest": {"state": "STANDBY", "last_update": None},
                        "news": {"state": "DISABLED", "last_update": None}},
            "stats": {"events_analyzed": 0, "relevant_news": 0, "opportunities": 0, "accepted": 0,
                      "rejected": 0, "decisions": 0},
            "market": [], "events": [], "opportunities": [], "decisions": [], "positions": [],
            "performance": {"initial_capital": None, "cash": None, "equity": None, "net_pnl": None,
                            "return_pct": None, "drawdown_pct": None, "closed_trades": 0,
                            "win_rate_pct": None, "profit_factor": None, "exposure": None,
                            "observation_days": 0, "costs": None, "environment": "SHADOW",
                            "data_quality": "UNAVAILABLE", "benchmark_cash_return_pct": 0,
                            "benchmark_buy_hold": None},
            "health": {"latency_ms": None, "reconnects": 0, "errors": 0, "last_error": None,
                       "ws_messages": 0, "rest_calls": 0, "news_calls": 0, "ai_reviews": 0,
                       "ai_errors": 0, "buffer_seconds": 302, "uptime_seconds": 0},
            "research": {"state": "FORWARD_ONLY", "hypothesis_version": RULE_VERSION,
                         "promotion_allowed": False, "limitations": list(LIMITATIONS)}}


def market_pulse_snapshot(data_dir: Path | str, *, now: float | None = None,
                          kill_switch_path: Path | str | None = None) -> dict:
    """Read-only bounded projection; absent database never creates a wallet."""
    now = time.time() if now is None else now
    path = Path(data_dir) / DB_NAME
    result = _empty_snapshot(now)
    if not path.is_file():
        return result
    marker = Path(kill_switch_path) if kill_switch_path else Path(data_dir) / "MARKET_PULSE_PAUSED"
    try:
        with _connect(path, readonly=True) as db:
            # Consistent read across all journal/ledger tables.
            db.execute("BEGIN")
            updated = float(_meta(db, "updated_at", "0")) or None
            age = max(0, now - updated) if updated else None
            stale = age is None or age > 30
            result.update(updated_at=iso(updated), freshness={"state": "UNAVAILABLE" if age is None else "STALE" if stale else "FRESH", "age_seconds": age})
            result["market"] = json.loads(_meta(db, "market", "[]"))[:10]
            result["news_providers"] = json.loads(_meta(db, "news_providers", "[]"))[:5]
            result["universe"] = dict(UNIVERSE_METADATA)
            for market in result["market"]:
                market["fresh"] = bool(market["fresh"] and not stale and (timestamp(market["at"]) or 0) >= now - 30)
            result["sources"] = json.loads(_meta(db, "sources", _json(result["sources"])))
            if stale:
                result["sources"]["binance_ws"]["state"] = "STALE"
            result["health"] = json.loads(_meta(db, "health", _json(result["health"])))
            paused = bool(_meta(db, "paused") or marker.exists())
            result["state"] = "PAUSED" if paused else "DEGRADED" if stale else "WARMING_UP" if not result["market"] or not all(m["complete"] for m in result["market"]) else "SHADOW" if all(m["fresh"] for m in result["market"]) else "DEGRADED"
            event_count = int(_meta(db, "events_analyzed", "0"))
            result["stats"] = {key: int(_meta(db, key, "0")) for key in ("decisions", "opportunities", "accepted", "rejected")}
            event_rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM pulse_events ORDER BY received DESC LIMIT 10")]
            result["events"] = [{key: event.get(key) for key in _EVENT_KEYS} for event in event_rows]
            result["stats"].update(events_analyzed=event_count, relevant_news=sum(e["credibility"] >= 0.8 and e["decision"] != "REJECT" for e in event_rows))
            for row in db.execute("SELECT data FROM pulse_decisions ORDER BY at DESC,rowid DESC LIMIT 12"):
                decision = json.loads(row[0])
                decision["evidence"] = {key: decision["evidence"][key] for key in _EVIDENCE_KEYS
                                        if key in decision["evidence"]}
                result["decisions"].append(decision)
            for row in db.execute("SELECT data FROM pulse_decisions WHERE score>=40 ORDER BY at DESC,rowid DESC LIMIT 10"):
                decision = json.loads(row[0])
                decision.pop("evidence", None)
                result["opportunities"].append(decision)
            hypotheses = json.loads(_meta(db, "hypotheses", "{}"))
            exit_cost_rate = (hypotheses.get("fee_bps", 10) + hypotheses.get("slippage_bps", 10)) / 10000
            cash = float(_meta(db, "cash"))
            exposure = 0.0
            held_marks_current = True
            for row in db.execute("SELECT data FROM pulse_positions ORDER BY symbol LIMIT 3"):
                position = json.loads(row[0])
                exposure += position["quantity"] * position["mark_price"]
                projected = {key: position[key] for key in ("symbol", "quantity", "entry_price", "mark_price", "stop", "target", "opened_at", "environment")}
                projected["unrealized_pnl"] = position["quantity"] * position["mark_price"] * (1 - exit_cost_rate) - position["entry_value"] - position["entry_fee"]
                mark_current = any(m["symbol"] == position["symbol"] and m["fresh"] for m in result["market"])
                if not mark_current:
                    held_marks_current = False
                    projected["mark_price"] = projected["unrealized_pnl"] = None
                result["positions"].append(projected)
            equity, initial = cash + exposure * (1 - exit_cost_rate), float(_meta(db, "initial_capital"))
            closed, wins, gross_profit, gross_loss = (float(_meta(db, key, "0")) for key in ("closed_trades", "wins", "gross_profit", "gross_loss"))
            quality = "COMPLETE" if result["market"] and all(m["complete"] and m["fresh"] for m in result["market"]) else "PARTIAL"
            result["performance"] = {"initial_capital": initial, "cash": cash, "equity": equity,
                                     "net_pnl": equity - initial, "return_pct": (equity / initial - 1) * 100,
                                     "drawdown_pct": float(_meta(db, "drawdown_pct", "0")), "closed_trades": int(closed),
                                     "win_rate_pct": wins / closed * 100 if closed else None,
                                     "profit_factor": gross_profit / gross_loss if gross_loss else None,
                                     "exposure": exposure, "observation_days": max(0, now - float(_meta(db, "started_at"))) / 86400,
                                     "costs": float(_meta(db, "costs", "0")), "environment": "SHADOW", "data_quality": quality,
                                     "benchmark_cash_return_pct": 0, "benchmark_buy_hold": None}
            # Identical registration/current observation period, costs on both ends.
            benchmarks = {}
            for market in result["market"]:
                row = db.execute("SELECT data FROM pulse_observations WHERE symbol=? ORDER BY at LIMIT 1", (market["symbol"],)).fetchone()
                if row and market["fresh"]:
                    first = json.loads(row[0])
                    if first.get("price") and market.get("price"):
                        rate = (hypotheses.get("fee_bps", 10) + hypotheses.get("slippage_bps", 10)) / 10000
                        benchmarks[market["symbol"]] = ((market["price"] * (1 - rate)) / (first["price"] * (1 + rate)) - 1) * 100
            result["performance"]["benchmark_buy_hold"] = benchmarks or None
            if not held_marks_current:
                # Historical ledger marks remain recoverable, but cannot be
                # presented as a current liquidation value or current P&L.
                for key in ("equity", "net_pnl", "return_pct", "exposure"):
                    result["performance"][key] = None
                result["performance"]["data_quality"] = "PARTIAL"
        _json(result)  # Reject non-finite/corrupt persisted numbers rather than inventing state.
    except (sqlite3.Error, ValueError, KeyError, TypeError, OverflowError):
        result = _empty_snapshot(now)
        result["state"] = "DEGRADED"
        result["health"].update(errors=1, last_error="SHADOW_LEDGER_UNAVAILABLE")
    return result


def market_pulse_control(data_dir: Path | str, action: str, *, kill_switch_path: Path | str | None = None) -> dict:
    """Only independent new-entry pause/resume; no mode or risk promotion."""
    path = Path(data_dir) / DB_NAME
    marker = Path(kill_switch_path) if kill_switch_path else Path(data_dir) / "MARKET_PULSE_PAUSED"
    if action not in {"pause", "resume"}:
        raise ValueError("Only Market Pulse pause/resume is supported")
    if not path.is_file():
        raise ValueError("Market Pulse Shadow observer has not initialized")
    with _connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        paused = _meta(db, "paused")
        if marker.exists() and not marker.is_file():
            raise ValueError("Market Pulse pause marker is not an ordinary file")
        marker_text = marker.read_text(encoding="utf-8") if marker.is_file() else None
        if action == "pause":
            if paused not in {"", OWNER_PAUSE} or marker_text not in {None, OWNER_PAUSE}:
                raise ValueError("Existing Market Pulse safety pause must not be overwritten")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(OWNER_PAUSE, encoding="utf-8")
            _set(db, "paused", OWNER_PAUSE)
        else:
            if paused not in {"", OWNER_PAUSE} or marker_text not in {None, OWNER_PAUSE}:
                raise ValueError("Resume only applies to the exact owner's Market Pulse pause")
            # Either half can survive an interrupted two-resource transaction.
            # Absence is safe, but any non-owner safety marker remains blocked.
            if marker_text is not None:
                marker.unlink()
            _set(db, "paused", "")
    return {"ok": True, "engine": "AI_MARKET_PULSE", "mode": "SHADOW", "paused": action == "pause",
            "execution_enabled": False, "protective_monitoring": True}


def replay_decisions(data_dir: Path | str, *, limit: int = 1000) -> dict:
    """Deterministic audit of frozen evidence, with no network/future events.

    This reproduces opportunity gates, not historical account execution. Portfolio
    and protective overrides stay explicit; no return, OOS success or promotion
    claim is inferred from replaying observations already inspected.
    """
    checked, mismatches, invalid_time = 0, 0, 0
    with _connect(Path(data_dir) / DB_NAME, readonly=True) as db:
        for row in db.execute("SELECT data FROM pulse_decisions ORDER BY at LIMIT ?", (max(1, min(10_000, limit)),)):
            decision = json.loads(row[0])
            evidence = decision["evidence"]
            at = timestamp(evidence["decision_at"])
            times = [timestamp(evidence.get(key)) for key in ("published_at", "received_at")]
            market_at = timestamp(evidence["market"].get("at"))
            if at is None or any(value is not None and value > at for value in times + [market_at]):
                invalid_time += 1
                continue
            if evidence["rule_version"] != RULE_VERSION:
                mismatches += 1
                continue
            if decision["action"] != "SELL":
                reproduced = score_opportunity(evidence["market"], evidence.get("_btc"), evidence.get("_event"), cost_bps=evidence.get("_cost_bps", 40))
                if reproduced["score"] != decision["score"]:
                    mismatches += 1
            checked += 1
    return {"state": "FROZEN_EVIDENCE_REPLAY", "checked": checked, "mismatches": mismatches,
            "invalid_timestamps": invalid_time, "promotion_allowed": False,
            "limitations": ["Replays recorded deterministic scores; portfolio overrides and simulated fills are separate.",
                            "Not an independent out-of-sample test or retrospective news backtest."]}
