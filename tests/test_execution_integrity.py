"""Regressions for the execution audit; only isolated ledgers and fake transports."""
import copy
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from trader.config import load_config
from trader.database import Database
from trader.domain import AIReview, Candle, Signal
from trader.engine import TradingEngine
from trader.futures_forward import FuturesForwardEngine
from trader.futures_testnet import FuturesTestnetExecutionError
from trader.futures_testnet_ledger import FuturesTestnetLedger
from trader.portal_snapshot import dashboard_snapshot
from trader.testnet import plan_order
from trader.testnet_broker import BinanceTestnetBroker


class ExecutionIntegrityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        base = load_config()
        self.config = replace(base,
            bot=replace(base.bot, database_path=self.root/'spot.db', kill_switch_path=self.root/'spot.kill'),
            futures_testnet=replace(base.futures_testnet, database_path=self.root/'futures.db',
                                   kill_switch_path=self.root/'futures.kill'))
        self.engine = FuturesForwardEngine(self.config, None)
        self.ledger = self.engine.ledger
        self.db = Database(self.config.bot.database_path)
        self.broker = BinanceTestnetBroker(self.db, self.config.paper, self.config.risk)
        self.signal = Signal('BTCUSDT','BUY',80,100,95,110,2,60,101,99,1.3,'unit','now')
        self.fs = dict(direction='LONG',score=80,long_score=80,short_score=10,
                       price=100.,atr=2.,rsi=60.,ema_fast=101.,ema_slow=99.,volume_ratio=1.3)
        self.candles = [Candle(0,99.,101.,98.,100.,10.,999)]
        self.account = dict(wallet_balance=1000,available_balance=1000,unrealized_pnl=0)

    def pending_buy(self):
        return dict(client_order_id='buy-one',symbol='BTCUSDT',side='BUY',signal=self.signal.to_dict(),
                    executed_qty='0.1',cumulative_quote='10',commission_quote='0',commission_base='0',
                    status='FILLED',reason='unit')

    def position(self):
        return dict(symbol='BTCUSDT',direction='LONG',leverage=1,quantity=.1,entry_price=100,
                    stop_price=95,take_profit=110,liquidation_price=None,signal_score=80,
                    opened_at=datetime.now(UTC).isoformat())

    def test_exposed_v3_row_joins_symbol_config_without_any_order(self):
        row = dict(symbol='BTCUSDT',positionAmt='.1',entryPrice='100',positionSide='BOTH')
        def signed(method, endpoint, fields):
            self.assertEqual(method,'GET')
            if endpoint == '/fapi/v3/positionRisk': return [row]
            self.assertEqual(endpoint,'/fapi/v1/symbolConfig')
            return [dict(symbol='BTCUSDT',marginType='ISOLATED',leverage=1)]
        with patch('trader.futures_testnet.signed_request',side_effect=signed) as request:
            actual = self.engine.lab._position_rows('BTCUSDT')[0]
        self.assertEqual(actual['marginType'],'isolated')
        self.assertEqual(actual['leverage'],1)
        self.assertEqual(request.call_count,2)

    def test_crossed_configuration_is_normalized(self):
        with patch('trader.futures_testnet.signed_request',return_value=[
                dict(symbol='BTCUSDT',marginType='CROSSED',leverage=1)]):
            self.assertEqual(self.engine.lab._symbol_config('BTCUSDT')['marginType'],'cross')

    def test_missing_configuration_never_triggers_a_repair_close(self):
        row=dict(symbol='BTCUSDT',positionAmt='.1',entryPrice='100',positionSide='BOTH')
        with patch.object(self.engine.lab,'forward_submit') as submit:
            with self.assertRaisesRegex(FuturesTestnetExecutionError,'not confirmed'):
                self.engine._repair_cross_position(self.position(),row)
            submit.assert_not_called()

    def test_market_and_lot_steps_are_both_enforced(self):
        info=dict(symbol='BTCUSDT',filters=[
            dict(filterType='LOT_SIZE',minQty='.001',maxQty='10',stepSize='.002'),
            dict(filterType='MARKET_LOT_SIZE',minQty='.001',maxQty='.02',stepSize='.003')])
        plan=plan_order('BTCUSDT','BUY',1000,info,quantity=.017)
        self.assertEqual(Decimal(plan.quantity),Decimal('.012'))
        self.assertEqual(plan.status,'READY_FOR_MANUAL_REVIEW')
        too_large=plan_order('BTCUSDT','BUY',1000,info,quantity=.1)
        self.assertNotEqual(too_large.status,'READY_FOR_MANUAL_REVIEW')

    def test_spot_crash_rolls_back_cash_trade_position_and_applied_marker(self):
        pending=self.pending_buy()
        self.broker._save_pending(pending)
        with patch.object(self.broker,'_save_pending',side_effect=RuntimeError('power loss')):
            with self.assertRaises(RuntimeError): self.broker._apply_terminal_fill(pending)
        self.assertEqual(self.db.cash(),self.config.paper.initial_cash_usdt)
        self.assertIsNone(self.db.position('BTCUSDT'))
        self.assertEqual(self.db.recent('trades',10),[])
        self.assertFalse(pending.get('applied'))
        self.broker._apply_terminal_fill(pending)
        self.assertAlmostEqual(self.db.cash(),self.config.paper.initial_cash_usdt-10)

    def test_partial_sell_receipt_survives_restart_and_stale_journal_replay(self):
        self.broker._apply_terminal_fill(self.pending_buy())
        pending=dict(client_order_id='sell-one',symbol='BTCUSDT',side='SELL',
            position=self.db.position('BTCUSDT').to_dict(),executed_qty='.04',cumulative_quote='4.4',
            commission_quote='0',commission_base='0',status='CANCELED',reason='partial')
        original=copy.deepcopy(pending)
        self.broker._apply_terminal_fill(pending)
        cash=self.db.cash()
        broker=BinanceTestnetBroker(Database(self.db.path),self.config.paper,self.config.risk)
        broker._apply_terminal_fill(original)
        self.assertEqual(self.db.cash(),cash)
        self.assertAlmostEqual(self.db.position('BTCUSDT').quantity,.06)
        self.assertEqual(len(self.db.recent('trades',10)),2)
        self.assertAlmostEqual(original['realized_pnl'],.4)

    def test_base_asset_buy_fee_reconciles_realized_pnl_with_cash_loss(self):
        buy=self.pending_buy(); buy['commission_base']='.001'
        self.broker._apply_terminal_fill(buy)
        sell=dict(client_order_id='sell-one',symbol='BTCUSDT',side='SELL',
            position=self.db.position('BTCUSDT').to_dict(),executed_qty='.099',cumulative_quote='9.9',
            commission_quote='0',commission_base='0',status='FILLED',reason='close')
        self.broker._apply_terminal_fill(sell)
        self.assertAlmostEqual(sell['realized_pnl'],-.1)
        self.assertAlmostEqual(self.db.cash()-self.config.paper.initial_cash_usdt,-.1)
        self.assertAlmostEqual(sum(t['fee'] for t in self.db.recent('trades',10)),.1)

    def test_once_per_closed_candle_persists_across_engine_restart(self):
        for engine in (self.engine,FuturesForwardEngine(self.config,None)):
            with patch.object(engine,'_validated_rows',return_value=[]), \
                 patch.object(engine,'_signal',return_value=self.fs), \
                 patch.object(engine.lab,'_position_rows',return_value=[]), \
                 patch.object(engine.lab,'_reference',return_value=(Decimal('100'),None)), \
                 patch.object(engine.lab,'forward_quantity',return_value=(Decimal('.1'),Decimal('100'))), \
                 patch.object(engine.ai,'review_futures',return_value=AIReview('REJECT',1,0,'unit')) as review:
                result=engine.cycle_symbol('ETHUSDT',self.candles,self.account)
                if engine is self.engine:
                    self.assertEqual(result['status'],'AI_REJECTED'); review.assert_called_once()
                    proposal=review.call_args.args[0]
                    self.assertEqual(proposal['symbol'],'ETHUSDT')
                    self.assertEqual(proposal['proposed_notional_usdt'],10.)
                    self.assertEqual(proposal['estimated_stop_loss_usdt'],.4)
                else:
                    self.assertEqual(result['status'],'NO_NEW_CANDLE'); review.assert_not_called()

    def test_pause_during_ai_review_prevents_open_write(self):
        def review(*args):
            self.config.futures_testnet.kill_switch_path.write_text('owner pause')
            return AIReview('ALLOW',1,1,'unit')
        with patch.object(self.engine,'_validated_rows',return_value=[]), \
             patch.object(self.engine,'_signal',return_value=self.fs), \
             patch.object(self.engine.lab,'_position_rows',return_value=[]), \
             patch.object(self.engine.lab,'_reference',return_value=(Decimal('100'),None)), \
             patch.object(self.engine.lab,'forward_quantity',return_value=(Decimal('.1'),Decimal('100'))), \
             patch.object(self.engine.ai,'review_futures',side_effect=review), \
             patch.object(self.engine.lab,'forward_submit') as submit:
            self.assertEqual(self.engine.cycle_symbol('BTCUSDT',self.candles,self.account)['status'],'KILLED')
            submit.assert_not_called()

    def test_notional_ceiling_is_strict_and_blocks_before_ai(self):
        with patch.object(self.engine,'_validated_rows',return_value=[]), \
             patch.object(self.engine,'_signal',return_value=self.fs), \
             patch.object(self.engine.lab,'_position_rows',return_value=[]), \
             patch.object(self.engine.lab,'_reference',return_value=(Decimal('100'),None)), \
             patch.object(self.engine.lab,'forward_quantity',return_value=(Decimal('1.01'),Decimal('100'))), \
             patch.object(self.engine.ai,'review_futures') as review:
            self.assertEqual(self.engine.cycle_symbol('BTCUSDT',self.candles,self.account)['status'],'BUDGET_LIMIT')
            review.assert_not_called()

    def test_futures_ai_budget_is_durable_and_bounded(self):
        self.assertTrue(self.ledger.claim_ai_budget(1))
        self.assertFalse(FuturesTestnetLedger(self.config.futures_testnet.database_path).claim_ai_budget(1))

    def test_daily_loss_gate_is_independent_and_latched(self):
        now=datetime.now(UTC)
        with self.ledger._connect() as db:
            db.execute('INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)',
                       (1000,1000,0,(now-timedelta(days=1)).isoformat()))
        self.assertTrue(self.engine._risk_halt(dict(wallet_balance=970,unrealized_pnl=0)))
        self.assertTrue(self.engine._risk_halt(dict(wallet_balance=1000,unrealized_pnl=0)))
        self.assertEqual(self.ledger.forward_scorecard()['risk_halt'],{'active':True,'period':'daily'})
        self.assertFalse(self.config.bot.kill_switch_path.exists())
        self.assertFalse(self.config.futures_testnet.kill_switch_path.exists())

    def test_equity_history_over_1000_points_keeps_observation_and_drawdown(self):
        now=datetime.now(UTC)
        with self.ledger._connect() as db:
            db.executemany('INSERT INTO forward_equity(wallet_balance,available_balance,unrealized_pnl,created_at) VALUES(?,?,?,?)',
                [(1000 if i==0 else 900,900,0,(now-timedelta(days=31)+timedelta(minutes=i)).isoformat()) for i in range(1001)])
        self.ledger.record_forward_equity(950,950,0)
        card=self.ledger.forward_scorecard()
        self.assertEqual(card['equity_points'],1002)
        self.assertGreaterEqual(card['observed_days'],31)
        self.assertAlmostEqual(card['sampled_max_drawdown_pct'],10)

    def test_technical_closes_cannot_satisfy_strategy_evidence_threshold(self):
        for reason in ['CONFIG_REPAIR','RECOVERED_CLOSE','STOP']:
            self.ledger.set_forward_position(self.position())
            self.ledger.close_forward_position(symbol='BTCUSDT',exit_price=90,gross_pnl=-1,exit_reason=reason)
        card=self.ledger.forward_scorecard()
        self.assertEqual(card['closed_trades'],3)
        self.assertEqual(card['technical_closed_trades'],2)
        self.assertEqual(card['strategy_closed_trades'],1)
        self.assertEqual(card['strategy_gross_pnl_usdt'],-1)

    def test_shadow_70_variant_is_independent_and_short_return_uses_entry_denominator(self):
        variant=dict(key='v2-s70-unit',score=70,atr_mult=1.5,rr=1.5)
        signal={**self.fs,'direction':None,'score':70,'long_score':10,'short_score':70}
        self.ledger.shadow_step('ETHUSDT',signal,[variant])
        self.ledger.shadow_step('ETHUSDT',{**signal,'price':90},[variant])
        card=self.ledger.shadow_scorecard()[0]
        self.assertAlmostEqual(card['pnl_pct'],10)
        self.assertFalse(card['legacy_measurement'])
        self.assertNotIn('leverage_simulated_return_pct',card)

    def test_portal_producer_includes_bounded_latest_contract_signal(self):
        signal={**self.fs,'symbol':'ETHUSDT','timeframe':'1h','candle_close_time':999,
                'at':datetime.now(UTC).isoformat()}
        self.ledger.set_setting('forward_last_signal_ETHUSDT',signal)
        snapshot=dashboard_snapshot(self.config,self.root/'missing.json')
        self.assertEqual(snapshot['futures_forward']['latest_signals']['ETHUSDT'],signal)
        self.assertIsNone(snapshot['futures_forward']['latest_signals']['BTCUSDT'])

    def test_futures_cycle_diagnostic_keeps_symbol_level_failure_reason(self):
        engine=TradingEngine(self.config)
        result={"status":"ACTIVE","results":[
            {"symbol":"ATOMUSDT","status":"ASSET_UNAVAILABLE","error":"reference unavailable","signal":self.fs},
            {"symbol":"NEARUSDT","status":"NO_DATA","error":"stale Futures candle history"},
        ]}
        diagnostic=engine._futures_cycle_diagnostic(result)
        self.assertEqual(diagnostic["state"],"ATTENTION")
        self.assertEqual(diagnostic["statuses"],{"ASSET_UNAVAILABLE":1,"NO_DATA":1})
        self.assertEqual(diagnostic["issues"][0]["symbol"],"ATOMUSDT")
        self.assertEqual(diagnostic["issues"][0]["reason"],"reference unavailable")
        self.assertEqual(diagnostic["issues"][1]["symbol"],"NEARUSDT")

    def test_futures_contract_data_excludes_forming_candle_and_caches(self):
        engine=TradingEngine(self.config)
        now=200000000
        duration=3600000
        start=now//duration*duration
        rows=[[start-duration,99,101,98,100,10,start-1],
              [start,100,102,99,101,10,start+duration-1]]
        with patch('trader.engine.time.time',return_value=now/1000), \
             patch('trader.engine.futures_public_request',return_value=rows) as request:
            candles=engine._futures_candles('ETHUSDT')
            self.assertEqual(len(candles),1)
            self.assertEqual(candles[0].close_time,start-1)
            self.assertEqual(engine._futures_candles('ETHUSDT'),candles)
            request.assert_called_once_with('GET','/fapi/v1/klines',
                {'symbol':'ETHUSDT','interval':'1h','limit':250},allow_fallback=False)

    def test_spot_entry_normalizes_using_testnet_rules_before_preflight(self):
        engine=TradingEngine(self.config)
        info=dict(symbol='BTCUSDT',status='TRADING',isSpotTradingAllowed=True,
                  filters=[dict(filterType='LOT_SIZE',minQty='.001',maxQty='10',stepSize='.001')])
        with patch.object(engine.broker,'reconcile_pending',return_value=True), \
             patch.object(engine.exchange,'top_usdt_symbols',return_value=['BTCUSDT']), \
             patch.object(engine,'_fetch_candles',return_value={'BTCUSDT':self.candles}), \
             patch.object(engine,'_run_futures_forward_cycle'), \
             patch.object(engine.exchange,'latest_prices',return_value={'BTCUSDT':100}), \
             patch.object(engine.strategy,'btc_regime',return_value=True), \
             patch.object(engine.strategy,'evaluate',return_value=self.signal), \
             patch.object(engine.ai,'review',return_value=AIReview('ALLOW',1,1,'unit')), \
             patch.object(engine,'_position_size',return_value=.853729), \
             patch.object(engine.exchange,'testnet_symbol_info',return_value=info) as testnet_rules, \
             patch.object(engine.exchange,'cached_symbol_info',side_effect=AssertionError('production filters used')), \
             patch.object(engine,'_buy_or_skip_guardrail',return_value=True) as buy:
            result=engine.cycle()
        self.assertEqual(result['opened'],['BTCUSDT'])
        self.assertEqual(buy.call_args.args[1],.853)
        testnet_rules.assert_called_once_with('BTCUSDT')
