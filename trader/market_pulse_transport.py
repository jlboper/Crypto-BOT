"""Bounded, anonymous, read-only Binance market-data transport.

Only the market-data-only hosts are used. There is deliberately no signing,
account endpoint or exchange execution interface in this module.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Public data redirect refused", headers, None)


urlopen = build_opener(ProxyHandler({}), _NoRedirect()).open


class PublicRateLimitError(RuntimeError):
    def __init__(self, retry_after: float = 60) -> None:
        self.retry_after = min(3600, max(60, retry_after))
        super().__init__("PUBLIC_RATE_LIMIT")


def public_json(path: str, params: dict) -> object:
    if path not in {"/api/v3/aggTrades", "/api/v3/depth"}:
        raise ValueError("Market Pulse public endpoint not allowlisted")
    request = Request("https://data-api.binance.vision" + path + "?" + urlencode(params),
                      headers={"User-Agent": "CryptoAITrader-MarketPulse/1.0"})
    try:
        with urlopen(request, timeout=3) as response:
            if response.url.split("/")[2] != "data-api.binance.vision":
                raise ValueError("Unexpected public data redirect")
            payload = response.read(256_001)
            if len(payload) > 256_000:
                raise ValueError("Public data response too large")
            return json.loads(payload)
    except HTTPError as exc:
        if exc.code in {418, 429}:
            try:
                delay = float(exc.headers.get("Retry-After", "60"))
            except ValueError:
                delay = 60
            raise PublicRateLimitError(delay) from None
        raise


def rest_recovery(symbol: str, last_id: int | None = None) -> tuple[list[dict], dict]:
    """A bounded recovery page, not a claim of complete historical coverage."""
    params = {"symbol": symbol, "limit": 1000}
    if last_id is not None:
        params["fromId"] = last_id + 1
    trades = public_json("/api/v3/aggTrades", params)
    depth = public_json("/api/v3/depth", {"symbol": symbol, "limit": 5})
    if not isinstance(trades, list) or not isinstance(depth, dict):
        raise ValueError("Invalid market recovery payload")
    return trades, depth


class BinancePublicStream:
    """Small RFC6455 client for fixed combined JSON streams using stdlib TLS.

    TLS/upgrade are checked, control frames answered, fragmentation bounded,
    partial frames retained across socket timeouts. No external package needed.
    """
    MAX_MESSAGE = 65_536

    def __init__(self, symbols: tuple[str, ...]) -> None:
        self.socket = None
        self.buffer = bytearray()
        self.fragments = bytearray()
        self.fragment_active = False
        streams = "/".join(f"{symbol.lower()}@{kind}" for symbol in symbols
                           for kind in ("aggTrade", "depth5"))
        host = "data-stream.binance.vision"
        raw = socket.create_connection((host, 443), timeout=3)
        try:
            self.socket = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
            nonce = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (f"GET /stream?streams={streams} HTTP/1.1\r\nHost: {host}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n")
            self.socket.sendall(request.encode("ascii"))
            while b"\r\n\r\n" not in self.buffer:
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise ConnectionError("PUBLIC_WS_UPGRADE_CLOSED")
                self.buffer.extend(chunk)
                if len(self.buffer) > 8192:
                    raise ValueError("PUBLIC_WS_UPGRADE_TOO_LARGE")
            headers, body = bytes(self.buffer).split(b"\r\n\r\n", 1)
            self.buffer = bytearray(body)
            lines = headers.decode("ascii").split("\r\n")
            fields = {key.lower(): value.strip() for key, value in (line.split(":", 1) for line in lines[1:] if ":" in line)}
            expected = base64.b64encode(hashlib.sha1(
                (nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode()
            if (not lines[0].startswith("HTTP/1.1 101 ")
                    or fields.get("sec-websocket-accept", "") != expected
                    or fields.get("upgrade", "").lower() != "websocket"
                    or "upgrade" not in fields.get("connection", "").lower()):
                raise ConnectionError("PUBLIC_WS_UPGRADE_INVALID")
            self.socket.settimeout(0.5)
        except BaseException:
            self.close()
            raw.close()
            raise

    def _send_control(self, opcode: int, payload: bytes) -> None:
        if len(payload) > 125:
            raise ValueError("PUBLIC_WS_CONTROL_TOO_LARGE")
        mask = os.urandom(4)
        packet = bytes((0x80 | opcode, 0x80 | len(payload))) + mask
        packet += bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.socket.sendall(packet)

    def receive(self) -> dict | None:
        while True:
            if len(self.buffer) >= 2:
                first, second = self.buffer[:2]
                if first & 0x70 or second & 0x80:
                    raise ValueError("PUBLIC_WS_INVALID_FLAGS")
                length, offset = second & 0x7f, 2
                if length == 126 and len(self.buffer) >= 4:
                    length, offset = struct.unpack("!H", self.buffer[2:4])[0], 4
                elif length == 127 and len(self.buffer) >= 10:
                    length, offset = struct.unpack("!Q", self.buffer[2:10])[0], 10
                elif length >= 126:
                    length = None
                if length is not None:
                    if length > self.MAX_MESSAGE:
                        raise ValueError("PUBLIC_WS_FRAME_TOO_LARGE")
                    if len(self.buffer) >= offset + length:
                        payload = bytes(self.buffer[offset:offset + length])
                        del self.buffer[:offset + length]
                        opcode, final = first & 0xf, bool(first & 0x80)
                        if opcode in {8, 9, 10}:
                            if not final or length > 125:
                                raise ValueError("PUBLIC_WS_INVALID_CONTROL")
                            if opcode == 8:
                                raise ConnectionError("PUBLIC_WS_CLOSED")
                            if opcode == 9:
                                self._send_control(10, payload)
                            continue
                        if opcode == 1 and self.fragment_active:
                            raise ValueError("PUBLIC_WS_INVALID_FRAGMENT")
                        if opcode not in {0, 1} or (opcode == 0 and not self.fragment_active):
                            raise ValueError("PUBLIC_WS_UNSUPPORTED_FRAME")
                        self.fragment_active = True
                        self.fragments.extend(payload)
                        if len(self.fragments) > self.MAX_MESSAGE:
                            raise ValueError("PUBLIC_WS_MESSAGE_TOO_LARGE")
                        if not final:
                            continue
                        payload = bytes(self.fragments)
                        self.fragments.clear()
                        self.fragment_active = False
                        value = json.loads(payload)
                        if not isinstance(value, dict):
                            raise ValueError("PUBLIC_WS_INVALID_JSON")
                        return value
            try:
                chunk = self.socket.recv(16_384)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("PUBLIC_WS_DISCONNECTED")
            self.buffer.extend(chunk)
            if len(self.buffer) > self.MAX_MESSAGE + 16_384:
                raise ValueError("PUBLIC_WS_BUFFER_TOO_LARGE")

    def close(self) -> None:
        sock, self.socket = self.socket, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
