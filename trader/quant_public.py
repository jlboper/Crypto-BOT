"""Anonymous bounded reference data for the SHADOW laboratory, never execution.

The fixed GET allowlist deliberately excludes account/order endpoints, credentials,
redirects, environment overrides and arbitrary URLs. Public production prices are
reference observations; they are never represented as Testnet/Demo fills.
"""
from __future__ import annotations

import json
import math
import statistics
import threading
import time
from collections import deque
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
_HOSTS = {"SPOT_REFERENCE": "https://data-api.binance.vision",
          "FUTURES_REFERENCE": "https://fapi.binance.com"}
_PATHS = {"SPOT_REFERENCE": {"/api/v3/depth"},
          "FUTURES_REFERENCE": {"/fapi/v1/depth", "/fapi/v1/premiumIndex",
                                "/fapi/v1/fundingRate", "/fapi/v1/fundingInfo"}}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "REFERENCE_REDIRECT_REFUSED", headers, None)


_open = build_opener(ProxyHandler({}), _NoRedirect()).open


class ReferenceRateLimit(RuntimeError):
    def __init__(self, retry_after=60):
        try:
            seconds = float(retry_after)
        except (ValueError, TypeError):
            seconds = 60
        self.retry_after = max(60, min(3600, seconds if math.isfinite(seconds) else 60))
        super().__init__("REFERENCE_RATE_LIMIT")


def reference_json(venue, path, params):
    if venue not in _HOSTS or path not in _PATHS[venue]:
        raise ValueError("Reference endpoint is not allowlisted")
    if not isinstance(params, dict) or set(params) - {"symbol", "limit", "startTime", "endTime"}:
        raise ValueError("Reference parameters are not allowlisted")
    if path.endswith("fundingInfo"):
        if params:
            raise ValueError("Funding information requires no parameters")
    elif params.get("symbol") not in SYMBOLS:
        raise ValueError("Reference symbol is not reviewed")
    if path.endswith("depth") and params != {"symbol": params.get("symbol"), "limit": 5}:
        raise ValueError("Reference depth must be bounded to five levels")
    if path.endswith("premiumIndex") and set(params) != {"symbol"}:
        raise ValueError("Reference premium requires one symbol")
    if path.endswith("fundingRate") and params.get("limit") != 32:
        raise ValueError("Funding reference page must be bounded")
    url = _HOSTS[venue] + path + ("?" + urlencode(params) if params else "")
    request = Request(url, method="GET", headers={"User-Agent": "CryptoAITrader-QuantShadow/1.0",
                                                  "Accept": "application/json"})
    try:
        with _open(request, timeout=2) as response:
            if urlsplit(response.url).netloc != urlsplit(_HOSTS[venue]).netloc:
                raise ValueError("Unexpected reference redirect")
            raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("Reference response too large")
            return json.loads(raw)
    except HTTPError as exc:
        if exc.code in (418, 429):
            raise ReferenceRateLimit(exc.headers.get("Retry-After", "60")) from None
        raise


def _finite(value, positive=False):
    if isinstance(value, bool):
        raise ValueError("Boolean reference number")
    number = float(value)
    if not math.isfinite(number) or positive and number <= 0:
        raise ValueError("Invalid reference number")
    return number


def _book(raw, symbol, received_at, *, futures=False, slippage=.001):
    if not isinstance(raw, dict):
        raise ValueError("Invalid reference book")
    ladders = []
    for name in ("bids", "asks"):
        rows = raw.get(name)
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
            raise ValueError("Incomplete reference depth")
        ladders.append([(_finite(row[0], True), _finite(row[1], True)) for row in rows])
    bids, asks = ladders
    if (bids[0][0] >= asks[0][0] or any(a[0] <= b[0] for a, b in zip(bids, bids[1:]))
            or any(a[0] >= b[0] for a, b in zip(asks, asks[1:]))):
        raise ValueError("Crossed or unordered reference book")
    at = _finite(raw.get("E", raw.get("T", received_at * 1000)), True) / 1000 if futures else received_at
    if not -5 <= received_at - at <= 90:
        raise ValueError("Reference book is stale or future dated")
    return {"symbol": symbol, "bid": bids[0][0], "ask": asks[0][0], "at": at,
            "received_at": received_at,
            "bid_depth_usdt": sum(p*q for p, q in bids if p >= bids[0][0]*(1-slippage)),
            "ask_depth_usdt": sum(p*q for p, q in asks if p <= asks[0][0]*(1+slippage)),
            "depth_scope": "TOP_FIVE_WITHIN_SLIPPAGE_BAND"}


