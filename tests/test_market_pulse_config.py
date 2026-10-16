import tempfile
import unittest
from pathlib import Path
from trader.config import PROJECT_ROOT, load_config


class PulseConfigTests(unittest.TestCase):
    def test_absent_section_supports_older_signed_supervisor_configuration(self):
        raw = (PROJECT_ROOT/'config.toml').read_text().split('[market_pulse]')[0]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.toml'
            path.write_text(raw)
            config=load_config(path)
            self.assertEqual(config.market_pulse.mode, 'SHADOW')
            self.assertEqual(config.market_pulse.ai_max_reviews_per_day, 6)
            self.assertEqual(config.market_pulse.windows_seconds,(60,300))

    def test_execution_and_budget_increases_cannot_be_configured(self):
        raw=(PROJECT_ROOT/'config.toml').read_text()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.toml'
            for old,new in [('mode = "SHADOW"','mode = "LIVE"'),('mode = "SHADOW"','mode = "TESTNET"'),('ai_max_reviews_per_day = 6','ai_max_reviews_per_day = 7'),('ai_min_interval_seconds = 300','ai_min_interval_seconds = 299'),('enabled = true\nmode = "SHADOW"','enabled = "yes"\nmode = "SHADOW"')]:
                path.write_text(raw.replace(old,new))
                with self.assertRaises(ValueError): load_config(path)
