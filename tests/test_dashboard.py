import json
import tempfile
import threading
import os
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from trader.config import load_config
from trader.dashboard import DashboardServer
from trader.database import Database
from trader.update_supervisor import ProcessRuntime


class DashboardTests(unittest.TestCase):
    def test_runtime_health_binds_port_and_identifies_exact_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=root/'test.db'),
                             dashboard=replace(config.dashboard, host='127.0.0.1', port=0))
            dashboard = DashboardServer(config, Database(config.bot.database_path))
            dashboard.runtime_token = 'a'*64
            dashboard.start_thread()
            try:
                port = dashboard.server.server_port
                (root/'config.toml').write_text(f'[dashboard]\nhost="127.0.0.1"\nport={port}\n')
                runtime = ProcessRuntime(root)
                child = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
                self.assertTrue(runtime.health(child, 'a'*64))
                self.assertFalse(runtime.health(child, 'b'*64))
                self.assertFalse(runtime.health(SimpleNamespace(pid=-1, poll=lambda: None), 'a'*64))
                conflict = DashboardServer(replace(config, dashboard=replace(config.dashboard, port=port)), dashboard.db)
                with self.assertRaises(OSError):
                    conflict.start_thread()
                marker = config.bot.database_path.parent/'UPDATE_MAINTENANCE.json'
                marker.write_text('{}')
                request = urllib.request.Request(f'http://127.0.0.1:{port}/api/resume', method='POST')
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 503)
            finally:
                dashboard.close()

    def test_research_endpoint_and_security_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = load_config()
            config = replace(
                config,
                bot=replace(config.bot, database_path=root / "test.db", kill_switch_path=root / "kill"),
                research=replace(config.research, report_path=root / "research.json"),
            )
            dashboard = DashboardServer(config, Database(config.bot.database_path))
            server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard._handler())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/api/research") as response:
                    payload = json.loads(response.read())
                    self.assertEqual(payload["status"], "NOT_RUN")
                    self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                request = urllib.request.Request(
                    base + "/api/kill", method="POST", headers={"Origin": "https://evil.example"}
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 403)
                self.assertFalse(config.bot.kill_switch_path.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
