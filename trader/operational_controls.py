"""Allowlisted owner controls for the single supervised trading motor."""
from __future__ import annotations

import json
import os
import secrets
import time
import tomllib
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile

from .config import load_config
from .runtime import single_instance
from .runtime_control import RuntimeControl
from .update_manager import atomic_json
from .update_supervisor import ProcessRuntime

MODELS = frozenset({'gpt-5.6-luna', 'gpt-6-luna'})
EXECUTION_MODES = frozenset({'paper', 'testnet'})


def _override_file(source: Path, key: str, value: str) -> None:
    path = source / '.env.local'
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Local credential file unavailable')
    original = path.read_text(encoding='utf-8')
    rows = [row for row in original.splitlines() if row.partition('=')[0].strip() != key]
    rows.append(key + '=' + value)
    temporary = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=source, prefix='.env-control-', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write('\n'.join(rows) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _model_file(source: Path, model: str) -> None:
    _override_file(source, 'OPENAI_MODEL', model)


def _execution_file(source: Path, mode: str) -> None:
    if mode not in EXECUTION_MODES:
        raise ValueError('Unsupported execution mode')
    _override_file(source, 'EXECUTION_MODE', mode)


def execute(source: Path, action: str, payload: dict) -> dict:
    source = source.resolve(strict=True)
    if not isinstance(payload, dict) or action not in {'ai_model', 'restart_engine', 'execution_mode', 'testnet_smoke'}:
        raise ValueError('Unknown operational control')
    if action == 'ai_model':
        if set(payload) != {'model'} or payload['model'] not in MODELS:
            raise ValueError('Unknown model')
    elif action == 'execution_mode':
        if set(payload) != {'mode'} or payload['mode'] not in EXECUTION_MODES:
            raise ValueError('Unknown execution mode')
    elif action in {'restart_engine', 'testnet_smoke'} and payload:
        raise ValueError('Operational action does not accept parameters')

    config = load_config(source / 'config.toml')
    if config.bot.mode not in EXECUTION_MODES:
        raise ValueError('Supported trading motor required')
    data = config.bot.database_path.parent
    control = RuntimeControl(data)
    with (source / 'pyproject.toml').open('rb') as stream:
        version = tomllib.load(stream)['project']['version']

    with single_instance(source / 'data/update-supervisor.lock'):
        if control.maintenance.exists():
            raise ValueError('Maintenance already in progress')
        status = json.loads(control.status.read_text(encoding='utf-8'))
        if status.get('mode') != config.bot.mode or status.get('phase') != 'running' or status.get('version') != version:
            raise ValueError('Healthy installed trading motor required')

        old_model = config.ai.model
        old_mode = config.bot.mode
        if old_model not in MODELS:
            raise ValueError('Active model is not a supported rollback target')
        selected_model = payload['model'] if action == 'ai_model' else old_model
        selected_mode = payload['mode'] if action == 'execution_mode' else old_mode
        if action == 'testnet_smoke' and old_mode != 'testnet':
            raise ValueError('Testnet smoke test requires TESTNET mode')

        if action == 'ai_model':
            from .ai_advisor import AIAdvisor
            from .domain import Signal
            advisor = AIAdvisor(replace(config.ai, model=selected_model, enabled=True, fail_closed=True))
            if not advisor.api_key:
                raise ValueError('OpenAI key unavailable')
            signal = Signal('BTCUSDT', 'BUY', 80, 100., 95., 110., 2., 60., 101., 99., 1.3,
                            'synthetic model access check; no order', 'synthetic')
            review = advisor.review(signal, True, {'equity_usdt': 1000., 'cash_usdt': 1000.,
                                                   'exposure_pct': 0., 'open_positions': 0.})
            if review.reason.startswith('AI review failed safely:'):
                raise ValueError('Selected AI model probe failed')

        if action == 'execution_mode' and selected_mode == 'testnet' and selected_mode != old_mode:
            from .exchange import BinanceClient
            probe = BinanceClient(timeout=10).verify_testnet_credentials()
            if probe.get('can_trade') is not True:
                raise ValueError('Binance Spot Testnet credentials cannot trade')

        runtime = ProcessRuntime(source)
        token = secrets.token_hex(32)
        atomic_json(control.maintenance, {'token': token, 'phase': 'stopping'})
        child = None
        model_changed = False
        mode_changed = False
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
                raise TimeoutError('Trading motor did not stop cooperatively')
            stopped = True

            if action == 'ai_model' and selected_model != old_model:
                _model_file(source, selected_model)
                model_changed = True
            if action == 'execution_mode' and selected_mode != old_mode:
                _execution_file(source, selected_mode)
                mode_changed = True

            smoke_result = None
            if action == 'testnet_smoke':
                from datetime import UTC, datetime
                from .database import Database
                from .domain import Signal
                from .exchange import BinanceClient
                from .testnet_broker import BinanceTestnetBroker

                smoke_config = load_config(source / 'config.toml')
                if smoke_config.bot.mode != 'testnet':
                    raise ValueError('Testnet smoke test requires TESTNET mode')
                smoke_db = Database(smoke_config.bot.database_path)
                if smoke_db.positions():
                    raise ValueError('Testnet smoke test requires no open positions')
                broker = BinanceTestnetBroker(smoke_db, smoke_config.paper, smoke_config.risk)
                if not broker.reconcile_pending():
                    raise ValueError('Testnet smoke test requires no pending order')
                client = BinanceClient(timeout=10)
                symbol = 'BTCUSDT'
                price = float(client.testnet_reference_price(symbol))
                if not price > 0:
                    raise ValueError('Testnet smoke reference price unavailable')
                quote_target = min(10.0, smoke_db.cash() * 0.05)
                if quote_target < 6.0:
                    raise ValueError('Testnet smoke allocation too small')
                quantity = quote_target / price
                signal = Signal(
                    symbol, 'BUY', 100, price, price * 0.99, price * 1.01,
                    price * 0.005, 50.0, price, price, 1.0,
                    'supervised Testnet smoke test', datetime.now(UTC).isoformat(),
                )
                position = broker.buy(signal, quantity, 'supervised TESTNET smoke BUY')
                close_price = float(client.testnet_reference_price(symbol))
                realized = broker.sell(position, close_price, 'supervised TESTNET smoke SELL')
                if not broker.reconcile_pending() or smoke_db.position(symbol) is not None:
                    raise RuntimeError('Testnet smoke reconciliation incomplete')
                smoke_result = {
                    'symbol': symbol,
                    'buy_quantity': position.quantity,
                    'buy_price': position.entry_price,
                    'close_reference': close_price,
                    'realized_pnl_usdt': realized,
                    'pending': False,
                }

            control.maintenance.unlink()
            os.environ['OPENAI_MODEL'] = selected_model
            os.environ['EXECUTION_MODE'] = selected_mode
            child = runtime.start()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                state = json.loads(control.status.read_text(encoding='utf-8'))
                if (state.get('pid') == child.pid and state.get('phase') == 'running'
                        and state.get('mode') == selected_mode and runtime.health(child, None)):
                    result = {'ok': True, 'model': selected_model, 'mode': selected_mode, 'pid': child.pid}
                    if smoke_result is not None:
                        result['testnet_smoke'] = smoke_result
                    return result
                if child.poll() is not None:
                    break
                time.sleep(.2)
            raise RuntimeError('New motor did not pass supervised health')
        except BaseException:
            runtime.stop_owned(child)
            if model_changed:
                _model_file(source, old_model)
            if mode_changed:
                _execution_file(source, old_mode)
            control.maintenance.unlink(missing_ok=True)
            os.environ['OPENAI_MODEL'] = old_model
            os.environ['EXECUTION_MODE'] = old_mode
            if stopped:
                recovered = runtime.start()
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline and not runtime.health(recovered, None):
                    if recovered.poll() is not None:
                        break
                    time.sleep(.2)
            raise
