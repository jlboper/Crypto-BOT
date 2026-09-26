"""The independent agent reads future signed bot projections without copying modules."""
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.windows_agent import SUPERVISOR_MODULES, dashboard_from_source, source_settings, supervisor_modules_current
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

    def test_stale_supervisor_blocks_remote_install_capability(self):
        import hashlib
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, agent = root / 'source', root / 'agent'
            source.mkdir(); agent.mkdir()
            (source / 'pyproject.toml').write_text('[project]\nversion="0.6.23"\n', encoding='utf-8')
            files = {}
            for name in SUPERVISOR_MODULES:
                src, dst = source / name, agent / name
                src.parent.mkdir(parents=True, exist_ok=True)
                dst.parent.mkdir(parents=True, exist_ok=True)
                payload = ('signed-' + name).encode()
                src.write_bytes(payload); dst.write_bytes(payload)
                files[name] = hashlib.sha256(payload).hexdigest()
            state = agent / 'data/remote-updates'
            state.mkdir(parents=True)
            (state / 'journal.json').write_text(json.dumps({
                'phase':'committed','version':'0.6.23','files':files
            }), encoding='utf-8')
            with patch('scripts.windows_agent.ROOT', agent):
                self.assertTrue(supervisor_modules_current(source))
                (agent / SUPERVISOR_MODULES[-1]).write_text('stale', encoding='utf-8')
                self.assertFalse(supervisor_modules_current(source))

    def test_older_installation_keeps_existing_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            from unittest.mock import patch
            source = Path(directory)
            with patch('scripts.windows_agent.dashboard_snapshot', return_value={'status': {'mode': 'PAPER'}}) as fallback:
                self.assertEqual(dashboard_from_source(source, object())['status']['mode'], 'PAPER')
                fallback.assert_called_once()
