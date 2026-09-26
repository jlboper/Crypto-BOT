from __future__ import annotations

import os
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_environment() -> None:
    candidates = [
        PROJECT_ROOT / ".env.local",
        PROJECT_ROOT / ".env",
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            _load_env_file(resolved)


@dataclass(frozen=True)
class BotSettings:
    mode: str
    cycle_seconds: int
    timeframe: str
    universe_size: int
    max_parallel_requests: int
    database_path: Path
    kill_switch_path: Path
    protection_seconds: int = 30


@dataclass(frozen=True)
class PaperSettings:
    initial_cash_usdt: float
    fee_rate: float
    slippage_rate: float


@dataclass(frozen=True)
class RiskSettings:
    max_positions: int
    max_position_pct: float
    max_total_exposure_pct: float
    risk_per_trade_pct: float
    daily_loss_limit_pct: float
    weekly_loss_limit_pct: float
    stop_atr_multiple: float
    minimum_stop_pct: float
    reward_to_risk: float
    trailing_atr_multiple: float
    max_consecutive_errors: int


@dataclass(frozen=True)
class StrategySettings:
    minimum_score: int
    ema_fast: int
    ema_slow: int
    rsi_period: int
    atr_period: int
    breakout_period: int
    volume_period: int


@dataclass(frozen=True)
class AISettings:
    enabled: bool
    model: str
    max_reviews_per_cycle: int
    minimum_confidence: float
    fail_closed: bool
    timeout_seconds: int
    max_output_tokens: int = 800
    max_reviews_per_day: int = 30


@dataclass(frozen=True)
class DashboardSettings:
    host: str
    port: int


@dataclass(frozen=True)
class ResearchSettings:
    symbols: tuple[str, ...]
    history_candles: int
    train_bars: int
    test_bars: int
    report_path: Path


@dataclass(frozen=True)
class AppConfig:
    bot: BotSettings
    paper: PaperSettings
    risk: RiskSettings
    strategy: StrategySettings
    ai: AISettings
    dashboard: DashboardSettings
    research: ResearchSettings


def _project_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_config(path: str | Path | None = None) -> AppConfig:
    load_environment()
    config_path = Path(path) if path else PROJECT_ROOT / "config.toml"
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    bot = raw["bot"]
    paper = raw["paper"]
    risk = raw["risk"]
    strategy = raw["strategy"]
    ai = raw["ai"]
    dashboard = raw["dashboard"]
    research = raw.get("research", {})

    mode = str(bot.get("mode", "paper")).lower()
    if mode not in {"paper", "testnet"}:
        raise ValueError("Execution mode must be paper or testnet. Binance LIVE is not implemented.")
    for section in (paper, risk, strategy):
        for key, value in section.items():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid numeric setting: {key}")
    if paper["initial_cash_usdt"] <= 0 or not 0 <= paper["fee_rate"] < 0.1 or not 0 <= paper["slippage_rate"] < 0.1:
        raise ValueError("Invalid paper costs/capital")
    for key in ("max_position_pct", "max_total_exposure_pct", "risk_per_trade_pct", "daily_loss_limit_pct", "weekly_loss_limit_pct", "minimum_stop_pct"):
        if not 0 < risk[key] <= 1:
            raise ValueError(f"Invalid risk fraction: {key}")
    if risk["max_position_pct"] > risk["max_total_exposure_pct"] or risk["reward_to_risk"] <= 0:
        raise ValueError("Inconsistent risk limits")
    for key in ("max_positions", "max_consecutive_errors"):
        if type(risk[key]) is not int or risk[key] < 1:
            raise ValueError(f"Invalid risk count: {key}")
    for key, value in strategy.items():
        if type(value) is not int or not 1 <= value <= 200:
            raise ValueError(f"Invalid strategy setting: {key}")
    if not 10 <= bot["cycle_seconds"] <= 86400 or not 1 <= bot["max_parallel_requests"] <= 16 or not 1 <= bot["universe_size"] <= 100:
        raise ValueError("Invalid engine resource limits")
    if bot["timeframe"] not in {"1m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d"}:
        raise ValueError("Unsupported timeframe")
    if not 0 <= ai["minimum_confidence"] <= 1 or not 1 <= ai["timeout_seconds"] <= 120 or not 0 <= ai["max_reviews_per_cycle"] <= 10:
        raise ValueError("Invalid AI limits")

    return AppConfig(
        bot=BotSettings(
            mode=mode,
            cycle_seconds=int(bot["cycle_seconds"]),
            timeframe=str(bot["timeframe"]),
            universe_size=int(bot["universe_size"]),
            max_parallel_requests=int(bot["max_parallel_requests"]),
            database_path=_project_path(str(bot["database_path"])),
            kill_switch_path=_project_path(str(bot["kill_switch_path"])),
            protection_seconds=max(10, min(300, int(bot.get("protection_seconds", 30)))),
        ),
        paper=PaperSettings(**paper),
        risk=RiskSettings(**risk),
        strategy=StrategySettings(**strategy),
        ai=AISettings(
            enabled=bool(ai["enabled"]),
            model=os.getenv("OPENAI_MODEL", str(ai["model"])),
            max_reviews_per_cycle=int(ai["max_reviews_per_cycle"]),
            minimum_confidence=float(ai["minimum_confidence"]),
            fail_closed=bool(ai["fail_closed"]),
            timeout_seconds=int(ai["timeout_seconds"]),
            max_output_tokens=max(256, min(4096, int(ai.get("max_output_tokens", 800)))),
            max_reviews_per_day=max(0, min(100, int(ai.get("max_reviews_per_day", 30)))),
        ),
        dashboard=DashboardSettings(host=str(dashboard["host"]), port=int(dashboard["port"])),
        research=ResearchSettings(
            symbols=tuple(str(symbol).upper() for symbol in research.get(
                "symbols", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
            )),
            history_candles=int(research.get("history_candles", 5000)),
            train_bars=int(research.get("train_bars", 1200)),
            test_bars=int(research.get("test_bars", 400)),
            report_path=_project_path(str(research.get("report_path", "data/research/latest.json"))),
        ),
    )
