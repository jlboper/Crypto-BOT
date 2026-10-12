"""Minimal transport for Binance USDⓈ-M Futures Demo.

The REST host is fixed to Binance Futures Testnet used by Binance Demo Trading. Production USDⓈ-M hosts are
not configurable here. Signed writes are never retried automatically.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HOST = "https://testnet.binancefuture.com"
PUBLIC_FALLBACK_HOST = "https://fapi.binance.com"

_PUBLIC = {
    ("GET", "/fapi/v1/time"),
    ("GET", "/fapi/v1/exchangeInfo"),
    ("GET", "/fapi/v1/ticker/price"),
    ("GET", "/fapi/v1/premiumIndex"),
    ("GET", "/fapi/v1/klines"),
}
_SIGNED = {
    ("GET", "/fapi/v1/income"),
    ("GET", "/fapi/v3/account"),
    ("GET", "/fapi/v3/positionRisk"),
    ("GET", "/fapi/v1/order"),
    ("GET", "/fapi/v1/algoOrder"),
    ("POST", "/fapi/v1/algoOrder"),
    ("DELETE", "/fapi/v1/algoOrder"),
    ("GET", "/fapi/v1/positionSide/dual"),
    ("GET", "/fapi/v1/symbolConfig"),
    ("POST", "/fapi/v1/order"),
    ("POST", "/fapi/v1/order/test"),
    ("POST", "/fapi/v1/leverage"),
    ("POST", "/fapi/v1/marginType"),
    ("POST", "/fapi/v1/positionSide/dual"),
}


class FuturesTestnetExecutionError(ValueError):
    def __init__(self, message: str, *, code: int | None = None,
                 api_message: str | None = None, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.api_message = api_message
        self.uncertain = uncertain


def _signed_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
             {"redirect_request": lambda *args: None})(),
    )


def _public_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
             {"redirect_request": lambda *args: None})(),
    )


def _decode(response, maximum: int = 262144) -> Any:
    raw = response.read(maximum+1)
    if len(raw) > maximum:
        raise FuturesTestnetExecutionError('Futures response exceeds size limit')
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise FuturesTestnetExecutionError("Invalid Futures Testnet response") from None


def public_request(method: str, endpoint: str, fields: dict | None = None, *, allow_fallback: bool = True) -> Any:
    if (method, endpoint) not in _PUBLIC:
        raise FuturesTestnetExecutionError("Futures Testnet public endpoint blocked")
    query = urllib.parse.urlencode(fields or {})
    last_error = None
    hosts = (HOST, PUBLIC_FALLBACK_HOST) if allow_fallback else (HOST,)
    for host in hosts:
        url = host + endpoint + (("?" + query) if query else "")
        request = urllib.request.Request(url, method=method)
        try:
            with _public_opener().open(request, timeout=10) as response:
                # exchangeInfo is a full contract catalogue even when a symbol
                # is supplied; it now exceeds the former 256 KiB read budget.
                return _decode(response, maximum=2097152 if endpoint == '/fapi/v1/exchangeInfo' else 262144)
        except FuturesTestnetExecutionError:
            # Semantic/size errors inherit ValueError; never label them as a
            # network outage or silently switch their data source.
            raise
        except urllib.error.HTTPError as error:
            last_error = FuturesTestnetExecutionError(
                "Futures public HTTP " + str(error.code) + " at " + host
            )
        except (urllib.error.URLError, TimeoutError, ValueError):
            last_error = FuturesTestnetExecutionError(
                "Futures public connection failed at " + host
            )
    raise last_error or FuturesTestnetExecutionError("Futures public connection failed")


_clock_lock = threading.Lock()
_clock_sample: tuple[int, float] | None = None


def _request_timestamp() -> int:
    """Anchor signed timestamps to Demo time, independent of Windows clock jumps."""
    global _clock_sample
    with _clock_lock:
        now = time.monotonic()
        if _clock_sample is None or not 0 <= now - _clock_sample[1] < 300:
            _clock_sample = None
            started = time.monotonic()
            payload = public_request("GET", "/fapi/v1/time", allow_fallback=False)
            received = time.monotonic()
            server_time = payload.get("serverTime") if isinstance(payload, dict) else None
            if type(server_time) is not int or server_time <= 0:
                raise FuturesTestnetExecutionError("Futures Demo server time unavailable")
            if not 0 <= received - started <= 2:
                raise FuturesTestnetExecutionError("Futures Demo server time response too slow")
            # Use the received server time conservatively: no latency estimate
            # may push a timestamp ahead of Binance's one-second tolerance.
            _clock_sample = (server_time, received)
            now = received
        return _clock_sample[0] + int((now - _clock_sample[1]) * 1000)


def signed_request(method: str, endpoint: str, fields: dict | None = None) -> Any:
    global _clock_sample
    # Only a read can be retried. Order and cancellation writes always go
    # through their existing durable reconciliation before another write.
    for attempt in range(2 if method == "GET" else 1):
        try:
            return _signed_request_once(method, endpoint, fields)
        except FuturesTestnetExecutionError as exc:
            if exc.code != -1021:
                raise
            with _clock_lock:
                _clock_sample = None
            if method != "GET" or attempt == 1:
                raise


def _signed_request_once(method: str, endpoint: str, fields: dict | None = None) -> Any:
    if (method, endpoint) not in _SIGNED:
        raise FuturesTestnetExecutionError("Futures Testnet endpoint blocked")
    key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY", "")
    secret = os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET", "")
    if not key or not secret:
        raise FuturesTestnetExecutionError("Futures Testnet credentials unavailable")
    values = {**(fields or {}), "timestamp": _request_timestamp(), "recvWindow": 5000}
    query = urllib.parse.urlencode(values)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    encoded = f"{query}&signature={signature}"
    url = HOST + endpoint + ("?" + encoded if method in {"GET", "DELETE"} else "")
    request = urllib.request.Request(
        url,
        data=encoded.encode() if method == "POST" else None,
        method=method,
        headers={"X-MBX-APIKEY": key, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with _signed_opener().open(request, timeout=10) as response:
            return _decode(response)
    except urllib.error.HTTPError as error:
        code = None
        api_message = None
        try:
            payload = json.loads(error.read(4097))
            if isinstance(payload, dict):
                if isinstance(payload.get("code"), int):
                    code = payload["code"]
                if isinstance(payload.get("msg"), str):
                    api_message = " ".join(payload["msg"].split())[:180]
        except Exception:
            pass
        detail = (" · Binance " + str(code) + ": " + api_message) if code is not None and api_message else ""
        raise FuturesTestnetExecutionError(
            "Futures Demo HTTP " + str(error.code) + detail,
            code=code, api_message=api_message,
            uncertain=error.code >= 500 or code in {-1006, -1007},
        ) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise FuturesTestnetExecutionError(
            "Futures Testnet response uncertain; reconcile before another write",
            uncertain=True,
        ) from None
