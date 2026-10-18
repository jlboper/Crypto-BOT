"""Bounded, credential-free dashboard projection from the existing database."""
import json
import re
import sqlite3
import math
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .research_runtime import studied_symbols
from .domain import Position
from .monitoring import activity_status, position_metrics, usable_price, spot_cycle_status
from .paper_scorecard import paper_scorecard
from .risk_control import PROFILES
from .futures_testnet_ledger import FuturesTestnetLedger
from .native_protection import SPOT_KEY, projection


def public_text(value):
    value = str(value)
    value = re.sub(r'https?://\S+', '[URL omitida]', value)
    value = re.sub(r'(?i)(?:sk-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]+', '[credencial omitida]', value)
    value = re.sub(r'(?i)(?:bearer|api[_ -]?key|token|secret|password)\s*[:= ]\s*\S+', '[credencial omitida]', value)
    return value[:1000]


PULSE_MARKET_FIELDS = frozenset(('symbol', 'price', 'change_1m_pct', 'change_5m_pct',
    'relative_volume', 'anomaly_z', 'momentum', 'acceleration', 'volatility_pct',
    'spread_bps', 'depth_quote', 'imbalance', 'liquidity_change_pct', 'fresh', 'complete', 'at'))
PULSE_EVENT_FIELDS = frozenset(('id', 'published_at', 'received_at', 'symbol', 'source', 'url',
    'title', 'impact', 'credibility', 'kind', 'decision', 'reason', 'market_reaction_pct'))
PULSE_DECISION_FIELDS = frozenset(('id', 'at', 'symbol', 'score', 'confidence', 'action',
    'favorable', 'risks', 'reason', 'evidence'))
PULSE_POSITION_FIELDS = frozenset(('symbol', 'quantity', 'entry_price', 'mark_price',
    'stop', 'target', 'opened_at', 'unrealized_pnl', 'environment'))
PULSE_PERFORMANCE_FIELDS = frozenset(('initial_capital', 'cash', 'equity', 'net_pnl', 'return_pct',
    'drawdown_pct', 'closed_trades', 'win_rate_pct', 'profit_factor', 'exposure', 'observation_days',
    'costs', 'environment', 'data_quality', 'benchmark_cash_return_pct', 'benchmark_buy_hold'))
PULSE_HEALTH_FIELDS = frozenset(('latency_ms', 'reconnects', 'errors', 'last_error', 'ws_messages',
    'rest_calls', 'news_calls', 'ai_reviews', 'ai_errors', 'buffer_seconds', 'uptime_seconds',
    'ai_daily_cap', 'ai_used_today', 'ai_min_interval_seconds', 'ai_max_output_tokens', 'ai_max_input_bytes'))
PULSE_EVIDENCE_FIELDS = frozenset(('market', 'event_id', 'rule_version', 'published_at', 'received_at',
    'decision_at', 'btc_change_1m_pct', 'btc_change_5m_pct', 'estimated_cost_bps', 'confirmations',
    'selection_rank', 'selection_pool', 'selection_rule'))
PULSE_NEWS_PROVIDER_FIELDS = frozenset(('id', 'name', 'url', 'kind', 'state', 'last_update', 'last_error'))


def _pulse_public_value(value, depth=0):
    """Sanitize selected structured data; provider strings never become instructions."""
    if depth > 5:
        raise ValueError('Market Pulse projection depth exceeded')
    if value is None or isinstance(value, bool):
        return value
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite Market Pulse value')
        return value
    if isinstance(value, str):
        return public_text(value)[:280]
    if isinstance(value, list):
        return [_pulse_public_value(item, depth + 1) for item in value[:16]]
    if isinstance(value, dict):
        return {str(key): _pulse_public_value(item, depth + 1) for key, item in value.items()}
    raise ValueError('Invalid Market Pulse value')


def _pulse_source_url(value):
    """Keep an attributable HTTPS link, dropping query/fragment/userinfo entirely."""
    try:
        url = urlsplit(value if isinstance(value, str) else '')
        if (url.scheme != 'https' or not url.hostname or url.username or url.password or
                url.port not in (None, 443) or len(url.hostname) > 160):
            return None
        host = url.hostname.encode('idna').decode('ascii')
        if (not re.fullmatch(r'[a-z0-9.-]+', host) or '.' not in host or host.endswith(('.local', '.localhost'))
                or re.search(r'(?i)(?:sk-|gh[pousr]_|github_pat_|api[_-]?key|token|secret|password)', url.path)):
            return None
        return urlunsplit(('https', host, url.path[:300], '', ''))
    except (ValueError, UnicodeError):
        return None


