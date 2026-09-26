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
class FuturesTestnetSettings:
    enabled: bool
    database_path: Path
    default_leverage: int
    max_leverage: int
    margin_type: str
    position_mode: str
    smoke_margin_usdt: float
    forward_enabled: bool
    forward_symbol: str
    forward_leverage: int
    forward_margin_usdt: float
    forward_min_score: int
    forward_stop_atr_multiple: float
    forward_minimum_stop_pct: float
    forward_reward_to_risk: float
    kill_switch_path: Path


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
    futures_testnet: FuturesTestnetSettings


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
    futures_testnet = raw.get("futures_testnet", {})

    mode = os.getenv("EXECUTION_MODE", str(bot.get("mode", "paper"))).lower()
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
    futures_default = int(futures_testnet.get("default_leverage", 2))
    futures_max = int(futures_testnet.get("max_leverage", 3))
    futures_margin = str(futures_testnet.get("margin_type", "ISOLATED")).upper()
    futures_position_mode = str(futures_testnet.get("position_mode", "ONE_WAY")).upper()
    futures_smoke_margin = float(futures_testnet.get("smoke_margin_usdt", 10.0))
    # Forward-test enablement is part of the signed release configuration.
    # Runtime pausing uses the dedicated Futures kill switch. A stale local
    # FUTURES_FORWARD_ENABLED override must not silently disable the motor.
    futures_forward_enabled = mode == "testnet" or bool(futures_testnet.get("forward_enabled", False))
    futures_forward_symbol = str(futures_testnet.get("forward_symbol", "BTCUSDT")).upper()
    futures_forward_leverage = int(futures_testnet.get("forward_leverage", 1))
    futures_forward_margin = float(futures_testnet.get("forward_margin_usdt", 10.0))
    futures_forward_min_score = int(futures_testnet.get("forward_min_score", 75))
    futures_forward_stop_atr = float(futures_testnet.get("forward_stop_atr_multiple", 2.0))
    futures_forward_min_stop = float(futures_testnet.get("forward_minimum_stop_pct", 0.025))
    futures_forward_rr = float(futures_testnet.get("forward_reward_to_risk", 2.0))
    if futures_default not in {1, 2, 3} or futures_max not in {1, 2, 3} or futures_default > futures_max:
        raise ValueError("Futures Testnet leverage must stay within 1x/2x/3x")
    if futures_margin != "ISOLATED" or futures_position_mode != "ONE_WAY":
        raise ValueError("Futures Testnet must remain ISOLATED and ONE_WAY")
    if not math.isfinite(futures_smoke_margin) or not 5 <= futures_smoke_margin <= 25:
        raise ValueError("Invalid Futures Testnet smoke margin")
    if futures_forward_symbol != "BTCUSDT":
        raise ValueError("Futures forward test is initially restricted to BTCUSDT")
    if futures_forward_leverage != 1:
        raise ValueError("Automatic Futures forward test must stay at 1x")
    if not math.isfinite(futures_forward_margin) or not 5 <= futures_forward_margin <= 100:
        raise ValueError("Invalid Futures forward-test margin")
    if not 60 <= futures_forward_min_score <= 95:
        raise ValueError("Invalid Futures forward-test score")
    if not math.isfinite(futures_forward_stop_atr) or not 1 <= futures_forward_stop_atr <= 5:
        raise ValueError("Invalid Futures forward-test ATR stop")
    if not math.isfinite(futures_forward_min_stop) or not 0.01 <= futures_forward_min_stop <= 0.10:
        raise ValueError("Invalid Futures forward-test minimum stop")
    if not math.isfinite(futures_forward_rr) or not 1 <= futures_forward_rr <= 5:
        raise ValueError("Invalid Futures forward-test reward/risk")

    selected_database = bot.get("testnet_database_path", "data/testnet-trader.db") if mode == "testnet" else bot["database_path"]
    return AppConfig(
        bot=BotSettings(
            mode=mode,
            cycle_seconds=int(bot["cycle_seconds"]),
            timeframe=str(bot["timeframe"]),
            universe_size=int(bot["universe_size"]),
            max_parallel_requests=int(bot["max_parallel_requests"]),
            database_path=_project_path(str(selected_database)),
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
        futures_testnet=FuturesTestnetSettings(
            enabled=bool(futures_testnet.get("enabled", True)),
            database_path=_project_path(str(bot.get("futures_testnet_database_path", "data/futures-testnet.db"))),
            default_leverage=futures_default,
            max_leverage=futures_max,
            margin_type=futures_margin,
            position_mode=futures_position_mode,
            smoke_margin_usdt=futures_smoke_margin,
            forward_enabled=futures_forward_enabled,
            forward_symbol=futures_forward_symbol,
            forward_leverage=futures_forward_leverage,
            forward_margin_usdt=futures_forward_margin,
            forward_min_score=futures_forward_min_score,
            forward_stop_atr_multiple=futures_forward_stop_atr,
            forward_minimum_stop_pct=futures_forward_min_stop,
            forward_reward_to_risk=futures_forward_rr,
            kill_switch_path=_project_path(str(futures_testnet.get("kill_switch_path", "data/FUTURES_KILL_SWITCH"))),
        ),
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
