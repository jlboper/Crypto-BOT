import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from trader.market_pulse import MarketPulseService, PulseConfig
from trader.market_pulse_news import NEWS_PROVIDERS, PublicNewsFeeds, iso, normalize_event
from trader.market_pulse_universe import DEFAULT_SYMBOLS
from test_market_pulse import NOW, market


class ExpansionTests(unittest.TestCase):
    def test_legacy_additive_expansion_preserves_wallet_and_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            old = MarketPulseService(folder, config=replace(PulseConfig(), symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"), news_interval=300), clock=lambda: NOW)
            old._initialize()
            old.ingest_event({'title':'Bitcoin Core released','url':'https://bitcoincore.org/news','published_at':iso(NOW-10)})
            new = MarketPulseService(folder, clock=lambda: NOW+1)
            new._initialize()
            with closing(sqlite3.connect(new.path)) as db:
                self.assertEqual(db.execute("SELECT value FROM pulse_meta WHERE key='cash'").fetchone()[0], '1000.0')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM pulse_events').fetchone()[0],1)
                self.assertEqual(len(json.loads(db.execute("SELECT value FROM pulse_meta WHERE key='hypothesis_history'").fetchone()[0])),1)
            self.assertEqual(len(new.windows),10)
            with self.assertRaises(ValueError):
                MarketPulseService(folder,config=replace(PulseConfig(),fee_bps=20),clock=lambda:NOW+2)._initialize()

    def test_quantitative_ranking_uses_best_asset_before_portfolio_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            service=MarketPulseService(folder,config=replace(PulseConfig(),max_positions=1),clock=lambda:NOW)
            service._initialize()
            for symbol,window in service.windows.items():
                window.metrics=Mock(return_value=market(symbol))
                window.bid,window.ask,window.book_at=99.98,100.02,NOW
                window.bid_quote=window.ask_quote=50000
            service.ingest_event({'title':'Chainlink approved update','url':'https://www.sec.gov/newsroom/chainlink-approved','published_at':iso(NOW-10)})
            result=service.evaluate(NOW)
            self.assertEqual([p['symbol'] for p in result['positions']],['LINKUSDT'])
            with closing(sqlite3.connect(service.path)) as db:
                decision=json.loads(db.execute("SELECT data FROM pulse_decisions WHERE symbol='LINKUSDT'").fetchone()[0])
            self.assertEqual(decision['evidence']['selection_rank'],1)
            self.assertEqual(decision['evidence']['selection_pool'],10)

    def test_queue_selects_highest_available_priority_without_exceeding_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            service=MarketPulseService(folder,clock=lambda:NOW)
            service._initialize()
            for window in service.windows.values(): window.metrics=Mock(return_value=market())
            for index in range(10):
                event={'id':str(index),'_admissible':True,'published_at':iso(NOW-10),'credibility':.9,'impact':'positive'}
                service._queue_review(event,market(relative_volume=1 if index<9 else 3))
            self.assertLessEqual(service._review_queue.qsize(),8)
            reviewed=[]
            def review(item):
                reviewed.append(item['event']['id']);service._stop.set();return {'impact':'uncertain','confidence':.5,'reason':'synthetic'}
            service.reviewer=review
            service._auxiliary()
            self.assertEqual(reviewed,['9'])

    def test_five_feed_round_robin_rate_limit_and_outage_isolation(self):
        now=[0]
        feeds=PublicNewsFeeds(clock=lambda:now[0],wall_clock=lambda:NOW)
        with patch('trader.market_pulse_news.urlopen') as opener:
            response=opener.return_value.__enter__.return_value
            response.read.return_value=b'<rss><channel/></rss>'
            for index,provider in enumerate(NEWS_PROVIDERS):
                now[0]=index*60;response.url=provider.url
                if index==1:
                    opener.side_effect=OSError('synthetic')
                    with self.assertRaises(OSError):feeds()
                    opener.side_effect=None
                else: self.assertEqual(feeds(),[])
                feeds()  # Same instant cannot consume another HTTP request.
            self.assertEqual(opener.call_count,5)
        states={row['id']:row['state'] for row in feeds.health()}
        self.assertEqual(states['bitcoin'],'ERROR')
        self.assertEqual(states['sec'],'READY')

    def test_macro_context_never_creates_asset_order_or_ai_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            service=MarketPulseService(folder,clock=lambda:NOW,reviewer=Mock())
            service._initialize()
            self.assertEqual(service.ingest_event({'title':'Federal Reserve issues FOMC statement','url':'https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm','published_at':iso(NOW-10)}),1)
            self.assertTrue(service._review_queue.empty())
            with closing(sqlite3.connect(service.path)) as db: event=json.loads(db.execute('SELECT data FROM pulse_events').fetchone()[0])
            self.assertEqual(event['symbol'],'MARKET');self.assertFalse(event['_admissible'])

    def test_issuer_opinion_and_ambiguous_ticker_words_are_not_confirmation(self):
        raw={'title':'Bitcoin price prediction and hype: follow the link','url':'https://blog.kraken.com/news/forecast','published_at':iso(NOW-10)}
        rows=normalize_event(raw,NOW,DEFAULT_SYMBOLS)
        self.assertEqual([r['symbol'] for r in rows],['BTCUSDT'])
        self.assertFalse(rows[0]['_admissible'])
        self.assertNotIn('cointelegraph.com',{host for p in NEWS_PROVIDERS for host in p.hosts})
