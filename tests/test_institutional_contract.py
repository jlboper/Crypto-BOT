"""Public context contract; synthetic CFTC and SEC metadata, no HTTP."""
from copy import deepcopy
import json
import unittest

from trader.market_pulse_institutional import (InstitutionalContextFeeds, WATCHLIST,
    institutional_snapshot, parse_cftc, parse_sec_submissions)
from trader.market_pulse_institutional_contract import valid_institutional_context
from trader.market_pulse_news import timestamp


NOW = timestamp("2026-10-25T12:00:00.000Z")


def fixture():
    raw = {"cftc_contract_market_code":"133741", "report_date_as_yyyy_mm_dd":"2026-10-20",
        "open_interest_all":"1000", "dealer_positions_long_all":"250", "dealer_positions_short_all":"200",
        "asset_mgr_positions_long":"300", "asset_mgr_positions_short":"100", "lev_money_positions_long":"150",
        "lev_money_positions_short":"350", "change_in_open_interest_all":"-5", "change_in_asset_mgr_long":"20",
        "change_in_asset_mgr_short":"-10", "change_in_lev_money_long":"-8", "change_in_lev_money_short":"10"}
    cftc = parse_cftc(json.dumps([raw]).encode(), NOW)
    sec = {"cik":1980994, "filings":{"recent":{"accessionNumber":["0001980994-26-000001"],
        "form":["8-K"], "reportDate":["2026-10-23"], "acceptanceDateTime":["2026-10-24T12:00:00.000Z"]}}}
    filings = parse_sec_submissions(json.dumps(sec).encode(), WATCHLIST[0], NOW)
    # No source call: constructor only prepares a bounded, disabled SEC route.
    providers = InstitutionalContextFeeds(clock=lambda:0, wall_clock=lambda:NOW).health()
    return institutional_snapshot([item.payload for item in [*cftc, *filings]], providers, NOW)


class InstitutionalContractTests(unittest.TestCase):
    def test_synthetic_public_context_is_bounded_and_contains_no_activation(self):
        value = fixture()
        self.assertTrue(valid_institutional_context(value))
        self.assertLessEqual(len(json.dumps(value, ensure_ascii=True, separators=(",", ":"))), 8000)
        self.assertEqual(len(value["observations"]), 2)
        self.assertEqual(value["providers"][1]["last_error"], "SEC_CONTACT_REQUIRED")
        self.assertFalse(value["execution_enabled"])

    def test_authority_future_timestamps_unknown_fields_metrics_and_sources_rejected(self):
        mutations = (lambda x:x.update(execution_enabled=True), lambda x:x.update(mode="TRADING"),
            lambda x:x.update(secret="private"), lambda x:x["providers"][0].update(url="https://evil.example"),
            lambda x:x["providers"][0].update(name="impersonation"),
            lambda x:x["observations"][0]["metrics"].update(usd_flows=100),
            lambda x:x["observations"][0]["metrics"].update(open_interest_contracts=True),
            lambda x:x["observations"][0].update(received_at="2026-10-26T00:00:00.000Z"),
            lambda x:x["observations"][1]["metrics"].update(etf_net_flows_usd=100),
            lambda x:x["observations"][1].update(url="https://www.sec.gov.evil.example/Archives/"),
            lambda x:x["observations"][1].update(title="<script>buy()</script>"))
        for mutate in mutations:
            value = fixture()
            mutate(value)
            self.assertFalse(valid_institutional_context(value))

    def test_duplicate_observations_do_not_become_independent_votes(self):
        value = fixture()
        value["observations"].append(deepcopy(value["observations"][0]))
        self.assertFalse(valid_institutional_context(value))


if __name__ == "__main__":
    unittest.main()