def bounded_market_pulse_projection(pulse, maximum=20000):
    """Thin optional remote history only; preserve positions and aggregate totals."""
    def size():
        return len(json.dumps(pulse, ensure_ascii=True, allow_nan=False, separators=(',', ':')))
    while size() >= maximum:
        candidates = [key for key in ('events', 'opportunities', 'decisions')
                      if isinstance(pulse.get(key), list) and pulse[key]]
        if not candidates:
            raise ValueError('Market Pulse safety evidence exceeds remote budget')
        key = max(candidates, key=lambda name: len(json.dumps(pulse[name], ensure_ascii=True)))
        pulse[key] = pulse[key][:len(pulse[key]) // 2]
    return pulse


def market_pulse_projection(config):
    """Read only the observer ledger. Pulse faults cannot invalidate other engines."""
    settings = getattr(config, 'market_pulse', None)
    enabled = bool(settings and settings.enabled and settings.mode == 'SHADOW')
    unavailable = {'schema': 1, 'engine': 'AI_MARKET_PULSE', 'mode': 'SHADOW',
        'state': 'NOT_STARTED', 'at': datetime.now(UTC).isoformat(), 'updated_at': None,
        'freshness': {'state': 'UNAVAILABLE', 'age_seconds': None}, 'enabled': enabled,
        'controls_available': False, 'execution_enabled': False, 'sources': {}, 'stats': {},
        'market': [], 'events': [], 'opportunities': [], 'decisions': [], 'positions': [],
        'performance': {}, 'health': {}, 'research': {'state': 'FORWARD_ONLY',
        'hypothesis_version': 'pulse-v1', 'promotion_allowed': False,
        'limitations': ['No historical event replay with complete evidence is available yet.']}}
    if not settings:
        return unavailable
    try:
        from .market_pulse import market_pulse_snapshot
        raw = market_pulse_snapshot(config.bot.database_path.parent,
            kill_switch_path=settings.kill_switch_path)
        if not isinstance(raw, dict) or raw.get('mode') != 'SHADOW' or raw.get('execution_enabled') is not False:
            raise ValueError('Unsafe Market Pulse projection')
        result = {key: _pulse_public_value(raw[key]) for key in
            ('schema', 'engine', 'mode', 'state', 'at', 'updated_at') if key in raw}
        def pick(value, fields):
            if not isinstance(value, dict):
                raise ValueError('Invalid Market Pulse object')
            return {key: _pulse_public_value(value[key]) for key in fields if key in value}
        result['freshness'] = pick(raw.get('freshness', {}), ('state', 'age_seconds'))
        result['sources'] = {key: pick(raw['sources'][key], ('state', 'last_update')) for key in
            ('binance_ws', 'binance_rest', 'news') if key in raw.get('sources', {})}
        result['stats'] = pick(raw.get('stats', {}), ('events_analyzed', 'relevant_news',
            'opportunities', 'accepted', 'rejected', 'decisions'))
        result['research'] = pick(raw.get('research', {}), ('state', 'hypothesis_version',
            'promotion_allowed', 'limitations'))
        initialized = (raw.get('updated_at') is not None and raw.get('state') != 'NOT_STARTED'
            and type(raw.get('performance', {}).get('initial_capital')) in (int, float)
            and raw['performance']['initial_capital'] > 0
            and raw.get('health', {}).get('last_error') != 'SHADOW_LEDGER_UNAVAILABLE')
        result.update(enabled=enabled, controls_available=bool(enabled and initialized), execution_enabled=False)
        for key, fields, count in (('market', PULSE_MARKET_FIELDS, 10),
                ('events', PULSE_EVENT_FIELDS, 12), ('opportunities', PULSE_DECISION_FIELDS - {'evidence'}, 12),
                ('decisions', PULSE_DECISION_FIELDS, 16), ('positions', PULSE_POSITION_FIELDS, 3)):
            rows = raw.get(key, [])
            if not isinstance(rows, list) or (key in {'market', 'positions'} and len(rows) > count):
                raise ValueError('Invalid Market Pulse rows')
            result[key] = []
            for row in rows[:count]:
                if not isinstance(row, dict):
                    raise ValueError('Invalid Market Pulse row')
                projected = {field: _pulse_public_value(row[field]) for field in fields
                             if field in row and field not in {'url', 'evidence'}}
                if key == 'events':
                    projected['url'] = _pulse_source_url(row.get('url'))
                if key == 'decisions' and isinstance(row.get('evidence'), dict):
                    evidence = pick(row['evidence'], PULSE_EVIDENCE_FIELDS - {'market'})
                    if isinstance(row['evidence'].get('market'), dict):
                        evidence['market'] = pick(row['evidence']['market'], PULSE_MARKET_FIELDS)
                    projected['evidence'] = evidence
                result[key].append(projected)
        for key, fields in (('performance', PULSE_PERFORMANCE_FIELDS), ('health', PULSE_HEALTH_FIELDS)):
            value = raw.get(key, {})
            if not isinstance(value, dict):
                raise ValueError('Invalid Market Pulse section')
            result[key] = {field: _pulse_public_value(value[field]) for field in fields if field in value}
            if key == 'performance' and isinstance(value.get('benchmark_buy_hold'), dict):
                if len(value['benchmark_buy_hold']) > 10:
                    raise ValueError('Market Pulse benchmark universe exceeds budget')
                result[key]['benchmark_buy_hold'] = {symbol: _pulse_public_value(item) for symbol, item in
                    value['benchmark_buy_hold'].items() if re.fullmatch(r'[A-Z0-9]{2,24}USDT', symbol)
                    and type(item) in (int, float)}
        if 'news_providers' in raw:
            providers = raw['news_providers']
            if not isinstance(providers, list) or len(providers) > 5:
                raise ValueError('Invalid Market Pulse providers')
            result['news_providers'] = []
            for provider in providers:
                projected = pick(provider, PULSE_NEWS_PROVIDER_FIELDS - {'url'})
                if (set(projected) != PULSE_NEWS_PROVIDER_FIELDS - {'url'}
                        or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', str(projected.get('id', '')))
                        or not isinstance(projected.get('name'), str)
                        or projected.get('kind') not in {'official', 'editorial', 'regulatory'}
                        or projected.get('state') not in {'READY', 'ERROR', 'STANDBY', 'DISABLED'}):
                    raise ValueError('Invalid Market Pulse provider metadata')
                updated = projected.get('last_update')
                error = projected.get('last_error')
                if (updated is not None and (not isinstance(updated, str) or _timestamp(updated) is None)
                        or error is not None and (not isinstance(error, str)
                            or not re.fullmatch(r'[A-Z0-9_:.-]{1,100}', error))):
                    raise ValueError('Invalid Market Pulse provider health')
                projected['url'] = _pulse_source_url(provider.get('url'))
                result['news_providers'].append(projected)
            if len({provider['id'] for provider in result['news_providers']}) != len(result['news_providers']):
                raise ValueError('Duplicate Market Pulse provider identity')
        if 'universe' in raw:
            result['universe'] = pick(raw['universe'], ('selection', 'selected_at', 'source'))
            if not all(isinstance(value, str) for value in result['universe'].values()):
                raise ValueError('Invalid Market Pulse universe metadata')
            source = raw['universe'].get('source')
            if isinstance(source, str) and source.startswith('https://'):
                result['universe']['source'] = _pulse_source_url(source) or '[URL omitida]'
        return bounded_market_pulse_projection(result)
    except Exception:
        unavailable['state'] = 'DEGRADED'
        unavailable['controls_available'] = False
        unavailable['health'] = {'last_error': 'PULSE_PROJECTION_UNAVAILABLE'}
        return unavailable


def bounded_futures_projection(futures, maximum=72000):
    """Bound the remote view, preserving all live safety evidence and totals.

    Financial ledgers are untouched. Only optional historical rows are thinned;
    chronological equity keeps its newest point, newest-first tables keep theirs.
    The deployed validator also accepts older exporters up to 120,000 characters.
    """
    histories = ("signals", "equity", "trades", "shadow_scorecard")
    # Match the exporter's ASCII-safe wire encoding (including escaped Unicode).
    def size(): return len(json.dumps(futures, ensure_ascii=True, separators=(",", ":")))
    while size() >= maximum:
        candidates = [key for key in histories if isinstance(futures.get(key), list) and len(futures[key]) > 1]
        if not candidates: raise ValueError("Futures safety evidence exceeds remote budget")
        key = max(candidates, key=lambda key: len(json.dumps(futures[key], ensure_ascii=True)))
        rows = futures[key]
        # Equity is oldest first; retain both endpoints and reduce interior rows.
        if key == "equity" and len(rows) > 2:
            futures[key] = [rows[0], *rows[1:-1:2], rows[-1]]
        elif key == "equity": futures[key] = rows[-1:]
        else: futures[key] = rows[:max(1, len(rows) // 2)]
    return futures



def _timestamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _futures_pause_diagnostics(config, ledger):
    path = config.futures_testnet.kill_switch_path
    killed = path.exists()
    raw_reason = None
    paused_at = None
    if killed:
        try:
            if path.stat().st_size <= 4096:
                raw_reason = path.read_text(encoding='utf-8', errors='replace').strip()
            paused_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        except OSError:
            raw_reason = 'Futures pause state unavailable'
    detail = public_text(raw_reason) if raw_reason else None
    normalized = (detail or '').lower()
    if not killed:
        label = None
        source = None
        error_key = 'forward_last_error'
        counter_key = 'forward_consecutive_errors'
    elif normalized == 'owner pause':
        label = 'Pausa manual del propietario'
        source = 'manual'
        error_key = 'forward_last_error'
        counter_key = 'forward_consecutive_errors'
    elif 'three consecutive futures protection errors' in normalized:
        label = '3 errores consecutivos de protección Futures'
        source = 'automatic_safety'
        error_key = 'forward_last_protection_error'
        counter_key = 'forward_protection_consecutive_errors'
    elif 'three consecutive futures forward errors' in normalized:
        label = '3 errores consecutivos del ciclo Futures'
        source = 'automatic_safety'
        error_key = 'forward_last_cycle_error'
        counter_key = 'forward_cycle_consecutive_errors'
    elif any(term in normalized for term in ('untracked futures', 'position identity mismatch', 'missing or ambiguous', 'recovery requires owner review', 'could not be reconstructed')):
        label = 'Inconsistencia o reconciliación de posición Futures'
        source = 'automatic_safety'
        error_key = 'forward_last_error'
        counter_key = 'forward_consecutive_errors'
    else:
        label = detail or 'Pausa de seguridad Futures'
        source = 'automatic_safety'
        error_key = 'forward_last_error'
        counter_key = 'forward_consecutive_errors'
    last_error = ledger.setting(error_key) or ledger.setting('forward_last_error')
    if isinstance(last_error, dict):
        last_error = {
            'message': public_text(last_error.get('message', '')),
            'at': str(last_error.get('at', ''))[:40] or None,
        }
    else:
        last_error = None
    consecutive = ledger.setting(counter_key)
    if consecutive is None:
        consecutive = ledger.setting('forward_consecutive_errors')
    incident = ledger.setting('forward_active_incident') or ledger.setting('forward_last_incident')
    if isinstance(incident, dict):
        incident = {
            'id': public_text(incident.get('id', ''))[:32] or None,
            'source': public_text(incident.get('source', ''))[:32] or None,
            'message': public_text(incident.get('message', '')),
            'repetitions': int(incident.get('repetitions', 1) or 1),
            'first_at': str(incident.get('first_at', ''))[:40] or None,
            'last_at': str(incident.get('last_at', ''))[:40] or None,
            'resolved_at': str(incident.get('resolved_at', ''))[:40] or None,
        }
    else:
        incident = None
    return {
        'active': killed,
        'label': label,
        'detail': detail,
        'source': source,
        'paused_at': paused_at,
        'last_error': last_error,
        'consecutive_errors': int(consecutive or 0),
        'incident': incident,
        'pending_reconciliation': bool(ledger.setting('forward_pending_order')),
    }


def _spot_observation_health(connection, config, latest, positions, settings):
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    since_iso = since.isoformat()
    first_row = connection.execute("SELECT created_at FROM equity ORDER BY id LIMIT 1").fetchone()
    first_at = _timestamp(first_row["created_at"]) if first_row else None
    period_start = max(since, first_at) if first_at else now
    elapsed = max(0.0, (now - period_start).total_seconds())
    expected = max(1, int(elapsed / config.bot.cycle_seconds) + 1) if first_at else 0
    samples = int(connection.execute(
        "SELECT COUNT(*) AS n FROM equity WHERE created_at>=?", (since_iso,)
    ).fetchone()["n"])
    times = [_timestamp(row["created_at"]) for row in connection.execute(
        "SELECT created_at FROM equity WHERE created_at>=? ORDER BY id DESC LIMIT 200", (since_iso,)
    )]
    times = sorted(value for value in times if value is not None)
    gaps = [(b-a).total_seconds() for a,b in zip(times,times[1:])]
    errors = int(connection.execute(
        "SELECT COUNT(*) AS n FROM events WHERE created_at>=? AND level IN ('ERROR','CRITICAL') AND message NOT GLOB 'Futures Demo *'", (since_iso,)
    ).fetchone()["n"])
    warnings = int(connection.execute(
        "SELECT COUNT(*) AS n FROM events WHERE created_at>=? AND level='WARN' AND message NOT GLOB 'Futures Demo *'", (since_iso,)
    ).fetchone()["n"])
    ai = connection.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN verdict='REJECT' THEN 1 ELSE 0 END) AS rejected
           FROM ai_reviews WHERE created_at>=?""", (since_iso,)
    ).fetchone()
    closed = connection.execute(
        """SELECT COUNT(*) AS total, COALESCE(SUM(realized_pnl),0) AS pnl
           FROM trades WHERE created_at>=? AND side='SELL'""", (since_iso,)
    ).fetchone()
    pending = connection.execute(
        "SELECT value FROM settings WHERE key='unified_testnet_pending_order'"
    ).fetchone()
    pending_order = bool(pending and str(pending["value"]).strip())
    last_at = _timestamp(latest.get("created_at"))
    last_age = max(0.0, (now-last_at).total_seconds()) if last_at else None
    market_at = _timestamp(settings.get("market_prices_at"))
    market_age = max(0.0, (now-market_at).total_seconds()) if market_at else None
    coverage = min(100.0, 100.0*samples/expected) if expected else 0.0
    starting = first_at is None or elapsed < config.bot.cycle_seconds * 2
    integrity = {
        "positions_within_limit": len(positions) <= config.risk.max_positions,
        "order_journal_clear": not pending_order,
        "market_prices_fresh": market_age is not None and market_age <= config.bot.cycle_seconds * 2,
    }
    healthy_integrity = all(integrity.values())
    consecutive_errors = int(settings.get("consecutive_errors", "0") or 0)
    try:
        last_error = json.loads(settings.get("spot_last_error", "null") or "null")
    except (TypeError, ValueError, json.JSONDecodeError):
        last_error = None
    try:
        last_recovery = json.loads(settings.get("spot_last_recovery", "null") or "null")
    except (TypeError, ValueError, json.JSONDecodeError):
        last_recovery = None
    # Older restarts reset the in-memory counter without writing a recovery.
    # Use a recorded successful cycle as evidence; keep the original error.
    error_at = _timestamp(last_error.get("at")) if isinstance(last_error, dict) else None
    recovered_at = _timestamp(last_recovery.get("at")) if isinstance(last_recovery, dict) else None
    if (consecutive_errors == 0 and error_at and last_at and last_at > error_at
            and (recovered_at is None or recovered_at <= error_at)):
        recovery_row = connection.execute(
            """SELECT created_at FROM events WHERE level='INFO'
               AND message GLOB 'Cycle complete: *'
               AND julianday(created_at)>julianday(?)
               AND julianday(created_at)<=julianday(?)
               ORDER BY julianday(created_at) LIMIT 1""",
            (error_at.isoformat(), last_at.isoformat()),
        ).fetchone()
        if recovery_row:
            last_recovery = {"recovered_errors": int(last_error.get("consecutive_errors", 0) or 0),
                             "at": recovery_row["created_at"]}
    recovered_at = _timestamp(last_recovery.get("at")) if isinstance(last_recovery, dict) else None
    error_resolved = (consecutive_errors == 0 and error_at is not None
                      and recovered_at is not None and recovered_at > error_at
                      and last_at is not None and last_at > error_at)
    stale_cycle = last_age is None or last_age > config.bot.cycle_seconds * 2
    reasons = []
    if coverage < 90:
        reasons.append("cycle_coverage_below_90")
    if stale_cycle:
        reasons.append("cycle_stale")
    if errors:
        reasons.append("errors_observed")
    if warnings:
        reasons.append("warnings_observed")
    if consecutive_errors:
        reasons.append("consecutive_errors_active")
    if not integrity["positions_within_limit"]:
        reasons.append("position_count_exceeded")
    if not integrity["order_journal_clear"]:
        reasons.append("order_journal_pending")
    if not integrity["market_prices_fresh"]:
        reasons.append("market_prices_stale")
    active_attention = consecutive_errors >= max(2, int(config.risk.max_consecutive_errors) - 1)
    state = ("STARTING" if starting else
             "ATTENTION" if stale_cycle or active_attention or not healthy_integrity else
             "WATCH" if coverage < 90 or errors > 0 or warnings > 0 or consecutive_errors > 0 else
             "OK")
    return {
        "window_hours": 24,
        "state": state,
        "samples": samples,
        "expected_samples": expected,
        "cycle_coverage_pct": round(coverage, 1),
        "average_cycle_gap_seconds": round(sum(gaps)/len(gaps), 1) if gaps else None,
        "last_cycle_age_seconds": round(last_age, 1) if last_age is not None else None,
        "errors": errors,
        "warnings": warnings,
        "consecutive_errors": consecutive_errors,
        # Keep the stored error and events, but don't export a confirmed
        # recovery as an outstanding failure, including to older clients.
        "last_error": last_error if isinstance(last_error, dict) and not error_resolved else None,
        "last_recovery": last_recovery if isinstance(last_recovery, dict) else None,
        "ai_reviews": int(ai["total"] or 0),
        "ai_rejects": int(ai["rejected"] or 0),
        "closed_trades": int(closed["total"] or 0),
        "realized_pnl_usdt": round(float(closed["pnl"] or 0.0), 8),
        "reason_codes": reasons,
        "integrity": integrity,
    }


def spot_observation_health(config):
    """Read the same observation projection for the local status endpoint."""
    connection = sqlite3.connect(config.bot.database_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')
        row = connection.execute('SELECT * FROM equity ORDER BY id DESC LIMIT 1').fetchone()
        latest = dict(row) if row else {}
        positions = list(connection.execute('SELECT symbol FROM positions'))
        settings = dict(connection.execute("SELECT key,value FROM settings WHERE key IN ('market_prices_at','consecutive_errors','spot_last_error','spot_last_recovery')"))
        return _spot_observation_health(connection, config, latest, positions, settings)
    finally:
        connection.close()


QUANT_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
QUANT_STRATEGIES = ('FUNDING_CARRY', 'STATISTICAL_ARBITRAGE')
QUANT_METRIC_FIELDS = frozenset(('observed_funding_rate', 'funding_interval_seconds',
    'next_funding_at', 'spot_mid', 'futures_mid', 'mark_price', 'basis_rate',
    'spot_spread_bps', 'futures_spread_bps', 'projected_funding_usdt',
    'conditional_net_estimate_usdt', 'settled_funding_usdt', 'history_mean_funding_rate',
    'history_min_funding_rate', 'history_funding_std', 'quantity_per_leg',
    'spot_notional_usdt', 'futures_notional_usdt', 'gross_notional_usdt',
    'conditional_funding_rate', 'projected_event_count', 'roundtrip_cost_usdt',
    'basis_cost_reserve_usdt', 'adverse_one_event_funding_usdt', 'estimated_stress_loss_usdt',
    'required_virtual_cash_usdt', 'virtual_collateral_usdt', 'leverage', 'hedge_ratio',
    'hedge_drift_fraction', 'spread', 'train_spread_mean', 'train_spread_sigma', 'z_score',
    'residual_adf_lag1_t', 'residual_adf_heuristic_threshold', 'ar1_phi',
    'approximate_half_life_observations', 'holdout_mean_shift_sigma', 'holdout_sigma_ratio',
    'train_return_correlation', 'holdout_return_correlation', 'recent_return_correlation',
    'return_volatility_a', 'return_volatility_b', 'roundtrip_fee_slippage_rate',
    'convergence_scenario_rate', 'net_convergence_scenario_rate'))
QUANT_PERFORMANCE_FIELDS = ('initial_capital', 'equity', 'cash', 'collateral_usdt',
    'gross_exposure_usdt', 'net_pnl', 'return_pct', 'drawdown_pct', 'closed_trades',
    'wins', 'win_rate', 'profit_factor', 'costs_usdt', 'stress_costs_usdt',
    'simulated_funding_usdt', 'observation_days')
QUANT_LEG_FIELDS = ('symbol', 'venue', 'direction', 'quantity', 'entry_price',
    'entry_reference', 'entry_fee_usdt', 'entry_priced_at', 'entry_received_at',
    'leverage', 'margin_model', 'mark_price', 'notional_usdt', 'unrealized_pnl_usdt',
    'priced_at', 'received_at', 'state')
QUANT_POSITION_FIELDS = ('id', 'strategy', 'instrument', 'opened_at', 'collateral_usdt',
    'entry_fees_usdt', 'entry_slippage_usdt', 'funding_usdt', 'risk_budget_usdt',
    'hedge_atomic', 'environment', 'state', 'mark_complete', 'gross_exposure_usdt',
    'net_exposure_usdt', 'unrealized_pnl_usdt', 'net_pnl_usdt', 'estimated_exit_cost_usdt')
QUANT_MARKET_FIELDS = ('symbol', 'state', 'spot_price', 'futures_price', 'basis_bps',
    'observed_funding_rate', 'next_funding_at', 'funding_interval_seconds', 'at', 'received_at')
QUANT_FUNDING_FIELDS = ('id', 'position_id', 'symbol', 'funding_at', 'received_at',
    'rate', 'mark_price', 'quantity', 'simulated_cashflow_usdt', 'environment', 'state')
QUANT_DECISION_FIELDS = ('id', 'strategy', 'instrument', 'at', 'action', 'reason',
    'environment', 'rule_version', 'qualification')


def bounded_quant_projection(quant, maximum=20000):
    """Bound historical detail; every live paired position and leg is retained."""
    def size():
        return len(json.dumps(quant, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode())
    while size() >= maximum:
        candidates = [(quant, key) for key in ('decisions', 'funding', 'journal') if quant.get(key)]
        candidates.extend((strategy, 'signals') for strategy in quant.get('strategies', []) if strategy.get('signals'))
        if not candidates:
            raise ValueError('Quant safety evidence exceeds remote budget')
        parent, key = max(candidates, key=lambda pair: len(json.dumps(pair[0][pair[1]], ensure_ascii=True)))
        parent[key].pop()
    return quant


def public_quant_projection(raw):
    """Allowlist the independent SHADOW observer; external/model strings are data."""
    from .portfolio_guardian import quant_not_started
    if (not isinstance(raw, dict) or raw.get('schema') != 1
            or raw.get('engine') != 'QUANT_ARBITRAGE' or raw.get('mode') != 'SHADOW'
            or raw.get('execution_enabled') is not False or raw.get('promotion_allowed') is not False):
        raise ValueError('Unsafe Quant projection')
    def scalar(value):
        if value is None or type(value) is bool:
            return value
        if type(value) in (int, float):
            if not math.isfinite(value):
                raise ValueError('Non-finite Quant value')
            return value
        if isinstance(value, str):
            return public_text(value)[:160]
        raise ValueError('Invalid Quant scalar')
    def pick(value, fields):
        if not isinstance(value, dict):
            raise ValueError('Invalid Quant object')
        return {key: scalar(value[key]) for key in fields if key in value}
    def rows(value, count):
        if not isinstance(value, list) or len(value) > count:
            raise ValueError('Unbounded Quant rows')
        if any(not isinstance(row, dict) for row in value):
            raise ValueError('Invalid Quant rows')
        return value
    def metrics(value):
        result = pick(value, QUANT_METRIC_FIELDS)
        if any(value is not None and type(value) not in (int, float) for value in result.values()):
            raise ValueError('Invalid Quant numeric model evidence')
        return result
    if raw.get('initialized') is not True:
        if raw.get('initialized') is not False or raw.get('state') not in {'NOT_STARTED', 'DEGRADED'}:
            raise ValueError('Invalid Quant initialization')
        result = quant_not_started()
        result['at'] = scalar(raw.get('at')) or result['at']
        if raw.get('state') == 'DEGRADED':
            result['state'] = 'DEGRADED'
            result['health'] = pick(raw.get('health', {}), ('last_error', 'error_type'))
        return result
    if raw.get('state') not in {'SHADOW', 'PAUSED', 'DEGRADED'}:
        raise ValueError('Invalid Quant state')
    result = pick(raw, ('schema', 'engine', 'mode', 'state', 'initialized', 'enabled',
        'execution_enabled', 'controls_available', 'promotion_allowed', 'at', 'updated_at',
        'last_evaluation', 'paused'))
    if any(type(result.get(key)) is not bool for key in ('initialized', 'enabled', 'controls_available', 'paused')):
        raise ValueError('Invalid Quant capabilities')
    result['freshness'] = pick(raw.get('freshness'), ('state', 'age_seconds'))
    result['performance'] = pick(raw.get('performance'), QUANT_PERFORMANCE_FIELDS)
    result['limits'] = pick(raw.get('limits'), ('gross_usdt', 'risk_per_trade_fraction',
        'max_positions', 'stale_seconds', 'evaluation_interval_seconds'))
    risk_halt = raw.get('risk_halt')
    result['risk_halt'] = pick(risk_halt, ('state', 'at', 'method'))
    for period in ('daily', 'weekly'):
        result['risk_halt'][period] = pick(risk_halt.get(period), ('period_start',
            'baseline_at', 'baseline_equity', 'return_pct', 'limit_pct', 'halted', 'resets_at'))
    result['positions'] = []
    for row in rows(raw.get('positions'), 2):
        item = pick(row, QUANT_POSITION_FIELDS)
        if row.get('hedge_atomic') is not False or row.get('environment') != 'SHADOW':
            raise ValueError('Unsafe Quant position')
        item['legs'] = [pick(leg, QUANT_LEG_FIELDS) for leg in rows(row.get('legs'), 2)]
        if len(item['legs']) != 2:
            raise ValueError('Incomplete Quant pair inventory')
        result['positions'].append(item)
    result['market'] = [pick(row, QUANT_MARKET_FIELDS) for row in rows(raw.get('market'), 3)]
    result['funding'] = [pick(row, QUANT_FUNDING_FIELDS) for row in rows(raw.get('funding'), 10)]
    result['decisions'] = []
    for row in rows(raw.get('decisions'), 12):
        item = pick(row, QUANT_DECISION_FIELDS)
        item['available_at_decision'] = pick(row.get('available_at_decision'),
            ('observation_cutoff', 'aligned_observations', 'source_digest', 'hypotheses_digest'))
        if 'metrics' in row:
            item['metrics'] = metrics(row['metrics'])
        result['decisions'].append(item)
    result['journal'] = [pick(row, ('id', 'at', 'kind', 'position_id', 'decision_id',
        'reason', 'simulated_loss_usdt', 'stress_costs_usdt', 'fees_usdt', 'slippage_usdt'))
        for row in rows(raw.get('journal', []), 12)]
    result['strategies'] = []
    for row in rows(raw.get('strategies'), 2):
        item = pick(row, ('id', 'state'))
        item['performance'] = pick(row.get('performance'), ('closed_trades', 'net_pnl_usdt',
            'simulated_funding_usdt', 'costs_usdt'))
        item['signals'] = []
        for signal in rows(row.get('signals'), 6):
            projected = pick(signal, ('instrument', 'action', 'reason', 'at', 'qualification'))
            projected['metrics'] = metrics(signal.get('metrics', {}))
            item['signals'].append(projected)
        result['strategies'].append(item)
    result['sources'] = []
    for row in rows(raw.get('sources'), 12):
        item = pick(row, ('id', 'state', 'error'))
        stamp = row.get('at')
        item['at'] = datetime.fromtimestamp(stamp, UTC).isoformat() if type(stamp) in (int, float) and math.isfinite(stamp) else scalar(stamp)
        result['sources'].append(item)
    result['health'] = pick(raw.get('health'), ('errors', 'last_error', 'last_error_at',
        'last_success_at', 'calls', 'backoff_until', 'max_calls_per_minute'))
    result['data_quality'] = pick(raw.get('data_quality'), ('market', 'funding', 'execution', 'statistical_qualification'))
    result['benchmarks'] = [pick(row, ('symbol', 'started_at', 'buy_hold_return_pct',
        'cash_return_pct', 'method')) for row in rows(raw.get('benchmarks'), 3)]
    if not isinstance(raw.get('limitations'), list) or len(raw['limitations']) > 12:
        raise ValueError('Invalid Quant limitations')
    result['limitations'] = [scalar(value) for value in raw['limitations']]
    return bounded_quant_projection(result)


def quant_projection(config):
    """Installed-code read-only import; independent-agent modules do not import Quant."""
    from .portfolio_guardian import quant_not_started
    settings = getattr(config, 'quant_arbitrage', getattr(config, 'quant', None))
    if settings is None:
        return quant_not_started()
    try:
        from .quant_shadow import quant_snapshot
        raw = quant_snapshot(config.bot.database_path.parent)
        if raw.get('initialized') is True:
            raw['enabled'] = settings.enabled is True and settings.mode == 'SHADOW'
            raw['controls_available'] = raw['enabled']
            if not raw['enabled'] or settings.kill_switch_path and settings.kill_switch_path.exists():
                raw.update(state='PAUSED', paused=True)
        return public_quant_projection(raw)
    except Exception as exc:
        result = quant_not_started()
        result.update(state='DEGRADED', health={'last_error': 'SHADOW_LEDGER_UNAVAILABLE',
                                              'error_type': type(exc).__name__[:80]})
        return result


def platform_projection(payload):
    """Optional read-only identities and diagnostics, isolated from engine views.

    Use the rich local snapshot: the legacy remote exporter omits individual
    Futures marks. No engine, exchange, coordinator or reservation is constructed.
    """
    try:
        from .portfolio_guardian import (build_guardian, engine_catalog,
                                         guardian_unavailable, quant_not_started)
        now = datetime.now(UTC)
        quant = public_quant_projection(payload['quant']) if 'quant' in payload else quant_not_started(now)
        evidence = {**payload, 'quant': quant}
        catalog = engine_catalog(evidence)
        try:
            guardian = build_guardian(evidence, now=now)
            if (not isinstance(guardian, dict) or guardian.get('engine') != 'PORTFOLIO_GUARDIAN'
                    or guardian.get('mode') != 'OBSERVER'
                    or any(guardian.get(key) is not False for key in
                           ('controls_enabled', 'can_veto', 'execution_enabled'))
                    or not isinstance(guardian.get('scopes'), list) or len(guardian['scopes']) != 4):
                raise ValueError('Invalid observational Guardian result')
            if len(json.dumps(guardian, allow_nan=False, ensure_ascii=True,
                              separators=(',', ':')).encode()) >= 15_000:
                raise ValueError('Guardian exceeds observation budget')
        except Exception:
            guardian = guardian_unavailable(now)
        result = {'engine_catalog': catalog, 'portfolio_guardian': guardian, 'quant': quant}
        if len(json.dumps({**payload, **result}, allow_nan=False).encode()) > 480_000:
            # Existing financial/protection evidence has priority at the shared
            # dashboard budget; optional expansion cannot invalidate that view.
            return {}
        return result
    except Exception:
        # A broken optional module must not hide existing ledgers/protections.
        return {}


def guardian_intelligence_projection(config):
    """Read only the optional observer's own journal, never a financial ledger.

    Failed/missing modules or oversized evidence cannot remove four-engine data.
    The journal reader returns public allowlisted metadata and frozen assessments.
    """
    try:
        from .guardian_shadow import guardian_shadow_snapshot
        value = guardian_shadow_snapshot(config.bot.database_path.parent)
        if (not isinstance(value, dict) or type(value.get('schema')) is not int or value.get('schema') != 1
                or value.get('engine') != 'GUARDIAN_INTELLIGENCE' or value.get('mode') != 'SHADOW'
                or type(value.get('autonomy_level')) is not int or value.get('autonomy_level') != 0
                or any(value.get(k) is not False for k in ('controls_enabled', 'can_veto',
                    'execution_enabled', 'reservations_enabled', 'promotion_allowed'))
                or len(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()) > 12000):
            return None
        return value
    except Exception:
        return None


def dashboard_snapshot(config, report_path=None):
    connection = sqlite3.connect(config.bot.database_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')
        def rows(table, columns, limit):
            return [dict(row) for row in connection.execute(f'SELECT {columns} FROM {table} ORDER BY id DESC LIMIT ?', (limit,))]
        equity = rows('equity','equity,cash,exposure,created_at',300)
        latest = equity[0] if equity else {}
        settings = dict(connection.execute("SELECT key,value FROM settings WHERE key IN ('market_prices','market_prices_at','paper_cash','paper_risk_profile','unified_testnet_pending_order','consecutive_errors','spot_last_error','spot_last_recovery','spot_last_cycle','spot_native_protection','native_protection_started_at')"))
        prices = json.loads(settings.get('market_prices','{}'))
        positions = [position_metrics(Position(**dict(p)),
                     usable_price(prices.get(p['symbol']), settings.get('market_prices_at'), config.bot.cycle_seconds), config.paper)
                     for p in connection.execute('SELECT * FROM positions LIMIT 100')]
        initial = config.paper.initial_cash_usdt
        current = latest.get('equity',initial)
        futures_ledger = FuturesTestnetLedger(config.futures_testnet.database_path)
        futures_pause = _futures_pause_diagnostics(config, futures_ledger)
        payload = {
            'status': {'mode':config.bot.mode.upper(),'killed':config.bot.kill_switch_path.exists(),'ai_enabled':config.ai.enabled,
                       'ai_model':config.ai.model,'equity':current,'cash':latest.get('cash',float(settings.get('paper_cash',initial))),
                       'exposure':latest.get('exposure',0),'return_pct':(current/initial-1)*100,
                       'positions':len(positions),'max_positions':config.risk.max_positions,'risk':asdict(config.risk),
                       'paper_risk_profile':settings.get('paper_risk_profile','normal') if settings.get('paper_risk_profile','normal') in PROFILES else 'invalid',
                       'cycle_seconds':config.bot.cycle_seconds,
                       'spot_cycle':spot_cycle_status(settings.get('spot_last_cycle'), config.bot.cycle_seconds),
                       'native_protection':projection(json.loads(settings.get(SPOT_KEY) or '{}')) if config.bot.mode == 'testnet' else None,
                       'native_protection_started_at':settings.get('native_protection_started_at'),
                       'activity':activity_status(latest.get('created_at'),config.bot.cycle_seconds),
                       'observation_health':_spot_observation_health(connection, config, latest, positions, settings)},
            'positions':positions, 'equity':list(reversed(equity)),
            'trades':rows('trades','id,symbol,side,quantity,price,fee,realized_pnl,reason,created_at',50),
            'reviews':rows('ai_reviews','id,symbol,verdict,confidence,risk_multiplier,reason,created_at',50),
            'events':rows('events','id,level,message,created_at',50),
            'risk':asdict(config.risk),
            'paper_scorecard':paper_scorecard(connection, prices=prices,
                prices_at=settings.get('market_prices_at'), cycle_seconds=config.bot.cycle_seconds,
                paper=config.paper, research_symbols=studied_symbols(config.research.report_path, config.research.symbols), mode=config.bot.mode),
            'research':{'mode':'RESEARCH_ONLY','status':'NOT_RUN','assets':[]},
            'research_state':{'running':False,'error':None},
            'updates':{'status':'not_configured','message':'Falta configurar el canal firmado y la recuperación supervisada.'},
            'market_pulse': market_pulse_projection(config),
            'futures_forward': {
                'enabled': bool(config.bot.mode == 'testnet' and config.futures_testnet.forward_enabled),
                'killed': config.futures_testnet.kill_switch_path.exists(),
                'pause_diagnostics': futures_pause,
                'symbols': list(config.futures_testnet.forward_symbols),
                'automatic_leverage': config.futures_testnet.forward_leverage,
                'leverage_trials': futures_ledger.leverage_trial_status(
                    config.futures_testnet.forward_leverage_trials, config.futures_testnet.forward_margin_usdt),
                'portfolio_budget': futures_ledger.setting('forward_portfolio_budget'),
                'cycle_diagnostic': futures_ledger.setting('forward_last_cycle_diagnostic'),
                'guardrails': {
                    'margin_type': config.futures_testnet.margin_type,
                    'position_mode': config.futures_testnet.position_mode,
                    'max_positions': config.futures_testnet.forward_max_positions,
                    'forward_timeframe': config.futures_testnet.forward_timeframe,
                    'forward_margin_usdt': config.futures_testnet.forward_margin_usdt,
                    'forward_total_notional_usdt': config.futures_testnet.forward_total_notional_usdt,
                    'forward_total_stop_loss_usdt': config.futures_testnet.forward_total_stop_loss_usdt,
                    'forward_min_score': config.futures_testnet.forward_min_score,
                    'forward_stop_atr_multiple': config.futures_testnet.forward_stop_atr_multiple,
                    'forward_minimum_stop_pct': config.futures_testnet.forward_minimum_stop_pct,
                    'forward_reward_to_risk': config.futures_testnet.forward_reward_to_risk,
                },
                'ai_model': config.ai.model,
                'last_ai_reviews': {symbol: futures_ledger.setting(f'forward_last_ai_review_{symbol}') for symbol in config.futures_testnet.forward_symbols},
                'latest_signals': {symbol: futures_ledger.setting(f'forward_last_signal_{symbol}') for symbol in config.futures_testnet.forward_symbols},
                'symbol_health': futures_ledger.setting('forward_symbol_health') or {},
                'last_auto_recovery': futures_ledger.setting('forward_last_auto_recovery'),
                'last_journal_recovery': futures_ledger.setting('forward_last_journal_recovery'),
                'evidence_gap': futures_ledger.setting('forward_evidence_gap'),
                'observation_health': futures_ledger.observation_health(config.bot.cycle_seconds, max_positions=config.futures_testnet.forward_max_positions),
                'recovery': {
                    'durable_order_journal': True,
                    'startup_position_reconciliation': True,
                    'separate_kill_switch': True,
                    'automatic_config_repair': True,
                    'automatic_safe_resume': True,
                    'native_exchange_stop_orders': True,
                },
                'live_readiness': {
                    'enabled': False,
                    'reason': 'LIVE remains disabled. Native orders require per-position exchange confirmation and Demo observation.',
                },
                **futures_ledger.forward_snapshot(),
            },
        }
        for key in ('trades','reviews','events'):
            for row in payload[key]:
                for field in ('reason','message'):
                    if field in row:
                        row[field] = public_text(row[field])
        path = Path(report_path or config.research.report_path)
        from .research_runtime import project_report, lab_state
        payload['research_state'] = lab_state(path, automatic=config.research.automatic)
        if path.is_file() and path.stat().st_size <= 12_000_000:
            report = json.loads(path.read_text(encoding='utf-8'))
            if report.get('mode') == 'RESEARCH_ONLY' and isinstance(report.get('assets'), list):
                payload['research'] = project_report(report)
        payload.update(platform_projection({**payload, 'quant': quant_projection(config)}))
        intelligence = guardian_intelligence_projection(config)
        if intelligence is not None and len(json.dumps({**payload, 'guardian_intelligence': intelligence},
                allow_nan=False).encode()) <= 480_000:
            payload['guardian_intelligence'] = intelligence
        if len(json.dumps(payload,allow_nan=False).encode()) > 480_000:
            raise ValueError('Dashboard projection exceeds size budget')
        return payload
    finally:
        connection.close()
