"""Frozen public46 observer from main a851908a; no Git/network needed in CI.

The exact Git blob was extracted with git show. It only opens synthetic test
journals when a test explicitly calls it, never operating data or a trading bot.
"""
import hashlib
import importlib.util
from pathlib import Path


def load_observer46():
    path=Path(__file__).parent/'fixtures'/'opportunity_observer_v01046.py'
    # Git may check this text blob out with CRLF on Windows. Compare its exact
    # canonical Git text, rather than treating checkout newlines as code edits.
    if hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!='951fa3c76d29944ba7d7d2a9363b38e8bc8b7f84d743894b501aee7b102343b1':
        raise AssertionError('Frozen release46 observer changed')
    spec=importlib.util.spec_from_file_location('trader._synthetic_observer46',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
