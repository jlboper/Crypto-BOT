import json
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.domain import AIReview, Candle, Signal
from trader.engine import TradingEngine
from trader.monitoring import spot_cycle_status
from trader.portal_snapshot import dashboard_snapshot


class SpotCycleStatusTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        config = load_config()
        config = replace(config, bot=replace(config.bot, mode='paper', database_path=root/'test.db',
                                             kill_switch_path=root/'kill'))
        self.engine = TradingEngine(config)
        self.engine.db.initialize_cash(config.paper.initial_cash_usdt)
        self.candles = [Candle(i*1000, 99, 102, 98, 100, 1000, i*1000+999) for i in range(80)]
        self.maps = {'BTCUSDT': self.candles, 'TESTUSDT': self.candles}
        self.prices = {'BTCUSDT': 100, 'TESTUSDT': 100}
        self.buy = Signal('TESTUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'synthetic','now')
        self.hold = replace(self.buy, action='HOLD', score=50, stop_price=None, take_profit=None)
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(self.engine.exchange, 'top_usdt_symbols', return_value=['TESTUSDT']))
        stack.enter_context(patch.object(self.engine, '_fetch_candles', side_effect=lambda _: self.maps))
        stack.enter_context(patch.object(self.engine.exchange, 'latest_prices', side_effect=lambda _: self.prices))
        stack.enter_context(patch.object(self.engine.strategy, 'btc_regime', return_value=True))
        self.evaluate = stack.enter_context(patch.object(self.engine.strategy, 'evaluate',
            side_effect=lambda symbol, *_: self.buy if symbol == 'TESTUSDT' else replace(self.hold, symbol=symbol)))
        self.review = stack.enter_context(patch.object(self.engine.ai, 'review', return_value=AIReview('REJECT',1,0,'unit')))
        stack.enter_context(patch.object(self.engine.exchange, 'cached_symbol_info', return_value=None))

    def report(self):
        return json.loads(self.engine.db.setting('spot_last_cycle'))

    def test_no_opportunity_is_a_completed_scan_without_ai_or_trades(self):
        self.evaluate.side_effect = lambda symbol, *_: replace(self.hold, symbol=symbol)
        self.assertEqual(self.engine.cycle()['status'], 'ok')
        report = self.report()
        self.assertEqual(report['state'], 'NO_OPPORTUNITIES')
        self.assertEqual((report['universe'],report['evaluated'],report['signals'],report['reviews']), (1,2,0,0))
        self.assertEqual(report['reasons'], {'BELOW_SCORE': 2})
        self.review.assert_not_called()
        self.assertFalse(self.engine.db.recent('trades'))

    def test_ai_rejection_is_distinct_from_unavailable_ai(self):
        self.engine.cycle()
        report = self.report()
        self.assertEqual(report['state'], 'FILTERED')
        self.assertEqual((report['signals'],report['candidates'],report['reviews'],report['opened']), (1,1,1,0))
        self.assertEqual(report['reasons']['AI_REJECTED'], 1)
        self.maps['TESTUSDT'] = [replace(c, close_time=c.close_time+100000) for c in self.candles]
        self.review.return_value = AIReview('REJECT',1,0,'AI review failed safely: RuntimeError')
        self.engine.cycle()
        report = self.report()
        self.assertEqual(report['state'], 'ATTENTION')
        self.assertEqual(report['reasons']['AI_UNAVAILABLE'], 1)
        self.assertNotIn('AI_REJECTED', report['reasons'])

    def test_missing_market_data_is_not_reported_as_no_opportunity(self):
        del self.maps['TESTUSDT']
        self.engine.cycle()
        self.assertEqual(self.report()['state'], 'ATTENTION')
        self.assertEqual(self.report()['reasons']['MISSING_CANDLES'], 1)
        self.review.assert_not_called()

    def test_missing_entry_quote_is_attention_without_review(self):
        del self.prices['TESTUSDT']
        self.engine.cycle()
        self.assertEqual(self.report()['state'], 'ATTENTION')
        self.assertEqual(self.report()['reasons']['QUOTE_UNAVAILABLE'], 1)
        self.review.assert_not_called()

    def test_review_budget_and_candle_dedup_have_explicit_reasons(self):
        with patch.object(self.engine, '_ai_budget_available', return_value=False):
            self.engine.cycle()
        self.assertEqual(self.report()['state'], 'LIMITED')
        self.assertEqual(self.report()['reasons']['AI_DAILY_LIMIT'], 1)
        self.review.assert_not_called()
        self.engine.cycle()
        self.review.reset_mock()
        self.engine.cycle()
        self.assertEqual(self.report()['state'], 'FILTERED')
        self.assertEqual(self.report()['reasons']['CANDLE_ALREADY_CHECKED'], 1)
        self.review.assert_not_called()

    def test_paused_and_loss_gate_cycles_do_not_claim_a_completed_scan(self):
        self.engine.config.bot.kill_switch_path.write_text('synthetic pause')
        self.assertEqual(self.engine.cycle()['status'], 'killed')
        self.assertEqual(self.report()['state'], 'PAUSED')
        self.assertEqual(self.report()['evaluated'], 0)
        self.engine.config.bot.kill_switch_path.unlink()
        with patch.object(self.engine, '_risk_halt', return_value=True):
            self.assertEqual(self.engine.cycle()['status'], 'risk_halt')
        self.assertEqual(self.report()['state'], 'RISK_HALT')
        self.review.assert_not_called()

    def test_loss_gate_reports_exact_period_and_reset_time(self):
        detail = self.engine._risk_halt(970.0)
        self.assertEqual(detail["periods"], ["daily"])
        self.assertAlmostEqual(detail["daily_return_pct"], -3.0)
        self.assertEqual(detail["daily_limit_pct"], 2.0)
        self.assertEqual(detail["weekly_limit_pct"], 5.0)
        self.assertGreater(datetime.fromisoformat(detail["resets_at"]), datetime.now(UTC))
        self.assertEqual(self.engine.db.setting("daily_halt"),
                         datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat())

    def test_fatal_error_replaces_success_and_recovers_on_next_cycle(self):
        self.evaluate.side_effect = lambda symbol, *_: replace(self.hold, symbol=symbol)
        self.engine.cycle()
        with patch.object(self.engine.exchange, 'top_usdt_symbols', side_effect=ValueError('synthetic secret detail')):
            with self.assertRaises(ValueError):
                self.engine.cycle()
        report = self.report()
        self.assertEqual(report['state'], 'ERROR')
        self.assertEqual(report['error_code'], 'UNEXPECTED_VALUE_ERROR')
        self.assertNotIn('synthetic secret detail', json.dumps(report))
        self.assertEqual(self.engine.db.setting('consecutive_errors'), '1')
        self.engine.cycle()
        self.assertEqual(self.report()['state'], 'NO_OPPORTUNITIES')
        self.assertEqual(self.engine.db.setting('consecutive_errors'), '0')

    def test_guardrail_is_limited_without_fatal_error_or_order(self):
        self.review.return_value = AIReview('ALLOW',1,1,'unit')
        with patch.object(self.engine.broker, 'buy', side_effect=ValueError('per-trade risk limit')):
            self.engine.cycle()
        self.assertEqual(self.report()['state'], 'LIMITED')
        self.assertEqual(self.report()['reasons']['PER_TRADE_RISK_LIMIT'], 1)
        self.assertEqual(self.engine.db.setting('consecutive_errors'), '0')
        self.assertFalse(self.engine.db.recent('trades'))

    def test_diagnostic_preserves_real_paper_entry_and_projects_read_only(self):
        self.review.return_value = AIReview('ALLOW',1,1,'unit')
        self.assertEqual(self.engine.cycle()['opened'], ['TESTUSDT'])
        self.assertEqual(self.report()['state'], 'OPENED')
        self.assertEqual(self.report()['opened'], 1)
        self.assertEqual(len(self.engine.db.positions()), 1)
        self.assertEqual(len(self.engine.db.recent('trades')), 1)
        path = self.engine.db.path
        before = path.read_bytes()
        payload = dashboard_snapshot(self.engine.config, Path(self.folder.name)/'missing.json')
        self.assertEqual(payload['status']['spot_cycle']['state'], 'OPENED')
        self.assertTrue(payload['status']['spot_cycle']['fresh'])
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_invalid_and_stale_reports_never_infer_health(self):
        self.engine.cycle()
        now = datetime.now(UTC)
        report = self.report()
        self.assertIsNone(spot_cycle_status(None, 900, now))
        self.assertIsNone(spot_cycle_status('bad json', 900, now))
        for update in ({'evaluated': True}, {'state': 'UNKNOWN'}, {'signals': -1},
                       {'reasons': {'raw secret': 1}}, {'error_code': 'secret'},
                       {'at': (now+timedelta(minutes=3)).isoformat()}):
            with self.subTest(update=update):
                self.assertIsNone(spot_cycle_status({**report, **update}, 900, now))
        projected = spot_cycle_status({**report, 'at': (now-timedelta(hours=1)).isoformat(),
                                       'private': 'secret'}, 900, now)
        self.assertFalse(projected['fresh'])
        self.assertEqual(projected['age_seconds'], 3600)
        self.assertNotIn('secret', json.dumps(projected))


if __name__ == '__main__':
    unittest.main()
