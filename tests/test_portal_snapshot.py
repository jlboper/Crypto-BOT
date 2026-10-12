import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from dataclasses import replace
from trader.config import load_config
from trader.database import Database
from trader.portal_snapshot import dashboard_snapshot, public_text, _spot_observation_health, spot_observation_health
from trader.paper_scorecard import paper_scorecard
from trader.futures_testnet_ledger import FuturesTestnetLedger

class PortalSnapshotTests(unittest.TestCase):
    def spot_health(self, database, config, settings=None):
        with closing(sqlite3.connect(database.path)) as connection:
            connection.row_factory = sqlite3.Row
            latest = dict(connection.execute('SELECT * FROM equity ORDER BY id DESC LIMIT 1').fetchone())
            return _spot_observation_health(connection, config, latest, [], settings or {
                'market_prices_at': datetime.now(UTC).isoformat(), 'consecutive_errors': '0'})

    def test_spot_health_excludes_futures_events_but_keeps_unknown_alerts(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder)/'spot.db')
            database.record_equity(1000,1000,0)
            config = load_config()
            database.event('WARN','Futures Demo protection failed: FuturesTestnetExecutionError')
            database.event('ERROR','Futures Demo forward cycle failed: RuntimeError')
            health = self.spot_health(database, config)
            self.assertEqual((health['warnings'],health['errors']),(0,0))
            self.assertNotIn('warnings_observed',health['reason_codes'])
            database.event('WARN','Spot order protection warning')
            database.event('WARN','Unclassified warning must remain visible')
            database.event('ERROR','Unclassified error must remain visible')
            health = self.spot_health(database, config)
            self.assertEqual((health['warnings'],health['errors']),(2,1))
            self.assertIn('warnings_observed',health['reason_codes'])
            self.assertIn('errors_observed',health['reason_codes'])

    def test_legacy_spot_recovery_requires_completed_cycle_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder)/'spot.db')
            now = datetime.now(UTC)
            error = {'code':'UNEXPECTED_VALUE_ERROR','at':(now-timedelta(hours=2)).isoformat(),
                     'consecutive_errors':282}
            recovered = (now-timedelta(hours=1)).astimezone(timezone(timedelta(hours=-6))).isoformat()
            database.record_equity(1000,1000,0)
            database.event('INFO','Cycle complete: 60 symbols, 0 buys, opened 0')
            with closing(sqlite3.connect(database.path)) as connection:
                connection.execute('UPDATE events SET created_at=?',(recovered,))
                connection.commit()
            settings = {'market_prices_at':now.isoformat(),'consecutive_errors':'0',
                        'spot_last_error':json.dumps(error)}
            before = database.path.read_bytes()
            health = self.spot_health(database,load_config(),settings)
            self.assertIsNone(health['last_error'])
            self.assertEqual(json.loads(settings['spot_last_error']),error)
            self.assertEqual(health['last_recovery'],{'recovered_errors':282,'at':recovered})
            self.assertNotIn('consecutive_errors_active',health['reason_codes'])
            self.assertNotIn('spot_last_recovery',settings)
            self.assertEqual(database.path.read_bytes(),before)

    def test_spot_recovery_is_not_inferred_from_zero_counter_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder)/'spot.db')
            database.record_equity(1000,1000,0)
            now = datetime.now(UTC)
            for active, offset, event in ((0,-3600,False),(3,-3600,True),(0,3600,True)):
                with self.subTest(active=active,offset=offset,event=event):
                    if event:
                        database.event('INFO','Cycle complete: 60 symbols, 0 buys, opened 0')
                    settings = {'market_prices_at':now.isoformat(),'consecutive_errors':str(active),
                        'spot_last_error':json.dumps({'at':(now+timedelta(seconds=offset)).isoformat()})}
                    health=self.spot_health(database,load_config(),settings)
                    self.assertIsNone(health['last_recovery'])
                    self.assertIsNotNone(health['last_error'])

    def test_current_diagnostic_clears_only_after_confirmed_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'spot.db')
            db.record_equity(1000,1000,0)
            now=datetime.now(UTC)
            error={'code':'TESTNET_EXECUTION_ERROR','at':(now-timedelta(hours=1)).isoformat()}
            for counter,recovery,cleared in (
                    (0,(now-timedelta(minutes=30)).isoformat(),True),
                    (2,(now-timedelta(minutes=30)).isoformat(),False),
                    (0,(now-timedelta(hours=2)).isoformat(),False),
                    (0,'invalid timestamp',False)):
                with self.subTest(counter=counter,recovery=recovery):
                    settings={'market_prices_at':now.isoformat(),'consecutive_errors':str(counter),
                        'spot_last_error':json.dumps(error),
                        'spot_last_recovery':json.dumps({'at':recovery,'recovered_errors':1})}
                    health=self.spot_health(db,load_config(),settings)
                    self.assertEqual(health['last_error'],None if cleared else error)
                    self.assertEqual(json.loads(settings['spot_last_error']),error)

    def test_local_observation_reader_preserves_database_and_unknown_alerts(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'spot.db'
            db=Database(path)
            db.record_equity(1000,1000,0)
            db.record_market_snapshot({'BTCUSDT':100})
            error={'code':'UNEXPECTED_VALUE_ERROR','at':datetime.now(UTC).isoformat()}
            db.set_setting('spot_last_error',json.dumps(error))
            db.set_setting('consecutive_errors','1')
            db.event('WARN','unknown alert')
            config=load_config()
            config=replace(config,bot=replace(config.bot,database_path=path))
            before=path.read_bytes()
            health=spot_observation_health(config)
            self.assertEqual(health['last_error'],error)
            self.assertEqual(health['consecutive_errors'],1)
            self.assertEqual(health['warnings'],1)
            self.assertEqual(path.read_bytes(),before)

    def test_low_spot_coverage_is_watch_only_while_latest_cycle_is_fresh(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder)/'spot.db')
            database.record_equity(1000,1000,0)
            database.record_equity(1000,1000,0)
            with closing(sqlite3.connect(database.path)) as connection:
                connection.execute('UPDATE equity SET created_at=? WHERE id=1',
                                   ((datetime.now(UTC)-timedelta(hours=23)).isoformat(),))
                connection.commit()
            config=load_config()
            health=self.spot_health(database,config)
            self.assertLess(health['cycle_coverage_pct'],70)
            self.assertEqual(health['state'],'WATCH')
            self.assertIn('cycle_coverage_below_90',health['reason_codes'])
            with closing(sqlite3.connect(database.path)) as connection:
                connection.execute('UPDATE equity SET created_at=? WHERE id=2',
                    ((datetime.now(UTC)-timedelta(seconds=config.bot.cycle_seconds*3)).isoformat(),))
                connection.commit()
            health=self.spot_health(database,config)
            self.assertEqual(health['state'],'ATTENTION')
            self.assertIn('cycle_stale',health['reason_codes'])

    def test_financial_strategy_result_excludes_smoke_and_reconciles_flat_allocation(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'spot.db')
            db.record_trade('BTCUSDT','SELL',1,100,0,-2,'TESTNET protective stop')
            db.record_trade('BTCUSDT','SELL',1,100,0,-.01,'TESTNET supervised smoke SELL')
            db.record_equity(997.99,997.99,0)
            with closing(sqlite3.connect(db.path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                report=paper_scorecard(connection,paper=load_config().paper)
            finance=report['financial']
            self.assertEqual(finance['strategy_closed_trades'],1)
            self.assertEqual(finance['technical_closed_trades'],1)
            self.assertEqual(finance['strategy_net_expectancy_usdt'],-2)
            self.assertEqual(finance['flat_allocation_reconciliation_usdt'],0)
            self.assertEqual(finance['result'],'NEGATIVE_EXPECTANCY')

    def test_breakeven_close_does_not_dilute_average_loss_or_invent_open_exposure(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'spot.db')
            for pnl in (-6, 0, 3):
                db.record_trade('BTCUSDT','SELL',1,100,0,pnl,'test')
            with closing(sqlite3.connect(db.path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                report=paper_scorecard(connection)
            self.assertEqual(report['closed_trades'],3)
            self.assertEqual(report['average_loss_usdt'],-6)
            self.assertEqual(report['average_win_usdt'],3)
            self.assertEqual(report['expectancy_usdt_per_close'],-1)
            self.assertEqual(report['by_asset'][0]['open_exposure_usdt'],0)
            self.assertEqual(report['by_asset'][0]['estimated_open_pnl_usdt'],0)

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
            self.assertEqual(payload['status']['mode'],'TESTNET')
            self.assertEqual(payload['status']['risk']['max_position_pct'],config.risk.max_position_pct)
            self.assertEqual(payload['research']['assets'],[])
            self.assertEqual(payload['paper_scorecard']['status'],'INSUFFICIENT_EVIDENCE')
            self.assertEqual(payload['paper_scorecard']['closed_trades'],0)
            self.assertIn(payload['status']['observation_health']['state'], {'STARTING','OK','WATCH','ATTENTION'})
            self.assertGreaterEqual(payload['status']['observation_health']['cycle_coverage_pct'],0)
            self.assertIn('order_journal_clear',payload['status']['observation_health']['integrity'])
            self.assertIn('warnings_observed',payload['status']['observation_health']['reason_codes'])
            self.assertEqual(payload['status']['observation_health']['consecutive_errors'],0)
            self.assertIsNone(payload['status']['observation_health']['last_error'])
            self.assertIn('observation_health',payload['futures_forward'])
            self.assertIn('order_journal_clear',payload['futures_forward']['observation_health']['integrity'])
            self.assertEqual(payload['futures_forward']['guardrails']['max_positions'],10)
            self.assertEqual(payload['futures_forward']['guardrails']['forward_timeframe'],'1h')
            self.assertEqual(payload['futures_forward']['guardrails']['forward_min_score'],70)
            self.assertEqual(payload['futures_forward']['guardrails']['margin_type'],'ISOLATED')
            self.assertEqual(payload['futures_forward']['guardrails']['forward_margin_usdt'],100.0)
            self.assertEqual(payload['futures_forward']['automatic_leverage'],1)
            self.assertEqual(len(payload['futures_forward']['symbols']),15)
            self.assertEqual(len(payload['futures_forward']['latest_signals']),15)
            self.assertEqual(payload['futures_forward']['guardrails']['forward_total_notional_usdt'],300)
            self.assertEqual(payload['futures_forward']['guardrails']['forward_total_stop_loss_usdt'],7.5)
            self.assertNotIn('TEST_CREDENTIAL',json.dumps(payload))
            self.assertNotIn('example.test',json.dumps(payload))
            self.assertEqual(path.read_bytes(),before)

    def test_futures_pause_diagnostics_expose_bounded_remote_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            spot=root/'spot.db'
            futures=root/'futures.db'
            kill=root/'FUTURES_KILL_SWITCH'
            config=load_config()
            config=replace(config,
                bot=replace(config.bot,database_path=spot,kill_switch_path=root/'SPOT_KILL_SWITCH'),
                futures_testnet=replace(config.futures_testnet,database_path=futures,kill_switch_path=kill))
            db=Database(spot)
            db.initialize_cash(1000)
            db.record_equity(1000,1000,0)
            ledger=FuturesTestnetLedger(futures)
            ledger.set_setting('forward_consecutive_errors',18)
            ledger.set_setting('forward_protection_consecutive_errors',3)
            ledger.set_setting('forward_last_error',{'message':'three consecutive Futures protection errors','at':'2026-09-27T16:40:24+00:00'})
            ledger.set_setting('forward_last_protection_error',{'message':'FuturesTestnetExecutionError: Futures mark price unavailable','at':'2026-09-27T16:40:23+00:00'})
            ledger.set_setting('forward_pending_order',{'symbol':'SOLUSDT'})
            kill.write_text('three consecutive Futures protection errors\n',encoding='utf-8')
            payload=dashboard_snapshot(config,root/'missing.json')
            diag=payload['futures_forward']['pause_diagnostics']
            self.assertTrue(diag['active'])
            self.assertEqual(diag['source'],'automatic_safety')
            self.assertEqual(diag['label'],'3 errores consecutivos de protección Futures')
            self.assertEqual(diag['consecutive_errors'],3)
            self.assertTrue(diag['pending_reconciliation'])
            self.assertEqual(diag['last_error']['message'],'FuturesTestnetExecutionError: Futures mark price unavailable')
            self.assertIsNotNone(diag['paused_at'])

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
            self.assertEqual(result['gross_profit_usdt'],40)
            self.assertEqual(result['gross_loss_usdt'],-10)
            self.assertEqual(result['average_win_usdt'],2)
            self.assertEqual(result['average_loss_usdt'],-1)
            self.assertEqual(result['expectancy_usdt_per_close'],1)
            self.assertAlmostEqual(result['fees_to_abs_net_pnl_pct'],20.33,places=2)
            self.assertFalse(result['mae_mfe_available'])
            self.assertIn('intratrade_mae_mfe_not_recorded',result['limitations'])
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
