from __future__ import annotations

import hashlib
import hmac
import json
import os
import math
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .domain import Candle


class ExchangeError(RuntimeError):
    pass


class BinanceClient:
    def __init__(self, base_url: str = "https://api.binance.com", timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = os.getenv("BINANCE_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_API_SECRET", "")
        self._info_cache = None
        self._info_until = 0.0

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        # No order-writing transport is available, even if called accidentally.
        if method != "GET":
            raise ExchangeError("PAPER transport only permits GET")
        for attempt in range(3):
            try:
                return self._request_once(method, path, params, signed)
            except ExchangeError as exc:
                cause = exc.__cause__
                transient = isinstance(cause, (urllib.error.URLError, TimeoutError))
                if isinstance(cause, urllib.error.HTTPError):
                    transient = cause.code in {429, 500, 502, 503, 504}
                if not transient or attempt == 2 or signed:
                    raise
                delay = 2 ** attempt + random.random()
                if isinstance(cause, urllib.error.HTTPError) and cause.headers:
                    try:
                        retry = float(cause.headers.get("Retry-After", "0"))
                    except ValueError:
                        raise exc
                    if not math.isfinite(retry) or retry > 30:
                        raise exc
                    delay = max(delay, retry)
                time.sleep(delay)

    def _request_once(self, method: str, path: str, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        params = dict(params or {})
        headers = {"User-Agent": "CryptoAITradingBot/0.1"}
        if signed:
            if not self.api_key or not self.api_secret:
                raise ExchangeError("BINANCE_API_KEY and BINANCE_API_SECRET are required")
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            query = urllib.parse.urlencode(params)
            params["signature"] = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self.api_key
        encoded = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}"
        data = None
        if method in {"POST", "PUT", "DELETE"}:
            data = encoded.encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif encoded:
            url = f"{url}?{encoded}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ExchangeError(f"Binance HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ExchangeError("Binance connection failed") from exc

    def server_time(self) -> int:
        return int(self._request("GET", "/api/v3/time")["serverTime"])

    def top_usdt_symbols(self, limit: int) -> list[str]:
        if self._info_cache is None or time.monotonic() >= self._info_until:
            self._info_cache = self._request("GET", "/api/v3/exchangeInfo")
            self._info_until = time.monotonic() + 3600
        info = self._info_cache
        tickers = self._request("GET", "/api/v3/ticker/24hr")
        excluded_bases = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "TRY", "BRL", "MXN"}
        allowed: set[str] = set()
        for item in info.get("symbols", []):
            base = item.get("baseAsset", "")
            symbol = item.get("symbol", "")
            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get("isSpotTradingAllowed", True)
                and base not in excluded_bases
                and not base.endswith(("UP", "DOWN", "BULL", "BEAR"))
            ):
                allowed.add(symbol)
        ranked = sorted(
            (item for item in tickers if item.get("symbol") in allowed),
            key=lambda item: float(item.get("quoteVolume", 0.0)),
            reverse=True,
        )
        symbols = [item["symbol"] for item in ranked[:limit]]
        if "BTCUSDT" not in symbols:
            symbols.insert(0, "BTCUSDT")
        return symbols

    def cached_symbol_info(self, symbol: str) -> dict | None:
        """Use the exchangeInfo already fetched for universe selection; no new request."""
        if not isinstance(self._info_cache, dict) or time.monotonic() >= self._info_until:
            return None
        return next((item for item in self._info_cache.get('symbols', [])
                     if isinstance(item, dict) and item.get('symbol') == symbol), None)

    def candles(self, symbol: str, interval: str, limit: int = 250) -> list[Candle]:
        payload = self._request("GET", "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        return self._parse_candles(payload)

    @staticmethod
    def _parse_candles(payload: list[list[Any]]) -> list[Candle]:
        now_ms = int(time.time() * 1000)
        candles = [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=int(row[6]),
            )
            for row in payload
        ]
        closed = [candle for candle in candles if candle.close_time < now_ms]
        if any(not all(math.isfinite(v) for v in (c.open, c.high, c.low, c.close, c.volume))
               or not 0 < c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high
               or c.volume < 0 for c in closed):
            raise ExchangeError("Invalid OHLCV data")
        if any(b.open_time <= a.open_time for a, b in zip(closed, closed[1:])):
            raise ExchangeError("Unordered or duplicate candles")
        return closed

    def historical_candles(self, symbol: str, interval: str, limit: int = 2000) -> list[Candle]:
        """Fetch up to 10,000 closed candles without relying on a single API page."""
        if not 100 <= limit <= 10_000:
            raise ValueError("historical candle limit must be between 100 and 10000")
        collected: dict[int, Candle] = {}
        end_time: int | None = None
        while len(collected) < limit:
            batch_size = min(1000, limit - len(collected))
            params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": batch_size}
            if end_time is not None:
                params["endTime"] = end_time
            payload = self._request("GET", "/api/v3/klines", params)
            batch = self._parse_candles(payload)
            if not batch:
                break
            for candle in batch:
                collected[candle.open_time] = candle
            oldest = min(candle.open_time for candle in batch)
            next_end = oldest - 1
            if end_time is not None and next_end >= end_time:
                break
            end_time = next_end
            if len(payload) < batch_size:
                break
        return sorted(collected.values(), key=lambda candle: candle.open_time)[-limit:]

    def latest_prices(self, symbols: set[str] | list[str] | tuple[str, ...]) -> dict[str, float]:
        wanted = set(symbols)
        if not wanted:
            return {}
        payload = self._request("GET", "/api/v3/ticker/price")
        prices = {
            str(item["symbol"]): float(item["price"])
            for item in payload
            if item.get("symbol") in wanted
        }
        if set(prices) != wanted or any(not math.isfinite(p) or p <= 0 for p in prices.values()):
            raise ExchangeError("Missing or invalid spot prices")
        return prices

    def verify_testnet_credentials(self) -> dict[str, Any]:
        original = self.base_url
        self.base_url = "https://testnet.binance.vision"
        try:
            account = self._request("GET", "/api/v3/account", signed=True)
            return {
                "can_trade": bool(account.get("canTrade")),
                "account_type": account.get("accountType"),
                "permissions": account.get("permissions", []),
            }
        finally:
            self.base_url = original
