"""Single-owner WSGI portal. Run behind a HTTPS reverse proxy, never on the PC."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit
from contextlib import contextmanager


def password_hash(password: str, salt: str | None = None) -> str:
    if len(password) < 14:
        raise ValueError("Use a password of at least 14 characters")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + digest


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Portal:
    def __init__(self, path: Path, origin: str, owner_hash: str, device_hash: str):
        parts = urlsplit(origin)
        if parts.scheme != "https" or not parts.hostname or parts.path or parts.query or parts.fragment or parts.username:
            raise ValueError("A canonical HTTPS origin is required")
        if len(device_hash) != 64 or len(owner_hash.split(":")) != 2:
            raise ValueError("Provision owner and device credentials first")
        self.path, self.origin = path, origin
        self.owner_hash, self.device_hash = owner_hash, device_hash
        self.web = Path(__file__).resolve().parent.parent / "portal_web"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY, at REAL);
                CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT, at REAL);
                CREATE TABLE IF NOT EXISTS commands(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT UNIQUE, action TEXT, expires REAL, status TEXT, created REAL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def __call__(self, env, start_response):
        headers = [("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
            ("Strict-Transport-Security", "max-age=31536000"),
            ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]

        def respond(status, payload, kind="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode()
            start_response(status, headers + [("Content-Type", kind), ("Content-Length", str(len(body)))])
            return [body]

        try:
            path, method = env.get("PATH_INFO", "/"), env.get("REQUEST_METHOD", "GET")
            if env.get("HTTP_HOST") != urlsplit(self.origin).netloc:
                return respond("400 Bad Request", {"error": "host"})
            if method not in {"GET", "POST"}:
                return respond("405 Method Not Allowed", {"error": "method"})
            body = {}
            if method == "POST":
                size = int(env.get("CONTENT_LENGTH") or "0")
                if not 0 < size <= 65536:
                    return respond("413 Payload Too Large", {"error": "body size"})
                if env.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                    return respond("415 Unsupported Media Type", {"error": "JSON required"})
                body = json.loads(env["wsgi.input"].read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(body, dict):
                    raise ValueError("object required")
            now = time.time()
            if path == "/v1/device/sync" and method == "POST":
                authorization = env.get("HTTP_AUTHORIZATION", "")
                if not authorization.startswith("Bearer ") or not hmac.compare_digest(digest(authorization[7:]), self.device_hash):
                    return respond("401 Unauthorized", {"error": "device"})
                snapshot = body.get("snapshot")
                if not isinstance(snapshot, dict) or snapshot.get("mode") != "PAPER":
                    raise ValueError("PAPER snapshot required")
                allowed = {"mode", "equity", "cash", "exposure", "positions", "killed", "last_cycle_at", "ai_model", "update_state"}
                if set(snapshot) - allowed:
                    raise ValueError("unknown snapshot fields")
                acks = body.get("acks", [])
                if not isinstance(acks, list) or len(acks) > 50:
                    raise ValueError("invalid acknowledgements")
                with self.connect() as db:
                    db.execute("INSERT INTO snapshots VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,at=excluded.at", (json.dumps(snapshot, allow_nan=False), now))
                    for ack in acks:
                        if type(ack) is not int:
                            raise ValueError("invalid acknowledgement")
                        db.execute("UPDATE commands SET status='applied' WHERE id=? AND status='pending' AND expires>?", (ack, now))
                    db.execute("UPDATE commands SET status='expired' WHERE status='pending' AND expires<=?", (now,))
                    rows = db.execute("SELECT id,action,expires FROM commands WHERE status='pending' ORDER BY id LIMIT 50").fetchall()
                    db.execute("DELETE FROM commands WHERE status!='pending' AND created<?", (now-90*86400,))
                return respond("200 OK", {"commands": [dict(r) for r in rows], "poll_seconds": 30})
            if method == "POST" and env.get("HTTP_ORIGIN") != self.origin:
                return respond("403 Forbidden", {"error": "origin"})
            if path == "/v1/login" and method == "POST":
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("DELETE FROM login_attempts WHERE at<?", (now-300,))
                    count = db.execute("SELECT count(*) FROM login_attempts").fetchone()[0]
                    if count >= 10:
                        return respond("429 Too Many Requests", {"error": "Wait five minutes"})
                    db.execute("INSERT INTO login_attempts(at) VALUES(?)", (now,))
                password = body.get("password", "")
                if not isinstance(password, str) or not 14 <= len(password) <= 1024:
                    return respond("401 Unauthorized", {"error": "credentials"})
                candidate = password_hash(password, self.owner_hash.split(":")[0])
                if not hmac.compare_digest(candidate, self.owner_hash):
                    return respond("401 Unauthorized", {"error": "credentials"})
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with self.connect() as db:
                    db.execute("DELETE FROM sessions WHERE expires<?", (now,))
                    db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), csrf, now+3600))
                    db.execute("DELETE FROM sessions WHERE rowid NOT IN (SELECT rowid FROM sessions ORDER BY expires DESC LIMIT 10)")
                headers.append(("Set-Cookie", f"__Host-session={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600"))
                return respond("200 OK", {"csrf": csrf})
            if path in {"/", "/app.js", "/style.css"} and method == "GET":
                filename, kind = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}[path]
                return respond("200 OK", (self.web / filename).read_bytes(), kind)
            cookies = SimpleCookie()
            cookies.load(env.get("HTTP_COOKIE", ""))
            cookie = cookies.get("__Host-session")
            with self.connect() as db:
                session = db.execute("SELECT * FROM sessions WHERE token=? AND expires>?", (digest(cookie.value if cookie else ""), now)).fetchone()
            if not session:
                return respond("401 Unauthorized", {"error": "session"})
            if method == "POST" and not hmac.compare_digest(env.get("HTTP_X_CSRF_TOKEN", ""), session["csrf"]):
                return respond("403 Forbidden", {"error": "csrf"})
            if path == "/v1/status" and method == "GET":
                with self.connect() as db:
                    row = db.execute("SELECT * FROM snapshots WHERE id=1").fetchone()
                    commands = [dict(r) for r in db.execute("SELECT id,action,status,expires FROM commands ORDER BY id DESC LIMIT 20")]
                return respond("200 OK", {"csrf": session["csrf"], "snapshot": json.loads(row["payload"]) if row else None,
                    "received_at": row["at"] if row else None, "stale": not row or now-row["at"] > 120, "commands": commands})
            if path == "/v1/commands" and method == "POST":
                action, request_id = body.get("action"), body.get("request_id")
                if action not in {"kill", "resume"} or not isinstance(request_id, str) or not 16 <= len(request_id) <= 100:
                    raise ValueError("invalid command")
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT id,action FROM commands WHERE request_id=?", (request_id,)).fetchone()
                    if row and row["action"] != action:
                        return respond("409 Conflict", {"error": "idempotency conflict"})
                    if not row:
                        # Only newest desired state remains executable; a delayed resume cannot override a later kill.
                        db.execute("UPDATE commands SET status='superseded' WHERE status='pending'")
                        cursor = db.execute("INSERT INTO commands(request_id,action,expires,status,created) VALUES(?,?,?,'pending',?)", (request_id, action, now+120, now))
                        identifier = cursor.lastrowid
                    else:
                        identifier = row["id"]
                return respond("202 Accepted", {"id": identifier, "status": "queued"})
            if path == "/v1/logout" and method == "POST":
                with self.connect() as db:
                    db.execute("DELETE FROM sessions WHERE token=?", (session["token"],))
                headers.append(("Set-Cookie", "__Host-session=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"))
                return respond("200 OK", {"ok": True})
            return respond("404 Not Found", {"error": "not found"})
        except (ValueError, TypeError, KeyError):
            return respond("400 Bad Request", {"error": "invalid request"})
        except Exception:
            return respond("503 Service Unavailable", {"error": "service unavailable"})


def create_app():
    return Portal(Path(os.environ["PORTAL_DB"]), os.environ["PORTAL_ORIGIN"],
                  os.environ["PORTAL_PASSWORD_HASH"], os.environ["PORTAL_DEVICE_HASH"])


if __name__ == "__main__":
    from waitress import serve
    serve(create_app(), host="127.0.0.1", port=int(os.getenv("PORT", "8080")),
          threads=4, max_request_body_size=65536, channel_timeout=30)
