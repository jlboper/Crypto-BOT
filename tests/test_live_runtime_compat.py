"""Prepared owner-gated runtime/update compatibility; no real accounts or network."""
import base64
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from scripts.windows_agent import source_settings
from trader.config import load_config
from trader.live_runtime_gate import LIVE_DATABASES,LIVE_SPOT_DATABASE,LIVE_SPOT_KILL,require_runtime_mode
from trader.update_manager import UpdateManager,atomic_json,canonical,release_id,verify
from trader.update_supervisor import ProcessRuntime,UpdateSupervisor

SOURCE=Path(__file__).resolve().parents[1]


class LiveRuntimeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        # Hosted Windows may return an 8.3 TEMP alias. The production path
        # confinement resolves it; compare the same canonical physical root.
        self.root=Path(self.temp.name).resolve()
        (self.root/"data").mkdir(); (self.root/"trader").mkdir()
        (self.root/"config.toml").write_bytes((SOURCE/"config.toml").read_bytes())
        (self.root/"pyproject.toml").write_text('[project]\nversion="0.10.53"\n')
        (self.root/"trader/runtime_control.py").write_text("# old runtime fixture\n")
        (self.root/"trader/__main__.py").write_text("# old code fixture\n")
        self.env=patch.dict(os.environ,{"EXECUTION_MODE":"testnet"}); self.env.start(); self.addCleanup(self.env.stop)
        self.owner=patch("trader.live_runtime_gate.owner_mode_authorized",return_value=False)
        self.authorized=self.owner.start(); self.addCleanup(self.owner.stop)
        self.key=Ed25519PrivateKey.generate(); self.pub=self.root/"trusted.pub"
        self.pub.write_bytes(self.key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
        self.manager=UpdateManager(self.root,self.pub)

    def enable_synthetic_live(self):
        self.authorized.return_value=True
        (self.root/".env.local").write_text("EXECUTION_MODE=live\n")
        os.environ["EXECUTION_MODE"]="live"

    def package(self,prepared=1):
        payloads={"trader/__main__.py":b"# candidate fixture\n","trader/runtime_control.py":b"# candidate runtime\n",
            "pyproject.toml":b'[project]\nversion="0.10.54"\n'}
        if prepared is not None:
            payloads.update({name:b"# prepared fixture\n" for name in ("trader/live_runtime_gate.py",
                "trader/live_authorization.py","trader/local_protection.py","trader/central_admission.py")})
        package=self.root/"test-package.zip"; envelope=self.root/"test-manifest.json"
        with zipfile.ZipFile(package,"w") as archive:
            for name,payload in payloads.items(): archive.writestr(name,payload)
        manifest={"app":"crypto-ai-trading-bot","mode":"testnet","version":"0.10.54","runtime_protocol":1,
            "sequence":1,"expires":time.time()+3600,"size":package.stat().st_size,
            "sha256":hashlib.sha256(package.read_bytes()).hexdigest(),
            "files":{name:hashlib.sha256(value).hexdigest() for name,value in payloads.items()}}
        if prepared is not None: manifest["prepared_live_protocol"]=prepared
        atomic_json(envelope,{"manifest":manifest,"signature":base64.b64encode(self.key.sign(canonical(manifest))).decode()})
        return package,envelope,manifest

    def test_protected_owner_proof_and_explicit_request_are_both_required(self):
        with self.assertRaises(ValueError): require_runtime_mode(self.root,"live")
        self.authorized.return_value=True
        self.assertEqual(load_config(self.root/"config.toml").bot.mode,"testnet")
        self.assertFalse((self.root/"data/live").exists())
        self.enable_synthetic_live(); cfg=load_config(self.root/"config.toml")
        self.assertEqual(cfg.bot.mode,"live")
        self.assertEqual(cfg.bot.database_path,self.root/LIVE_SPOT_DATABASE)
        self.assertEqual(cfg.bot.kill_switch_path,self.root/LIVE_SPOT_KILL)
        self.assertNotEqual(cfg.bot.database_path,cfg.futures_testnet.database_path)
        self.assertFalse(cfg.research.automatic)
        self.assertFalse((self.root/"data/live").exists())
        self.authorized.return_value=False
        with self.assertRaises(ValueError): load_config(self.root/"config.toml")

    def test_agent_live_projection_requires_existing_ledger_and_owner_proof(self):
        self.enable_synthetic_live()
        with self.assertRaisesRegex(ValueError,"Existing active database"): source_settings(self.root)
        ledger=self.root/LIVE_SPOT_DATABASE; ledger.parent.mkdir()
        with closing(sqlite3.connect(ledger)) as db: db.execute("CREATE TABLE original(value INTEGER)"); db.commit()
        cfg=source_settings(self.root)
        self.assertEqual(cfg.bot.mode,"live"); self.assertEqual(cfg.bot.database_path,ledger)
        self.authorized.return_value=False
        with self.assertRaises(ValueError): source_settings(self.root)

    def test_four_separate_live_paths_use_the_same_global_supervisor_lock(self):
        self.enable_synthetic_live()
        self.assertEqual(tuple(x.relative_to(self.root).as_posix() for x in self.manager.database_paths()),LIVE_DATABASES)
        supervisor=UpdateSupervisor(self.manager,runtime=Mock())
        self.assertEqual(supervisor.control.directory,self.root/"data")
        self.authorized.return_value=False
        with self.assertRaises(ValueError): self.manager.database_path()

    def test_live_health_checks_proof_pid_and_token(self):
        self.enable_synthetic_live(); runtime=ProcessRuntime(self.root); child=Mock(pid=777); child.poll.return_value=None
        def response(pid=777): return io.BytesIO(json.dumps({"mode":"live","pid":pid,"token":"TOKEN"}).encode())
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.return_value=response(); self.assertTrue(runtime.health(child,"TOKEN"))
            opener.return_value.open.return_value=response(778); self.assertFalse(runtime.health(child,"TOKEN"))
            self.authorized.return_value=False
            opener.return_value.open.return_value=response(); self.assertFalse(runtime.health(child,"TOKEN"))

    def test_signed_prepared_protocol_has_no_activation_authority_and_rejects_unknown_versions(self):
        package,envelope,manifest=self.package()
        self.assertEqual(verify(package,envelope,self.pub)["prepared_live_protocol"],1)
        self.assertEqual(manifest["mode"],"testnet"); self.assertFalse(self.authorized.return_value)
        for invalid in (True,0,2,"1"):
            package,envelope,_=self.package(invalid)
            with self.assertRaisesRegex(ValueError,"prepared LIVE protocol"): verify(package,envelope,self.pub)

    def test_live_update_requires_supervised_compatible_candidate_before_mutation(self):
        self.enable_synthetic_live()
        package,envelope,manifest=self.package(None)
        with self.assertRaisesRegex(ValueError,"compatible supervised"):
            self.manager.apply(package,envelope,expected_release=release_id(manifest),defer_commit=True)
        package,envelope,_=self.package()
        with self.assertRaisesRegex(ValueError,"compatible supervised"): self.manager.apply(package,envelope)
        self.assertEqual((self.root/"trader/__main__.py").read_text(),"# old code fixture\n")

    def test_live_precommit_recovery_restores_code_but_never_rewinds_financial_facts(self):
        self.enable_synthetic_live()
        for path in self.manager.database_paths():
            path.parent.mkdir(exist_ok=True)
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE financial(value INTEGER)"); db.execute("INSERT INTO financial VALUES(16)"); db.commit()
        package,envelope,manifest=self.package()
        self.manager.apply(package,envelope,expected_release=release_id(manifest),defer_commit=True)
        record=json.loads(self.manager.journal.read_text())
        self.assertEqual(record["financial_state_policy"],"PRESERVE_LIVE")
        self.assertEqual(len(record["live_database_snapshots"]),4)
        for path in self.manager.database_paths():
            with closing(sqlite3.connect(path)) as db: db.execute("UPDATE financial SET value=17"); db.commit()
        self.assertTrue(self.manager.recover())
        self.assertEqual((self.root/"trader/__main__.py").read_text(),"# old code fixture\n")
        for path in self.manager.database_paths():
            with closing(sqlite3.connect(path)) as db: self.assertEqual(db.execute("SELECT value FROM financial").fetchone()[0],17)
        for snapshot in record["live_database_snapshots"]:
            with closing(sqlite3.connect(self.manager.state/snapshot["backup"])) as db:
                self.assertEqual(db.execute("SELECT value FROM financial").fetchone()[0],16)


if __name__=="__main__": unittest.main()
