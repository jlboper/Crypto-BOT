"""Durable daily scheduling and bounded portal projection; stdlib + lock only."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from .runtime import single_instance

DAY = 86400
MAX_SECONDS = 6900
_cancel = ContextVar('research_cancel', default=None)


def check_cancel():
    check = _cancel.get()
    if check is not None:
        check()


@contextmanager
def cancellation(config):
    from .runtime_control import RuntimeControl
    control = RuntimeControl(config.bot.database_path.parent)
    deadline = time.monotonic()+MAX_SECONDS
    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError('Research maximum duration reached')
        control.guard_start()
    token = _cancel.set(check)
    try:
        check_cancel()
        yield
    finally:
        _cancel.reset(token)


def atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.stat().st_size <= 2_000_000 else {}
    except (OSError, ValueError):
        return {}


def iso(timestamp: float | None) -> str | None:
    return datetime.fromtimestamp(timestamp, UTC).isoformat() if timestamp else None


def lab_state(report_path: Path, *, automatic: bool = True) -> dict:
    directory = report_path.parent
    state = read(directory/'state.json')
    try:
        with single_instance(directory/'research.lock'):
            running = False
    except RuntimeError:
        running = True
    generated = state.get('last_completed_at') or read(report_path).get('generated_at')
    return {'running': running, 'automatic': automatic, 'interval_hours': 24,
            'started_at': state.get('started_at'), 'last_completed_at': generated,
            'next_run_at': iso(state.get('next_due', time.time())),
            'progress': state.get('progress', '') if running else '',
            'error': state.get('error'), 'status': 'RUNNING' if running else
            'INTERRUPTED' if state.get('running') else state.get('status', 'WAITING'),
            'requires_running_app': True}


def progress(report_path: Path, text: str) -> None:
    check_cancel()
    state = read(report_path.parent/'state.json')
    state.update(running=True, progress=text[:150])
    atomic(report_path.parent/'state.json', state)


def studied_symbols(report_path: Path, fallback=()):
    import re
    symbols = read(report_path.parent/'state.json').get('studied_spot', [])
    if symbols and len(symbols) <= 30 and all(isinstance(s, str) and re.fullmatch(r'[A-Z0-9]{2,30}', s) for s in symbols):
        return tuple(symbols)
    return fallback


class ResearchScheduler:
    """Starts a low-priority independent child. Never executes analysis in trading threads."""
    def __init__(self, config):
        self.config = config
        self.child = None
        self.started = 0.0
        self.log = None

    def tick(self, *, manual: bool = False, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        directory = self.config.research.report_path.parent
        if self.child is not None:
            if self.child.poll() is None and now-self.started <= MAX_SECONDS:
                return False
            if self.child.poll() is None:
                self.child.kill()
                self.child.wait()
            if self.log:
                self.log.close()
            self.child = None
        if not manual and not self.config.research.automatic:
            return False
        try:
            with single_instance(directory/'launch.lock'):
                if lab_state(self.config.research.report_path)['running']:
                    return False
                state = read(directory/'state.json')
                if not manual and now < state.get('next_due', 0):
                    return False
                from .config import PROJECT_ROOT
                source = PROJECT_ROOT
                config_path = getattr(self.config, 'source_path', None) or source/'config.toml'
                if state.get('status') == 'STARTING' and now-state.get('launch_at', 0) < 60:
                    return False
                directory.mkdir(parents=True, exist_ok=True)
                self.log = (directory/'worker.log').open('w', encoding='utf-8')
                state.update(next_due=now+DAY, launch_at=now, status='STARTING', error=None,
                             trigger='manual' if manual else 'daily')
                atomic(directory/'state.json', state)
                try:
                    self.child = subprocess.Popen(
                        [sys.executable, '-I', '-B', str(source/'scripts/research_worker.py'),
                         '--config', str(config_path), '--report', str(self.config.research.report_path)],
                        cwd=source, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)|getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0))
                    self.started = now
                except Exception:
                    self.log.close()
                    state.update(status='FAILED', error='No se pudo iniciar el análisis')
                    atomic(directory/'state.json', state)
                    raise
                return True
        except RuntimeError:
            return False


def archive_report(report: dict, path: Path) -> None:
    """Immutable full runs; the portal carries only the latest 30 summaries."""
    import hashlib
    stamp = report['generated_at'].replace(':', '').replace('+', '_')
    run_id = stamp+'-'+hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:12]
    report['run_id'] = run_id
    report['history'] = []
    archive = path.parent/'runs'/f'{run_id}.json'
    archive.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create protects evidence from a repeated ID.
    with archive.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    index_path = path.parent/'history.json'
    index = read(index_path).get('runs', [])
    index.append({'run_id': run_id, 'generated_at': report['generated_at'],
                  'assets': report['summary']['assets'], 'futures_assets': len(report.get('futures_assets', [])),
                  'candidates': report['summary'].get('forward_test_ready', 0),
                  'scenarios': [{k: s.get(k) for k in ('market', 'profile', 'leverage', 'net_return_pct',
                                'max_drawdown_pct', 'closed_trades', 'liquidations')}
                                for s in report.get('joint_portfolios', [])]})
    # Full reports are retained. The bounded index avoids growing snapshot cost.
    atomic(index_path, {'runs': index[-90:]})
    report['history'] = index[-30:]
    atomic(path, report)


def project_report(report: dict) -> dict:
    """Same compact report in local and remote UI; full evidence stays in run archives."""
    result = copy.deepcopy(report)
    result.pop('correlations', None)
    result.pop('promotion_pipeline', None)
    for asset in result.get('assets', []):
        asset.pop('windows', None)
        if 'fixed_strategy' in asset:
            asset.pop('walk_forward', None)
            asset.pop('monte_carlo', None)
        if isinstance(asset.get('candidate_full_sample'), dict):
            asset['candidate_full_sample'] = {k:v for k,v in asset['candidate_full_sample'].items()
                if k in ('return_pct', 'benchmark_return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'trades')}
        for candidate in asset.get('candidates', []):
            for key in list(candidate):
                if key not in ('strategy', 'family', 'development_oos_return_pct', 'development_oos_trades',
                               'development_positive_folds_pct', 'selected_folds'):
                    candidate.pop(key)
        for key in ('base_costs', 'double_costs'):
            if isinstance(asset.get('holdout', {}).get(key), dict):
                asset['holdout'][key] = {k:v for k,v in asset['holdout'][key].items()
                    if k in ('return_pct', 'benchmark_return_pct', 'max_drawdown_pct', 'sharpe_ratio', 'trades')}
        for name in ('fixed_strategy', 'adaptive_selector', 'walk_forward'):
            if isinstance(asset.get(name), dict):
                asset[name].pop('windows', None)
                asset[name].pop('details', None)
                asset[name].pop('trade_records', None)
    for scenario in result.get('joint_portfolios', []):
        scenario.pop('trades', None)
        for key in ('holdout', 'double_cost_holdout'):
            if isinstance(scenario.get(key), dict):
                scenario[key] = {k:v for k,v in scenario[key].items() if k in
                    ('net_return_pct', 'max_drawdown_pct', 'closed_trades', 'fees', 'funding_cost', 'liquidations')}
    for asset in result.get('futures_assets', []):
        for key in ('holdout', 'double_cost_holdout'):
            if isinstance(asset.get(key), dict):
                asset[key] = {k:v for k,v in asset[key].items() if k in
                    ('net_return_pct', 'max_drawdown_pct', 'closed_trades', 'fees', 'funding_cost', 'liquidations')}
    # Bounded summaries, curves and detailed evidence per asset fit the sync budget.
    result['history'] = result.get('history', [])[-12:]
    if len(json.dumps(result, allow_nan=False).encode()) > 240_000:
        for asset in result.get('assets', []):
            asset.pop('candidates', None)
            asset.pop('parameter_sensitivity', None)
            asset.pop('regime_analysis', None)
        for scenario in result.get('joint_portfolios', []):
            curve = scenario.get('curve', [])
            scenario['curve'] = curve[::4]+([curve[-1]] if curve and curve[-1] != curve[::4][-1] else [])
        result['projection_note'] = 'Detalle completo conservado en el historial local de ejecuciones.'
    if len(json.dumps(result, allow_nan=False).encode()) > 240_000:
        raise ValueError('Research projection exceeds size budget')
    return result
