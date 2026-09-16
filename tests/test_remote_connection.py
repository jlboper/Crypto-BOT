import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from trader.config import load_config
from trader.database import Database
from trader.remote_agent import RemoteAgent


class RemoteConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.root = root
        config = load_config()
        self.config = replace(config, bot=replace(config.bot, database_path=root/'source/trader.db', kill_switch_path=root/'source/KILL'))
        self.config.bot.database_path.parent.mkdir()
        self.agent = RemoteAgent(self.config, 'https://portal.example', 'x'*43, state_directory=root/'isolated')

    def command(self, identifier, action):
        return {'id':identifier, 'action':action, 'expires':110}

    def test_checkpoint_is_isolated_and_source_database_is_untouched(self):
        Database(self.config.bot.database_path)
        before = self.config.bot.database_path.read_bytes()
        self.agent.snapshot()
        self.agent.apply(self.command(1,'kill'), now=100)
        self.agent.apply(self.command(2,'resume'), now=100)
        self.assertFalse(self.config.bot.kill_switch_path.exists())
        self.assertEqual(self.config.bot.database_path.read_bytes(), before)
        self.assertTrue((self.root/'isolated/remote-state.json').is_file())
        self.assertFalse((self.root/'source/remote-state.json').exists())

    def test_local_halt_cannot_be_claimed_or_cleared_remotely(self):
        kill = self.config.bot.kill_switch_path
        kill.write_text('automatic halt after consecutive errors\n')
        self.agent.apply(self.command(1,'kill'), now=100)
        with self.assertRaises(ValueError):
            self.agent.apply(self.command(2,'resume'), now=100)
        self.assertEqual(kill.read_text(),'automatic halt after consecutive errors\n')
        self.assertEqual(self.agent._last_id(),1)

    def test_live_refused_and_missing_database_not_created(self):
        with self.assertRaises(ValueError):
            RemoteAgent(replace(self.config, bot=replace(self.config.bot, mode='live')), 'https://portal.example', 'x'*43)
        with self.assertRaises(Exception):
            self.agent.snapshot()
        self.assertFalse(self.config.bot.database_path.exists())

    def test_source_guard_prevents_network_and_stop_prevents_loop(self):
        with patch.object(self.agent,'sync') as sync:
            self.agent.run(stop=lambda:True)
            sync.assert_not_called()
            stopped = []
            def report(ok):
                self.assertFalse(ok)
                stopped.append(True)
            def invalid():
                raise ValueError('mode changed')
            self.agent.run(stop=lambda:bool(stopped), validate=invalid, report=report)
            sync.assert_not_called()
