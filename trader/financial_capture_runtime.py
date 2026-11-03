"""GET-only financial capture owned by the existing supervised process."""
from pathlib import Path
import threading

from .financial_capture import FinancialCaptureService
from .financial_evidence_io import _atomic_anchor
from .live_credentials import LiveCredentialVault


class CombinedFinancialCaptureService:
    """Share one observation thread and a fixed logical GET budget."""
    def __init__(self, services):
        self.services = tuple(services)
        if not 1 <= len(self.services) <= 2 or any(not callable(getattr(service,'tick',None)) for service in self.services):
            raise ValueError('EXPLICIT_BOUNDED_CAPTURE_SERVICES_REQUIRED')

    def tick(self, *, max_calls=16, should_stop=None):
        if type(max_calls) is not int or not len(self.services) <= max_calls <= 192:
            raise ValueError('BOUNDED_COMBINED_CAPTURE_BUDGET_REQUIRED')
        if should_stop is not None and not callable(should_stop):
            raise ValueError('CAPTURE_STOP_CALLBACK_REQUIRED')
        results = []
        share, extra = divmod(max_calls,len(self.services))
        for index,service in enumerate(self.services):
            if should_stop is not None and should_stop():
                break
            try:
                results.append(service.tick(max_calls=share+(index < extra),should_stop=should_stop))
            except Exception:
                # One optional account observer cannot suppress the other or
                # escape into the engine's protection/decision threads.
                results.append({'state':'CAPTURE_SERVICE_UNAVAILABLE','execution_enabled':False})
        return {'schema':1,'mode':'SEGREGATED_GET_CAPTURE','state':'CAPTURE_STOP_REQUESTED' if len(results)<len(self.services) else 'CAPTURE_TICK_RECORDED',
            'services':results,'execution_enabled':False,'financial_authorization':False,
            'ready_for_live':False,'automatic_activation':False}


class FinancialCaptureWorker:
    def __init__(self, service, status_path, *, interval_seconds=300):
        if type(interval_seconds) is not int or not 60 <= interval_seconds <= 3600:
            raise ValueError('BOUNDED_CAPTURE_WORKER_INTERVAL_REQUIRED')
        self.service, self.status_path = service, Path(status_path)
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='financial-capture-readonly', daemon=True)
            self._thread.start()
            return True

    def _run(self):
        while not self._stop.is_set():
            try:
                # All HTTP and decryption stay on this worker, never a
                # protection thread or the prospective cohort recorder.
                value = self.service.tick(max_calls=16, should_stop=self._stop.is_set)
                if not self._stop.is_set():
                    self.status_path.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_anchor(self.status_path, value)
            except Exception:
                pass  # Optional observation cannot control existing trading.
            self._stop.wait(self.interval)

    def stop(self):
        # Serialize the stop signal/thread snapshot with start's clear/start.
        # Otherwise stop could report success before a racing start clears it.
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            # One signed request can include a <=2s validated clock sample and
            # the bounded 8s HTTP request. No next capture operation starts
            # after stop; an already-started signed request may finish.
            thread.join(timeout=12)
        return thread is None or not thread.is_alive()


def create_capture_worker(config):
    """Called only after the candidate activation barrier; no keys read here."""
    data = config.bot.database_path.parent
    vault_path = data/'live-preproduction/credentials.dpapi'
    if config.bot.mode not in {'paper', 'testnet'}:
        return None
    services = []
    if vault_path.is_file():
        symbols = tuple(sorted(set(config.futures_testnet.forward_symbols) | {'BTCUSDT', 'ETHUSDT'}))
        vault = LiveCredentialVault(vault_path)
        services.append(FinancialCaptureService(vault.read, data/'live-preproduction/financial-capture', symbols=symbols))
    if config.bot.mode == 'testnet':
        from .testnet_financial_capture import create_testnet_capture_service
        service = create_testnet_capture_service(config)
        if service is not None:
            services.append(service)
    if not services:
        return None
    service = services[0] if len(services)==1 else CombinedFinancialCaptureService(services)
    return FinancialCaptureWorker(service, data/'live-preproduction/financial-capture-status.json')
