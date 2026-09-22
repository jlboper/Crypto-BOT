"""Synthetic process fixture. Never imports the trading engine or uses APIs."""
import json
import os
import sqlite3
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from trader.runtime import single_instance
from trader.runtime_control import RuntimeControl

root = Path(sys.argv[2])
token = os.environ.get('CRYPTO_UPDATE_TOKEN')
behavior = sys.argv[3]
control = RuntimeControl(root/'data', token)
with single_instance(root/'data/engine.lock'):
    control.guard_start()
    version = tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
    if token:
        connection = sqlite3.connect(root/'data/bot.db')
        if connection.execute("SELECT name FROM sqlite_master WHERE name='candidate_schema'").fetchone() is None:
            connection.execute('UPDATE balance SET amount=123')
            connection.execute('CREATE TABLE candidate_schema (value TEXT)')
            connection.commit()
        connection.close()
        if behavior == 'exit':
            raise SystemExit(17)
    control.ready(version, dashboard_ready=True)
    if token and behavior == 'wrong-token':
        record = json.loads(control.status.read_text())
        record['token'] = '0'*64
        control.status.write_text(json.dumps(record))
    control.await_activation(timeout=10)
    if token:
        journal = json.loads((root/'data/updates/journal.json').read_text())
        if journal['phase'] not in {'committed','restored'}:
            (root/'UNSAFE_CYCLE').write_text('cycle before durable commit')
        (root/'candidate-cycle').write_text('synthetic cycle')
    while not control.should_stop():
        time.sleep(0.02)
