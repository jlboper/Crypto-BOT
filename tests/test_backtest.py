import unittest
from datetime import UTC, datetime

from trader.backtest import run_backtest
from trader.config import load_config
from trader.domain import Candle, Signal


class OneShotStrategy:
    minimum_history = 5

    def __init__(self):
        self.sent = False

    def btc_regime(self, candles):
        return True

    def evaluate(self, symbol, candles, btc_bullish=True):
        buy = not self.sent
        self.sent = True
        return Signal(
            symbol=symbol, action="BUY" if buy else "HOLD", score=90, price=candles[-1].close,
            stop_price=candles[-1].close - 5 if buy else None,
            take_profit=candles[-1].close + 10 if buy else None,
            atr=2, rsi=60, ema_fast=101, ema_slow=99, volume_ratio=1.2,
            reason="test", created_at=datetime.now(UTC).isoformat(),
        )

    def should_exit(self, candles):
        return False, "open"


class BacktestTests(unittest.TestCase):
    def test_next_bar_execution_and_conservative_intrabar_order(self):
        candles = []
        for index in range(70):
            price = 100.0
            open_price = 110.0 if index == 17 else price
            high, low = (125.0, 100.0) if index == 17 else (101.0, 99.0)
            candles.append(Candle(index * 1000, open_price, high, low, price, 1000, index * 1000 + 999))
        result = run_backtest("BTCUSDT", candles, load_config(), strategy=OneShotStrategy())
        self.assertGreaterEqual(result.trades, 1)
        trade = result.trade_records[0]
        self.assertAlmostEqual(trade.entry_price, 110.0 * 1.0005, places=6)
        self.assertEqual(trade.exit_reason, "stop_before_target_conservative")
        self.assertEqual(trade.entry_time, candles[17].open_time)


if __name__ == "__main__":
    unittest.main()
