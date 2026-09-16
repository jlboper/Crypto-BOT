import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

from trader.config import load_config
from trader.dashboard import DashboardServer
from trader.database import Database


class DashboardTests(unittest.TestCase):
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
