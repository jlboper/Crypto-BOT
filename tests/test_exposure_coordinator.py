import tempfile
import unittest
from pathlib import Path
from trader.exposure_coordinator import ExposureCoordinator, pulse_execution_admission


class ExposureCoordinatorTests(unittest.TestCase):
    def test_shared_account_duplicate_cap_and_crash_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"reservations.db"
            coordinator = ExposureCoordinator(path)
            scope = coordinator.scope("SPOT_TESTNET", "account-A", "SPOT")
            self.assertEqual(scope, coordinator.scope("SPOT_TESTNET", "account-A", "PULSE"))
            request = dict(identity="s1", scope=scope, symbol="BTCUSDT", engine="SPOT", notional=60, stop_risk=2, available_cash=100, exposure_limit=100, stop_risk_limit=3)
            self.assertTrue(coordinator.reserve(**request)["accepted"])
            coordinator = ExposureCoordinator(path)
            self.assertTrue(coordinator.reserve(**request)["accepted"])
            self.assertFalse(coordinator.reserve(**{**request, "identity": "p1", "engine": "PULSE"})["accepted"])
            self.assertFalse(coordinator.reserve(**{**request, "identity": "p2", "engine": "PULSE", "symbol": "ETHUSDT"})["accepted"])
            with self.assertRaises(ValueError): coordinator.release_reconciled("s1", confirmed_flat=False)
            coordinator.release_reconciled("s1", confirmed_flat=True)
            self.assertTrue(coordinator.reserve(**{**request, "identity": "p1", "engine": "PULSE"})["accepted"])

    def test_environment_isolation_and_all_execution_remains_blocked(self):
        self.assertNotEqual(ExposureCoordinator.scope("SHADOW", "same", "PULSE"), ExposureCoordinator.scope("SHADOW", "same", "SPOT"))
        self.assertNotEqual(ExposureCoordinator.scope("SPOT_TESTNET", "same", "SPOT"), ExposureCoordinator.scope("FUTURES_DEMO", "same", "FUTURES"))
        for environment in ("PAPER", "TESTNET", "SPOT_TESTNET", "FUTURES_DEMO", "LIVE"):
            self.assertFalse(pulse_execution_admission(environment)["allowed"])
        with self.assertRaises(ValueError): ExposureCoordinator.scope("LIVE", "same", "PULSE")
