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
from unittest.mock import patch

from trader.config import load_config
from trader.dashboard import DashboardServer
from trader.database import Database
from trader.broker import PaperBroker
from trader.domain import Signal
from trader.update_supervisor import ProcessRuntime


class DashboardTests(unittest.TestCase):
    def test_local_paper_close_uses_fresh_quote_and_blocks_reentry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = load_config()
            config = replace(config, bot=replace(config.bot, database_path=root/'paper.db', kill_switch_path=root/'kill'))
            db = Database(config.bot.database_path)
            dashboard = DashboardServer(config, db)
            broker = PaperBroker(db, config.paper, config.risk)
            signal = Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
            position = broker.buy(signal, 1, 'synthetic')
            server = ThreadingHTTPServer(('127.0.0.1',0), dashboard._handler())
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            def post(route, value, origin=None):
                headers={'Content-Type':'application/json'}
                if origin: headers['Origin']=origin
                request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}{route}',
                    data=json.dumps(value).encode(),headers=headers,method='POST')
                return urllib.request.urlopen(request)
            try:
                with patch('trader.exchange.BinanceClient.latest_prices',return_value={'BTCUSDT':104}):
                    with self.assertRaises(urllib.error.HTTPError) as moved:
                        post('/api/paper/close-position',{'symbol':'BTCUSDT','opened_at':position.opened_at,
                                                           'reference_price':100})
                self.assertEqual(moved.exception.code,409)
                self.assertIsNotNone(db.position('BTCUSDT'))
                with patch('trader.exchange.BinanceClient.latest_prices', return_value={'BTCUSDT':101}) as prices:
                    with post('/api/paper/close-position',{'symbol':'BTCUSDT','opened_at':position.opened_at,
                                                           'reference_price':100}) as response:
                        self.assertTrue(json.load(response)['ok'])
                prices.assert_called_once_with({'BTCUSDT'})
                self.assertIsNone(db.position('BTCUSDT'))
                with self.assertRaisesRegex(ValueError,'cooldown'):
                    broker.buy(signal,1,'synthetic')
                with self.assertRaises(urllib.error.HTTPError) as stale:
                    post('/api/paper/close-position',{'symbol':'BTCUSDT','opened_at':position.opened_at,
                                                       'reference_price':100})
                self.assertEqual(stale.exception.code,409)
                with post('/api/paper/risk-profile',{'profile':'prudente'}) as response:
                    self.assertEqual(json.load(response)['profile'],'prudente')
                other=replace(signal,symbol='ETHUSDT')
                with self.assertRaisesRegex(ValueError,'risk limit'):
                    broker.buy(other,1,'synthetic')
                with self.assertRaises(urllib.error.HTTPError) as cross_origin:
                    post('/api/paper/risk-profile',{'profile':'normal'},'https://evil.example')
                self.assertEqual(cross_origin.exception.code,403)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)

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
