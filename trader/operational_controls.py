"""Allowlisted owner controls; only a supervised PAPER motor can be restarted."""
from __future__ import annotations

import json
import os
import secrets
import time
import tomllib
from dataclasses import replace
from pathlib import Path

from .config import load_config
from .runtime import single_instance
from .runtime_control import RuntimeControl
from .update_manager import atomic_json
from .update_supervisor import ProcessRuntime

MODELS = frozenset({'gpt-5.6-luna', 'gpt-6-luna'})


def _model_file(source: Path, model: str) -> None:
    path = source / '.env.local'
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Local credential file unavailable')
    original = path.read_text(encoding='utf-8')
    rows = [row for row in original.splitlines() if row.partition('=')[0].strip() != 'OPENAI_MODEL']
    rows.append('OPENAI_MODEL=' + model)
    from tempfile import NamedTemporaryFile
    temporary = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=source, prefix='.env-model-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write('\n'.join(rows) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def execute(source: Path, action: str, payload: dict) -> dict:
    source = source.resolve(strict=True)
    if not isinstance(payload, dict) or action not in {'ai_model', 'restart_engine'}:
        raise ValueError('Unknown operational control')
    if action == 'ai_model':
        if set(payload) != {'model'} or payload['model'] not in MODELS:
            raise ValueError('Unknown model')
    elif payload:
        raise ValueError('Restart does not accept parameters')
    config = load_config(source / 'config.toml')
    if config.bot.mode not in {'paper', 'testnet'}:
        raise ValueError('Supported trading motor required')
    data = config.bot.database_path.parent
    control = RuntimeControl(data)
    with (source / 'pyproject.toml').open('rb') as stream:
        version = tomllib.load(stream)['project']['version']
    # Serialize with signed installs and restoration, including their recovery path.
    with single_instance(source / 'data/update-supervisor.lock'):
        if control.maintenance.exists():
            raise ValueError('Maintenance already in progress')
        status = json.loads(control.status.read_text(encoding='utf-8'))
        if status.get('mode') != config.bot.mode or status.get('phase') != 'running' or status.get('version') != version:
            raise ValueError('Healthy installed trading motor required')
        old_model = config.ai.model
        if old_model not in MODELS:
            raise ValueError('Active model is not a supported rollback target')
        selected = payload['model'] if action == 'ai_model' else old_model
        if action == 'ai_model':
            # Probe the exact model before changing the local override.
            from .ai_advisor import AIAdvisor
            from .domain import Signal
            advisor = AIAdvisor(replace(config.ai, model=selected, enabled=True, fail_closed=True))
            if not advisor.api_key:
                raise ValueError('OpenAI key unavailable')
            signal = Signal('BTCUSDT', 'BUY', 80, 100., 95., 110., 2., 60., 101., 99., 1.3,
                            'synthetic model access check; no order', 'synthetic')
            review = advisor.review(signal, True, {'equity_usdt': 1000., 'cash_usdt': 1000.,
                                                   'exposure_pct': 0., 'open_positions': 0.})
            if review.reason.startswith('AI review failed safely:'):
                raise ValueError('Selected AI model probe failed')
        runtime = ProcessRuntime(source)
        token = secrets.token_hex(32)
        atomic_json(control.maintenance, {'token': token, 'phase': 'stopping'})
        child = None
        changed = False
        stopped = False
        try:
            deadline = time.monotonic() + 80
            while time.monotonic() < deadline:
                try:
                    with single_instance(data / 'engine.lock'):
                        break
                except RuntimeError:
                    time.sleep(.1)
            else:
                raise TimeoutError('PAPER motor did not stop cooperatively')
            stopped = True
            if action == 'ai_model':
                _model_file(source, selected)
                changed = True
            control.maintenance.unlink()
            os.environ['OPENAI_MODEL'] = selected
            child = runtime.start()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                state = json.loads(control.status.read_text(encoding='utf-8'))
                if state.get('pid') == child.pid and state.get('phase') == 'running' and runtime.health(child, None):
                    return {'ok': True, 'model': selected, 'pid': child.pid}
                if child.poll() is not None:
                    break
                time.sleep(.2)
            raise RuntimeError('New motor did not pass supervised health')
        except BaseException:
            runtime.stop_owned(child)
            if changed:
                _model_file(source, old_model)
            control.maintenance.unlink(missing_ok=True)
            # Restoring the original model is a safety action, not a second trading engine.
            if changed:
                os.environ['OPENAI_MODEL'] = old_model
            if stopped:
                recovered = runtime.start()
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline and not runtime.health(recovered, None):
                    if recovered.poll() is not None:
                        break
                    time.sleep(.2)
            raise
