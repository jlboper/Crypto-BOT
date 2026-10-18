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
_PATHS = {"SPOT_REFERENCE": {"/api/v3/depth", "/api/v3/klines"},
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
    if not isinstance(params, dict) or set(params) - {"symbol", "limit", "startTime", "endTime", "interval"}:
        raise ValueError("Reference parameters are not allowlisted")
    if path.endswith("fundingInfo"):
        if params:
            raise ValueError("Funding information requires no parameters")
    elif path.endswith("premiumIndex"):
        if params:
            raise ValueError("Reference premium requires the fixed public batch")
    elif params.get("symbol") not in SYMBOLS:
        raise ValueError("Reference symbol is not reviewed")
    if path.endswith("depth") and params != {"symbol": params.get("symbol"), "limit": 5}:
        raise ValueError("Reference depth must be bounded to five levels")
    if path.endswith("klines") and (set(params) != {"symbol", "interval", "limit"}
            or params["interval"] != "1m" or type(params["limit"]) is not int or params["limit"] not in {5,500}):
        raise ValueError("Reference bars require reviewed one-minute pages")
    if path.endswith("fundingRate") and params != {"symbol":params.get("symbol"),"limit":32}:
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


def _closed_bars(raw, received_at):
    """Validate UTC closed minutes; historical prices become known on receipt.

    Binance's inclusive closeTime is minute-end minus one millisecond. Expose the
    normalized exclusive minute end and require it to precede receipt by 5s. No
    interpolation, forward fill, retrospective availability or open-bar use.
    """
    received_at = _finite(received_at, True)
    if not isinstance(raw,list) or len(raw)>500:
        raise ValueError("Invalid bounded minute bars")
    result, previous = [], None
    for row in raw:
        if not isinstance(row,list) or len(row)!=12:
            raise ValueError("Invalid minute bar schema")
        opened, closed, trades = row[0], row[6], row[8]
        if (type(opened) is not int or type(closed) is not int or type(trades) is not int
                or not 0<opened<=253402300799999 or opened%60000 or closed!=opened+59999
                or not 0<=trades<=1_000_000_000 or previous is not None and opened<=previous):
            raise ValueError("Invalid UTC minute chronology")
        previous = opened
        opening,high,low,price = [_finite(row[index],True) for index in (1,2,3,4)]
        volumes = [_finite(row[index]) for index in (5,7,9,10)]
        if (not all(1e-12<=value<=1e12 for value in (opening,high,low,price))
                or low>min(opening,price) or high<max(opening,price) or low>high
                or any(not 0<=value<=1e18 for value in volumes)
                or volumes[2]>volumes[0]*(1+1e-12) or volumes[3]>volumes[1]*(1+1e-12)
                or (volumes[0]==0)!=(volumes[1]==0) or (volumes[2]==0)!=(volumes[3]==0)
                or (trades==0)!=(volumes[0]==0)
                or _finite(row[11])!=0):
            raise ValueError("Invalid minute OHLC or volume")
        end = (opened+60000)/1000
        if end+5<=received_at:
            result.append({"at":end,"received_at":received_at,"price":price})
    return result


def _premium_batch(raw, received_at):
    if not isinstance(raw,list) or len(raw)>2000:
        raise ValueError("Invalid bounded premium batch")
    selected, rejected, seen = {}, set(), set()
    for row in raw:
        if not isinstance(row,dict) or not isinstance(row.get("symbol"),str):
            raise ValueError("Invalid premium batch schema")
        symbol = row["symbol"]
        if symbol not in SYMBOLS:
            continue
        if symbol in seen:
            rejected.add(symbol)
            selected.pop(symbol,None)
            continue
        seen.add(symbol)
        try:
            at = _finite(row["time"],True)/1000
            mark = _finite(row["markPrice"],True)
            rate = _finite(row["lastFundingRate"])
            next_at = _finite(row["nextFundingTime"],True)/1000
            if not -5<=received_at-at<=90 or not 1e-12<=mark<=1e12 or abs(rate)>.1:
                raise ValueError("Invalid premium observation")
            selected[symbol] = {"mark_price":mark,"observed_funding_rate":rate,
                "next_funding_at":next_at,"at":at,"received_at":received_at}
        except (KeyError,TypeError,ValueError,OverflowError):
            rejected.add(symbol)
    return {symbol:value for symbol,value in selected.items() if symbol not in rejected}


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
        self._last_bar_at = {}
        self._info_at = None
        self._last_pass = None
        self._stop = threading.Event()
        self._backoff_until = 0.
        self._consecutive_errors = 0
        self._last = {"markets": [], "sources": [], "closed_bars": {}, "at": None}
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
        closed_bars = {symbol:[] for symbol in SYMBOLS}
        if now < self._backoff_until:
            return {"markets": [], "sources": [{"id": "BINANCE_PUBLIC", "state": "BACKOFF",
                    "at": now, "error": "REFERENCE_RATE_LIMIT"}], "closed_bars":closed_bars,
                    "at": now, "health": dict(self.health)}
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
        # Read all current books before the batch mark and historical pages. An
        # early batch mark must not become older than later ETH/SOL Spot books.
        for symbol in SYMBOLS:
            item = {"symbol": symbol, "spot": None, "futures": None, "history": []}
            try:
                raw = self._get("SPOT_REFERENCE", "/api/v3/depth", {"symbol": symbol, "limit": 5})
                item["spot"] = _book(raw, symbol, self.clock())
            except Exception as exc:
                sources.append({"id": "SPOT_"+symbol, "state": "ERROR", "at": self.clock(), "error": type(exc).__name__})
            try:
                raw = self._get("FUTURES_REFERENCE", "/fapi/v1/depth", {"symbol": symbol, "limit": 5})
                item["futures"] = _book(raw, symbol, self.clock(), futures=True)
            except Exception as exc:
                sources.append({"id": "FUTURES_"+symbol, "state": "ERROR", "at": self.clock(), "error": type(exc).__name__})
            markets.append(item)
        premiums = {}
        try:
            raw = self._get("FUTURES_REFERENCE","/fapi/v1/premiumIndex",{})
            premiums = _premium_batch(raw,self.clock())
        except Exception as exc:
            sources.append({"id":"FUTURES_PREMIUM","state":"ERROR","at":self.clock(),"error":type(exc).__name__})
        for item in markets:
            symbol = item["symbol"]
            try:
                book = item["futures"]
                if book is None:
                    continue
                mark = premiums.get(symbol)
                if mark is None:
                    raise ValueError("Missing valid reviewed premium")
                book.update(mark_price=mark["mark_price"],observed_funding_rate=mark["observed_funding_rate"],
                            next_funding_at=mark["next_funding_at"],at=min(book["at"],mark["at"]),
                            received_at=max(book["received_at"],mark["received_at"]))
                item["futures"] = book
            except Exception as exc:
                item["futures"] = None
                sources.append({"id": "FUTURES_"+symbol, "state": "ERROR", "at": self.clock(), "error": type(exc).__name__})
        for item in markets:
            symbol = item["symbol"]
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
            if item["spot"] and item["futures"]:
                sources.append({"id": symbol, "state": "READY", "at": self.clock(), "error": None})
        for symbol in SYMBOLS:
            try:
                # A real limit=5 page includes the open minute and can exclude a
                # just-closed minute under the five-second guard: only three
                # closed slots are guaranteed. Choose with the current clock at
                # this request, not the earlier pass start or a stale receipt.
                # Include the existing two-second timeout in the cutoff margin.
                possible_end = math.floor((self.clock()+2-5)/60)*60
                previous_end = self._last_bar_at.get(symbol)
                limit = 500 if previous_end is None or possible_end-previous_end>180 else 5
                raw = self._get("SPOT_REFERENCE","/api/v3/klines",{"symbol":symbol,"interval":"1m","limit":limit})
                rows = _closed_bars(raw,self.clock())
                if not rows:
                    raise ValueError("No closed minute bars available")
                closed_bars[symbol] = rows
                self._last_bar_at[symbol] = max(rows[-1]["at"],previous_end or 0)
            except Exception as exc:
                sources.append({"id":"BARS_"+symbol,"state":"ERROR","at":self.clock(),"error":type(exc).__name__})
        failed = any(row["state"] == "ERROR" for row in sources)
        # A rejected research-only candle page must not throttle current quotes
        # used by Funding Carry protection. Exchange-wide rate-limit backoff in
        # _get still applies to every route, including the closed-bar connector.
        core_failed = any(row["state"] == "ERROR" and not row["id"].startswith("BARS_") for row in sources)
        self._consecutive_errors = self._consecutive_errors+1 if core_failed else 0
        if failed:
            self.health["errors"] += 1
            self.health["last_error"] = "REFERENCE_PARTIAL"
            if self._consecutive_errors >= 3:
                self._backoff_until = max(self._backoff_until, self.clock()+min(900, 60*2**min(4,self._consecutive_errors-3)))
                self.health["backoff_until"] = self._backoff_until
        else:
            self.health["last_error"] = None
            self.health["backoff_until"] = None
        self._last = {"markets": markets, "sources": sources[:12], "closed_bars":closed_bars,
                      "at": self.clock(), "health": dict(self.health)}
        return self._last
