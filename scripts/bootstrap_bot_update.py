"""One-time signed activation after the owner has stopped the legacy engine.

This command never stops a discovered process. It refuses an occupied engine
lock. Routine subsequent updates use the cooperative remote supervisor.
"""
import argparse
import json
import secrets
import sys
import tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from trader.update_manager import UpdateManager,atomic_json,release_id,verify
from trader.update_supervisor import UpdateSupervisor
from trader.runtime import single_instance


def activate_stopped(manager,package,envelope,approved,runtime=None):
    supervisor=UpdateSupervisor(manager,runtime)
    with single_instance(supervisor.lock):
        manifest=verify(package,envelope,manager.public_key)
        if release_id(manifest)!=approved or manifest.get('runtime_protocol')!=1:
            raise ValueError('Exact supervised release approval required')
        with manager.locks():
            # No process is stopped by bootstrap, including an existing legacy engine.
            old=tomllib.loads((manager.root/'pyproject.toml').read_text())['project']['version']
        token=secrets.token_hex(32)
        state={'token':token,'release_id':approved,'old_version':old,'version':manifest['version'],
               'phase':'bootstrap','job_id':None}
        atomic_json(supervisor.record,state)
        supervisor.phase(token,'stopping')
        child=None
        try:
            manager.apply(package,envelope,expected_release=approved,defer_commit=True)
            supervisor.phase(token,'candidate')
            child=supervisor.runtime.start(token)
            supervisor.wait_ready(child,token,manifest['version'],'candidate')
            manager.commit_pending(approved,lambda:supervisor.ready(child,token,manifest['version'],'candidate'))
            atomic_json(supervisor.control.activation,{'token':token,'release_id':approved})
            supervisor.control.maintenance.unlink()
            supervisor.wait_ready(child,token,manifest['version'],'running')
            atomic_json(supervisor.record,{**state,'phase':'completed'})
            return {'status':'installed_healthy','version':manifest['version']}
        except BaseException:
            record=json.loads(manager.journal.read_text()) if manager.journal.exists() else {}
            if record.get('phase')=='committed' and record.get('release_id')==approved:
                atomic_json(supervisor.record,{**state,'phase':'committed_restart_required'})
                raise
            supervisor.phase(token,'cancelled')
            supervisor.runtime.stop_owned(child)
            manager.recover()
            # The original legacy engine lacks the handshake. Restore its files
            # and data, but require the owner to restart it rather than guess health.
            atomic_json(supervisor.record,{**state,'phase':'bootstrap_rolled_back'})
            raise RuntimeError('Bootstrap failed; original code and database restored, engine remains stopped')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--release-id',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    manager=UpdateManager(args.source,ROOT/'data/trusted-update.pub',ROOT/'data/remote-updates')
    package=manager.state/'staged.zip';envelope=manager.state/'staged.zip.manifest.json'
    manifest=verify(package,envelope,manager.public_key)
    if release_id(manifest)!=args.release_id:
        raise ValueError('Approved package changed')
    if args.apply:
        print(json.dumps(activate_stopped(manager,package,envelope,args.release_id)))
    else:
        print(json.dumps({'verified':True,'version':manifest['version'],'release_id':release_id(manifest),'engine_started':False}))


if __name__=='__main__':main()
