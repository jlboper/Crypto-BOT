"""Local/remote research projection boundaries, synthetic files only."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from tests.emit_capital_lab_fixture import make_capital_lab
from trader.capital_protocol_lab import run_capital_protocol_lab
from trader.config import load_config
from trader.dashboard import DashboardServer
from trader.database import Database
from trader.portal_snapshot import capital_lab_projection, dashboard_snapshot


class CapitalLabContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(bot=SimpleNamespace(database_path=self.root/'data/spot.db',mode='paper'))
        self.output = self.root/'data/research/capital-lab'

    def test_real_producer_variants_are_bounded_synthetic_and_have_no_global_financial_total(self):
        for variant, state in (('ready','PASSED'),('failed','FAILED'),('not-run','NOT_RUN'),('corrupt','UNAVAILABLE')):
            with self.subTest(variant=variant):
                value = make_capital_lab(variant=variant)
                self.assertEqual(value['state'], state)
                self.assertLessEqual(len(json.dumps(value,ensure_ascii=True,separators=(',',':')).encode()),8000)
                self.assertEqual(value['mode'],'RESEARCH_ONLY')
                self.assertIs(value['execution_enabled'],False)
                self.assertIs(value['real_account_adapter'],False)
                self.assertIs(value['synthetic'],True)
                self.assertNotIn('equity',value)
                if variant in ('ready','failed'):
                    self.assertEqual(len(value['scenarios']),7)
                    for row in value['scenarios']:
                        self.assertEqual(row['scope']['currency'],'USDT')
                        self.assertEqual(row['scope']['scenario_environment'],'SHADOW')
                        self.assertTrue(row['scope']['simulated_account_id'].startswith('SIM_'))

    def test_absent_projection_creates_nothing_and_never_opens_sqlite_or_initializes(self):
        with patch('sqlite3.connect',side_effect=AssertionError('projection opened database')), \
                patch('trader.capital_manager_shadow.CapitalManagerShadow.initialize',side_effect=AssertionError('projection initialized wallet')):
            self.assertEqual(capital_lab_projection(self.config)['state'],'NOT_RUN')
        self.assertFalse((self.root/'data').exists())

    def test_valid_projection_reads_json_without_touching_any_wallet(self):
        recorded = run_capital_protocol_lab(self.output)
        before = {p:p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        with patch('sqlite3.connect',side_effect=AssertionError('projection opened database')):
            self.assertEqual(capital_lab_projection(self.config),recorded)
        self.assertEqual({p:p.read_bytes() for p in self.output.rglob('*') if p.is_file()},before)

    def test_corrupt_json_and_missing_optional_module_are_isolated(self):
        self.output.mkdir(parents=True)
        (self.output/'latest.json').write_text('private malformed payload',encoding='utf-8')
        value = capital_lab_projection(self.config)
        self.assertEqual(value['state'],'UNAVAILABLE')
        self.assertEqual(value['scenarios'],[])
        self.assertNotIn('private',json.dumps(value))
        with patch.dict('sys.modules',{'trader.capital_protocol_lab':None}):
            self.assertIsNone(capital_lab_projection(self.config))

    def test_unsafe_producer_flags_cannot_enter_portal_projection(self):
        original = make_capital_lab(variant='not-run')
        for key,bad in (('mode','LIVE'),('synthetic',False),('execution_enabled',True),
                        ('real_account_adapter',True),('autonomy_level',False),('autonomy_level',1)):
            value = {**original,key:bad}
            with self.subTest(key=key,bad=bad),patch('trader.capital_protocol_lab.capital_protocol_lab_snapshot',return_value=value):
                self.assertIsNone(capital_lab_projection(self.config))

    def test_platform_keeps_capital_json_when_broader_financial_snapshot_fails(self):
        lab = make_capital_lab()
        server = object.__new__(DashboardServer)
        server.config=self.config;server._platform_lock=threading.Lock()
        server._platform_cache=None;server._platform_cached_at=0.
        from trader.portfolio_guardian import quant_not_started
        with patch('trader.portal_snapshot.dashboard_snapshot',side_effect=RuntimeError('isolated source failure')), \
                patch('trader.portal_snapshot.quant_projection',return_value=quant_not_started()), \
                patch('trader.portal_snapshot.guardian_intelligence_projection',return_value=None), \
                patch('trader.portal_snapshot.capital_lab_projection',return_value=lab):
            result=server._platform_snapshot()
        self.assertEqual(result['capital_lab'],lab)
        self.assertEqual(result['quant']['state'],'NOT_STARTED')
        self.assertIn('portfolio_guardian',result)

    def test_actual_dashboard_export_includes_optional_lab_without_creating_it(self):
        with patch('trader.config.load_environment'):
            config=load_config()
        config=replace(config,bot=replace(config.bot,mode='paper',database_path=self.config.bot.database_path,
            kill_switch_path=self.root/'data/KILL'),
            futures_testnet=replace(config.futures_testnet,database_path=self.root/'data/futures.db'),
            research=replace(config.research,report_path=self.root/'data/research/report.json'))
        database=Database(config.bot.database_path)
        database.initialize_cash(1000)
        result=dashboard_snapshot(config)
        self.assertEqual(result['capital_lab']['state'],'NOT_RUN')
        self.assertFalse(self.output.exists())
        self.assertIn('quant',result)
        self.assertIn('market_pulse',result)


if __name__=='__main__':
    unittest.main()
