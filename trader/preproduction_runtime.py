"""Owned, non-authoritative observation within the existing engine process."""
from .operational_cohort import fingerprints_for_config
from .preproduction_observer import PreproductionObserverService, SourceSpec

_SERVICE = None


def create_observer(config):
    if config.bot.mode not in {"paper", "testnet"}:
        raise ValueError("OPERATING_OBSERVATION_SCOPE_UNSUPPORTED")
    data = config.bot.database_path.parent
    specs = [SourceSpec("SPOT", "SPOT_TESTNET" if config.bot.mode == "testnet" else "PAPER", config.bot.database_path)]
    if config.bot.mode == "testnet":
        specs.append(SourceSpec("FUTURES", "FUTURES_DEMO", config.futures_testnet.database_path))
    if config.market_pulse.enabled:
        specs.append(SourceSpec("AI_MARKET_PULSE", "SHADOW", data / "market-pulse.db"))
    if config.quant_arbitrage.enabled:
        specs.append(SourceSpec("QUANT_ARBITRAGE", "SHADOW", data / "quant-shadow.db"))
    return PreproductionObserverService(data, sources=tuple(specs),
        semantic_config={item.engine: fingerprints_for_config(config, item.engine) for item in specs})


def register_observer(service):
    global _SERVICE
    if type(service) is not PreproductionObserverService or (_SERVICE is not None and _SERVICE is not service):
        return False
    _SERVICE = service
    return True


def unregister_observer(service):
    global _SERVICE
    if _SERVICE is service:
        _SERVICE = None


def enqueue_proposal(payload):
    """Fixed bounded queue route only. No source reads or arbitrary callbacks."""
    service = _SERVICE
    if type(service) is not PreproductionObserverService:
        return False
    try:
        return service.record_proposal(payload)
    except Exception:
        return False
