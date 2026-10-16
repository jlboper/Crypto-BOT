import tempfile
import unittest
from pathlib import Path
from trader.market_pulse_research import pulse_research_evidence


class PulseResearchTests(unittest.TestCase):
    def test_missing_evidence_never_creates_database_or_claims_backtest_or_promotion(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            report=pulse_research_evidence(path)
            self.assertEqual(report['state'],'FORWARD_ONLY')
            self.assertFalse(report['historical_backtest_valid'])
            self.assertFalse(report['out_of_sample_validated'])
            self.assertFalse(report['automatic_promotion'])
            self.assertEqual(report['decisions'],0)
            self.assertFalse(list(path.iterdir()))
