import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from trader.broker import PaperBroker
from trader.config import load_config
from trader.database import Database
from trader.domain import Signal


class BrokerTests(unittest.TestCase):
    def test_round_trip_updates_cash_and_pnl(self):
        config=load_config()
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/"test.db")
            broker=PaperBroker(db,config.paper,config.risk)
            signal=Signal("BTCUSDT","BUY",80,100.0,95.0,110.0,2.0,60.0,101.0,99.0,1.3,"test",datetime.now(UTC).isoformat())
            position=broker.buy(signal,1.0,"unit test")
            pnl=broker.sell(position,110.0,"unit test exit")
            self.assertGreater(pnl,9.0)
            self.assertGreater(db.cash(),1008.0)
            self.assertEqual(db.positions(),[])


if __name__ == "__main__":
    unittest.main()

