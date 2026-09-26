from __future__ import annotations

import json
from dataclasses import asdict
import hmac
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import AppConfig, PROJECT_ROOT
from .database import Database
from .monitoring import activity_status, position_metrics, usable_price
from .risk_control import profile_name


WEB_ROOT = PROJECT_ROOT / "web"


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can let two servers bind the same port.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DashboardServer:
    def __init__(self, config: AppConfig, database: Database) -> None:
        self.config = config
        self.db = database
        self.db.initialize_cash(config.paper.initial_cash_usdt)
        self.token = os.getenv("DASHBOARD_TOKEN", "")
        self._research_lock = threading.Lock()
        self._research_state = {"running": False, "started_at": None, "error": None, "process_id": None}
        if config.dashboard.host not in {"127.0.0.1", "localhost", "::1"} and not self.token:
            raise ValueError("DASHBOARD_TOKEN is required when dashboard is exposed beyond localhost")

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:
                return

            def _authorized(self) -> bool:
                host = urlparse("//" + self.headers.get("Host", "")).hostname
                if outer.config.dashboard.host in {"127.0.0.1", "localhost", "::1"} and host not in {"127.0.0.1", "localhost", "::1"}:
                    return False
                if not outer.token:
                    return True
                return hmac.compare_digest(self.headers.get("X-Dashboard-Token", ""), outer.token)

            def _same_origin(self) -> bool:
                origin = self.headers.get("Origin")
                if not origin:
                    return True
                return urlparse(origin).netloc == self.headers.get("Host", "")

            def _common_headers(self) -> None:
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                )

            def _json(self, payload, status=HTTPStatus.OK) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self._common_headers()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/health/runtime":
                    host = urlparse("//" + self.headers.get("Host", "")).hostname
                    if self.client_address[0] not in {"127.0.0.1", "::1"} or host not in {"127.0.0.1", "localhost", "::1"}:
                        self._json({"error": "loopback only"}, HTTPStatus.FORBIDDEN)
                    elif not hasattr(outer, "runtime_token"):
                        self._json({"error": "runtime not supervised"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    else:
                        self._json({"pid": os.getpid(), "token": outer.runtime_token, "mode": outer.config.bot.mode})
                    return
                if path == "/health":
                    equity_rows = outer.db.recent("equity", 1)
                    latest_at = equity_rows[0]["created_at"] if equity_rows else None
                    activity = activity_status(latest_at, outer.config.bot.cycle_seconds)
                    healthy = activity["state"] == "operational"
                    self._json(
                        {"ok": healthy, **activity},
                        HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                if path.startswith("/api/"):
                    if not self._authorized():
                        self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                        return
                    self._api(path)
                    return
                self._static(path)

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if (outer.config.bot.database_path.parent / "UPDATE_MAINTENANCE.json").exists():
                    self._json({"error": "update maintenance in progress"}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                if not self._authorized():
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                if not self._same_origin():
                    self._json({"error": "origin not allowed"}, HTTPStatus.FORBIDDEN)
                    return
                if path in {"/api/operations/model", "/api/operations/restart", "/api/operations/execution-mode", "/api/operations/testnet-smoke", "/api/operations/futures-check", "/api/operations/futures-smoke", "/api/operations/futures-reconcile", "/api/operations/futures-forward-pause", "/api/operations/futures-forward-resume"}:
                    try:
                        if self.headers.get('Content-Type', '').split(';', 1)[0].strip() != 'application/json':
                            raise ValueError('JSON required')
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 128:
                            raise ValueError('Invalid request size')
                        payload = json.loads(self.rfile.read(length))
                        if not isinstance(payload, dict):
                            raise ValueError('Invalid request')
                        action = ('ai_model' if path.endswith('/model') else
                                  'execution_mode' if path.endswith('/execution-mode') else
                                  'testnet_smoke' if path.endswith('/testnet-smoke') else
                                  'futures_testnet_check' if path.endswith('/futures-check') else
                                  'futures_testnet_smoke' if path.endswith('/futures-smoke') else
                                  'futures_testnet_reconcile' if path.endswith('/futures-reconcile') else
                                  'futures_forward_pause' if path.endswith('/futures-forward-pause') else
                                  'futures_forward_resume' if path.endswith('/futures-forward-resume') else
                                  'restart_engine')
                        invalid = (
                            (action == 'ai_model' and (set(payload) != {'model'} or payload['model'] not in {'gpt-5.6-luna','gpt-6-luna'}))
                            or (action == 'execution_mode' and (set(payload) != {'mode'} or payload['mode'] not in {'paper','testnet'}))
                            or (action in {'restart_engine','testnet_smoke','futures_testnet_check','futures_testnet_reconcile','futures_forward_pause','futures_forward_resume'} and bool(payload))
                            or (action == 'futures_testnet_smoke' and (
                                set(payload) != {'direction','leverage'}
                                or payload.get('direction') not in {'LONG','SHORT'}
                                or payload.get('leverage') not in {1,2,3}
                            ))
                        )
                        if invalid:
                            raise ValueError('Invalid operational request')
                        script = PROJECT_ROOT / 'scripts/execute_paper_control.py'
                        process = subprocess.Popen([sys.executable, '-I', '-B', str(script), str(PROJECT_ROOT)],
                            cwd=PROJECT_ROOT, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        process.stdin.write(json.dumps({'action':action,'payload':payload}).encode('utf-8'))
                        process.stdin.close()
                        self._json({'status':'pending','message':'Windows está verificando el motor activo'}, HTTPStatus.ACCEPTED)
                    except (ValueError, OSError):
                        self._json({'error':'Acción no disponible'}, HTTPStatus.CONFLICT)
                    return
                if path in {"/api/paper/risk-profile", "/api/paper/close-position"}:
                    try:
                        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                            raise ValueError("JSON required")
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 512:
                            raise ValueError("invalid body size")
                        data = json.loads(self.rfile.read(length))
                        if not isinstance(data, dict):
                            raise ValueError("object required")
                        from .paper_controls import execute
                        self._json(execute(outer.config, outer.db,
                            "risk_profile" if path == "/api/paper/risk-profile" else "paper_close", data))
                        return
                    except ValueError:
                        self._json({"error": "invalid or stale trading request"}, HTTPStatus.CONFLICT)
                        return
                    except Exception:
                        self._json({"error": "Trading action unavailable; no confirmation"}, HTTPStatus.SERVICE_UNAVAILABLE)
                        return
                if path == "/api/kill":
                    outer.config.bot.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
                    outer.config.bot.kill_switch_path.write_text("manual kill switch\n", encoding="utf-8")
                    outer.db.event("CRITICAL", "Kill switch activated from dashboard")
                    self._json({"ok": True, "killed": True})
                elif path == "/api/resume":
                    outer.config.bot.kill_switch_path.unlink(missing_ok=True)
                    outer.db.event("INFO", "Kill switch cleared from dashboard")
                    self._json({"ok": True, "killed": False})
                elif path == "/api/research/run":
                    with outer._research_lock:
                        if outer._research_state["running"]:
                            self._json({"error": "research already running"}, HTTPStatus.CONFLICT)
                            return
                        outer._research_state = {
                            "running": True,
                            "started_at": datetime.now(UTC).isoformat(),
                            "error": None,
                            "process_id": None,
                        }

                    def research_job() -> None:
                        try:
                            log_path = outer.config.research.report_path.parent / "worker.log"
                            log_path.parent.mkdir(parents=True, exist_ok=True)
                            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            with log_path.open("w", encoding="utf-8") as log:
                                process = subprocess.Popen(
                                    [sys.executable, "-m", "trader", "research"],
                                    cwd=PROJECT_ROOT,
                                    stdout=log,
                                    stderr=subprocess.STDOUT,
                                    creationflags=creation_flags,
                                )
                                with outer._research_lock:
                                    outer._research_state["process_id"] = process.pid
                                return_code = process.wait()
                            if return_code != 0:
                                detail = log_path.read_text(encoding="utf-8", errors="replace")[-500:]
                                raise RuntimeError(detail or f"research process exited with code {return_code}")
                            if not outer.config.research.report_path.is_file():
                                raise RuntimeError("research process completed without producing a report")
                            outer.db.event("INFO", "Research Lab completed its multi-asset analysis")
                        except Exception as exc:
                            with outer._research_lock:
                                outer._research_state["error"] = str(exc)[:500]
                            outer.db.event("ERROR", f"Research Lab failed: {str(exc)[:300]}")
                        finally:
                            with outer._research_lock:
                                outer._research_state["running"] = False

                    threading.Thread(target=research_job, name="research-lab", daemon=True).start()
                    self._json({"ok": True, **outer._research_state}, HTTPStatus.ACCEPTED)
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

            def _api(self, path: str) -> None:
                if path == '/api/operations/last':
                    record = PROJECT_ROOT / 'data/operation-last.json'
                    try:
                        if record.stat().st_size > 2000:
                            raise ValueError('Oversized operation status')
                        self._json(json.loads(record.read_text(encoding='utf-8')))
                    except (OSError, ValueError):
                        self._json({'status':'unavailable'})
                    return
                if path == "/api/status":
                    equity_rows = outer.db.recent("equity", 1)
                    latest = equity_rows[0] if equity_rows else {}
                    initial = outer.config.paper.initial_cash_usdt
                    current = float(latest.get("equity", initial))
                    activity = activity_status(latest.get("created_at"), outer.config.bot.cycle_seconds)
                    prices, prices_at = outer.db.market_snapshot()
                    self._json({
                        "mode": outer.config.bot.mode.upper(),
                        "killed": outer.config.bot.kill_switch_path.exists(),
                        "ai_enabled": outer.config.ai.enabled,
                        "ai_model": outer.config.ai.model,
                        "equity": current,
                        "cash": float(latest.get("cash", outer.db.cash())),
                        "exposure": float(latest.get("exposure", 0)),
                        "return_pct": ((current / initial) - 1) * 100 if initial else 0,
                        "positions": len(outer.db.positions()),
                        "max_positions": outer.config.risk.max_positions,
                        "risk": asdict(outer.config.risk),
                        "paper_risk_profile": profile_name(outer.db),
                        "cycle_seconds": outer.config.bot.cycle_seconds,
                        "activity": activity,
                        "prices_at": prices_at,
                        "market_prices": len(prices),
                    })
                elif path == "/api/positions":
                    prices, prices_at = outer.db.market_snapshot()
                    rows = []
                    for position in outer.db.positions():
                        price = usable_price(prices.get(position.symbol), prices_at, outer.config.bot.cycle_seconds)
                        row = position_metrics(position, price, outer.config.paper)
                        row["price_as_of"] = prices_at
                        rows.append(row)
                    self._json(rows)
                elif path == "/api/trades":
                    self._json(outer.db.recent("trades", 50))
                elif path == "/api/signals":
                    self._json(outer.db.recent("signals", 50))
                elif path == "/api/equity":
                    self._json(list(reversed(outer.db.recent("equity", 300))))
                elif path == "/api/futures-forward":
                    from .futures_testnet_ledger import FuturesTestnetLedger
                    snapshot = FuturesTestnetLedger(outer.config.futures_testnet.database_path).forward_snapshot()
                    self._json({
                        "enabled": bool(outer.config.bot.mode == "testnet" and outer.config.futures_testnet.forward_enabled),
                        "killed": outer.config.futures_testnet.kill_switch_path.exists(),
                        "symbol": outer.config.futures_testnet.forward_symbol,
                        "automatic_leverage": outer.config.futures_testnet.forward_leverage,
                        "daily_loss_limit_pct": outer.config.futures_testnet.forward_daily_loss_limit_pct * 100.0,
                        "weekly_loss_limit_pct": outer.config.futures_testnet.forward_weekly_loss_limit_pct * 100.0,
                        "max_consecutive_errors": outer.config.futures_testnet.forward_max_consecutive_errors,
                        **snapshot,
                    })
                elif path == "/api/paper-scorecard":
                    import sqlite3
                    from contextlib import closing
                    from .paper_scorecard import paper_scorecard
                    with closing(sqlite3.connect(outer.config.bot.database_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)) as connection:
                        prices, prices_at = outer.db.market_snapshot()
                        self._json(paper_scorecard(connection, prices=prices, prices_at=prices_at,
                            cycle_seconds=outer.config.bot.cycle_seconds, paper=outer.config.paper, mode=outer.config.bot.mode,
                            research_symbols=outer.config.research.symbols))
                elif path == "/api/events":
                    self._json(outer.db.recent("events", 50))
                elif path == "/api/ai-reviews":
                    self._json(outer.db.recent("ai_reviews", 50))
                elif path == "/api/research/status":
                    with outer._research_lock:
                        self._json(dict(outer._research_state))
                elif path == "/api/research":
                    report_path = outer.config.research.report_path
                    if not report_path.is_file():
                        self._json({
                            "version": "0.6.2",
                            "mode": "RESEARCH_ONLY",
                            "status": "NOT_RUN",
                            "assets": [],
                        })
                        return
                    try:
                        self._json(json.loads(report_path.read_text(encoding="utf-8")))
                    except (OSError, json.JSONDecodeError):
                        self._json({"error": "research report unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

            def _static(self, path: str) -> None:
                relative = "index.html" if path in {"", "/"} else path.lstrip("/")
                candidate = (WEB_ROOT / relative).resolve()
                if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if not candidate.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                body = candidate.read_bytes()
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                if candidate.suffix == ".webmanifest":
                    content_type = "application/manifest+json"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self._common_headers()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def serve_forever(self) -> None:
        server = LocalHTTPServer((self.config.dashboard.host, self.config.dashboard.port), self._handler())
        server.serve_forever()

    def start_thread(self) -> threading.Thread:
        # Bind synchronously so callers cannot report healthy after a bind failure.
        server = LocalHTTPServer((self.config.dashboard.host, self.config.dashboard.port), self._handler())
        self.server = server
        thread = threading.Thread(target=server.serve_forever, name="dashboard", daemon=True)
        thread.start()
        return thread

    def close(self):
        server = getattr(self, "server", None)
        if server is not None:
            server.shutdown()
            server.server_close()
