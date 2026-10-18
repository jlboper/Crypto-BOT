"""Anonymous reference fixtures only; no accounts, network or retrospective fills."""
import copy
import json
import unittest
from unittest.mock import patch

from trader.quant_public import QuantPublicFeed, SYMBOLS, _closed_bars, _premium_batch, reference_json


NOW = 1_800_000_010.


def bar(opened):
    milliseconds = int(opened*1000)
    return [milliseconds,"100","101","99","100.5","10",milliseconds+59999,
            "1000",2,"5","500","0"]


class Clock:
    def __init__(self):
        self.now = NOW
    def __call__(self):
        return self.now


def premium(symbol, now=NOW):
    return {"symbol":symbol,"markPrice":"100","lastFundingRate":".0001",
            "nextFundingTime":int((now+3600)*1000),"time":int(now*1000)}


class ClosedMinuteParserTests(unittest.TestCase):
    def test_normalized_minute_end_has_actual_receipt_availability(self):
        result = _closed_bars([bar(NOW-70)],NOW)
        self.assertEqual(result,[{"at":NOW-10,"received_at":NOW,"price":100.5}])
        self.assertNotEqual(result[0]["at"],result[0]["received_at"])
    def test_open_future_and_just_closed_minutes_are_not_available(self):
        current = NOW-10
        self.assertEqual(_closed_bars([bar(current)],NOW),[])
        self.assertEqual(_closed_bars([bar(current+60)],NOW),[])
        self.assertEqual(_closed_bars([bar(current-60)],current+4.999),[])
        self.assertEqual(_closed_bars([bar(current-60)],current+5),
                         [{"at":current,"received_at":current+5,"price":100.5}])
    def test_no_interpolation_for_a_real_gap_and_no_input_mutation(self):
        rows = [bar(NOW-250),bar(NOW-130)]
        previous = copy.deepcopy(rows)
        result = _closed_bars(rows,NOW)
        self.assertEqual([row["at"] for row in result],[NOW-190,NOW-70])
        self.assertEqual(rows,previous)
    def test_duplicate_or_nonmonotonic_minutes_reject_the_page(self):
        for rows in ([bar(NOW-130),bar(NOW-130)],[bar(NOW-70),bar(NOW-130)]):
            with self.subTest(rows=rows),self.assertRaises(ValueError):
                _closed_bars(rows,NOW)
    def test_exact_utc_grid_and_millisecond_close_are_required(self):
        for index,value in ((0,int((NOW-70)*1000)+1),(0,float((NOW-70)*1000)),
                            (6,int((NOW-10)*1000)),(6,True),(8,-1),(8,False)):
            row = bar(NOW-70)
            row[index] = value
            with self.subTest(index=index,value=value),self.assertRaises(ValueError):
                _closed_bars([row],NOW)
    def test_schema_and_page_bounds_are_not_guessed(self):
        for rows in ({"rows":[bar(NOW-70)]},[bar(NOW-70)[:-1]],[{"close":"100"}],
                     [bar(NOW-70)+["extra"]],[bar(NOW-70)]*501):
            with self.subTest(type=type(rows).__name__),self.assertRaises(ValueError):
                _closed_bars(rows,NOW)
    def test_finite_consistent_ohlc_and_nonnegative_volumes_are_required(self):
        changes = [(1,"nan"),(2,"inf"),(3,"-1"),(4,"0"),(2,"99.5"),(3,"100.1"),
                   (5,"-1"),(7,"nan"),(9,"11"),(10,"1001"),(11,"untrusted instructions"),
                   (5,"0"),(9,"0"),(8,0)]
        for index,value in changes:
            row = bar(NOW-70)
            row[index] = value
            with self.subTest(index=index,value=value),self.assertRaises(ValueError):
                _closed_bars([row],NOW)
    def test_zero_volume_bar_is_valid_when_prices_and_grid_are_valid(self):
        row = bar(NOW-70)
        for index in (5,7,9,10):
            row[index] = "0"
        row[8] = 0
        self.assertEqual(_closed_bars([row],NOW)[0]["price"],100.5)


