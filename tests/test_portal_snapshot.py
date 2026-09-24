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
            self.assertEqual(payload['status']['risk']['max_position_pct'],config.risk.max_position_pct)
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
            self.assertIsNone(result['benchmark']['paper_return_pct'])
            self.assertIn('benchmark_starts_with_new_samples',result['limitations'])

    def test_forward_benchmark_only_compares_matched_new_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paper.db'
            database=Database(path)
            database.record_equity(1000,1000,0)
            database.record_equity(1050,1050,0,100)
            database.record_equity(1100,1100,0,120)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("UPDATE equity SET created_at='2026-01-01T00:00:00+00:00' WHERE id=2")
                connection.execute("UPDATE equity SET created_at='2026-01-02T00:00:00+00:00' WHERE id=3")
                connection.execute("UPDATE equity SET created_at='2025-12-31T00:00:00+00:00' WHERE id=1")
                connection.commit()
                report=paper_scorecard(connection,paper=load_config().paper)
            self.assertEqual(report['benchmark']['matched_points'],2)
            self.assertEqual(report['benchmark']['observed_days'],1)
            self.assertAlmostEqual(report['benchmark']['paper_return_pct'],4.762,places=3)
            self.assertEqual(report['benchmark']['btc_return_pct'],20)
            self.assertAlmostEqual(report['benchmark']['difference_pp'],-15.238,places=3)
            self.assertLess(report['benchmark']['btc_net_return_pct'],20)
            self.assertAlmostEqual(report['benchmark']['net_difference_pp'],
                                   report['benchmark']['paper_return_pct']-report['benchmark']['btc_net_return_pct'],places=3)

    def test_attribution_reconciles_all_assets_exits_and_research_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paper.db'
            db=Database(path)
            for index in range(55):
                db.record_trade(f'COIN{index:02}USDT','SELL',1,100,0.1,
                                -2.0 if index >= 50 else 1.0,
                                'protective stop' if index >= 50 else 'take profit')
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                report=paper_scorecard(connection,research_symbols=('COIN00USDT','COIN54USDT'))
            self.assertEqual(report['closed_trades'],55)
            self.assertEqual(report['net_realized_pnl_usdt'],40)
            self.assertEqual(len(report['by_asset']),50)
            self.assertEqual(report['omitted_assets'],5)
            self.assertEqual(report['attribution']['omitted_closed_trades'],5)
            self.assertEqual(report['attribution']['omitted_net_realized_pnl_usdt'],-10)
            self.assertAlmostEqual(sum(row['net_realized_pnl_usdt'] for row in report['by_asset'])+
                                   report['attribution']['omitted_net_realized_pnl_usdt'],
                                   report['net_realized_pnl_usdt'])
            self.assertEqual(report['attribution']['research_closed_trades'],2)
            self.assertEqual(sum(row['closed_trades'] for row in report['attribution']['exit_reasons']),55)
            self.assertEqual(sum(row['net_realized_pnl_usdt'] for row in report['attribution']['exit_reasons']),40)


    def test_asset_breakdown_requires_fresh_price_for_open_estimate(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paper.db'
            Database(path)
            at=datetime(2026, 1, 1, tzinfo=UTC)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?)',
                    ('ETHUSDT',1,100,90,120,100,2,0.1,at.isoformat()))
                connection.execute('INSERT INTO trades(symbol,side,quantity,price,fee,realized_pnl,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    ('ETHUSDT','SELL',1,110,0.1,9.7,'test',at.isoformat()))
                connection.execute('INSERT INTO trades(symbol,side,quantity,price,fee,realized_pnl,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    ('BTCUSDT','SELL',1,50,0.1,-1,'test',at.isoformat()))
                connection.commit()
            config=load_config()
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                current=paper_scorecard(connection,prices={'ETHUSDT':110},prices_at=at.isoformat(),
                    cycle_seconds=900,paper=config.paper,now=at+timedelta(minutes=1))
                stale=paper_scorecard(connection,prices={'ETHUSDT':110},prices_at=at.isoformat(),
                    cycle_seconds=900,paper=config.paper,now=at+timedelta(hours=1))
            self.assertEqual(current['price_status'],'fresh')
            self.assertEqual(current['open_positions'],1)
            self.assertEqual(current['unpriced_positions'],0)
            self.assertGreater(current['estimated_open_pnl_usdt'],0)
            self.assertEqual(current['by_asset'][0]['symbol'],'ETHUSDT')
            self.assertEqual(current['by_asset'][0]['net_realized_pnl_usdt'],9.7)
            self.assertEqual(stale['price_status'],'stale_or_missing')
            self.assertIsNone(stale['estimated_open_pnl_usdt'])
            self.assertIsNone(stale['by_asset'][0]['estimated_open_pnl_usdt'])
