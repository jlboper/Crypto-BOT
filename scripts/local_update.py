"""Local, signed update center for the independent Windows supervisor.

No browser session or portal heartbeat is required to install an already
staged package. The online check still needs Internet to download a release.
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent



def discover_agent_root() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Automatic supervisor discovery requires Windows")
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", "Crypto Paper Portal Agent", "/XML"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or not result.stdout:
        raise FileNotFoundError("Independent supervisor task not found")
    root = ET.fromstring(result.stdout.decode("utf-16", errors="strict"))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    working = root.findtext(".//t:Exec/t:WorkingDirectory", namespaces=ns)
    if not working:
        raise FileNotFoundError("Independent supervisor working directory unavailable")
    path = Path(working).resolve(strict=True)
    if not (path / "scripts" / "windows_agent.py").is_file():
        raise FileNotFoundError("Independent supervisor installation unavailable")
    return path


def channel(source: Path, agent_root: Path):
    from trader.update_manager import UpdateManager
    source = source.resolve(strict=True)
    agent_root = agent_root.resolve(strict=True)
    if source == agent_root:
        raise ValueError('Separate supervisor installation required')
    with (source / 'config.toml').open('rb') as handle:
        configured_mode = str(tomllib.load(handle)['bot'].get('mode', 'paper')).lower()
    if configured_mode not in {'paper', 'testnet'}:
        raise ValueError('Source execution mode must be PAPER or TESTNET')
    key = agent_root / 'data/trusted-update.pub'
    settings_path = agent_root / 'data/trusted-release.json'
    if not key.is_file() or not settings_path.is_file():
        raise FileNotFoundError('Trusted local channel is not configured')
    settings = json.loads(settings_path.read_text(encoding='utf-8'))
    if settings.get('supervised_install_enabled') is not True:
        raise RuntimeError('Supervised installation is not enabled')
    return UpdateManager(source, key, state_dir=agent_root / 'data/remote-updates'), settings


def staged(manager) -> dict:
    from trader.update_manager import release_id, verify
    package = manager.state / 'staged.zip'
    envelope = manager.state / 'staged.zip.manifest.json'
    minimum = json.loads(manager.sequence.read_text())['sequence'] if manager.sequence.exists() else 0
    manifest = verify(package, envelope, manager.public_key, minimum)
    installed = tomllib.loads((manager.root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    if tuple(map(int, manifest['version'].split('.'))) <= tuple(map(int, installed.split('.'))):
        raise ValueError('Signed release is not newer than the installed version')
    if manifest.get('runtime_protocol') != 1 or 'trader/runtime_control.py' not in manifest['files']:
        raise ValueError('Signed release lacks supervised runtime')
    return {'version': manifest['version'], 'release_id': release_id(manifest),
            'commit': manifest.get('commit'), 'package': package, 'envelope': envelope}


def run(source: Path, action: str, approved: str | None = None, *, agent_root: Path = ROOT) -> dict:
    from trader.update_supervisor import UpdateSupervisor
    manager, settings = channel(source, agent_root)
    if action == 'check-online':
        manager.stage(settings['manifest_url'])
    info = staged(manager)
    if action != 'install':
        return {'status': 'verified_local_package', 'version': info['version'],
                'release_id': info['release_id'], 'commit': info['commit'],
                'order_submission_enabled': False}
    if approved != info['release_id']:
        raise ValueError('Exact signed release approval required')
    # The supervisor re-verifies the signature/hash and all runtime gates.
    return UpdateSupervisor(manager).install(info['package'], info['envelope'], approved)


def failure_code(error: Exception) -> str:
    message = str(error)
    known = {
        'Supervised installation is not enabled': 'SUPERVISOR_DISABLED',
        'Recover previous maintenance before installing': 'MAINTENANCE_PENDING',
        'Existing engine has no cooperative runtime status': 'ENGINE_RUNTIME_STALE',
        'Existing engine is stopped; supervised installation requires a running engine': 'ENGINE_STOPPED',
        'Owned engine exited before readiness': 'CANDIDATE_EXITED',
        'runtime health check failed; stop candidate before recovery': 'CANDIDATE_HEALTH_FAILED',
    }
    if message in known:
        return known[message]
    if isinstance(error, TimeoutError):
        return 'SUPERVISOR_TIMEOUT'
    if isinstance(error, FileNotFoundError):
        return 'LOCAL_CHANNEL_MISSING'
    if isinstance(error, ValueError):
        return 'LOCAL_VALIDATION_FAILED'
    return type(error).__name__.upper()


def main() -> None:
    parser = argparse.ArgumentParser(description='Independent local trading update center')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--agent-root', type=Path, required=False)
    parser.add_argument('--delay-seconds', type=float, default=0.0)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument('--check-online', action='store_true')
    options.add_argument('--check-offline', action='store_true')
    options.add_argument('--install', metavar='EXACT_RELEASE_ID')
    args = parser.parse_args()
    # Run the updater from the independent agent code, not the files that are
    # about to be replaced in the signed target installation.
    if args.delay_seconds < 0 or args.delay_seconds > 10:
        raise SystemExit('Invalid delay')
    if args.delay_seconds:
        import time
        time.sleep(args.delay_seconds)
    agent_root = args.agent_root.resolve(strict=True) if args.agent_root else discover_agent_root()
    if not (agent_root / 'scripts/windows_agent.py').is_file():
        raise SystemExit('Independent supervisor not found')
    sys.path.insert(0, str(agent_root))
    action = 'check-online' if args.check_online else 'check-offline' if args.check_offline else 'install'
    try:
        print(json.dumps(run(args.source, action, args.install, agent_root=agent_root), ensure_ascii=False))
    except Exception as error:
        # Emit only an allowlisted machine-readable category. Never expose paths,
        # credentials, HTTP bodies or raw exception text to the GUI.
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__,
                          'code': failure_code(error)}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
