import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from trader.futures_finance import financial_scorecard, milliseconds, sync_income
from trader.futures_testnet_ledger import FuturesTestnetLedger


class FuturesFinanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.ledger = FuturesTestnetLedger(Path(folder.name)/'futures.db')
        self.now = datetime(2026, 10, 9, 15, tzinfo=UTC)
        self.start = self.now-timedelta(hours=1)
        with self.ledger._connect() as db:
            db.execute('INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(5000,5000,0,?)', (self.start.isoformat(),))
            db.execute('''INSERT INTO forward_trades(symbol,direction,leverage,quantity,entry_price,
                exit_price,gross_pnl,exit_reason,opened_at,closed_at)
                VALUES('BTCUSDT','LONG',1,1,100,102,2,'TAKE_PROFIT',?,?)''',
                ((self.start+timedelta(minutes=1)).isoformat(), (self.now-timedelta(minutes=1)).isoformat()))

    def receipt(self, kind, amount, identity, *, asset='USDT', symbol='BTCUSDT'):
        instant = milliseconds(self.start)+120000 if kind=='COMMISSION' and identity==1 else milliseconds(self.now)-59500
        return dict(incomeType=kind,income=str(amount),tranId=identity,time=instant,
                    asset=asset,symbol=symbol)

    def report(self):
        with self.ledger._connect() as db:
            return financial_scorecard(db,self.ledger.setting('forward_income_sync'),now=self.now)

    def test_receipts_are_idempotent_and_funding_credits_increase_net(self):
        rows = [self.receipt('COMMISSION',-.1,1),self.receipt('COMMISSION',-.1,2),self.receipt('FUNDING_FEE',.1,1),
                self.receipt('REALIZED_PNL',2,1)]
        request=Mock(return_value=rows+rows)
        sync_income(self.ledger,now=self.now,request=request)
        sync_income(self.ledger,now=self.now+timedelta(minutes=16),request=request)
        self.now += timedelta(minutes=16)
        report=self.report()
        self.assertAlmostEqual(report['net_realized_pnl_usdt'],1.9)
        self.assertAlmostEqual(report['strategy_net_expectancy_usdt'],1.9)
        self.assertAlmostEqual(report['account_commissions_usdt'],.2)
        self.assertEqual(report['attributed_closed_trades'],1)

    def test_missing_income_and_mismatched_realized_never_mean_zero_costs(self):
        sync_income(self.ledger,now=self.now,request=Mock(return_value=[]))
        self.assertIsNone(self.report()['net_realized_pnl_usdt'])
        sync_income(self.ledger,now=self.now+timedelta(minutes=16),request=Mock(return_value=[
            self.receipt('COMMISSION',-.2,1),self.receipt('REALIZED_PNL',20,1)]))
        self.assertIsNone(self.report()['strategy_net_pnl_usdt'])

    def test_failed_page_never_advances_coverage_or_saves_partial_window(self):
        rows=[self.receipt('COMMISSION',-.1,i) for i in range(1000)]
        sync_income(self.ledger,now=self.now,request=Mock(side_effect=[rows,ValueError('read failure')]))
        state=self.ledger.setting('forward_income_sync')
        self.assertEqual(state['status'],'UNAVAILABLE')
        self.assertNotIn('through_ms',state)
        with self.ledger._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM forward_income').fetchone()[0],0)
        self.assertIsNone(self.report()['net_realized_pnl_usdt'])

    def test_foreign_fees_invalidate_attribution_and_stale_data_is_labelled(self):
        sync_income(self.ledger,now=self.now,request=Mock(return_value=[
            self.receipt('COMMISSION',-.2,1),self.receipt('COMMISSION',-.01,2,asset='BNB'),
            self.receipt('REALIZED_PNL',2,1)]))
        self.assertIsNone(self.report()['net_realized_pnl_usdt'])
        self.assertEqual(self.report()['non_usdt_receipts'],1)
        with self.ledger._connect() as db:
            report=financial_scorecard(db,self.ledger.setting('forward_income_sync'),now=self.now+timedelta(hours=1))
        self.assertEqual(report['status'],'STALE')
        self.assertIsNone(report['account_commissions_usdt'])

    def test_technical_closes_are_not_strategy_results(self):
        with self.ledger._connect() as db:
            db.execute("UPDATE forward_trades SET exit_reason='CONFIG_REPAIR'")
        sync_income(self.ledger,now=self.now,request=Mock(return_value=[
            self.receipt('COMMISSION',-.1,1),self.receipt('COMMISSION',-.1,2),self.receipt('REALIZED_PNL',2,1)]))
        self.assertAlmostEqual(self.report()['net_realized_pnl_usdt'],1.8)
        self.assertIsNone(self.report()['strategy_net_pnl_usdt'])

    def test_health_counts_more_than_200_daily_samples(self):
        with self.ledger._connect() as db:
            db.execute('DELETE FROM forward_equity')
            for index in range(288):
                instant=self.now-timedelta(seconds=(287-index)*300)
                db.execute('INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(5000,5000,0,?)',(instant.isoformat(),))
        report=self.ledger.observation_health(300,now=self.now)
        self.assertEqual(report['samples'],288)
        self.assertEqual(report['cycle_coverage_pct'],100)
        self.assertEqual(report['state'],'OK')

    def test_overlapping_positions_do_not_share_the_same_receipts(self):
        with self.ledger._connect() as db:
            db.execute('''INSERT INTO forward_trades(symbol,direction,leverage,quantity,entry_price,
                exit_price,gross_pnl,exit_reason,opened_at,closed_at)
                SELECT symbol,direction,leverage,quantity,entry_price,exit_price,gross_pnl,
                exit_reason,opened_at,closed_at FROM forward_trades''')
        sync_income(self.ledger,now=self.now,request=Mock(return_value=[
            self.receipt('COMMISSION',-.1,1),self.receipt('COMMISSION',-.1,2),self.receipt('REALIZED_PNL',2,1)]))
        self.assertIsNone(self.report()['net_realized_pnl_usdt'])
        self.assertEqual(self.report()['attributed_closed_trades'],0)
