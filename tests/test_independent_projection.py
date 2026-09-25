"""The independent agent reads future signed bot projections without copying modules."""
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.windows_agent import dashboard_from_source, source_settings
from trader.database import Database


ROOT = Path(__file__).resolve().parents[1]


class IndependentProjectionTests(unittest.TestCase):
    def test_source_projection_uses_installed_code_and_keeps_paper_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            shutil.copytree(ROOT / 'trader', source / 'trader',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (source / 'scripts').mkdir()
            for name in ('windows_agent.py', 'export_paper_snapshot.py'):
                shutil.copy2(ROOT / 'scripts' / name, source / 'scripts' / name)
            shutil.copy2(ROOT / 'config.toml', source / 'config.toml')
            database = Database(source / 'data/trader.db')
            database.initialize_cash(1000)
            database.record_equity(1000, 1000, 0)
            config = source_settings(source)
            before = config.bot.database_path.read_bytes()
            report = dashboard_from_source(source, config)
            self.assertEqual(report['status']['mode'], 'PAPER')
            self.assertIsInstance(report['paper_scorecard']['by_asset'], list)
            self.assertEqual(config.bot.database_path.read_bytes(), before)

    def test_older_installation_keeps_existing_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            from unittest.mock import patch
            source = Path(directory)
            with patch('scripts.windows_agent.dashboard_snapshot', return_value={'status': {'mode': 'PAPER'}}) as fallback:
                self.assertEqual(dashboard_from_source(source, object())['status']['mode'], 'PAPER')
                fallback.assert_called_once()
