"""Synthetic immutable research audits; no public API or operating wallet."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

from tests.test_quant_shadow import Clock, Source
from trader.quant_research import quant_research_evidence
from trader.quant_shadow import DB_NAME, QuantShadowService


class QuantResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.source = Source(self.clock)
        self.service = QuantShadowService(self.root, source=self.source, clock=self.clock)
        self.addCleanup(self.service.stop)

    def dump(self):
        with closing(sqlite3.connect(self.root/DB_NAME)) as db:
            return list(db.iterdump())

    def test_absent_directory_is_not_created_and_missing_is_unknown_not_zero(self):
        missing = self.root/'does-not-exist'
        report = quant_research_evidence(missing, now=self.clock())
        self.assertEqual(report['state'], 'NOT_STARTED')
        self.assertIsNone(report['counts']['decisions'])
        self.assertFalse(missing.exists())
        self.assertFalse(report['execution_enabled'])
        self.assertFalse(report['automatic_promotion'])

    def test_real_recorded_numerical_models_replay_without_mutation_or_source_calls(self):
        self.service.tick()
        before = self.dump()
        with patch.object(self.service, 'source', side_effect=AssertionError('No current provider')):
            report = quant_research_evidence(self.root, now=self.clock())
        self.assertEqual(report['state'], 'AVAILABLE')
        self.assertEqual(report['counts']['decisions'], 6)
        self.assertEqual(report['replay']['checked'], 6)
        self.assertEqual(report['replay']['matches'], 6)
        self.assertEqual(report['replay']['mismatches'], 0)
        self.assertEqual(report['replay']['unavailable'], 0)
        self.assertEqual(self.dump(), before)
        self.assertFalse(report['historical_backtest_valid'])
        self.assertFalse(report['out_of_sample_validated'])
        self.assertNotIn('wallet', json.dumps(report))

    def test_deterministic_sample_keeps_both_strategies_and_both_time_edges_bounded(self):
        for _ in range(10):
            self.service.tick()
            self.clock.now += 61
        with closing(sqlite3.connect(self.root/DB_NAME)) as db:
            expected = set()
            for strategy in ('FUNDING_CARRY', 'STATISTICAL_ARBITRAGE'):
                for order in ('ASC', 'DESC'):
                    expected.update(row[0] for row in db.execute(
                        'SELECT id FROM quant_decisions WHERE strategy=? ORDER BY at '+order+',id '+order+' LIMIT 4', (strategy,)))
        with patch('trader.quant_shadow.replay_quant_decision', return_value={'model_matches':True}) as replay:
            report = quant_research_evidence(self.root, now=self.clock())
        self.assertEqual({call.args[1] for call in replay.call_args_list}, expected)
        self.assertEqual(len(expected), 16)
        self.assertEqual(report['replay']['sampled'], 16)
        self.assertEqual(report['counts']['decisions'], 60)
        self.assertEqual(report['replay']['state'], 'MATCHED_SAMPLE')

    def test_future_decisions_are_not_evidence_available_by_cutoff(self):
        self.service.tick()
        cutoff = self.clock()
        self.clock.now += 61
        self.service.tick()
        report = quant_research_evidence(self.root, now=cutoff)
        self.assertEqual(report['counts']['decisions'], 6)
        self.assertEqual(report['replay']['sampled'], 6)
        self.assertEqual(report['replay']['matches'], 6)

    def test_replay_mismatch_and_failure_never_count_as_success_or_leak_content(self):
        self.service.tick()
        with patch('trader.quant_shadow.replay_quant_decision', side_effect=[
            {'model_matches':False}, ValueError('PRIVATE_PROVIDER_TEXT'),
            {'model_matches':'true'}, {'model_matches':True},
            {'model_matches':True}, {'model_matches':True}]):
            report = quant_research_evidence(self.root, now=self.clock())
        self.assertEqual(report['state'], 'PARTIAL')
        self.assertEqual(report['replay']['checked'], 4)
        self.assertEqual(report['replay']['matches'], 3)
        self.assertEqual(report['replay']['mismatches'], 1)
        self.assertEqual(report['replay']['unavailable'], 2)
        self.assertNotIn('PRIVATE_PROVIDER_TEXT', json.dumps(report))

    def test_corrupt_frozen_source_is_not_replaced_with_current_prices(self):
        self.service.tick()
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute('DELETE FROM quant_sources')
        report = quant_research_evidence(self.root, now=self.clock())
        self.assertEqual(report['state'], 'PARTIAL')
        self.assertEqual(report['replay']['checked'], 0)
        self.assertEqual(report['replay']['unavailable'], 6)

    def test_incompatible_database_does_not_migrate_and_unexpected_strategy_is_closed(self):
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute('CREATE TABLE original(value TEXT)')
        before = self.dump()
        report = quant_research_evidence(self.root, now=self.clock())
        self.assertEqual(report['state'], 'UNAVAILABLE')
        self.assertEqual(report['error'], 'QUANT_RESEARCH_EVIDENCE_UNAVAILABLE')
        self.assertEqual(self.dump(), before)

    def test_unknown_strategy_and_unsettled_funding_degrade_without_raw_text(self):
        self.service.tick()
        with closing(sqlite3.connect(self.root/DB_NAME)) as db, db:
            db.execute("UPDATE quant_decisions SET strategy='UNTRUSTED_INSTRUCTION' WHERE id=(SELECT id FROM quant_decisions LIMIT 1)")
            db.execute("INSERT INTO quant_pending_funding VALUES('test-position')")
        report = quant_research_evidence(self.root, now=self.clock())
        self.assertEqual(report['state'], 'PARTIAL')
        self.assertEqual(report['counts']['unrecognized_strategy_decisions'], 1)
        self.assertEqual(report['counts']['pending_funding'], 1)
        self.assertNotIn('UNTRUSTED_INSTRUCTION', json.dumps(report))

    def test_read_size_budget_and_invalid_cutoffs_fail_safely(self):
        self.service.tick()
        with patch('trader.quant_research.MAX_DATABASE_BYTES', 1):
            self.assertEqual(quant_research_evidence(self.root, now=self.clock())['state'], 'UNAVAILABLE')
        for cutoff in (True, float('nan'), float('inf'), -1, 253402300800):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                quant_research_evidence(self.root, now=cutoff)


if __name__ == '__main__':
    unittest.main()
