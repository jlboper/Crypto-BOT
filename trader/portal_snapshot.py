"""Bounded, credential-free dashboard projection from the existing database."""
import json
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
        "SELECT COUNT(*) AS n FROM events WHERE created_at>=? AND level IN ('ERROR','CRITICAL')", (since_iso,)
    ).fetchone()["n"])
    warnings = int(connection.execute(
        "SELECT COUNT(*) AS n FROM events WHERE created_at>=? AND level='WARN'", (since_iso,)
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
    reasons = []
    if coverage < 90:
        reasons.append("cycle_coverage_below_90")
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
             "ATTENTION" if coverage < 70 or active_attention or not healthy_integrity else
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
        "last_error": last_error if isinstance(last_error, dict) else None,
        "last_recovery": last_recovery if isinstance(last_recovery, dict) else None,
        "ai_reviews": int(ai["total"] or 0),
        "ai_rejects": int(ai["rejected"] or 0),
        "closed_trades": int(closed["total"] or 0),
        "realized_pnl_usdt": round(float(closed["pnl"] or 0.0), 8),
        "reason_codes": reasons,
        "integrity": integrity,
    }


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
        if len(json.dumps(payload,allow_nan=False).encode()) > 480_000:
            raise ValueError('Dashboard projection exceeds size budget')
        return payload
    finally:
        connection.close()
