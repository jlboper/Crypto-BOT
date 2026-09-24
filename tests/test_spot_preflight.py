import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trader.database import Database
from trader.paper_scorecard import paper_scorecard
from trader.spot_preflight import market_quantity_preflight


class SpotPreflightTests(unittest.TestCase):
    def setUp(self):
        self.info = {'symbol': 'BTCUSDT', 'filters': [
            {'filterType': 'LOT_SIZE', 'minQty': '0.001', 'maxQty': '100', 'stepSize': '0.001'},
            {'filterType': 'MARKET_LOT_SIZE', 'minQty': '0.01', 'maxQty': '10', 'stepSize': '0.01'},
            {'filterType': 'MIN_NOTIONAL', 'minNotional': '10', 'applyToMarket': True},
            {'filterType': 'NOTIONAL', 'minNotional': '5', 'maxNotional': '100',
             'applyMinToMarket': False, 'applyMaxToMarket': True},
        ]}

    def test_exact_decimal_steps_and_market_bounds(self):
        status, reasons = market_quantity_preflight(self.info, 0.015, 1000)
        self.assertEqual(status, 'incompatible')
        self.assertEqual(reasons, ['MARKET_LOT_SIZE_STEP'])
        self.assertEqual(market_quantity_preflight(self.info, 0.01, 1000),
                         ('estimated_compatible', []))
        self.assertIn('MIN_NOTIONAL_ESTIMATE',
                      market_quantity_preflight(self.info, 0.009, 1000)[1])
        self.assertIn('NOTIONAL_MAX_ESTIMATE',
                      market_quantity_preflight(self.info, 0.2, 1000)[1])
        self.assertIn('MARKET_LOT_SIZE_MIN',
                      market_quantity_preflight(self.info, 0.001, 1000)[1])

    def test_disabled_market_notional_and_missing_rules_never_claim_compatibility(self):
        info = {'filters': [self.info['filters'][0],
                            {'filterType':'MIN_NOTIONAL','minNotional':'100', 'applyToMarket':False}]}
        self.assertEqual(market_quantity_preflight(info, 0.01, 1000),
                         ('estimated_compatible', []))
        self.assertEqual(market_quantity_preflight(None, 1, 100),
                         ('unknown', ['RULES_UNAVAILABLE']))
        self.assertEqual(market_quantity_preflight({'filters':[]}, 1, 100),
                         ('unknown', ['LOT_SIZE_UNAVAILABLE']))
        self.assertEqual(market_quantity_preflight(self.info, float('nan'), 100),
                         ('unknown', ['INVALID_INPUT']))

    def test_diagnostic_counts_do_not_change_paper_trade_history(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Database(Path(folder)/'paper.db')
            db.record_trade('BTCUSDT','SELL',1,100,0.1,1,'take profit')
            db.record_order_preflight('BTCUSDT','estimated_compatible',[])
            db.record_order_preflight('ETHUSDT','incompatible',['LOT_SIZE_STEP'])
            with closing(sqlite3.connect(db.path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
                report=paper_scorecard(connection)
            self.assertEqual(report['closed_trades'],1)
            self.assertEqual(report['attribution']['market_preflight']['checked'],2)
            self.assertEqual(report['attribution']['market_preflight']['incompatible'],1)
            self.assertEqual(report['attribution']['market_preflight']['recent_issues'][0]['symbol'],'ETHUSDT')


if __name__ == '__main__':
    unittest.main()
