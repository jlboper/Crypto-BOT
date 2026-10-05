import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from trader.config import load_config
from trader.research_runtime import DAY, ResearchScheduler, archive_report, atomic, lab_state, project_report, failure_message
from trader.runtime import single_instance


class ResearchRuntimeTests(unittest.TestCase):
    def test_failure_diagnostic_includes_known_stage_without_exposing_arbitrary_text(self):
        message = failure_message(ValueError('Insufficient aligned portfolio history'),
                                  {'progress': 'Cartera Spot: señales BTCUSDT'})
        self.assertIn('Historial conjunto insuficiente', message)
        self.assertIn('Etapa: Cartera Spot: señales BTCUSDT', message)
        self.assertEqual(failure_message(ValueError('private credential'), {'progress': 'private path'}),
                         'Análisis detenido: ValueError')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'latest.json'
        config = load_config()
        self.config = replace(config, research=replace(config.research, report_path=self.path))

    def test_daily_due_persists_restart_and_manual_uses_same_lock(self):
        with patch('trader.research_runtime.subprocess.Popen') as popen:
            child = Mock()
            child.poll.return_value = None
            popen.return_value = child
            scheduler = ResearchScheduler(self.config)
            self.assertTrue(scheduler.tick(now=100))
            self.assertFalse(scheduler.tick(now=101, manual=True))
            self.assertFalse(ResearchScheduler(self.config).tick(now=102, manual=True))
            state = json.loads((self.path.parent/'state.json').read_text())
            state['status'] = 'COMPLETED'
            atomic(self.path.parent/'state.json', state)
            self.assertFalse(ResearchScheduler(self.config).tick(now=DAY))
            with single_instance(self.path.parent/'research.lock'):
                self.assertFalse(ResearchScheduler(self.config).tick(now=DAY+101, manual=True))
                self.assertTrue(lab_state(self.path)['running'])
            self.assertTrue(ResearchScheduler(self.config).tick(now=DAY+101))
            for instance in (scheduler,):
                if instance.log:
                    instance.log.close()
            # Explicitly close mock process handles (real worker exits independently).
            for call in popen.call_args_list:
                call.kwargs['stdout'].close()

    def test_automatic_can_be_disabled_but_manual_still_works(self):
        config = replace(self.config, research=replace(self.config.research, automatic=False))
        scheduler = ResearchScheduler(config)
        with patch('trader.research_runtime.subprocess.Popen', return_value=Mock()) as popen:
            self.assertFalse(scheduler.tick(now=100))
            self.assertTrue(scheduler.tick(now=100, manual=True))
            command = popen.call_args.args[0]
            self.assertIn('-I', command)
            self.assertIn('research_worker.py', command[3])
            scheduler.log.close()

    def test_stale_process_is_reported_as_interrupted(self):
        atomic(self.path.parent/'state.json', {'running':True, 'status':'RUNNING', 'next_due':1000})
        self.assertEqual(lab_state(self.path)['status'], 'INTERRUPTED')

    def test_immutable_history_and_recursive_projection(self):
        report = {'mode':'RESEARCH_ONLY','generated_at':'2026-10-04T01:00:00+00:00', 'summary':{'assets':1},
                  'assets':[{'fixed_strategy':{'details':[1,2]}, 'symbol':'BTCUSDT'}],
                  'joint_portfolios':[{'market':'SPOT','profile':'base','leverage':1,'curve':[], 'trades':[1],
                                       'holdout':{'curve':[1],'trades':[1]},'double_cost_holdout':{'trades':[1]}}]}
        archive_report(report, self.path)
        self.assertTrue(self.path.is_file())
        self.assertEqual(len(list((self.path.parent/'runs').glob('*.json'))), 1)
        self.assertEqual(len(report['history']),1)
        projected = project_report(report)
        self.assertNotIn('trades', projected['joint_portfolios'][0]['holdout'])
        self.assertNotIn('details', projected['assets'][0]['fixed_strategy'])
        self.assertIn('trades', report['joint_portfolios'][0])


if __name__ == '__main__':
    unittest.main()
