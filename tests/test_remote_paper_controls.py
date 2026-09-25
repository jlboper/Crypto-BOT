import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from trader.remote_paper_controls import RemotePaperControls


class RemotePaperControlTests(unittest.TestCase):
    def test_persist_before_execution_and_replay_does_not_repeat_close(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'bot/scripts/execute_paper_control.py'
            script.parent.mkdir(parents=True)
            script.write_text('# signed installed code')
            agent = RemotePaperControls(root / 'supervisor', root / 'bot')
            item = {'id': 17, 'action': 'paper_close', 'expires': time.time() + 200,
                    'payload': {'symbol': 'BTCUSDT', 'opened_at': 'sample', 'reference_price': 100}}
            with patch('trader.remote_paper_controls.subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = json.dumps({'ok': True, 'symbol': 'BTCUSDT'})
                agent.apply(item)
                agent.apply(item)
                run.assert_called_once()
            self.assertEqual(agent.results()[0]['status'], 'completed')
            with self.assertRaisesRegex(ValueError, 'conflict'):
                agent.apply({**item, 'payload': {**item['payload'], 'reference_price': 102}})

    def test_uncertain_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            script = root / 'bot/scripts/execute_paper_control.py'
            script.parent.mkdir(parents=True)
            script.write_text('# signed installed code')
            agent = RemotePaperControls(root / 'supervisor', root / 'bot')
            item = {'id': 18, 'action': 'risk_profile', 'expires': time.time() + 200,
                    'payload': {'profile': 'prudente'}}
            with patch('trader.remote_paper_controls.subprocess.run',side_effect=TimeoutError):
                agent.apply(item)
            self.assertEqual(agent.results()[0]['status'], 'failed')