class PremiumBatchTests(unittest.TestCase):
    def test_only_reviewed_symbols_and_fields_survive_the_batch(self):
        rows = [premium(symbol) for symbol in SYMBOLS]
        rows.append({"symbol":"UNREVIEWEDUSDT","markPrice":"not a number","instructions":"ignored"})
        rows[0]["private_extra"] = "not projected"
        result = _premium_batch(rows,NOW)
        self.assertEqual(set(result),set(SYMBOLS))
        self.assertEqual(set(result["BTCUSDT"]),{"mark_price","observed_funding_rate","next_funding_at","at","received_at"})
        self.assertEqual(result["BTCUSDT"]["received_at"],NOW)
    def test_duplicate_or_invalid_reviewed_symbol_does_not_poison_other_assets(self):
        rows = [premium(symbol) for symbol in SYMBOLS]+[premium("BTCUSDT")]
        result = _premium_batch(rows,NOW)
        self.assertEqual(set(result),{"ETHUSDT","SOLUSDT"})
        rows = [premium(symbol) for symbol in SYMBOLS]
        rows[0]["markPrice"] = "nan"
        self.assertEqual(set(_premium_batch(rows,NOW)),{"ETHUSDT","SOLUSDT"})
    def test_stale_and_future_selected_marks_reject_without_synthetic_replacement(self):
        for offset in (-91,6):
            row = premium("BTCUSDT",NOW+offset)
            self.assertEqual(_premium_batch([row],NOW),{})
    def test_batch_schema_and_count_are_bounded(self):
        for payload in (premium("BTCUSDT"),[premium("BTCUSDT")]*2001,[None],[{"not_symbol":"BTCUSDT"}]):
            with self.subTest(type=type(payload).__name__),self.assertRaises(ValueError):
                _premium_batch(payload,NOW)


