"""Explicit bridge to an existing PAPER install; never constructs a trading engine."""
import argparse
import json
import os
import sys
import time
import tomllib
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from trader.config import load_config
from trader.remote_agent import RemoteAgent
from trader.portal_snapshot import dashboard_snapshot
from trader.remote_jobs import RemoteJobs


def source_settings(source):
    source = Path(source).resolve(strict=True)
    raw = tomllib.loads((source / "config.toml").read_text(encoding="utf-8"))
    if raw["bot"]["mode"].lower() != "paper":
        raise ValueError("Source must remain PAPER")
    def confined(value):
        path = (source / value).resolve()
        if not path.is_relative_to(source) or path == source:
            raise ValueError("Source paths must remain within the selected installation")
        return path
    database = confined(raw["bot"]["database_path"])
    kill = confined(raw["bot"]["kill_switch_path"])
    if not database.is_file():
        raise ValueError("Existing database required; no database will be created")
    config = load_config(source / "config.toml")
    model = str(raw["ai"]["model"])
    # Read only the non-secret model override; never import source API credentials.
    for name in (".env.local", ".env"):
        file = source / name
        if file.is_file():
            found = next((line.split("=", 1)[1].strip().strip('"\'') for line in file.read_text(encoding="utf-8").splitlines()
                          if line.split("=", 1)[0].strip() == "OPENAI_MODEL" and "=" in line), None)
            if found:
                model = found
                break
    return replace(config, bot=replace(config.bot, database_path=database, kill_switch_path=kill), ai=replace(config.ai, model=model))


def recover_updates(source):
    # Recovery is opt-in and precedes reading a possibly migrated database.
    channel = ROOT/'data/trusted-release.json'
    recovery_record = ROOT/'data/remote-updates/supervisor.json'
    if channel.is_file() and recovery_record.is_file():
        settings = json.loads(channel.read_text())
        record = json.loads(recovery_record.read_text())
        if record.get('phase') == 'bootstrap_rolled_back':
            print('Initial update rolled back; legacy startup requires owner review')
            return
        if settings.get('supervised_install_enabled') is True and source.resolve() != ROOT:
            recovered = {'status': record.get('phase')}
            if record.get('phase') not in {'completed', 'rolled_back'}:
                from trader.update_manager import UpdateManager
                from trader.update_supervisor import UpdateSupervisor
                recovered = UpdateSupervisor(UpdateManager(source, ROOT/'data/trusted-update.pub',
                                                           state_dir=ROOT/'data/remote-updates')).recover()
            if type(record.get('job_id')) is int and record['job_id'] > 0:
                completed = recovered['status'] == 'completed'
                jobs = RemoteJobs(ROOT, source)
                try:
                    jobs.finish(record['job_id'], 'completed' if completed else 'failed',
                        'Actualización recuperada y arranque comprobado' if completed else 'Actualización interrumpida; versión anterior restaurada')
                except (OSError, ValueError):
                    print('Recovered update; remote job acknowledgement unavailable')


def update_candidate(source):
    candidate = ROOT/'data/verified-release.json'
    channel = ROOT/'data/trusted-release.json'
    sequence = ROOT/'data/remote-updates/sequence.json'
    if not candidate.is_file() or not channel.is_file():
        return None
    value = json.loads(candidate.read_text())
    if value['expires'] <= time.time() or (sequence.exists() and value['sequence'] <= json.loads(sequence.read_text())['sequence']):
        return None
    value['enabled'] = (json.loads(channel.read_text()).get('supervised_install_enabled') is True
                        and (source/'trader/runtime_control.py').is_file())
    return value


def restore_candidate(source):
    channel = ROOT/'data/trusted-release.json'
    key = ROOT/'data/trusted-update.pub'
    if source.resolve() == ROOT or not channel.is_file() or not key.is_file():
        return None
    if json.loads(channel.read_text()).get('supervised_install_enabled') is not True:
        return None
    from trader.update_manager import UpdateManager
    from trader.update_supervisor import UpdateSupervisor
    return UpdateSupervisor(UpdateManager(source,key,state_dir=ROOT/'data/remote-updates')).available_restore()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--autostart", action="store_true")
    args = parser.parse_args()
    if not args.check:
        recover_updates(args.source)
    config = source_settings(args.source)
    production = json.loads((ROOT / "cloudflare/wrangler.production.json").read_text())
    values = dict(line.split("=", 1) for line in (ROOT / "cloudflare/.secrets/windows-agent.env").read_text().splitlines() if "=" in line)
    if values["PORTAL_ORIGIN"] != production["vars"]["PORTAL_ORIGIN"]:
        raise ValueError("Device destination differs from the deployed portal")
    state = ROOT / "data"
    agent = RemoteAgent(config, values["PORTAL_ORIGIN"], values["PORTAL_DEVICE_TOKEN"], state_directory=state)
    agent.dashboard_provider = lambda: dashboard_snapshot(config, args.source / 'data/research/latest.json')
    agent.jobs = RemoteJobs(ROOT,args.source)
    agent.update_provider = lambda: update_candidate(args.source)
    agent.restore_provider = lambda: restore_candidate(args.source)
    snapshot = agent.snapshot()
    if args.check:
        print(json.dumps({"mode": snapshot["mode"], "database_readable": True,
                          "last_cycle_at": snapshot["last_cycle_at"], "engine_started": False}))
        return
    state.mkdir(parents=True, exist_ok=True)
    if args.autostart:
        (state / "REMOTE_STOP").unlink(missing_ok=True)
    def validate():
        raw = tomllib.loads((args.source / "config.toml").read_text(encoding="utf-8"))
        if str(raw["bot"]["mode"]).lower() != "paper":
            raise ValueError("Source must remain PAPER")
        if (args.source / raw["bot"]["database_path"]).resolve() != config.bot.database_path or (args.source / raw["bot"]["kill_switch_path"]).resolve() != config.bot.kill_switch_path:
            raise ValueError("Source paths changed; restart after review")
    last_success = None
    def report(ok):
        nonlocal last_success
        if ok:
            last_success = time.time()
        temporary = state / "remote-status.tmp"
        temporary.write_text(json.dumps({"pid": os.getpid(), "at": time.time(), "last_success": last_success,
                                         "sync_ok": ok, "error_type": agent.last_error, "mode": "PAPER", "engine_started": False}))
        temporary.replace(state / "remote-status.json")
    agent.run(stop=lambda: (state / "REMOTE_STOP").exists(), validate=validate, report=report)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No traceback containing server bodies, tokens or request headers.
        print("Remote agent stopped: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
