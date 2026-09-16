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
            manager.stage(json.loads(channel.read_text())['manifest_url'])
            if job['action']=='update_check':
                jobs.finish(args.id,'completed','Paquete descargado y firma verificada; instalación pendiente')
            else:
                # Until supervised activation exists, refuse changing an operational installation.
                jobs.finish(args.id,'failed','Paquete verificado; falta habilitar parada, reinicio y recuperación supervisados')
        else:
            raise ValueError('Invalid action')
    except Exception as error:
        jobs.finish(args.id,'failed','Trabajo detenido: '+type(error).__name__)

if __name__=='__main__':
    main()
