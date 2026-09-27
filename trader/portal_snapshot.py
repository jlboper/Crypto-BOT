"""Bounded, credential-free dashboard projection from the existing database."""
import json
import re
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from .domain import Position
from .monitoring import activity_status, position_metrics, usable_price
from .paper_scorecard import paper_scorecard
from .risk_control import PROFILES
from .futures_testnet_ledger import FuturesTestnetLedger


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
    last_error = ledger.setting('forward_last_error')
    if isinstance(last_error, dict):
        last_error = {
            'message': public_text(last_error.get('message', '')),
            'at': str(last_error.get('at', ''))[:40] or None,
        }
    else:
        last_error = None
    detail = public_text(raw_reason) if raw_reason else None
    normalized = (detail or '').lower()
    if not killed:
        label = None
        source = None
    elif normalized == 'owner pause':
        label = 'Pausa manual del propietario'
        source = 'manual'
    elif 'three consecutive futures protection errors' in normalized:
        label = '3 errores consecutivos de protección Futures'
        source = 'automatic_safety'
    elif 'three consecutive futures forward errors' in normalized:
        label = '3 errores consecutivos del ciclo Futures'
        source = 'automatic_safety'
    elif any(term in normalized for term in ('untracked futures', 'position identity mismatch', 'missing or ambiguous', 'recovery requires owner review', 'could not be reconstructed')):
        label = 'Inconsistencia o reconciliación de posición Futures'
        source = 'automatic_safety'
    else:
        label = detail or 'Pausa de seguridad Futures'
        source = 'automatic_safety'
    return {
        'active': killed,
        'label': label,
        'detail': detail,
        'source': source,
        'paused_at': paused_at,
        'last_error': last_error,
        'consecutive_errors': int(ledger.setting('forward_consecutive_errors') or 0),
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
    state = ("STARTING" if starting else
             "OK" if coverage >= 90 and errors == 0 and healthy_integrity else
             "WATCH" if coverage >= 70 and errors < config.risk.max_consecutive_errors and healthy_integrity else
             "ATTENTION")
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
        "ai_reviews": int(ai["total"] or 0),
        "ai_rejects": int(ai["rejected"] or 0),
        "closed_trades": int(closed["total"] or 0),
        "realized_pnl_usdt": round(float(closed["pnl"] or 0.0), 8),
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
        settings = dict(connection.execute("SELECT key,value FROM settings WHERE key IN ('market_prices','market_prices_at','paper_cash','paper_risk_profile','unified_testnet_pending_order')"))
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
                       'activity':activity_status(latest.get('created_at'),config.bot.cycle_seconds),
                       'observation_health':_spot_observation_health(connection, config, latest, positions, settings)},
            'positions':positions, 'equity':list(reversed(equity)),
            'trades':rows('trades','id,symbol,side,quantity,price,fee,realized_pnl,reason,created_at',50),
            'reviews':rows('ai_reviews','id,symbol,verdict,confidence,risk_multiplier,reason,created_at',50),
            'events':rows('events','id,level,message,created_at',50),
            'risk':asdict(config.risk),
            'paper_scorecard':paper_scorecard(connection, prices=prices,
                prices_at=settings.get('market_prices_at'), cycle_seconds=config.bot.cycle_seconds,
                paper=config.paper, research_symbols=config.research.symbols, mode=config.bot.mode),
            'research':{'mode':'RESEARCH_ONLY','status':'NOT_RUN','assets':[]},
            'research_state':{'running':False,'error':None},
            'updates':{'status':'not_configured','message':'Falta configurar el canal firmado y la recuperación supervisada.'},
            'futures_forward': {
                'enabled': bool(config.bot.mode == 'testnet' and config.futures_testnet.forward_enabled),
                'killed': config.futures_testnet.kill_switch_path.exists(),
                'pause_diagnostics': futures_pause,
                'symbols': list(config.futures_testnet.forward_symbols),
                'automatic_leverage': config.futures_testnet.forward_leverage,
                'guardrails': {
                    'margin_type': config.futures_testnet.margin_type,
                    'position_mode': config.futures_testnet.position_mode,
                    'max_positions': config.futures_testnet.forward_max_positions,
                    'forward_margin_usdt': config.futures_testnet.forward_margin_usdt,
                    'forward_min_score': config.futures_testnet.forward_min_score,
                    'forward_stop_atr_multiple': config.futures_testnet.forward_stop_atr_multiple,
                    'forward_minimum_stop_pct': config.futures_testnet.forward_minimum_stop_pct,
                    'forward_reward_to_risk': config.futures_testnet.forward_reward_to_risk,
                },
                'ai_model': config.ai.model,
                'last_ai_reviews': {symbol: futures_ledger.setting(f'forward_last_ai_review_{symbol}') for symbol in config.futures_testnet.forward_symbols},
                'observation_health': futures_ledger.observation_health(config.bot.cycle_seconds),
                'recovery': {
                    'durable_order_journal': True,
                    'startup_position_reconciliation': True,
                    'separate_kill_switch': True,
                    'native_exchange_stop_orders': False,
                },
                'live_readiness': {
                    'enabled': False,
                    'reason': 'Demo observation and exchange-native protective orders are required before LIVE.',
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
        if path.is_file() and path.stat().st_size <= 300_000:
            report = json.loads(path.read_text(encoding='utf-8'))
            if report.get('mode') == 'RESEARCH_ONLY' and isinstance(report.get('assets'), list):
                payload['research'] = report
        if len(json.dumps(payload,allow_nan=False).encode()) > 480_000:
            raise ValueError('Dashboard projection exceeds size budget')
        return payload
    finally:
        connection.close()
