"""Bounded, credential-free dashboard projection from the existing database."""
import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from .domain import Position
from .monitoring import activity_status, position_metrics, usable_price
from .paper_scorecard import paper_scorecard
from .risk_control import PROFILES


def public_text(value):
    value = str(value)
    value = re.sub(r'https?://\S+', '[URL omitida]', value)
    value = re.sub(r'(?i)(?:sk-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]+', '[credencial omitida]', value)
    value = re.sub(r'(?i)(?:bearer|api[_ -]?key|token|secret|password)\s*[:= ]\s*\S+', '[credencial omitida]', value)
    return value[:1000]


def dashboard_snapshot(config, report_path=None):
    connection = sqlite3.connect(config.bot.database_path.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')
        def rows(table, columns, limit):
            return [dict(row) for row in connection.execute(f'SELECT {columns} FROM {table} ORDER BY id DESC LIMIT ?', (limit,))]
        equity = rows('equity','equity,cash,exposure,created_at',300)
        latest = equity[0] if equity else {}
        settings = dict(connection.execute("SELECT key,value FROM settings WHERE key IN ('market_prices','market_prices_at','paper_cash','paper_risk_profile')"))
        prices = json.loads(settings.get('market_prices','{}'))
        positions = [position_metrics(Position(**dict(p)),
                     usable_price(prices.get(p['symbol']), settings.get('market_prices_at'), config.bot.cycle_seconds), config.paper)
                     for p in connection.execute('SELECT * FROM positions LIMIT 100')]
        initial = config.paper.initial_cash_usdt
        current = latest.get('equity',initial)
        payload = {
            'status': {'mode':'PAPER','killed':config.bot.kill_switch_path.exists(),'ai_enabled':config.ai.enabled,
                       'ai_model':config.ai.model,'equity':current,'cash':latest.get('cash',float(settings.get('paper_cash',initial))),
                       'exposure':latest.get('exposure',0),'return_pct':(current/initial-1)*100,
                       'positions':len(positions),'max_positions':config.risk.max_positions,'risk':asdict(config.risk),
                       'paper_risk_profile':settings.get('paper_risk_profile','normal') if settings.get('paper_risk_profile','normal') in PROFILES else 'invalid',
                       'cycle_seconds':config.bot.cycle_seconds,
                       'activity':activity_status(latest.get('created_at'),config.bot.cycle_seconds)},
            'positions':positions, 'equity':list(reversed(equity)),
            'trades':rows('trades','id,symbol,side,quantity,price,fee,realized_pnl,reason,created_at',50),
            'reviews':rows('ai_reviews','id,symbol,verdict,confidence,risk_multiplier,reason,created_at',50),
            'events':rows('events','id,level,message,created_at',50),
            'risk':asdict(config.risk),
            'paper_scorecard':paper_scorecard(connection, prices=prices,
                prices_at=settings.get('market_prices_at'), cycle_seconds=config.bot.cycle_seconds,
                paper=config.paper, research_symbols=config.research.symbols),
            'research':{'mode':'RESEARCH_ONLY','status':'NOT_RUN','assets':[]},
            'research_state':{'running':False,'error':None},
            'testnet':{
                'mode':'READ_ONLY_DRY_RUN',
                'order_submission_enabled':False,
                'planner':'public_filters_and_synthetic_reconciliation',
                'next_step':'Testnet execution is separate; inspect the execution ledger before any trade',
            },
            'updates':{'status':'not_configured','message':'Falta configurar el canal firmado y la recuperación supervisada.'},
        }
        from .testnet_execution import public_status
        payload['testnet_execution'] = public_status(config.bot.database_path.parent.parent)
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
