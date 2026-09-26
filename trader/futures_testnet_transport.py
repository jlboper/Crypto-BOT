"""Minimal transport for Binance USDⓈ-M Futures Testnet.

The REST host is fixed to Binance Futures Testnet. Production USDⓈ-M hosts are
not configurable here. Signed writes are never retried automatically.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HOST = "https://testnet.binancefuture.com"

_PUBLIC = {
    ("GET", "/fapi/v1/time"),
    ("GET", "/fapi/v1/exchangeInfo"),
    ("GET", "/fapi/v1/ticker/price"),
    ("GET", "/fapi/v1/premiumIndex"),
}
_SIGNED = {
    ("GET", "/fapi/v3/account"),
    ("GET", "/fapi/v3/positionRisk"),
    ("GET", "/fapi/v1/order"),
    ("GET", "/fapi/v1/positionSide/dual"),
    ("POST", "/fapi/v1/order"),
    ("POST", "/fapi/v1/leverage"),
    ("POST", "/fapi/v1/marginType"),
    ("POST", "/fapi/v1/positionSide/dual"),
}


class FuturesTestnetExecutionError(ValueError):
    def __init__(self, message: str, *, code: int | None = None, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


def _opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
             {"redirect_request": lambda *args: None})(),
    )


def _decode(response) -> Any:
    raw = response.read(262145)
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise FuturesTestnetExecutionError("Invalid Futures Testnet response") from None


def public_request(method: str, endpoint: str, fields: dict | None = None) -> Any:
    if (method, endpoint) not in _PUBLIC:
        raise FuturesTestnetExecutionError("Futures Testnet public endpoint blocked")
    query = urllib.parse.urlencode(fields or {})
    url = HOST + endpoint + (("?" + query) if query else "")
    request = urllib.request.Request(url, method=method)
    try:
        with _opener().open(request, timeout=10) as response:
            return _decode(response)
    except urllib.error.HTTPError as error:
        raise FuturesTestnetExecutionError("Futures Testnet HTTP " + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise FuturesTestnetExecutionError("Futures Testnet public connection failed") from None


def signed_request(method: str, endpoint: str, fields: dict | None = None) -> Any:
    if (method, endpoint) not in _SIGNED:
        raise FuturesTestnetExecutionError("Futures Testnet endpoint blocked")
    key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY", "")
    secret = os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET", "")
    if not key or not secret:
        raise FuturesTestnetExecutionError("Futures Testnet credentials unavailable")
    values = {**(fields or {}), "timestamp": int(time.time() * 1000), "recvWindow": 5000}
    query = urllib.parse.urlencode(values)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    encoded = f"{query}&signature={signature}"
    url = HOST + endpoint + ("?" + encoded if method == "GET" else "")
    request = urllib.request.Request(
        url,
        data=encoded.encode() if method == "POST" else None,
        method=method,
        headers={"X-MBX-APIKEY": key, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with _opener().open(request, timeout=10) as response:
            return _decode(response)
    except urllib.error.HTTPError as error:
        code = None
        try:
            payload = json.loads(error.read(4097))
            if isinstance(payload, dict) and isinstance(payload.get("code"), int):
                code = payload["code"]
        except Exception:
            pass
        raise FuturesTestnetExecutionError("Futures Testnet HTTP " + str(error.code), code=code) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise FuturesTestnetExecutionError(
            "Futures Testnet response uncertain; reconcile before another write",
            uncertain=True,
        ) from None