class QuantPublicFeed:
    """At most 15 public GETs/minute; one bounded pass per 60 seconds.

    Funding history is cached five minutes; adjusted interval information fifteen
    minutes. Missing symbols/errors remain missing. No synthetic quotes or rates
    replace failures. Relative interval is inferred only from consistent observed
    funding events or the explicit official adjustment feed, never a fixed 8h.
    """
    def __init__(self, *, request=None, clock=time.time, symbols=SYMBOLS):
        if tuple(symbols) != SYMBOLS:
            raise ValueError("Quant reference universe is fixed")
        self.request, self.clock = request or reference_json, clock
        self._calls = deque(maxlen=15)
        self._histories, self._history_at, self._intervals = {}, {}, {}
        self._info_at = None
        self._last_pass = None
        self._stop = threading.Event()
        self._backoff_until = 0.
        self._consecutive_errors = 0
        self._last = {"markets": [], "sources": [], "at": None}
        self.health = {"calls": 0, "errors": 0, "last_error": None,
                       "backoff_until": None, "max_calls_per_minute": 15}

    def _get(self, venue, path, params):
        if self._stop.is_set():
            raise RuntimeError("REFERENCE_STOPPED")
        now = self.clock()
        if now < self._backoff_until:
            raise ReferenceRateLimit(self._backoff_until-now)
        while self._calls and self._calls[0] <= now-60:
            self._calls.popleft()
        if len(self._calls) >= 15:
            raise ReferenceRateLimit(60)
        self._calls.append(now)
        self.health["calls"] += 1
        try:
            return self.request(venue, path, params)
        except ReferenceRateLimit as exc:
            self._backoff_until = self.clock()+exc.retry_after
            self.health["backoff_until"] = self._backoff_until
            raise

    def close(self):
        self._stop.set()

    def resume(self):
        self._stop.clear()

    def __call__(self, now=None):
        now = self.clock() if now is None else now
        if self._last_pass is not None and now < self._last_pass+60:
            return self._last
        self._last_pass = now
        markets, sources = [], []
        if now < self._backoff_until:
            return {"markets": [], "sources": [{"id": "BINANCE_PUBLIC", "state": "BACKOFF",
                    "at": now, "error": "REFERENCE_RATE_LIMIT"}], "at": now, "health": dict(self.health)}
        if self._info_at is None or now-self._info_at >= 900:
            try:
                rows = self._get("FUTURES_REFERENCE", "/fapi/v1/fundingInfo", {})
                if not isinstance(rows, list) or len(rows) > 2000:
                    raise ValueError("Invalid funding information")
                self._intervals = {row["symbol"]: _finite(row["fundingIntervalHours"], True)*3600
                                   for row in rows if isinstance(row, dict) and row.get("symbol") in SYMBOLS}
                self._info_at = self.clock()
            except Exception as exc:
                sources.append({"id": "FUNDING_INTERVAL", "state": "ERROR", "at": self.clock(),
                                "error": type(exc).__name__})
        for symbol in SYMBOLS:
            item = {"symbol": symbol, "spot": None, "futures": None, "history": []}
            try:
                raw = self._get("SPOT_REFERENCE", "/api/v3/depth", {"symbol": symbol, "limit": 5})
                item["spot"] = _book(raw, symbol, self.clock())
            except Exception as exc:
                sources.append({"id": "SPOT_"+symbol, "state": "ERROR", "at": self.clock(), "error": type(exc).__name__})
            try:
                raw = self._get("FUTURES_REFERENCE", "/fapi/v1/depth", {"symbol": symbol, "limit": 5})
                book = _book(raw, symbol, self.clock(), futures=True)
                mark = self._get("FUTURES_REFERENCE", "/fapi/v1/premiumIndex", {"symbol": symbol})
                if not isinstance(mark, dict) or mark.get("symbol") != symbol:
                    raise ValueError("Wrong premium symbol")
                mark_at, received = _finite(mark["time"], True)/1000, self.clock()
                if not -5 <= received-mark_at <= 90:
                    raise ValueError("Stale premium observation")
                book.update(mark_price=_finite(mark["markPrice"], True),
                            observed_funding_rate=_finite(mark["lastFundingRate"]),
                            next_funding_at=_finite(mark["nextFundingTime"], True)/1000,
                            at=min(book["at"], mark_at), received_at=received)
                item["futures"] = book
            except Exception as exc:
                sources.append({"id": "FUTURES_"+symbol, "state": "ERROR", "at": self.clock(), "error": type(exc).__name__})
            if symbol not in self._history_at or now-self._history_at[symbol] >= 300:
                try:
                    rows = self._get("FUTURES_REFERENCE", "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 32})
                    received = self.clock()
                    if not isinstance(rows, list) or len(rows) > 32:
                        raise ValueError("Invalid funding page")
                    history = [{"at": _finite(row["fundingTime"], True)/1000, "received_at": received,
                                "rate": _finite(row["fundingRate"]), "mark_price": _finite(row["markPrice"], True)}
                               for row in rows if isinstance(row, dict) and row.get("symbol") == symbol]
                    if len(history) != len(rows) or any(row["at"] > received for row in history):
                        raise ValueError("Future or mismatched funding event")
                    self._histories[symbol] = sorted(history, key=lambda row: row["at"])
                    self._history_at[symbol] = received
                except Exception as exc:
                    sources.append({"id": "FUNDING_"+symbol, "state": "ERROR", "at": self.clock(), "error": type(exc).__name__})
            item["history"] = self._histories.get(symbol, [])
            if item["futures"]:
                intervals = [b["at"]-a["at"] for a,b in zip(item["history"], item["history"][1:])][-6:]
                stable = bool(len(intervals) >= 3 and min(intervals) >= 3600 and max(intervals) <= 86400
                              and max(intervals)-min(intervals) <= 2)
                item["futures"]["funding_interval_seconds"] = self._intervals.get(symbol,
                    statistics.median(intervals) if stable else None)
                item["futures"]["funding_history_received_at"] = self._history_at.get(symbol)
            markets.append(item)
            if item["spot"] and item["futures"]:
                sources.append({"id": symbol, "state": "READY", "at": self.clock(), "error": None})
        failed = any(row["state"] == "ERROR" for row in sources)
        self._consecutive_errors = self._consecutive_errors+1 if failed else 0
        if failed:
            self.health["errors"] += 1
            self.health["last_error"] = "REFERENCE_PARTIAL"
            if self._consecutive_errors >= 3:
                self._backoff_until = max(self._backoff_until, self.clock()+min(900, 60*2**min(4,self._consecutive_errors-3)))
                self.health["backoff_until"] = self._backoff_until
        else:
            self.health["last_error"] = None
            self.health["backoff_until"] = None
        self._last = {"markets": markets, "sources": sources[:12], "at": self.clock(), "health": dict(self.health)}
        return self._last
