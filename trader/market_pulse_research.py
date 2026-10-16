"""Read-only Pulse evidence attached to the existing Research Lab's archived run."""
from datetime import UTC, datetime
from pathlib import Path
from .market_pulse import market_pulse_snapshot, replay_decisions


def pulse_research_evidence(data_dir):
    state = {"engine": "AI_MARKET_PULSE", "mode": "SHADOW", "state": "FORWARD_ONLY",
        "hypothesis_version": "pulse-v1", "captured_at": datetime.now(UTC).isoformat(),
        "automatic_promotion": False, "historical_backtest_valid": False,
        "out_of_sample_validated": False,
        "limitations": ["Complete historical ticks and contemporaneously received news are unavailable.",
            "Frozen-score replay audits already observed evidence; it is not independent OOS validation.",
            "Accumulate prospective data, reserve new holdouts and stress costs before any promotion review."]}
    pulse = market_pulse_snapshot(data_dir)
    state.update(decisions=pulse["stats"]["decisions"], events=pulse["stats"]["events_analyzed"],
        closed_trades=pulse["performance"]["closed_trades"], observation_days=pulse["performance"]["observation_days"])
    if not (Path(data_dir)/"market-pulse.db").is_file():
        state["replay"] = {"checked": 0, "mismatches": 0, "invalid_timestamps": 0}
    else:
        try:
            replay = replay_decisions(data_dir, limit=1000)
            state["replay"] = {key: replay[key] for key in ("checked", "mismatches", "invalid_timestamps")}
            state["limitations"].append("Replay is bounded to the earliest 1,000 decisions in this report; the full local journal remains intact.")
        except Exception:
            state["replay"] = None
            state["limitations"].append("Frozen-evidence replay unavailable; no validation success is inferred.")
    return state
