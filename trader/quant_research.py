"""Bounded read-only audits of Quant's already recorded numerical evidence.

No public provider, account client, model request, wallet initialization or
migration is used. A matching model replay is neither a fill reconstruction nor
independent out-of-sample evidence. Financial models and admission stay unchanged.
"""
from __future__ import annotations

from datetime import UTC, datetime
import math
from pathlib import Path
import re
import sqlite3
import time


STRATEGIES = ("FUNDING_CARRY", "STATISTICAL_ARBITRAGE")
MAX_DATABASE_BYTES = 256 * 1024 * 1024
SAMPLE_PER_EDGE = 4
MAX_COUNT = 1_000_000_000


def _iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ValueError("Invalid research count")
    return value


def _empty(now, state="NOT_STARTED"):
    return {"schema": 1, "engine": "QUANT_ARBITRAGE", "mode": "SHADOW",
        "state": state, "captured_at": _iso(now), "evidence_through": None,
        "execution_enabled": False, "automatic_promotion": False,
        "historical_backtest_valid": False, "out_of_sample_validated": False,
        "counts": {"decisions": None, "closed_trades": None, "pending_funding": None,
                   "unrecognized_strategy_decisions": None},
        "strategies": [{"id": strategy, "decisions": None, "closed_trades": None,
                        "first_decision_at": None, "last_decision_at": None}
                       for strategy in STRATEGIES],
        "replay": {"state": "NOT_STARTED", "checked": 0, "matches": 0,
                   "mismatches": 0, "unavailable": 0, "sampled": 0,
                   "maximum_sample": 16,
                   "selection": "EARLIEST_4_AND_LATEST_4_PER_STRATEGY_BY_CUTOFF"},
        "cost_model": "FROZEN_PER_LEG_FEES_SLIPPAGE_BASIS_AND_LEGGING_STRESS",
        "execution_model": "SIMULATED_NON_ATOMIC_NOT_EXCHANGE_FILLS",
        "statistical_entry_authorization": "BLOCKED_UNTIL_SEPARATE_VALIDATION_AND_AUTHORIZATION",
        "limitations": ["MODEL_REPLAY_NOT_FILL_RECONCILIATION_OR_INDEPENDENT_VALIDATION",
            "BOUNDED_DETERMINISTIC_SAMPLE_NOT_ALL_DECISIONS",
            "HISTORICAL_BARS_RECEIVED_DURING_OBSERVATION_NOT_FORWARD_OOS",
            "FUNDING_PROJECTION_NOT_SETTLED_INCOME",
            "PER_LEG_EXECUTION_AND_MARGIN_STRESS_ARE_SIMULATION_HYPOTHESES",
            "NO_MATCHED_OPERATIONAL_OR_AI_COUNTERFACTUAL_COHORT"],
        "error": None}


def quant_research_evidence(data_dir, *, now=None):
    """Audit a finite sample available by ``now`` without creating a database.

    Counts, sample selection and metadata share one SQLite read transaction.
    Immutable replay evidence is then read by the existing causal replay. A
    corrupt/missing sample remains unavailable; it is never counted as a match.
    The sample covers both edges of each strategy, preventing recent busy carry
    decisions from hiding the existence of statistical diagnostics.
    """
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or not 0 < now < 253402300799:
        raise ValueError("Invalid research cutoff")
    result = _empty(now)
    path = Path(data_dir) / "quant-shadow.db"
    if not path.is_file():
        return result
    selected = []
    try:
        if path.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError("Research database exceeds read budget")
        db = sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=.5)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            # Keep a damaged or unexpectedly expensive schema from monopolizing
            # the Research Lab worker. This affects only this read connection.
            deadline = time.monotonic()+2
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            counts = {row[0]: _count(row[1]) for row in db.execute(
                "SELECT strategy,COUNT(*) FROM quant_decisions WHERE at>0 AND at<=? GROUP BY strategy", (now,))}
            closed = {row[0]: _count(row[1]) for row in db.execute(
                "SELECT strategy,COUNT(*) FROM quant_trades WHERE closed>0 AND closed<=? GROUP BY strategy", (now,))}
            pending = _count(db.execute("SELECT COUNT(*) FROM quant_pending_funding").fetchone()[0])
            unknown = sum(value for key, value in counts.items() if key not in STRATEGIES)
            result["counts"] = {"decisions": _count(sum(counts.values())),
                "closed_trades": _count(sum(closed.values())), "pending_funding": pending,
                "unrecognized_strategy_decisions": _count(unknown)}
            for row in result["strategies"]:
                strategy = row["id"]
                row.update(decisions=counts.get(strategy, 0), closed_trades=closed.get(strategy, 0))
                bounds = db.execute("SELECT MIN(at),MAX(at) FROM quant_decisions WHERE strategy=? AND at>0 AND at<=?",
                                    (strategy, now)).fetchone()
                row.update(first_decision_at=_iso(bounds[0]) if bounds[0] is not None else None,
                           last_decision_at=_iso(bounds[1]) if bounds[1] is not None else None)
                for order in ("ASC", "DESC"):
                    # ``order`` comes from the closed tuple above, never content.
                    selected.extend(item[0] for item in db.execute(
                        "SELECT id FROM quant_decisions WHERE strategy=? AND at>0 AND at<=? ORDER BY at "+order+
                        ",id "+order+" LIMIT ?", (strategy, now, SAMPLE_PER_EDGE)))
            latest = max((row["last_decision_at"] for row in result["strategies"] if row["last_decision_at"]), default=None)
            result["evidence_through"] = latest
        finally:
            db.close()
        selected = list(dict.fromkeys(selected))
        result["replay"]["sampled"] = len(selected)
        from .quant_shadow import replay_quant_decision
        for identity in selected:
            replay = result["replay"]
            if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
                replay["unavailable"] += 1
                continue
            try:
                evidence = replay_quant_decision(data_dir, identity)
                if type(evidence.get("model_matches")) is not bool:
                    raise ValueError("Invalid replay result")
                replay["checked"] += 1
                replay["matches" if evidence["model_matches"] else "mismatches"] += 1
            except Exception:
                # Never expose a DB/provider payload or exception text remotely.
                replay["unavailable"] += 1
        replay = result["replay"]
        replay["state"] = ("MISMATCH" if replay["mismatches"] else "PARTIAL" if replay["unavailable"]
                           else "MATCHED_SAMPLE" if replay["checked"] else "NOT_STARTED")
        result["state"] = ("PARTIAL" if unknown or pending or replay["mismatches"] or replay["unavailable"]
                           else "AVAILABLE" if result["counts"]["decisions"] else "NOT_STARTED")
        return result
    except Exception:
        unavailable = _empty(now, "UNAVAILABLE")
        unavailable["error"] = "QUANT_RESEARCH_EVIDENCE_UNAVAILABLE"
        return unavailable
