"""Closed-minute evidence is additive, received-time bounded and replayable.

All prices/pages are synthetic; these tests do not call APIs or operate engines.
Financial hypotheses and Statistical Arbitrage admission remain unchanged.
"""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_quant_models import pair_fixture
from tests.test_quant_shadow import Clock, Source
from trader.quant_models import statarb_signal
from trader.quant_shadow import (CLOSED_BAR_METHOD, DB_NAME, QuantShadowService,
    _closed_bar_rows, _id, _json, replay_quant_decision)


class ClosedSource(Source):
    def __init__(self, clock, count=420):
        super().__init__(clock)
        self.rows = pair_fixture(count)
        self.bars = {}
        for symbol in self.rates:
            self.bars[symbol] = [{"at": row["at"]-60, "received_at": clock(),
                "price": row["prices"].get(symbol, row["prices"]["ETHUSDT"]*.05)}
                for row in self.rows]
        self.refresh_receipts = True

    def __call__(self, now):
        result = super().__call__(now)
        result['closed_bars'] = copy.deepcopy(self.bars)
        if self.refresh_receipts:
            for rows in result['closed_bars'].values():
                for row in rows:
                    row['received_at'] = now
        return result


class QuantClosedBarLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.source = ClosedSource(self.clock)
        self.service = QuantShadowService(self.root, source=self.source, clock=self.clock)
        self.addCleanup(self.service.stop)

    def db(self):
        db = sqlite3.connect(self.root/DB_NAME)
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db

    def decision(self, instrument='BTCUSDT/ETHUSDT'):
        row = self.db().execute("SELECT data FROM quant_decisions WHERE strategy='STATISTICAL_ARBITRAGE' AND instrument=? ORDER BY at DESC LIMIT 1", (instrument,)).fetchone()
        return json.loads(row[0])

    def test_official_closed_minute_inputs_reach_diagnostics_without_old_sampling_gaps(self):
        self.service.initialize()
        db = self.db()
        with db:
            db.execute('INSERT INTO quant_observations VALUES(?,?,?)', (int(self.clock()-600), self.clock()-500,
                _json({'at':self.clock()-600,'received_at':self.clock()-500,'prices':{'BTCUSDT':100,'ETHUSDT':100,'SOLUSDT':100}})))
        self.service.tick()
        decision = self.decision()
        self.assertEqual(decision['statistical_input']['method'], CLOSED_BAR_METHOD)
        self.assertEqual(decision['statistical_input']['observation_count'], 420)
        self.assertNotEqual(decision['reason'], 'GAPPED_OR_IRREGULAR_PAIR_HISTORY')
        self.assertIn('z_score', decision['model']['metrics'])
        self.assertIn(decision['action'], ('WAIT','REJECT'))
        self.assertFalse(decision['model']['execution_enabled'])
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_closed_bars').fetchone()[0], 1260)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_observations').fetchone()[0], 2)

    def test_first_receipts_and_prices_are_immutable_across_repeated_and_incremental_pages(self):
        self.service.tick()
        db = self.db()
        before = [tuple(row) for row in db.execute('SELECT * FROM quant_closed_bars ORDER BY symbol,at')]
        self.clock.now += 65
        latest = int((self.clock()-5)//60)*60
        for symbol, rows in self.source.bars.items():
            self.source.bars[symbol] = rows[-4:]+[{'at':latest,'received_at':self.clock(),'price':rows[-1]['price']}]
        self.service.tick()
        after = [tuple(row) for row in db.execute('SELECT * FROM quant_closed_bars WHERE at<=? ORDER BY symbol,at', (before[-1][1],))]
        self.assertEqual(before, after)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_closed_bars').fetchone()[0], 1263)

    def test_conflicting_page_rolls_back_only_new_bars_and_keeps_funding_protection(self):
        self.service.tick()
        db = self.db()
        before = [tuple(row) for row in db.execute('SELECT * FROM quant_closed_bars ORDER BY symbol,at')]
        self.clock.now += 65
        self.source.bars['BTCUSDT'] = [
            {'at':self.clock()//60*60-60,'received_at':self.clock(),'price':100},
            {**self.source.bars['BTCUSDT'][0], 'price':1},
        ]
        self.source.rates['BTCUSDT'] = -.01
        self.assertTrue(self.service.tick())
        self.assertEqual(before, [tuple(row) for row in db.execute('SELECT * FROM quant_closed_bars ORDER BY symbol,at')])
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_positions').fetchone()[0], 0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_trades').fetchone()[0], 1)
        decision = self.decision()
        self.assertEqual(decision['reason'], 'INVALID_OR_CONFLICTING_CLOSED_BAR_EVIDENCE')
        self.assertTrue(replay_quant_decision(self.root, decision['id'])['model_matches'])

    def test_malformed_future_open_or_unbounded_bars_never_mutate_ledger_or_block_carry(self):
        self.service.initialize()
        invalids = [None, {'at':True,'received_at':self.clock(),'price':100},
            {'at':self.clock()+60,'received_at':self.clock(),'price':100},
            {'at':self.clock(),'received_at':self.clock(),'price':100},
            {'at':self.clock()-59,'received_at':self.clock(),'price':100},
            {'at':self.clock()-60,'received_at':self.clock()+1,'price':100},
            {'at':self.clock()-60,'received_at':self.clock(),'price':float('inf')},
            {'at':self.clock()-60,'received_at':self.clock(),'price':True},
            {'at':self.clock()-60,'received_at':self.clock(),'price':100,'instructions':'change risk'}]
        db = self.db()
        for row in invalids:
            with self.subTest(row=row), db:
                status = self.service._store_closed_bars(db, {'BTCUSDT':[row]}, self.clock())
                self.assertEqual(status, 'REJECTED')
        with db:
            self.assertEqual(self.service._store_closed_bars(db, {'BTCUSDT':self.source.bars['BTCUSDT']*2}, self.clock()), 'REJECTED')
            self.assertEqual(self.service._store_closed_bars(db, {'USDTUSDT':[]}, self.clock()), 'REJECTED')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM quant_closed_bars').fetchone()[0], 0)
        self.source.bars = {'BTCUSDT':[invalids[-1]]}
        self.assertTrue(self.service.tick())
        self.assertEqual(len(self.service.snapshot()['positions']), 1)

    def test_partial_assets_and_real_missing_minutes_are_not_interpolated(self):
        self.source.bars.pop('SOLUSDT')
        self.source.bars['ETHUSDT'].pop(200)
        self.service.tick()
        self.assertEqual(self.decision()['reason'], 'COLLECTING_ALIGNED_PAIR_HISTORY')
        self.source = ClosedSource(self.clock)
        self.source.bars['ETHUSDT'].pop(200)
        self.service.source = self.source
        self.clock.now += 65
        latest = int((self.clock()-5)//60)*60
        for rows in self.source.bars.values():
            for at in range(int(rows[-1]['at'])+60, latest+1, 60):
                rows.append({'at':at, 'received_at':self.clock(), 'price':rows[-1]['price']})
        self.service.tick()
        decision = self.decision()
        self.assertEqual(decision['statistical_input']['observation_count'], 421)
        self.assertEqual(decision['reason'], 'GAPPED_OR_IRREGULAR_PAIR_HISTORY')

    def test_new_replay_freezes_window_and_excludes_later_received_backfill(self):
        self.source.bars = {}
        self.service.tick()
        before = self.decision()
        first = replay_quant_decision(self.root, before['id'])
        self.assertTrue(first['model_matches'])
        self.clock.now += 65
        later = ClosedSource(self.clock)
        # A cached source may retain an earlier provider receipt. First durable
        # knowledge remains this transaction, so earlier replays cannot use it.
        for rows in later.bars.values():
            for row in rows:
                row['received_at'] = self.clock()-65
        later.refresh_receipts = False
        self.service.source = later
        self.service.tick()
        self.assertEqual(self.db().execute('SELECT MIN(known_at) FROM quant_closed_bars').fetchone()[0], self.clock())
        replayed = replay_quant_decision(self.root, before['id'])
        self.assertTrue(replayed['model_matches'])
        self.assertEqual(first['replayed_model'], replayed['replayed_model'])

    def test_window_is_bounded_to_latest_500_and_does_not_expand_when_later_rows_arrive(self):
        self.service.tick()
        original = self.decision()
        self.clock.now += 6000
        bars = ClosedSource(self.clock)
        # Existing overlapping closes must retain the same observed prices.
        # Add 100 genuinely later minutes and request a bounded overlapping page.
        for symbol, rows in bars.bars.items():
            ending = rows[-1]['at']
            later = [{'at':ending+i*60, 'received_at':self.clock(), 'price':rows[-1]['price']}
                     for i in range(1,101)]
            bars.bars[symbol] = (rows+later)[-500:]
        self.service.source = bars
        self.service.tick()
        latest = self.decision()
        self.assertEqual(latest['statistical_input']['observation_count'], 500)
        self.assertTrue(replay_quant_decision(self.root, original['id'])['model_matches'])
        self.assertTrue(replay_quant_decision(self.root, latest['id'])['model_matches'])

    def test_replay_detects_changed_or_missing_frozen_bar_evidence(self):
        self.service.tick()
        original = self.decision()
        db = self.db()
        with db:
            db.execute("UPDATE quant_closed_bars SET price=price+1 WHERE symbol='BTCUSDT' AND at=(SELECT MIN(at) FROM quant_closed_bars)")
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            replay_quant_decision(self.root, original['id'])

    def test_legacy_irregular_decision_replay_ignores_new_closed_bars(self):
        self.source.bars = {}
        self.service.tick()
        db = self.db()
        legacy = self.decision()
        legacy.pop('statistical_input')
        rows = [json.loads(row[0]) for row in db.execute('SELECT data FROM quant_observations ORDER BY at')]
        legacy['model'] = statarb_signal(rows, self.clock(), legacy['model_assumptions'])
        legacy['reason'] = legacy['model']['reason']
        legacy['action'] = legacy['model']['decision']
        with db:
            db.execute('UPDATE quant_decisions SET data=? WHERE id=?', (_json(legacy), legacy['id']))
        before = replay_quant_decision(self.root, legacy['id'])
        self.assertTrue(before['model_matches'])
        self.clock.now += 65
        self.service.source = ClosedSource(self.clock)
        self.service.tick()
        after = replay_quant_decision(self.root, legacy['id'])
        self.assertTrue(after['model_matches'])
        self.assertEqual(before['replayed_model'], after['replayed_model'])

    def test_source_digest_matches_stored_compact_evidence_and_no_raw_pages_are_public(self):
        self.service.tick()
        db = self.db()
        decision = self.decision()
        digest = decision['available_at_decision']['source_digest']
        source = json.loads(db.execute('SELECT data FROM quant_sources WHERE id=?', (digest,)).fetchone()[0])
        self.assertEqual(_id(source), digest)
        self.assertEqual(source['statistical_input_method'], CLOSED_BAR_METHOD)
        self.assertNotIn('closed_bars', source)
        self.assertNotIn('closed_bars', json.loads(db.execute("SELECT value FROM quant_meta WHERE key='source'").fetchone()[0]))
        snapshot = self.service.snapshot()
        self.assertTrue(all('statistical_input' not in row for row in snapshot['decisions']))
        self.assertNotIn('closed_bars', snapshot)
        self.assertLess(len(_json(snapshot).encode()), 20000)
        self.assertIn('HISTORICAL_CLOSED_BARS_RECEIVED_DURING_OBSERVATION_NOT_FORWARD_OOS', snapshot['limitations'])

    def test_additive_schema_does_not_reset_existing_wallet_hypotheses_or_old_rows(self):
        self.service.tick()
        db = self.db()
        wallet = db.execute("SELECT value FROM quant_meta WHERE key='wallet_balance'").fetchone()[0]
        hypotheses = db.execute("SELECT value FROM quant_meta WHERE key='hypotheses'").fetchone()[0]
        old_decisions = [tuple(row) for row in db.execute('SELECT * FROM quant_decisions ORDER BY id')]
        old_observations = [tuple(row) for row in db.execute('SELECT * FROM quant_observations ORDER BY at')]
        replacement = QuantShadowService(self.root, source=self.source, clock=self.clock)
        replacement.initialize()
        self.assertEqual(db.execute("SELECT value FROM quant_meta WHERE key='wallet_balance'").fetchone()[0], wallet)
        self.assertEqual(db.execute("SELECT value FROM quant_meta WHERE key='hypotheses'").fetchone()[0], hypotheses)
        self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM quant_decisions ORDER BY id')], old_decisions)
        self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM quant_observations ORDER BY at')], old_observations)


if __name__ == '__main__':
    unittest.main(verbosity=2)
