"""Persist owner-requested trading controls before acknowledging their result."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


class RemotePaperControls:
    def __init__(self, supervisor, source):
        self.directory = Path(supervisor).resolve() / 'data/paper-controls'
        self.source = Path(source).resolve()
        self.script = self.source / 'scripts/execute_paper_control.py'
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def available(self):
        return self.script.is_file() and self.script.resolve().is_relative_to(self.source)

    def results(self):
        rows = []
        for path in sorted(self.directory.glob('*.json'), key=lambda p: int(p.stem) if p.stem.isdecimal() else -1)[-20:]:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if type(data['id']) is int and data['status'] in {'completed', 'failed'}:
                    rows.append({key: data[key] for key in ('id', 'status', 'message')})
            except (OSError, ValueError, KeyError):
                continue
        return rows

    def apply(self, item):
        now = time.time()
        identifier = item.get('id')
        action = item.get('action')
        payload = item.get('payload')
        expires = item.get('expires')
        if (not self.available or type(identifier) is not int or identifier <= 0 or
                action not in {'risk_profile', 'paper_close', 'ai_model', 'restart_engine', 'execution_mode', 'testnet_smoke', 'futures_testnet_check', 'futures_testnet_smoke', 'futures_testnet_reconcile'} or not isinstance(payload, dict) or
                type(expires) not in (int, float) or not now < expires <= now + 305):
            raise ValueError('Invalid or unavailable trading control')
        expected = {'action': action, 'payload': payload}
        encoded = json.dumps(expected, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded) > 450:
            raise ValueError('Oversized trading control')
        record = self.directory / (str(identifier) + '.json')
        if record.exists():
            prior = json.loads(record.read_text(encoding='utf-8'))
            if prior.get('request') != encoded:
                raise ValueError('Trading control identifier conflict')
            return
        # A durable receipt prevents an uncertain retry from selling a replacement position.
        with record.open('x', encoding='utf-8') as handle:
            json.dump({'id': identifier, 'request': encoded, 'status': 'failed',
                       'message': 'Resultado incierto; comprobar posición en Windows antes de repetir'}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            python = Path(sys.executable)
            if python.name.lower() == 'pythonw.exe':
                python = python.with_name('python.exe')
            result = subprocess.run([str(python), '-I', '-B', str(self.script), str(self.source)],
                input=encoded, text=True, cwd=self.source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=145, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if len(result.stdout) > 1000:
                message = 'Windows rechazó la acción; revisa el estado local'
                status = 'failed'
            else:
                response = json.loads(result.stdout)
                if result.returncode != 0:
                    code = response.get('reason') if isinstance(response, dict) else None
                    messages = {
                        'BINANCE_TESTNET_CANNOT_TRADE': 'Binance Testnet rechazó el cambio: la cuenta no tiene trading habilitado',
                        'BINANCE_TESTNET_CONNECTION_OR_AUTH_FAILED': 'No se pudieron validar las credenciales o conexión de Binance Testnet',
                        'ENGINE_NOT_HEALTHY': 'El motor instalado no estaba saludable para cambiar de entorno',
                        'MAINTENANCE_BUSY': 'El motor estaba ocupado con mantenimiento o actualización',
                        'ENGINE_STOP_TIMEOUT': 'El motor no se detuvo a tiempo para cambiar de entorno',
                        'ENGINE_START_HEALTH_FAILED': 'El nuevo entorno no superó la comprobación de arranque',
                        'LOCAL_ENV_UNAVAILABLE': 'Windows no pudo actualizar la configuración local privada',
                        'TESTNET_SMOKE_REQUIRES_TESTNET': 'Activa Binance Spot Testnet antes de ejecutar la prueba',
                        'TESTNET_SMOKE_NO_ISOLATED_SYMBOL': 'No hay un símbolo Testnet libre y válido para ejecutar la prueba aislada',
                        'TESTNET_SMOKE_PENDING_ORDER': 'Hay una orden Testnet pendiente de conciliación',
                        'TESTNET_SMOKE_ALLOCATION_TOO_SMALL': 'El ledger Testnet no tiene asignación suficiente para la prueba',
                        'TESTNET_SMOKE_RECONCILIATION_INCOMPLETE': 'La prueba terminó con una conciliación pendiente; revisa el ledger antes de repetir',
                        'BINANCE_TESTNET_EXECUTION_FAILED': 'Binance Testnet no completó la prueba; revisa órdenes y conciliación antes de repetir',
                        'FUTURES_TESTNET_REQUIRES_TESTNET': 'Mantén el motor principal en Spot TESTNET para usar el laboratorio de Futures',
                        'FUTURES_TESTNET_RECOVERY_REQUIRED': 'Futures Demo tiene una prueba previa que debe reconciliarse antes de continuar',
                        'FUTURES_TESTNET_CREDENTIALS_UNAVAILABLE': 'Faltan las credenciales separadas de Binance Futures Demo en Windows',
                        'FUTURES_TESTNET_CANNOT_TRADE': 'La cuenta de Binance Futures Demo no tiene trading habilitado',
                        'FUTURES_TESTNET_MARGIN_LOW': 'El saldo ficticio disponible en Futures Demo es insuficiente para la prueba',
                        'FUTURES_TESTNET_EXECUTION_FAILED': 'Futures Demo no completó la operación; usa Reconciliar Futures antes de repetir',
                    }
                    message = messages.get(code, 'Windows rechazó la acción; revisa el estado local')
                    detail = response.get('detail') if isinstance(response, dict) else None
                    if isinstance(detail, str) and detail:
                        message = (message + ' · ' + detail)[:290]
                    status = 'failed'
                else:
                    if response.get('ok') is not True:
                        raise ValueError('Unconfirmed trading response')
                    futures = response.get('futures_testnet') if isinstance(response.get('futures_testnet'), dict) else {}
                    liquidation = futures.get('liquidation_price')
                    messages = {
                        'risk_profile': 'Perfil de riesgo aplicado: ' + response.get('profile',''),
                        'paper_close': 'Posición cerrada en ' + response.get('mode','').upper() + ': ' + response.get('symbol',''),
                        'ai_model': 'Modelo activo: ' + response.get('model',''),
                        'restart_engine': 'Motor reiniciado y verificado',
                        'execution_mode': 'Entorno activo: ' + response.get('mode','').upper(),
                        'testnet_smoke': 'Prueba Spot Testnet completada · BUY y SELL conciliados',
                        'futures_testnet_check': 'Futures Demo verificado · disponible '
                            + str(round(float(futures.get('available_balance',0)),2)) + ' USDT · '
                            + str(futures.get('open_positions',0)) + ' posiciones abiertas',
                        'futures_testnet_smoke': 'Futures ' + str(futures.get('direction','')) + ' '
                            + str(futures.get('leverage','')) + 'x · ' + str(futures.get('symbol',''))
                            + ' · apertura/cierre reduceOnly conciliados'
                            + ((' · liq ' + str(round(float(liquidation),2))) if liquidation is not None else ''),
                        'futures_testnet_reconcile': 'Futures Demo reconciliado · posición técnica cerrada',
                    }
                    message = messages[action]
                    status = 'completed'
            temp = record.with_suffix('.tmp')
            with temp.open('w', encoding='utf-8') as handle:
                json.dump({'id': identifier, 'request': encoded, 'status': status, 'message': message}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(record)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            # The initial receipt remains failed; never claim a sale was completed.
            return
