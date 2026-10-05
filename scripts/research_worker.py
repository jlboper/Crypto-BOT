"""Installed-source entry point; supervisor never imports an old research module."""
import argparse
import os
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from trader.config import load_config
    from trader.research import execute_research
    from trader.research_runtime import DAY, atomic, read, failure_message
    from trader.runtime import single_instance
    from trader.runtime_control import RuntimeControl
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT/'config.toml')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.report:
        config = replace(config, research=replace(config.research, report_path=args.report))
    if os.name != 'nt':
        os.nice(10)
    with single_instance(config.research.report_path.parent/'research.lock'):
        RuntimeControl(config.bot.database_path.parent).guard_start()
        path = config.research.report_path.parent/'state.json'
        state = read(path)
        state.update(running=True, status='RUNNING', started_at=datetime.now(UTC).isoformat(),
                     error=None, next_due=time.time()+DAY)
        atomic(path, state)
        try:
            report = execute_research(config)
        except Exception as error:
            state = read(path)
            state.update(running=False, status='FAILED', error=failure_message(error, state), progress='')
            atomic(path, state)
            raise
        else:
            state = read(path)
            state.update(running=False, status='COMPLETED', error=None, progress='', next_due=time.time()+DAY,
                         last_completed_at=report['generated_at'])
            atomic(path, state)


if __name__ == '__main__':
    main()
