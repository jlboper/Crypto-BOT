"""Synthetic-only tests for the phase-2 RO acquisition prototype."""
import ast
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from trader import guardian_capture as capture
from trader.portfolio_guardian import build_guardian

NOW = 1800000010.


def iso(at):
    return datetime.fromtimestamp(at,UTC).isoformat()


@contextmanager
def fixture_db(path):
    db=sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def setting(db,table,key,value):
    if not isinstance(value,str):
        value=json.dumps(value,separators=(",",":"))
    db.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?)",(key,value))


def make_fixture(directory,at=NOW):
    """Create synthetic DBs in a caller-owned test temp directory only."""
    directory=Path(directory)
    spot,future=directory/"spot.db",directory/"future.db"
    config=NS(bot=NS(database_path=spot,mode="testnet",cycle_seconds=3600),
              risk=NS(max_total_exposure_pct=.5,max_positions=10),
              futures_testnet=NS(database_path=future,forward_symbols=("BTCUSDT","ETHUSDT","SOLUSDT"),
                                 forward_total_notional_usdt=300.,forward_total_stop_loss_usdt=7.5))
    with fixture_db(spot) as db:
        db.executescript("""
          CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE positions(symbol TEXT PRIMARY KEY,quantity REAL,entry_price REAL,stop_price REAL,take_profit REAL,opened_at TEXT);
          CREATE TABLE equity(id INTEGER PRIMARY KEY,equity REAL,cash REAL,exposure REAL,created_at TEXT);
          CREATE TABLE ai_reviews(id INTEGER PRIMARY KEY,symbol TEXT,verdict TEXT,confidence REAL,risk_multiplier REAL,reason TEXT,created_at TEXT);
        """)
        db.execute("INSERT INTO positions VALUES(?,?,?,?,?,?)",("BTCUSDT",.001,90000,88000,95000,iso(at-3600)))
        db.execute("INSERT INTO equity VALUES(?,?,?,?,?)",(1,1000,900,100,iso(at-1)))
        db.execute("INSERT INTO ai_reviews VALUES(?,?,?,?,?,?,?)",(1,"BTCUSDT","ALLOW",.8,1.,"Synthetic original review",iso(at-10)))
        setting(db,"settings","market_prices",{"BTCUSDT":100000.})
        setting(db,"settings","market_prices_at",iso(at-1))
        setting(db,"settings","spot_last_cycle",{"at":iso(at-1),"status":"COMPLETE"})
        setting(db,"settings","spot_native_protection",{"BTCUSDT":{"status":"ARMED","quantity":.001,"confirmed_at":iso(at-2)}})
    with fixture_db(future) as db:
        db.executescript("""
          CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE forward_position(symbol TEXT PRIMARY KEY,direction TEXT,leverage INTEGER,quantity REAL,entry_price REAL,stop_price REAL,take_profit REAL,opened_at TEXT);
          CREATE TABLE forward_equity(id INTEGER PRIMARY KEY,wallet_balance REAL,available_balance REAL,unrealized_pnl REAL,created_at TEXT);
        """)
        opened=iso(at-7200)
        db.execute("INSERT INTO forward_position VALUES(?,?,?,?,?,?,?,?)",("ETHUSDT","SHORT",1,.1,3000,3100,2800,opened))
        db.execute("INSERT INTO forward_equity VALUES(?,?,?,?,?)",(1,1000,950,2,iso(at-2)))
        setting(db,"settings","forward_position_metrics",{"at":iso(at-1),"positions":{"ETHUSDT":{"quantity":.1,"opened_at":opened,"mark_price":2980.,"unrealized_pnl_usdt":2.}}})
        setting(db,"settings","forward_portfolio_budget",{"at":iso(at-1),"notional_usdt":298.,"stop_loss_usdt":12.,"notional_limit_usdt":300.,"stop_loss_limit_usdt":7.5})
        setting(db,"settings","forward_last_cycle_diagnostic",{"at":iso(at-1),"status":"COMPLETE"})
        setting(db,"settings","forward_native_protection",{"ETHUSDT":{"status":"ARMED","quantity":.1,"confirmed_at":iso(at-2)}})
        setting(db,"settings","forward_last_ai_review_ETHUSDT",{"at":iso(at-10),"verdict":"ALLOW","confidence":.8,"direction":"SHORT","score":80,"reason":"Synthetic"})
        setting(db,"settings","forward_last_signal_ETHUSDT",{"at":iso(at-10),"symbol":"ETHUSDT","direction":"SHORT","score":80,"price":3000.})
    with fixture_db(directory/"market-pulse.db") as db:
        db.executescript("CREATE TABLE pulse_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE pulse_positions(symbol TEXT PRIMARY KEY,data TEXT NOT NULL);")
        for key,value in {"updated_at":at-1,"initial_capital":1000.,"cash":1000.,"paused":"",
                         "market":[{"symbol":"BTCUSDT","at":iso(at-1),"price":100000.,"fresh":True,"complete":True,"change_1m_pct":.1,"change_5m_pct":.2,"relative_volume":1.5,"volatility_pct":.15,"spread_bps":2.,"depth_quote":100000.}],
                         "hypotheses":{"fee_bps":10.,"slippage_bps":10.,"max_exposure_fraction":.15}}.items():
            setting(db,"pulse_meta",key,value)
    with fixture_db(directory/"quant-shadow.db") as db:
        db.executescript("""
          CREATE TABLE quant_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE quant_positions(id TEXT PRIMARY KEY,strategy TEXT,opened REAL,data TEXT NOT NULL);
          CREATE TABLE quant_equity(at INTEGER PRIMARY KEY,equity REAL,data TEXT NOT NULL);
          CREATE TABLE quant_closed_bars(symbol TEXT NOT NULL,at INTEGER NOT NULL,received REAL NOT NULL,known_at REAL NOT NULL,price REAL NOT NULL,PRIMARY KEY(symbol,at));
        """)
        markets=[]
        for symbol,price in (("BTCUSDT",100000.),("ETHUSDT",3000.),("SOLUSDT",150.)):
            quote={"symbol":symbol,"bid":price*.9999,"ask":price*1.0001,"at":at-1,"received_at":at-1}
            markets.append({"symbol":symbol,"spot":quote,"futures":quote})
        for key,value in {"market_updated_at":at-1,"last_evaluation":at-1,"initial_capital":1000.,"wallet_balance":1000.,
                         "hypotheses":{"max_exposure_fraction":.15},"source":{"markets":markets},"paused":"","kill_switch_active":""}.items():
            setting(db,"quant_meta",key,value)
        db.execute("INSERT INTO quant_equity VALUES(?,?,?)",(int((at-1)//60)*60,1000.,json.dumps({"at":iso(at-1),"equity":1000.})))
        end=int((at-5)//60)*60
        db.executemany("INSERT INTO quant_closed_bars VALUES(?,?,?,?,?)",[("BTCUSDT",end-i*60,at-2,at-1,100000.-i) for i in range(150)])
    return config


def fingerprint(directory):
    return {str(path.relative_to(directory)):(path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())
            for path in Path(directory).iterdir() if path.is_file()}


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.config=make_fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def read(self,at=NOW):
        with patch.object(capture.time,"time",return_value=at):
            return capture.capture_guardian(self.config,now=at)

    def alter(self,path,sql,args=()):
        with fixture_db(path) as db:
            db.execute(sql,args)

    def set(self,path,table,key,value):
        with fixture_db(path) as db:
            setting(db,table,key,value)

    def test_four_sources_match_existing_guardian_shape(self):
        result=self.read()
        self.assertEqual({row["state"] for row in result["source_metadata"].values()},{"FRESH"})
        self.assertEqual(len(result["btc_closed_bars"]),121)
        self.assertEqual(result["dashboard"]["positions"][0]["market_price"],100000.)
        observed=build_guardian(result["dashboard"],now=result["cutoff_at"])
        scopes={scope["id"]:scope for scope in observed["scopes"]}
        self.assertEqual(scopes["SPOT"]["gross_usdt"],100.)
        self.assertEqual(scopes["FUTURES"]["gross_usdt"],298.)
        self.assertEqual(scopes["AI_MARKET_PULSE"]["gross_usdt"],0.)
        self.assertEqual(scopes["QUANT_ARBITRAGE"]["gross_usdt"],0.)
        self.assertFalse(result["globally_atomic"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["promotion_allowed"])

    def test_missing_directory_never_created(self):
        absent=self.root/"absent"/"spot.db"
        self.config.bot.database_path=absent
        self.config.futures_testnet.database_path=absent.parent/"future.db"
        before=fingerprint(self.root)
        result=self.read()
        self.assertFalse(absent.parent.exists())
        self.assertEqual(before,fingerprint(self.root))
        self.assertTrue(all(m["state"]=="UNKNOWN" for m in result["source_metadata"].values()))
        guardian=build_guardian(result["dashboard"],now=NOW)
        self.assertTrue(all(s["gross_usdt"] is None for s in guardian["scopes"]))

    def test_no_schema_files_or_financial_changes(self):
        before=fingerprint(self.root)
        schema={}
        for path in self.root.glob("*.db"):
            with fixture_db(path) as db:
                schema[path.name]=db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
        self.read()
        self.assertEqual(before,fingerprint(self.root))
        for path in self.root.glob("*.db"):
            with fixture_db(path) as db:
                self.assertEqual(schema[path.name],db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall())

    def test_query_only_blocks_all_writes(self):
        with capture._read_only(self.config.bot.database_path) as db:
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0],1)
            self.assertTrue(db.in_transaction)
            for statement in ("CREATE TABLE forbidden(id)","INSERT INTO settings VALUES('forbidden','1')","PRAGMA user_version=99"):
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute(statement)

    def test_missing_futures_does_not_erase_known_spot(self):
        self.config.futures_testnet.database_path.unlink()
        result=self.read()
        self.assertEqual(result["source_metadata"]["futures"]["reason"],"MISSING_DATABASE")
        self.assertEqual(result["source_metadata"]["spot"]["state"],"FRESH")
        self.assertIsNone(result["dashboard"]["futures_forward"]["positions"])
        guardian=build_guardian(result["dashboard"],now=NOW)
        self.assertEqual(guardian["scopes"][0]["gross_usdt"],100.)
        self.assertIsNone(guardian["scopes"][1]["gross_usdt"])

    def test_corrupt_futures_is_isolated_and_error_is_sanitized(self):
        self.config.futures_testnet.database_path.write_bytes(b"private_secret_not_a_database")
        result=self.read()
        self.assertEqual(result["source_metadata"]["futures"]["reason"],"INVALID_DATABASE")
        self.assertNotIn("private_secret",json.dumps(result))
        self.assertEqual(result["source_metadata"]["spot"]["state"],"FRESH")

    def test_stale_timestamp_preserved_not_refreshed(self):
        old=iso(NOW-10000)
        self.set(self.config.bot.database_path,"settings","market_prices_at",old)
        result=self.read()
        self.assertEqual(result["source_metadata"]["spot"]["state"],"STALE")
        self.assertEqual(result["source_metadata"]["spot"]["source_at"],old)
        self.assertEqual(result["dashboard"]["paper_scorecard"]["prices_at"],old)
        self.assertEqual(result["dashboard"]["positions"][0]["priced_at"],old)
        self.assertIsNone(result["dashboard"]["positions"][0]["market_price"])
        guardian=build_guardian(result["dashboard"],now=NOW)
        self.assertIsNone(guardian["scopes"][0]["gross_usdt"])

    def test_future_source_not_tolerated_as_clock_freshness(self):
        self.set(self.config.bot.database_path,"settings","market_prices_at",iso(NOW+2))
        result=self.read()
        self.assertEqual(result["source_metadata"]["spot"]["state"],"UNKNOWN")
        self.assertEqual(result["source_metadata"]["spot"]["reason"],"FUTURE_SOURCE")
        self.assertIsNone(result["dashboard"]["positions"])

    def test_capture_receipt_cannot_be_backdated(self):
        with patch.object(capture.time,"time",return_value=NOW+1):
            result=capture.capture_guardian(self.config,now=NOW)
        self.assertEqual(result["cutoff_at"],NOW)
        self.assertEqual(result["captured_at"],iso(NOW+1))
        self.assertTrue(all(m["reason"]=="CAPTURE_AFTER_CUTOFF" for m in result["source_metadata"].values()))
        self.assertIsNone(result["dashboard"]["positions"])

    def test_runtime_cutoff_final_receipts_preserves_per_source_times(self):
        times=iter(NOW+i*.01 for i in range(40))
        with patch.object(capture.time,"time",side_effect=lambda:next(times)):
            result=capture.capture_guardian(self.config)
        self.assertTrue(all(capture._at(m["available_at"])<=result["cutoff_at"] for m in result["source_metadata"].values()))
        self.assertEqual(len({m["captured_at"] for m in result["source_metadata"].values()}),4)
        self.assertEqual(result["source_metadata"]["spot"]["source_at"],iso(NOW-1))

    def test_futures_mark_requires_same_position_identity(self):
        path=self.config.futures_testnet.database_path
        original=self.read()["dashboard"]["futures_forward"]["positions"][0]
        self.assertEqual(original["mark_price"],2980.)
        for field,value in (("opened_at",iso(NOW-7201)),("quantity",.2)):
            with self.subTest(field=field):
                metrics={"at":iso(NOW-1),"positions":{"ETHUSDT":{"opened_at":iso(NOW-7200),"quantity":.1,"mark_price":2980.,"unrealized_pnl_usdt":2.}}}
                metrics["positions"]["ETHUSDT"][field]=value
                self.set(path,"settings","forward_position_metrics",metrics)
                position=self.read()["dashboard"]["futures_forward"]["positions"][0]
                self.assertIsNone(position["mark_price"])
                self.assertNotIn("unrealized_pnl_usdt",position)

    def test_stale_and_future_futures_mark_not_used(self):
        path=self.config.futures_testnet.database_path
        for at in (NOW-601,NOW+1):
            with self.subTest(at=at):
                self.set(path,"settings","forward_position_metrics",{"at":iso(at),"positions":{"ETHUSDT":{"opened_at":iso(NOW-7200),"quantity":.1,"mark_price":2980.,"unrealized_pnl_usdt":2.}}})
                result=self.read()
                if at>NOW:
                    self.assertEqual(result["source_metadata"]["futures"]["state"],"UNKNOWN")
                    self.assertIsNone(result["dashboard"]["futures_forward"]["positions"])
                    continue
                position=result["dashboard"]["futures_forward"]["positions"][0]
                self.assertIsNone(position["mark_price"])
                self.assertEqual(position["priced_at"],iso(at))

    def test_future_quant_book_cannot_leave_fresh_empty_zero_exposure(self):
        path=self.root/"quant-shadow.db"
        with fixture_db(path) as db:
            value=json.loads(db.execute("SELECT value FROM quant_meta WHERE key='source'").fetchone()[0])
            value["markets"][0]["spot"]["received_at"]=NOW+1
            setting(db,"quant_meta","source",value)
        result=self.read()
        self.assertEqual(result["source_metadata"]["quant"]["state"],"UNKNOWN")
        self.assertIsNone(result["dashboard"]["quant"]["positions"])
        self.assertIsNone(build_guardian(result["dashboard"],now=NOW)["scopes"][3]["gross_usdt"])

    def test_future_native_confirmation_is_not_reported_armed(self):
        self.set(self.config.bot.database_path,"settings","spot_native_protection",{"BTCUSDT":{"status":"ARMED","confirmed_at":iso(NOW+1)}})
        result=self.read()
        self.assertEqual(result["dashboard"]["status"]["native_protection"]["positions"]["BTCUSDT"]["status"],"UNCONFIRMED")

    def test_mismatched_duplicate_quant_market_identity_is_unknown(self):
        path=self.root/"quant-shadow.db"
        with fixture_db(path) as db:
            value=json.loads(db.execute("SELECT value FROM quant_meta WHERE key='source'").fetchone()[0])
            value["markets"][1]=value["markets"][0]
            setting(db,"quant_meta","source",value)
        result=self.read()
        self.assertEqual(result["source_metadata"]["quant"]["reason"],"MALFORMED_MARKET_IDENTITY")

    def test_existing_pause_markers_are_observed_without_mutating_them(self):
        marker=self.root/"owner_pause"
        marker.write_text("synthetic owner pause")
        self.config.bot.kill_switch_path=marker
        self.config.futures_testnet.kill_switch_path=marker
        self.config.market_pulse=NS(kill_switch_path=marker)
        self.config.quant_arbitrage=NS(kill_switch_path=marker)
        before=fingerprint(self.root)
        result=self.read()
        self.assertTrue(result["dashboard"]["status"]["killed"])
        self.assertTrue(result["dashboard"]["futures_forward"]["killed"])
        self.assertEqual(result["dashboard"]["market_pulse"]["state"],"PAUSED")
        self.assertEqual(result["dashboard"]["quant"]["state"],"PAUSED")
        self.assertEqual(before,fingerprint(self.root))

    def test_frozen_hypothesis_corruption_not_used_to_invent_caps(self):
        for name,table in (("market-pulse.db","pulse_meta"),("quant-shadow.db","quant_meta")):
            with self.subTest(name=name):
                key="pulse" if name.startswith("market") else "quant"
                self.set(self.root/name,table,"hypotheses",{"max_exposure_fraction":.9,"fee_bps":-1000,"slippage_bps":10})
                result=self.read()
                self.assertEqual(result["source_metadata"][key]["state"],"UNKNOWN")
                self.assertIsNone(result["dashboard"]["market_pulse" if key=="pulse" else "quant"]["performance"]["equity"])

    def test_held_inventory_over_limit_fails_unknown_with_count(self):
        path=self.config.bot.database_path
        with fixture_db(path) as db:
            db.executemany("INSERT INTO positions VALUES(?,?,?,?,?,?)",[(f"AAA{i}USDT",1.,1.,.9,1.1,iso(NOW-10)) for i in range(10)])
        result=self.read()
        meta=result["source_metadata"]["spot"]
        self.assertEqual(meta["reason"],"INVENTORY_LIMIT")
        self.assertEqual(meta["positions_seen"],11)
        self.assertEqual(meta["positions_returned"],0)
        self.assertFalse(meta["inventory_complete"])
        self.assertIsNone(result["dashboard"]["positions"])

    def test_futures_locked_timeout_is_bounded_no_other_source_failure(self):
        connection=sqlite3.connect(self.config.futures_testnet.database_path)
        try:
            connection.execute("BEGIN EXCLUSIVE")
            started=time.monotonic()
            result=self.read()
            elapsed=time.monotonic()-started
            self.assertLess(elapsed,1.25)
            self.assertEqual(result["source_metadata"]["futures"]["reason"],"DATABASE_BUSY")
            self.assertEqual(result["source_metadata"]["spot"]["state"],"FRESH")
        finally:
            connection.close()

    def test_read_transaction_is_consistent_with_concurrent_wal_writer(self):
        path=self.config.bot.database_path
        writer=sqlite3.connect(path)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("INSERT OR REPLACE INTO settings VALUES('test_value','before')")
            writer.commit()
            before=fingerprint(self.root)
            with capture._read_only(path) as reader:
                self.assertEqual(reader.execute("SELECT value FROM settings WHERE key='test_value'").fetchone()[0],"before")
                writer.execute("UPDATE settings SET value='after' WHERE key='test_value'")
                writer.commit()
                self.assertEqual(reader.execute("SELECT value FROM settings WHERE key='test_value'").fetchone()[0],"before")
            after_write=fingerprint(self.root)
            self.read()
            after_read=fingerprint(self.root)
            # SQLite RO readers participate in shared-memory read locks. Main
            # DB/WAL bytes and directory inventory must remain unchanged; SHM
            # read marks are locking state, not financial writes or schema.
            self.assertEqual({k:v for k,v in after_write.items() if not k.endswith('-shm')},
                             {k:v for k,v in after_read.items() if not k.endswith('-shm')})
            self.assertEqual(set(after_write),set(after_read))
            self.assertEqual(set(before),set(after_write))
        finally:
            writer.close()

    def test_wal_missing_sidecars_does_not_create_them(self):
        path=self.config.bot.database_path
        with fixture_db(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
        # A closed WAL DB has the header set but no active sidecars.
        before=fingerprint(self.root)
        result=self.read()
        self.assertEqual(result["source_metadata"]["spot"]["reason"],"WAL_SIDECARS_UNAVAILABLE")
        self.assertEqual(before,fingerprint(self.root))

    def test_malformed_json_nan_deep_and_large_are_unknown(self):
        path=self.config.bot.database_path
        for raw in ("{broken",'{"BTCUSDT":NaN}',"["*22+"0"+"]"*22,'{"BTCUSDT":"'+"x"*70000+'"}'):
            with self.subTest(kind=len(raw)):
                self.set(path,"settings","market_prices",raw)
                result=self.read()
                self.assertEqual(result["source_metadata"]["spot"]["state"],"UNKNOWN")
                self.assertIsNone(result["dashboard"]["positions"])
                self.assertEqual(result["source_metadata"]["futures"]["state"],"FRESH")

    def test_closed_bars_cutoff_on_event_received_and_first_known(self):
        path=self.root/"quant-shadow.db"
        with fixture_db(path) as db:
            db.execute("DELETE FROM quant_closed_bars")
            end=int((NOW-5)//60)*60
            rows=[("BTCUSDT",end-120,NOW-3,NOW-2,100.),
                  ("BTCUSDT",end-60,NOW-3,NOW+1,101.),
                  ("BTCUSDT",end,NOW+1,NOW+1,102.),
                  ("BTCUSDT",end+60,NOW+70,NOW+70,103.)]
            db.executemany("INSERT INTO quant_closed_bars VALUES(?,?,?,?,?)",rows)
        result=self.read()
        self.assertEqual([row["price"] for row in result["btc_closed_bars"]],[100.])
        self.assertEqual(result["btc_closed_bars"][0]["known_at"],NOW-2)
        self.assertEqual(result["source_metadata"]["quant"]["state"],"FRESH")

    def test_closed_bars_irregular_or_invalid_isolated_from_wallet(self):
        path=self.root/"quant-shadow.db"
        self.alter(path,"UPDATE quant_closed_bars SET at=at+1 WHERE at=(SELECT MAX(at) FROM quant_closed_bars)")
        result=self.read()
        self.assertEqual(result["btc_closed_bars"],[])
        self.assertEqual(result["source_metadata"]["quant"]["closed_bars_reason"],"CLOSED_BARS_UNAVAILABLE")
        self.assertEqual(result["dashboard"]["quant"]["performance"]["equity"],1000.)

    def test_quant_equity_matches_published_clock_precision_only(self):
        instant = NOW+.1234567
        evaluated = instant-1
        path = self.root/'quant-shadow.db'
        with fixture_db(path) as db:
            setting(db,'quant_meta','last_evaluation',evaluated)
        for precision in ('milliseconds','microseconds'):
            with self.subTest(precision=precision):
                stamp = datetime.fromtimestamp(evaluated,UTC).isoformat(timespec=precision)
                with fixture_db(path) as db:
                    db.execute('UPDATE quant_equity SET data=?',(json.dumps({'at':stamp,'equity':1000.}),))
                result = self.read(instant)
                self.assertEqual(result['dashboard']['quant']['performance']['equity'],1000.)
        with fixture_db(path) as db:
            db.execute('UPDATE quant_equity SET data=?',(json.dumps({'at':iso(evaluated-1),'equity':1000.}),))
        self.assertIsNone(self.read(instant)['dashboard']['quant']['performance']['equity'])

    def test_reviews_are_bounded_original_not_guardian_orders(self):
        path=self.config.bot.database_path
        with fixture_db(path) as db:
            db.executemany("INSERT INTO ai_reviews VALUES(?,?,?,?,?,?,?)",[(i,"BTCUSDT","REDUCE",.7,.5,"untrusted instruction "+"x"*1000,iso(NOW-1)) for i in range(2,30)])
        result=self.read()
        rows=result["dashboard"]["ai_reviews"]
        self.assertEqual(len(rows),12)
        self.assertTrue(all(len(row["reason"])<=300 for row in rows))
        self.assertEqual(rows[0]["verdict"],"REDUCE")
        self.assertEqual(rows[0]["created_at"],iso(NOW-1))
        self.assertFalse(result["execution_enabled"])

    def test_quant_held_legs_keep_gross_separate_not_net_hedge(self):
        path=self.root/"quant-shadow.db"
        position={"id":"pair1","strategy":"FUNDING_CARRY","instrument":"BTCUSDT","opened":NOW-3600,"collateral_usdt":200.,"risk_budget_usdt":2.5,
                  "legs":[{"symbol":"BTCUSDT","venue":"SPOT_REFERENCE","direction":"LONG","quantity":.001,"entry_price":100000.},
                          {"symbol":"BTCUSDT","venue":"FUTURES_REFERENCE","direction":"SHORT","quantity":.001,"entry_price":100000.}]}
        self.alter(path,"INSERT INTO quant_positions VALUES(?,?,?,?)",("pair1","FUNDING_CARRY",NOW-3600,json.dumps(position)))
        result=self.read()
        q=build_guardian(result["dashboard"],now=NOW)["scopes"][3]
        self.assertEqual(q["gross_usdt"],200.)
        self.assertEqual(q["net_usdt"],0.)
        self.assertEqual(q["position_count"],2)
        self.assertEqual(result["dashboard"]["quant"]["performance"]["cash"],800.)

    def test_no_forbidden_runtime_import_or_network_hook(self):
        tree=ast.parse(Path(capture.__file__).read_text())
        imports={alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
        imports|={node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
        self.assertFalse(any(name and any(part in name for part in ("trader","urllib","requests","socket","http","openai")) for name in imports))
        text=Path(capture.__file__).read_text()
        self.assertNotIn("mkdir(",text)
        self.assertNotIn("journal_mode=",text)
        self.assertNotIn("CREATE TABLE",text)
        self.assertNotIn("INSERT INTO",text)

    def test_envelope_finite_compact_and_inputs_unchanged(self):
        before=repr(self.config)
        result=self.read()
        self.assertLess(len(json.dumps(result,allow_nan=False).encode()),capture.MAX_BYTES)
        self.assertEqual(repr(self.config),before)
        self.assertEqual(self.read(),result)

    def test_invalid_cutoff_raises_before_any_db_access(self):
        for value in (True,float("nan"),float("inf"),"not a time",-1):
            with self.subTest(value=value),patch.object(capture,"_read_only",side_effect=AssertionError("must not open")):
                with self.assertRaises(ValueError):
                    capture.capture_guardian(self.config,now=value)


if __name__=="__main__":
    unittest.main(verbosity=2)
