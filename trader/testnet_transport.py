"""Minimal signed transport for Binance Spot Testnet.

Only the unified Testnet broker uses this module. The host is fixed to
https://testnet.binance.vision and only the exact Spot endpoints required for
account reads, order reconciliation and MARKET order submission are allowed.
There is no production host and no retry for signed writes.
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

HOST = "https://testnet.binance.vision"
TERMINAL = {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}


class TestnetExecutionError(ValueError):
    def __init__(self, message: str, *, code: int | None = None,
                 api_message: str | None = None, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.api_message = api_message
        self.uncertain = uncertain


def signed_request(method: str, endpoint: str, fields: dict) -> dict:
    allowed = {
        ("GET", "/api/v3/account"),
        ("GET", "/api/v3/order"),
        ("GET", "/api/v3/myTrades"),
        ("POST", "/api/v3/order"),
    }
    if (method, endpoint) not in allowed:
        raise TestnetExecutionError("Testnet endpoint blocked")
    key = os.getenv("BINANCE_API_KEY", "")
    secret = os.getenv("BINANCE_API_SECRET", "")
    if not key or not secret:
        raise TestnetExecutionError("Testnet credentials unavailable")
    values = {**fields, "timestamp": int(time.time() * 1000), "recvWindow": 5000}
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
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        type(
            "NoRedirect",
            (urllib.request.HTTPRedirectHandler,),
            {"redirect_request": lambda *args: None},
        )(),
    )
    try:
        with opener.open(request, timeout=10) as response:
            result = json.loads(response.read(65537))
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
        raise TestnetExecutionError("Testnet HTTP " + str(error.code) + detail,
                                    code=code, api_message=api_message) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise TestnetExecutionError(
            "Testnet response uncertain; reconcile before another action",
            uncertain=True,
        ) from None
    if endpoint == "/api/v3/myTrades":
        if not isinstance(result, list):
            raise TestnetExecutionError("Invalid Testnet trades response")
    elif not isinstance(result, dict):
        raise TestnetExecutionError("Invalid Testnet response")
    return result
