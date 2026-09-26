"""Run a persisted allowlisted job outside the trading process."""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.windows_agent import source_settings
from trader.remote_jobs import RemoteJobs
from trader.runtime import single_instance

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--id',type=int,required=True)
    args=parser.parse_args()
    jobs=RemoteJobs(ROOT,args.source)
    job=json.loads((jobs.directory/(str(args.id)+'.json')).read_text())
    try:
        config=source_settings(args.source)
        if job['action']=='research':
            from trader.research import execute_research
            report=(args.source/'data/research/latest.json').resolve()
            config=replace(config,research=replace(config.research,report_path=report))
            with single_instance(report.parent/'research.lock'):
                from trader.runtime_control import RuntimeControl
                RuntimeControl(config.bot.database_path.parent).guard_start()
                execute_research(config)
            jobs.finish(args.id,'completed','Research Lab completado; informe sincronizado en el próximo ciclo del agente')
        elif job['action'] in ('update_check','update_install'):
            from trader.update_manager import UpdateManager
            channel=ROOT/'data/trusted-release.json'
            key=ROOT/'data/trusted-update.pub'
            if not channel.is_file() or not key.is_file():
                jobs.finish(args.id,'failed','Canal firmado y clave de confianza aún no configurados; no se instaló nada')
                return
            manager=UpdateManager(args.source,key,state_dir=ROOT/'data/remote-updates')
            settings = json.loads(channel.read_text())
            staged = manager.stage(settings['manifest_url'], allow_current=job['action']=='update_check')
            if job['action']=='update_install' and job.get('release_id') != staged['release_id']:
                raise ValueError('Approved release differs from staged package')
            if job['action']=='update_check':
                from trader.update_manager import atomic_json
                current_sequence = json.loads(manager.sequence.read_text())['sequence'] if manager.sequence.exists() else 0
                candidate = ROOT/'data/verified-release.json'
                if staged['sequence'] <= current_sequence:
                    candidate.unlink(missing_ok=True)
                    jobs.finish(args.id,'completed','Estás actualizado · bot '+staged['version']+' · firma verificada')
                else:
                    atomic_json(candidate, {key:staged[key] for key in ('version','release_id','sequence','expires','commit')})
                    jobs.finish(args.id,'completed','Versión '+staged['version']+' verificada y lista para instalar')
            else:
                if settings.get('supervised_install_enabled') is not True or args.source.resolve() == ROOT:
                    jobs.finish(args.id,'failed','Paquete verificado; instalación supervisada aún no aprovisionada')
                    return
                from trader.update_supervisor import UpdateSupervisor
                package = Path(staged['package'])
                result = UpdateSupervisor(manager).install(package, package.with_name(package.name+'.manifest.json'), job['release_id'], job_id=args.id)
                active=source_settings(args.source).bot.mode.upper()
                jobs.finish(args.id,'completed','Bot '+result['version']+' instalado; arranque y portal local comprobados en '+active)
        elif job['action'] == 'update_restore':
            from trader.update_manager import UpdateManager
            from trader.update_supervisor import UpdateSupervisor
            channel=ROOT/'data/trusted-release.json'
            key=ROOT/'data/trusted-update.pub'
            if (not channel.is_file() or not key.is_file() or args.source.resolve()==ROOT
                    or json.loads(channel.read_text()).get('supervised_install_enabled') is not True):
                raise RuntimeError('Restauración supervisada no configurada')
            manager=UpdateManager(args.source,key,state_dir=ROOT/'data/remote-updates')
            result=UpdateSupervisor(manager).restore(job['release_id'],job_id=args.id)
            active=source_settings(args.source).bot.mode.upper()
            jobs.finish(args.id,'completed','Código '+result['version']+' restaurado y motor '+active+' comprobado; datos financieros conservados')
        else:
            raise ValueError('Invalid action')
    except Exception as error:
        jobs.finish(args.id,'failed','Trabajo detenido: '+type(error).__name__)

if __name__=='__main__':
    main()
