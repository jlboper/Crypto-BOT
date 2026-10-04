import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.domain import Candle, AIReview
from trader.futures_forward import FuturesForwardEngine
from trader.futures_testnet import FuturesTestnetExecutionError


class FuturesLeverageTrialTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        base = load_config()
        self.config = replace(base, futures_testnet=replace(base.futures_testnet,
            database_path=self.root / 'f.db', kill_switch_path=self.root / 'KILL'))
        self.engine = FuturesForwardEngine(self.config, None)
        self.account = dict(wallet_balance=5000, available_balance=5000, unrealized_pnl=0)
        self.signal = dict(direction='LONG', score=80, long_score=80, short_score=10,
            price=100, atr=2, rsi=60, ema_fast=99, ema_slow=98, volume_ratio=1.4)
        self.rows = {}
        self.desired = {}
        self.orders = []

    def flat(self, symbol, leverage=1):
        if symbol in self.rows:
            raise FuturesTestnetExecutionError('not flat')
        self.desired[symbol] = leverage
        return dict(symbol=symbol, leverage=str(leverage), marginType='isolated', positionAmt='0')

    def submit(self, *, symbol, side, quantity, reduce_only):
        self.orders.append((symbol, quantity, self.desired[symbol]))
        self.rows[symbol] = dict(symbol=symbol, positionAmt=str(quantity), entryPrice='100',
            markPrice='100', leverage=str(self.desired[symbol]), marginType='isolated', positionSide='BOTH', liquidationPrice='1')
        return dict(avgPrice='100', status='FILLED')

    def enter(self, symbol, candle_id=1, verdict="ALLOW", quantity='.1', review_effect=None, size_effect=None):
        candle = Candle(open_time=0, close_time=candle_id, open=100, high=101, low=99, close=100, volume=100)
        with patch.object(self.engine, '_actual_rows', side_effect=lambda s: [self.rows[s]] if s in self.rows else []), \
             patch.object(self.engine.lab, '_position_rows', side_effect=lambda *a: list(self.rows.values())), \
             patch.object(self.engine, '_signal', return_value=self.signal), \
             patch.object(self.engine.lab, '_reference', return_value=(Decimal('100'), None)), \
             patch.object(self.engine.lab, 'forward_quantity', return_value=(Decimal(quantity), Decimal('100')), side_effect=size_effect), \
             patch.object(self.engine.lab, 'ensure_flat_forward_configuration', side_effect=self.flat), \
             patch.object(self.engine.lab, 'ensure_forward_position_configuration', side_effect=lambda s,r,l=1:r), \
             patch.object(self.engine.lab, 'forward_submit', side_effect=self.submit), \
             patch.object(self.engine.ai, 'review_futures', return_value=AIReview(verdict, .9, 1 if verdict == 'ALLOW' else 0, 'test'), side_effect=review_effect), \
             patch.object(self.engine.native, 'ensure'):
            return self.engine.cycle_symbol(symbol, [candle], self.account)

    def test_confirmed_entries_rotate_without_multiplying_quantity_and_keep_position_cap(self):
        for symbol, leverage in zip(self.engine.symbols[:5], (1,2,3,1,2)):
            result = self.enter(symbol)
            self.assertEqual(result['status'], 'OPENED')
            self.assertEqual(result['position']['leverage'], leverage)
            self.assertEqual(result['position']['quantity'], .1)
            self.assertEqual(result['signal']['proposed_notional_usdt'], 10)
        self.assertEqual([o[2] for o in self.orders], [1,2,3,1,2])
        self.assertEqual(self.enter('ADAUSDT')['status'], 'POSITION_LIMIT')
        self.assertEqual(len(self.orders), 5)
        self.assertEqual(self.engine.ledger.setting('forward_leverage_trial_cursor'), 5)

    def test_one_unavailable_candidate_does_not_pause_other_assets(self):
        result=self.enter('NEARUSDT',size_effect=FuturesTestnetExecutionError('contract unavailable'))
        self.assertEqual(result['status'],'ASSET_UNAVAILABLE')
        self.assertEqual(self.orders,[])
        self.assertFalse(self.engine.killed())
        self.assertEqual(self.enter('ETHUSDT')['status'],'OPENED')

    def test_aggregate_stop_budget_blocks_new_entry_but_preserves_existing_positions(self):
        self.assertEqual(self.enter('BTCUSDT', quantity='1')['status'], 'BUDGET_LIMIT')
        self.assertEqual(self.enter('BTCUSDT', candle_id=2, quantity='.7')['status'], 'OPENED')
        self.assertEqual(self.enter('ETHUSDT', quantity='.7')['status'], 'OPENED')
        self.assertEqual(self.enter('SOLUSDT', quantity='.7')['status'], 'BUDGET_LIMIT')
        self.assertEqual(len(self.engine.ledger.forward_positions()), 2)
        self.assertFalse(self.engine.killed())

    def test_gross_notional_never_nets_long_against_short(self):
        for symbol, direction in [('BTCUSDT','LONG'), ('ETHUSDT','SHORT')]:
            self.engine.ledger.set_forward_position(dict(symbol=symbol, direction=direction, leverage=1,
                quantity=1.4, entry_price=100, stop_price=100, take_profit=110,
                liquidation_price=1, signal_score=80, opened_at='2026-10-04T03:00:00Z'))
            self.rows[symbol] = dict(symbol=symbol, positionAmt='1.4' if direction=='LONG' else '-1.4',
                markPrice='100', leverage='1', marginType='isolated', positionSide='BOTH')
        self.assertEqual(self.enter('ADAUSDT', quantity='.3')['status'], 'BUDGET_LIMIT')
        self.assertEqual(self.engine.ledger.setting('forward_portfolio_budget')['notional_usdt'], 280)
        self.assertEqual(self.orders, [])

    def test_budget_is_refreshed_after_ai_and_missing_mark_or_untracked_exposure_blocks(self):
        self.enter('BTCUSDT', quantity='.1')
        def review(*args):
            self.rows['BTCUSDT']['markPrice'] = '200'
            return AIReview('ALLOW', .9, 1, 'unit')
        self.assertEqual(self.enter('ETHUSDT', review_effect=review)['status'], 'BUDGET_LIMIT')
        self.assertEqual(len(self.orders), 1)
        self.rows['BTCUSDT']['markPrice'] = '0'
        with self.assertRaisesRegex(FuturesTestnetExecutionError, 'mark price unavailable'):
            self.enter('ADAUSDT')
        self.rows['UNKNOWNUSDT'] = dict(symbol='UNKNOWNUSDT',positionAmt='1')
        with self.assertRaisesRegex(FuturesTestnetExecutionError, 'Untracked Futures exposure'):
            self.enter('LINKUSDT')

    def test_restore_blocks_expanded_asset_pending_plan_and_four_positions(self):
        from trader.native_protection_compat import require_native_compatible
        (self.root / 'config.toml').write_text('[bot]\nfutures_testnet_database_path="f.db"\n')
        target=self.root/'previous'
        (target/'trader').mkdir(parents=True)
        (target/'trader/native_protection.py').write_text('NATIVE_PROTECTION_PROTOCOL = 1')
        (target/'trader/futures_forward.py').write_text('FUTURES_LEVERAGE_TRIAL_PROTOCOL = 1')
        self.engine.ledger.set_setting('forward_open_plan', dict(symbol='ADAUSDT',leverage=1))
        with self.assertRaisesRegex(RuntimeError, 'expanded positions or plan'):
            require_native_compatible(self.root,target)
        self.engine.ledger.set_setting('forward_open_plan',None)
        for symbol in self.engine.symbols[:4]:
            self.enter(symbol)
        with self.assertRaisesRegex(RuntimeError, 'expanded positions or plan'):
            require_native_compatible(self.root,target)
        (target/'trader/futures_forward.py').write_text('FUTURES_LEVERAGE_TRIAL_PROTOCOL = 1\nFUTURES_PORTFOLIO_PROTOCOL = 1')
        require_native_compatible(self.root,target)
        self.assertTrue(self.engine.ledger.observation_health(900,max_positions=5)['integrity']['local_position_count_valid'])

    def test_rejected_ai_does_not_consume_rotation_or_submit(self):
        self.assertEqual(self.enter('BTCUSDT', verdict='REJECT')['status'], 'AI_REJECTED')
        self.assertEqual(self.orders, [])
        self.assertIsNone(self.engine.ledger.setting('forward_leverage_trial_cursor'))

    def test_trial_rejects_excess_notional_and_stop_that_consumes_margin(self):
        self.engine.ledger.set_setting('forward_leverage_trial_cursor', 2)
        self.assertEqual(self.enter('BTCUSDT', quantity='2')['status'], 'BUDGET_LIMIT')
        self.signal['atr'] = 15
        self.assertEqual(self.enter('ETHUSDT')['status'], 'TRIAL_MARGIN_RISK_LIMIT')
        self.assertEqual(self.orders, [])
        self.assertEqual(self.engine.ledger.setting('forward_leverage_trial_cursor'), 2)

    def test_restart_recovers_three_x_plan_and_advances_rotation_once(self):
        ledger = self.engine.ledger
        plan = dict(symbol='XRPUSDT', direction='LONG', leverage=3, leverage_trial_index=2,
            score=80, atr=2, opened_at='2026-10-04T03:00:00+00:00')
        pending = dict(symbol='XRPUSDT', side='BUY', quantity='.1', reduce_only=False, client_order_id='owned')
        row = dict(symbol='XRPUSDT', positionAmt='.1', entryPrice='100', leverage='3',
            marginType='isolated', positionSide='BOTH', liquidationPrice='65')
        ledger.set_setting('forward_open_plan', plan)
        ledger.set_setting('forward_pending_order', pending)
        with patch.object(self.engine, '_actual_rows', return_value=[row]), \
             patch.object(self.engine.lab, 'ensure_forward_position_configuration', return_value=row) as repair, \
             patch.object(self.engine.lab, 'forward_submit') as submit:
            self.assertEqual(self.engine._recover_journal()['status'], 'RECOVERED_OPEN')
        repair.assert_called_once_with('XRPUSDT', row, 3)
        submit.assert_not_called()
        self.assertEqual(ledger.forward_position('XRPUSDT')['leverage'], 3)
        self.assertEqual(ledger.setting('forward_leverage_trial_cursor'), 3)
        position = self.engine._reconstruct_open_position('XRPUSDT', pending, plan, row)
        ledger.set_forward_position(position)
        self.assertEqual(ledger.setting('forward_leverage_trial_cursor'), 3)

    def test_three_x_preserves_native_stop_and_reduce_only_close(self):
        self.engine.ledger.set_setting('forward_leverage_trial_cursor', 2)
        local = self.enter('XRPUSDT')['position']
        self.assertEqual(local['leverage'], 3)
        self.assertLess(local['stop_price'], local['entry_price'])
        self.assertGreater(local['stop_price'], local['liquidation_price'])
        def close(**kwargs):
            self.rows.pop(kwargs['symbol'])
            return dict(avgPrice='105')
        with patch.object(self.engine, '_actual_rows', side_effect=lambda s:[self.rows[s]] if s in self.rows else []), \
             patch.object(self.engine.lab, 'ensure_forward_position_configuration', side_effect=lambda s,r,l:r), \
             patch.object(self.engine.lab, 'forward_submit', side_effect=close) as submit, \
             patch.object(self.engine.lab, '_execution_price', return_value=Decimal('105')):
            trade = self.engine._close(local, 'TAKE_PROFIT')
        self.assertEqual(trade['leverage'], 3)
        self.assertTrue(submit.call_args.kwargs['reduce_only'])
        self.assertEqual(self.engine.ledger.leverage_trial_status((1,2,3), 100)['results'][2]['closed_trades'], 1)

    def test_config_rejects_expanded_caps_and_nonfinite_portfolio_limits(self):
        source=Path('config.toml').read_text()
        path=self.root/'invalid.toml'
        for old,new in [('forward_max_positions = 5','forward_max_positions = 6'),
                        ('forward_total_notional_usdt = 300.0','forward_total_notional_usdt = 301'),
                        ('forward_total_stop_loss_usdt = 7.5','forward_total_stop_loss_usdt = nan'),
                        ('forward_total_stop_loss_usdt = 7.5','forward_total_stop_loss_usdt = 8'),
                        ('forward_cost_buffer_pct = 0.005','forward_cost_buffer_pct = 0')]:
            path.write_text(source.replace(old,new))
            with self.assertRaises(ValueError): load_config(path)

    def test_config_rejects_invalid_trial_levels_and_old_config_defaults_to_one(self):
        source = Path('config.toml').read_text()
        path = self.root / 'config.toml'
        for value in ('[1,4]', '[1,2,2]', '[true]', '[]', '[1.0,2]'):
            path.write_text(source.replace('forward_leverage_trials = [1, 2, 3]', 'forward_leverage_trials = '+value))
            with self.assertRaisesRegex(ValueError, 'leverage trials'):
                load_config(path)
        path.write_text(source.replace('forward_leverage_trials = [1, 2, 3]', ''))
        self.assertEqual(load_config(path).futures_testnet.forward_leverage_trials, (1,))

    def test_restore_to_old_code_blocks_open_and_pending_leveraged_positions(self):
        from trader.native_protection_compat import require_native_compatible
        (self.root / 'config.toml').write_text('[bot]\nfutures_testnet_database_path="f.db"\n')
        target = self.root / 'previous'
        (target / 'trader').mkdir(parents=True)
        (target / 'trader/native_protection.py').write_text('NATIVE_PROTECTION_PROTOCOL = 1')
        self.engine.ledger.set_setting('forward_leverage_trial_cursor', 2)
        self.enter('XRPUSDT')
        with self.assertRaisesRegex(RuntimeError, '2x/3x position'):
            require_native_compatible(self.root, target)
        self.engine.ledger.set_forward_position(None, 'XRPUSDT')
        self.engine.ledger.set_setting('forward_open_plan', dict(leverage=2))
        with self.assertRaisesRegex(RuntimeError, 'pending 2x/3x plan'):
            require_native_compatible(self.root, target)
        (target / 'trader/futures_forward.py').write_text('FUTURES_LEVERAGE_TRIAL_PROTOCOL = 1')
        require_native_compatible(self.root, target)
