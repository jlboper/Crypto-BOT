import unittest
import urllib.error
from unittest.mock import patch

from trader.exchange import BinanceClient, ExchangeError


class ExchangeTests(unittest.TestCase):
    def test_ranked_universe_fills_from_supported_assets_and_excludes_stablecoins(self):
        symbols = ['BADUSDT','USD1USDT','RLUSDUSDT','BTCUSDT','ETHUSDT','SOLUSDT','中文USDT']
        info = {'symbols':[{'symbol':s,'baseAsset':s[:-4],'quoteAsset':'USDT','status':'TRADING'} for s in symbols]}
        tickers = [{'symbol':s,'quoteVolume':str(1000-i)} for i,s in enumerate(symbols)]
        client = BinanceClient()
        with patch.object(client,'_request',side_effect=[info,tickers]):
            result = client.top_usdt_symbols(2,supported_symbols={'USD1USDT','RLUSDUSDT','BTCUSDT','ETHUSDT','SOLUSDT'})
        self.assertEqual(result,['BTCUSDT','ETHUSDT'])

    def test_testnet_eligibility_is_cached_and_requires_oco_market_legs(self):
        client = BinanceClient()
        good = {'symbol':'ETHUSDT','status':'TRADING','quoteAsset':'USDT','ocoAllowed':True,
                'orderTypes':['MARKET','STOP_LOSS','TAKE_PROFIT']}
        bad = {**good,'symbol':'BADUSDT','ocoAllowed':False}
        with patch.object(client,'_request',return_value={'symbols':[good,bad]}) as request:
            self.assertEqual(client.testnet_tradeable_symbols(),{'ETHUSDT'})
            self.assertEqual(client.testnet_tradeable_symbols(),{'ETHUSDT'})
        request.assert_called_once()
        self.assertEqual(client.base_url,'https://api.binance.com')
    def test_transient_read_retry_and_write_rejection(self):
        client = BinanceClient()
        error = ExchangeError("network")
        error.__cause__ = urllib.error.URLError("offline")
        with patch.object(client, "_request_once", side_effect=[error, {"ok": True}]) as request, patch("trader.exchange.time.sleep"):
            self.assertEqual(client._request("GET", "/api/v3/time"), {"ok": True})
            self.assertEqual(request.call_count, 2)
        with self.assertRaises(ExchangeError):
            client._request("POST", "/api/v3/order")

    def test_missing_or_nonfinite_price_blocks_trading(self):
        client = BinanceClient()
        for payload in ([], [{"symbol": "BTCUSDT", "price": "NaN"}]):
            with patch.object(client, "_request", return_value=payload), self.assertRaises(ExchangeError):
                client.latest_prices({"BTCUSDT"})

    def test_latest_prices_filters_requested_symbols(self):
        payload = [
            {"symbol": "BTCUSDT", "price": "60000.5"},
            {"symbol": "ETHUSDT", "price": "2500.25"},
            {"symbol": "OTHERUSDT", "price": "1.0"},
        ]
        client = BinanceClient()
        with patch.object(client, "_request", return_value=payload):
            prices = client.latest_prices({"BTCUSDT", "ETHUSDT"})
        self.assertEqual(prices, {"BTCUSDT": 60000.5, "ETHUSDT": 2500.25})

    def test_historical_candles_paginates_and_orders_results(self):
        def row(index):
            return [index * 1000, "10", "11", "9", "10.5", "100", index * 1000 + 999]

        newest = [row(index) for index in range(1000, 2000)]
        older = [row(index) for index in range(500, 1000)]
        client = BinanceClient()
        with patch.object(client, "_request", side_effect=[newest, older]) as request:
            candles = client.historical_candles("BTCUSDT", "4h", 1500)
        self.assertEqual(len(candles), 1500)
        self.assertEqual(candles[0].open_time, 500000)
        self.assertEqual(candles[-1].open_time, 1999000)
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