class FeedClosedMinuteTests(unittest.TestCase):
    def setUp(self):
        self.clock,self.calls = Clock(),[]
        self.bad_bars = set()
    def request(self,venue,path,params):
        self.calls.append((venue,path,dict(params)))
        if path.endswith("fundingInfo"):
            return []
        if path.endswith("premiumIndex"):
            self.assertEqual(params,{})
            return [premium(symbol,self.clock()) for symbol in SYMBOLS]
        if path.endswith("depth"):
            return {"bids":[["99.99","1000"]],"asks":[["100.01","1000"]],"E":int(self.clock()*1000)}
        if path.endswith("klines"):
            if params["symbol"] in self.bad_bars:
                raise OSError("synthetic candle provider failure")
            end = int((self.clock()-5)//60)*60
            return [bar(end-(params["limit"]-index)*60) for index in range(params["limit"])]
        return [{"symbol":params["symbol"],"fundingTime":int((self.clock()-25200-index*28800)*1000),
                 "fundingRate":".0001","markPrice":"100"} for index in range(8)]
    def test_startup_fourteen_calls_then_ten_incremental_calls_and_same_budget(self):
        feed = QuantPublicFeed(request=self.request,clock=self.clock)
        first = feed()
        self.assertEqual(len(self.calls),14)
        self.assertEqual([len(first["closed_bars"][symbol]) for symbol in SYMBOLS],[500,500,500])
        self.assertTrue(all(row["futures"] is not None for row in first["markets"]))
        self.assertEqual(feed.health["max_calls_per_minute"],15)
        self.assertEqual(sum(path.endswith("premiumIndex") for _,path,_ in self.calls),1)
        self.assertIs(feed(),first)
        self.assertEqual(len(self.calls),14)
        self.clock.now += 60
        second = feed()
        self.assertEqual(len(self.calls),24)
        self.assertEqual([len(second["closed_bars"][symbol]) for symbol in SYMBOLS],[5,5,5])
        self.assertEqual(sum(path.endswith("fundingRate") for _,path,_ in self.calls),3)
        self.assertEqual(feed.health["errors"],0)
    def test_recovery_after_gap_uses_five_hundred_without_forward_fill(self):
        feed = QuantPublicFeed(request=self.request,clock=self.clock)
        feed()
        self.clock.now += 241
        result = feed()
        requests = [params for _,path,params in self.calls if path.endswith("klines")]
        self.assertTrue(all(params["limit"]==500 for params in requests))
        self.assertEqual(len(result["closed_bars"]["BTCUSDT"]),500)
        self.assertEqual(result["closed_bars"]["BTCUSDT"][-1]["received_at"],self.clock())
    def test_catchup_uses_current_request_time_after_live_request_latencies(self):
        self.clock.now = 1_800_000_059.
        delayed = False
        original = self.request
        def request(venue,path,params):
            if delayed:
                self.clock.now += 2
            if path.endswith("klines"):
                self.calls.append((venue,path,dict(params)))
                # Match Binance: the last candle is still open, rather than a
                # fixture containing only already closed records.
                latest_open = int(self.clock()//60)*60
                return [bar(latest_open-(params["limit"]-1-index)*60) for index in range(params["limit"])]
            return original(venue,path,params)
        feed = QuantPublicFeed(request=request,clock=self.clock)
        first = feed()
        previous = first["closed_bars"]["BTCUSDT"][-1]["at"]
        self.assertEqual(previous,1_800_000_000.)
        self.clock.now = 1_800_000_299.
        delayed = True
        following = feed()
        btc = following["closed_bars"]["BTCUSDT"]
        requests = [params for _,path,params in self.calls if path.endswith("klines") and params["symbol"]=="BTCUSDT"]
        self.assertEqual(requests[-1]["limit"],500)
        self.assertIn(previous+60,[row["at"] for row in btc])
        self.assertTrue(all(b["at"]-a["at"]==60 for a,b in zip(btc,btc[1:])))
        self.assertLessEqual(following["health"]["calls"]-first["health"]["calls"],15)
    def test_a_recent_receipt_of_old_valid_bars_cannot_suppress_recovery(self):
        stale = False
        original = self.request
        def request(venue,path,params):
            if stale and path.endswith("klines"):
                self.calls.append((venue,path,dict(params)))
                end = 1_800_000_000
                return [bar(end-(params["limit"]-index)*60) for index in range(params["limit"])]
            return original(venue,path,params)
        feed = QuantPublicFeed(request=request,clock=self.clock)
        feed()
        stale = True
        for _ in range(5):
            self.clock.now += 60
            feed()
        requests = [params for _,path,params in self.calls if path.endswith("klines") and params["symbol"]=="BTCUSDT"]
        self.assertEqual([params["limit"] for params in requests[:3]],[500,5,5])
        self.assertEqual(requests[-1]["limit"],500)
    def test_bad_bar_asset_keeps_quotes_and_other_bar_assets_operating(self):
        self.bad_bars.add("BTCUSDT")
        feed = QuantPublicFeed(request=self.request,clock=self.clock)
        for _ in range(4):
            result = feed()
            self.assertEqual(result["closed_bars"]["BTCUSDT"],[])
            self.assertTrue(result["closed_bars"]["ETHUSDT"])
            self.assertTrue(result["closed_bars"]["SOLUSDT"])
            self.assertTrue(all(row["spot"] and row["futures"] for row in result["markets"]))
            self.assertIsNone(feed.health["backoff_until"])
            self.clock.now += 60
        self.assertGreater(feed.health["errors"],0)
    def test_response_byte_cap_and_two_second_timeout_remain_in_force(self):
        class Response:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):
                self.limit = limit
                return b"x"*limit
        response = Response()
        with patch('trader.quant_public._open',return_value=response) as opened,self.assertRaisesRegex(ValueError,'too large'):
            reference_json("FUTURES_REFERENCE","/fapi/v1/premiumIndex",{})
        self.assertEqual(response.limit,262145)
        self.assertEqual(opened.call_args.kwargs['timeout'],2)
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(),'GET')
        self.assertNotIn('Authorization',dict(request.header_items()))
    def test_only_fixed_bar_limits_symbols_and_interval_can_reach_http(self):
        bad = [{"symbol":"BTCUSDT","interval":"5m","limit":500},
               {"symbol":"BTCUSDT","interval":"1m","limit":499},
               {"symbol":"BTCUSDT","interval":"1m","limit":1000},
               {"symbol":"BTCUSDT","interval":"1m","limit":True},
               {"symbol":"DOGEUSDT","interval":"1m","limit":5},
               {"symbol":"BTCUSDT","interval":"1m","limit":5,"timeZone":"8"},
               {"symbol":"BTCUSDT","interval":"1m","limit":5,"startTime":1}]
        for params in bad:
            with self.subTest(params=params),patch('trader.quant_public._open') as opened,self.assertRaises(ValueError):
                reference_json("SPOT_REFERENCE","/api/v3/klines",params)
            opened.assert_not_called()
    def test_bar_and_batch_parameters_cannot_escape_into_another_endpoint(self):
        cases = [("FUTURES_REFERENCE","/fapi/v1/premiumIndex",{"symbol":"BTCUSDT"}),
                 ("FUTURES_REFERENCE","/fapi/v1/fundingRate",{"symbol":"BTCUSDT","limit":32,"interval":"1m"}),
                 ("SPOT_REFERENCE","/api/v3/klines",{"symbol":"BTCUSDT","interval":"1m","limit":500,"signature":"ignored"})]
        for venue,path,params in cases:
            with self.subTest(path=path),patch('trader.quant_public._open') as opened,self.assertRaises(ValueError):
                reference_json(venue,path,params)
            opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
