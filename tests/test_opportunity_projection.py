import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from trader.config import load_config
from trader.portal_snapshot import opportunity_shadow_projection
from trader.opportunity_observer import opportunity_snapshot


class OpportunityProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        config=load_config()
        self.config=replace(config,bot=replace(config.bot,database_path=self.root/'source/trader.db'))

    def test_absence_is_read_only_and_preserves_unknown_values(self):
        result=opportunity_shadow_projection(self.config)
        self.assertEqual(result['state'],'NOT_STARTED')
        self.assertFalse(self.config.bot.database_path.parent.exists())
        self.assertIsNone(result['health']['records'])
        self.assertIsNone(result['health']['heartbeat_at'])
        self.assertEqual(result['scopes'],[])
        self.assertEqual(result['recent_records'],[])

    def test_authority_extension_cannot_reach_the_portal(self):
        for key in ('controls_enabled','can_veto','execution_enabled','reservations_enabled','promotion_allowed'):
            value=opportunity_snapshot(self.root)
            value[key]=True
            with self.subTest(key=key),patch('trader.opportunity_observer.opportunity_snapshot',return_value=value):
                self.assertIsNone(opportunity_shadow_projection(self.config))
        for key,value in (('autonomy_level',1),('mode','LIVE'),('schema',True)):
            result=opportunity_snapshot(self.root);result[key]=value
            with self.subTest(key=key),patch('trader.opportunity_observer.opportunity_snapshot',return_value=result):
                self.assertIsNone(opportunity_shadow_projection(self.config))

    def test_broken_optional_module_and_oversized_report_remain_optional(self):
        with patch('trader.opportunity_observer.opportunity_snapshot',side_effect=OSError('synthetic')):
            self.assertIsNone(opportunity_shadow_projection(self.config))
        value=opportunity_snapshot(self.root);value['recent_records']=['x'*12001]
        with patch('trader.opportunity_observer.opportunity_snapshot',return_value=value):
            self.assertIsNone(opportunity_shadow_projection(self.config))
        self.assertFalse(self.config.bot.database_path.parent.exists())
