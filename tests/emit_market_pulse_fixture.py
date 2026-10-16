"""Synthetic producer fixture, without touching any operating ledger or credential."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from trader.config import load_config
from trader.portal_snapshot import market_pulse_projection
from trader.market_pulse import MarketPulseService
from dataclasses import replace


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = load_config()
        config = replace(config, bot=replace(config.bot, database_path=root / 'spot.db'),
            market_pulse=replace(config.market_pulse, kill_switch_path=root / 'pulse-kill'))
        if '--initialized' in sys.argv:
            class SyntheticReviewer:
                def health(self):
                    return {'daily_cap': 6, 'used_today': 0, 'min_interval_seconds': 300,
                            'max_output_tokens': 250, 'max_input_bytes': 4800}
            observer = MarketPulseService(root, reviewer=SyntheticReviewer(),
                kill_switch_path=config.market_pulse.kill_switch_path)
            observer._initialize()
            observer.evaluate()
        print(json.dumps(market_pulse_projection(config), allow_nan=False))


if __name__ == '__main__':
    main()
