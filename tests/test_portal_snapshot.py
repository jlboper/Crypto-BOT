import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from dataclasses import replace
from trader.config import load_config
from trader.database import Database
from trader.portal_snapshot import dashboard_snapshot, public_text
from trader.paper_scorecard import paper_scorecard

class PortalSnapshotTests(unittest.TestCase):
    def test_projection_reads_without_mutating_and_redacts_event_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'trader.db'
            config=load_config()
            config=replace(config,bot=replace(config.bot,database_path=path,kill_switch_path=Path(folder)/'kill'))
            database=Database(path)
            database.initialize_cash(1000)
            database.record_equity(1000,1000,0)
            database.event('WARN','token=TEST_CREDENTIAL https://example.test/private?key=test')
            before=path.read_bytes()
            payload=dashboard_snapshot(config,Path(folder)/'missing.json')
            self.assertEqual(payload['status']['mode'],'PAPER')
            self.assertEqual(payload['research']['assets'],[])
            self.assertEqual(payload['paper_scorecard']['status'],'INSUFFICIENT_EVIDENCE')
            self.assertEqual(payload['paper_scorecard']['closed_trades'],0)
            self.assertNotIn('TEST_CREDENTIAL',json.dumps(payload))
            self.assertNotIn('example.test',json.dumps(payload))
            self.assertEqual(path.read_bytes(),before)

    def test_known_credentials_are_removed_from_text(self):
        self.assertNotIn('abc123',public_text('sk-abc123'))
        self.assertNotIn('abcdef',public_text('Bearer abcdef'))

    def test_forward_paper_evidence_uses_all_history_and_net_closed_pnl(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paper.db'
            Database(path)
            start=datetime(2026,1,1,tzinfo=UTC)
            with closing(sqlite3.connect(path)) as connection:
                connection.executemany('INSERT INTO equity(equity,cash,exposure,created_at) VALUES(?,?,?,?)',[
                    (1000,1000,0,start.isoformat()),
                    (900,700,200,(start+timedelta(days=15)).isoformat()),
                    (1080,1080,0,(start+timedelta(days=31)).isoformat()),
                ])
                connection.executemany('INSERT INTO trades(symbol,side,quantity,price,fee,realized_pnl,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',[
                    ('BTCUSDT','BUY',1,100,0.1,0,'test',start.isoformat()),
                    *[('BTCUSDT','SELL',1,100,0.2,2 if index<20 else -1,'test',(start+timedelta(days=index+1)).isoformat()) for index in range(30)],
                ])
                connection.commit()
            before=path.read_bytes()
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                result=paper_scorecard(connection)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(result['status'],'REVIEW_REQUIRED')
            self.assertEqual(result['closed_trades'],30)
            self.assertEqual(result['win_rate_pct'],round(20/30*100,2))
            self.assertEqual(result['net_realized_pnl_usdt'],30)
            self.assertEqual(result['fees_usdt'],6.1)
            self.assertEqual(result['sampled_max_drawdown_pct'],10)
            self.assertEqual(result['observed_days'],31)
            self.assertIn('no_historical_benchmark',result['limitations'])
