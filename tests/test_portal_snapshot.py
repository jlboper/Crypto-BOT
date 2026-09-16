import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from trader.config import load_config
from trader.database import Database
from trader.portal_snapshot import dashboard_snapshot, public_text

class PortalSnapshotTests(unittest.TestCase):
    def test_projection_reads_without_mutating_and_redacts_event_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'trader.db'
            config=load_config()
            config=replace(config,bot=replace(config.bot,database_path=path,kill_switch_path=Path(folder)/'kill'))
            database=Database(path)
            database.initialize_cash(1000)
            database.record_equity(1000,1000,0)
            database.event('WARN','token=TEST_CREDENTIAL https://example.test/private?key=test')
            before=path.read_bytes()
            payload=dashboard_snapshot(config,Path(folder)/'missing.json')
            self.assertEqual(payload['status']['mode'],'PAPER')
            self.assertEqual(payload['research']['assets'],[])
            self.assertNotIn('TEST_CREDENTIAL',json.dumps(payload))
            self.assertNotIn('example.test',json.dumps(payload))
            self.assertEqual(path.read_bytes(),before)

    def test_known_credentials_are_removed_from_text(self):
        self.assertNotIn('abc123',public_text('sk-abc123'))
        self.assertNotIn('abcdef',public_text('Bearer abcdef'))
