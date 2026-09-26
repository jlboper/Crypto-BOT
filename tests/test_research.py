import math
import unittest

from trader.config import load_config
from trader.domain import Candle
from trader.research import build_research_report, default_profiles, monte_carlo
from dataclasses import replace


class ResearchTests(unittest.TestCase):
    def test_candidate_families_are_diverse_and_research_only(self):
        config = load_config()
        profiles = default_profiles(config)
        self.assertEqual(len(profiles), 5)
        self.assertGreaterEqual(len({profile.family for profile in profiles}), 5)

    def test_monte_carlo_is_repeatable(self):
        returns = [0.01, -0.006, 0.004, 0.008, -0.003]
        self.assertEqual(monte_carlo(returns, simulations=100, seed=42), monte_carlo(returns, simulations=100, seed=42))

    def test_walk_forward_report_never_auto_promotes(self):
        candles = []
        for index in range(700):
            close = 100 + index * 0.035 + math.sin(index / 8) * 2.5
            candles.append(Candle(
                open_time=index * 14_400_000,
                open=close - 0.2,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1000 + (index % 13) * 20,
                close_time=(index + 1) * 14_400_000 - 1,
            ))
        report = build_research_report({"BTCUSDT": candles}, load_config(), train_bars=180, test_bars=100)
        self.assertEqual(report["mode"], "RESEARCH_ONLY")
        self.assertFalse(report["auto_promotion"])
        self.assertEqual(len(report["assets"][0]["candidates"]), 5)
        self.assertTrue(all('development_oos_return_pct' in candidate and
                            'development_oos_trades' in candidate for candidate in report['assets'][0]['candidates']))
        self.assertGreaterEqual(report["assets"][0]["walk_forward"]["folds"], 3)
        self.assertIn("portfolio", report)
        self.assertIn("correlations", report)
        self.assertEqual(len(report["assets"][0]["parameter_sensitivity"]), 3)
        self.assertEqual(len(report["assets"][0]["regime_analysis"]), 3)
        asset = report["assets"][0]
        self.assertEqual(asset["walk_forward"], asset["fixed_strategy"])
        self.assertIn("adaptive_selector", asset)
        self.assertIn("cash_folds", asset["adaptive_selector"])
        self.assertEqual(len(asset["qualification"]["gates"]), 14)
        promotion = asset["promotion"]
        self.assertIn(promotion["stage"], {"RESEARCH", "CANDIDATE"})
        self.assertFalse(promotion["automatic"])
        self.assertTrue(promotion["owner_approval_required"])
        self.assertFalse(promotion["testnet_eligible"])
        self.assertFalse(promotion["live_eligible"])
        self.assertEqual(promotion["forward_test"]["status"], "NOT_STARTED")
        self.assertEqual(promotion["forward_test"]["minimum_observed_days"], 30)
        self.assertEqual(promotion["forward_test"]["minimum_closed_trades"], 30)
        if asset["qualification"]["passed"]:
            self.assertEqual(promotion["stage"], "CANDIDATE")
            self.assertEqual(promotion["decision"], "ADVANCE_TO_FORWARD_TEST")
            self.assertEqual(promotion["next_gate"], "FORWARD_TEST")
        else:
            self.assertEqual(promotion["stage"], "RESEARCH")
            self.assertEqual(promotion["decision"], "KEEP_IN_RESEARCH")
        self.assertEqual(asset["qualification"]["gates"]["beats_asset_hold_oos"],
                         asset["fixed_strategy"]["oos_compounded_return_pct"] >
                         asset["fixed_strategy"]["oos_benchmark_return_pct"])
        self.assertEqual(asset["qualification"]["gates"]["holdout_beats_asset_hold"],
                         asset["holdout"]["base_costs"]["return_pct"] >
                         asset["holdout"]["base_costs"]["benchmark_return_pct"])
        self.assertEqual(asset["holdout"]["bars"], 100)
        self.assertLess(asset["fixed_strategy"]["details"][-1]["end_at"], asset["holdout"]["start_at"])
        self.assertEqual(
            {fold["strategy"] for fold in asset["fixed_strategy"]["details"]},
            {asset["champion_candidate"]},
        )
        altered = candles[:-100] + [replace(c, open=c.open*1.7, high=c.high*1.7, low=c.low*1.7, close=c.close*1.7) for c in candles[-100:]]
        changed = build_research_report({"BTCUSDT": altered}, load_config(), train_bars=180, test_bars=100)["assets"][0]
        self.assertEqual(changed["champion_candidate"], asset["champion_candidate"])
        self.assertEqual(changed["fixed_strategy"], asset["fixed_strategy"])
        self.assertEqual(changed["adaptive_selector"], asset["adaptive_selector"])
        self.assertEqual(changed['candidates'], asset['candidates'])
        pipeline = report["promotion_pipeline"]
        self.assertFalse(pipeline["automatic_promotion"])
        self.assertIn("LIVE remains a separate locked authorization", pipeline["rule"])
        self.assertEqual(report["summary"]["testnet_eligible"], 0)
        self.assertEqual(report["summary"]["live_eligible"], 0)


if __name__ == "__main__":
    unittest.main()
