"""Offline shared-capital simulator. No broker, credentials or order transport."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .domain import Candle
from .indicators import atr, ema_series, rsi
from .research_runtime import check_cancel


@dataclass(frozen=True)
class Intent:
    side: int  # +1 LONG, -1 SHORT
    distance: float
    reward: float = 2.0
    score: float = 0.0


@dataclass(frozen=True)
class Scenario:
    name: str
    risk: float
    position_cap: float
    gross_cap: float
    leverage: int = 1
    max_positions: int = 5
    maintenance: float = 0.01


def scenarios(market: str) -> list[Scenario]:
    profiles = [('prudente', .0025, .15, .5), ('base', .005, .2, .8),
                ('agresivo', .01, .3, 1.0 if market == 'SPOT' else 1.5)]
    return [Scenario(name, risk, cap, gross, leverage)
            for name, risk, cap, gross in profiles
            for leverage in ((1,) if market == 'SPOT' else (1, 2, 3, 5, 10))]


def futures_intents(candles: list[Candle]) -> dict[str, dict[int, Intent]]:
    """Five preregistered symmetric LONG/SHORT models, using closed bars only."""
    result = {name: {} for name in ('trend', 'fast_trend', 'conservative', 'pullback', 'breakout')}
    for index in range(105, len(candles)):
        if index % 64 == 0:
            check_cancel()
        window = candles[max(0, index-249):index+1]
        closes = [c.close for c in window]
        price = closes[-1]
        fast, slow = ema_series(closes, 20)[-1], ema_series(closes, 60)[-1]
        short_fast, short_slow = ema_series(closes, 12)[-1], ema_series(closes, 36)[-1]
        long_slow = ema_series(closes, 100)[-1]
        volatility = atr([c.high for c in window], [c.low for c in window], closes, 14)
        if not math.isfinite(volatility) or volatility <= 0:
            continue
        oscillator = rsi(closes, 14)
        side = 1 if price > fast > slow else -1 if price < fast < slow else 0
        conditions = {
            'trend': side if (side == 1 and 52 <= oscillator <= 72) or (side == -1 and 28 <= oscillator <= 48) else 0,
            'fast_trend': 1 if price > short_fast > short_slow and price > closes[-6] else
                          -1 if price < short_fast < short_slow and price < closes[-6] else 0,
            'conservative': side if (side == 1 and slow > long_slow and oscillator >= 55) or
                                    (side == -1 and slow < long_slow and oscillator <= 45) else 0,
            'pullback': side if abs(price-fast) <= volatility and 40 <= oscillator <= 60 else 0,
            'breakout': 1 if price > max(c.high for c in window[-21:-1]) else
                        -1 if price < min(c.low for c in window[-21:-1]) else 0,
        }
        for name, direction in conditions.items():
            if direction:
                result[name][candles[index].close_time] = Intent(direction, max(2*volatility, .01*price), 2, abs(price/slow-1))
    return result


def simulate(data: dict[str, list[Candle]], intents: dict[str, dict[int, Intent]], scenario: Scenario,
             *, initial_cash: float, fee: float, slippage: float, start: int, end: int,
             market: str = 'SPOT', marks: dict[str, list[Candle]] | None = None,
             funding: dict[str, list[dict]] | None = None) -> dict:
    """One clock, five position slots and one wallet, with next-open fills.

    Futures uses isolated margin; liquidation is a conservative mark-price stress
    model with assumed 1% maintenance, NOT Binance's contract/account brackets.
    Gross exposure is marked at each entry. Leverage never multiplies quantity.
    """
    if initial_cash <= 0 or fee < 0 or slippage < 0 or market not in ('SPOT', 'FUTURES'):
        raise ValueError('Invalid simulation settings')
    if (not 0 < scenario.risk <= .05 or not 0 < scenario.position_cap <= 1
            or not 0 < scenario.gross_cap <= 2 or scenario.leverage not in (1, 2, 3, 5, 10)
            or not 1 <= scenario.max_positions <= 5 or not 0 < scenario.maintenance < 1):
        raise ValueError('Invalid scenario')
    bars = {s: {c.open_time: c for c in rows if start <= c.open_time <= end} for s, rows in data.items()}
    # Only matching bars form a comparable portfolio. Never forward-fill a missing asset.
    times = sorted(set.intersection(*(set(rows) for rows in bars.values()))) if bars else []
    mark_bars = {s: {c.open_time: c for c in rows} for s, rows in (marks or {}).items()}
    funding_events = {s: sorted(rows, key=lambda e: e['time']) for s, rows in (funding or {}).items()}
    funding_times = {s: [e['time'] for e in rows] for s, rows in funding_events.items()}
    if market == 'FUTURES' and (any(s not in mark_bars or any(t not in mark_bars[s] for t in times) for s in bars)
                                or any(s not in (funding or {}) for s in bars)):
        raise ValueError('Futures needs aligned mark history and funding')
    cash = initial_cash
    positions: dict[str, dict] = {}
    pending: dict[str, Intent] = {}
    previous: dict[str, int] = {}
    curve = []
    trades = []
    fees = funding_cost = 0.0
    blocked = {'positions': 0, 'capital_or_exposure': 0}
    peak = initial_cash
    drawdown = 0.0
    max_open = 0
    max_gross_ratio = 0.0

    def equity(prices):
        return cash + sum(p['margin'] + p['quantity']*p['side']*(prices[s]-p['entry'])
                          for s, p in positions.items())

    def close(symbol, price, reason, timestamp):
        nonlocal cash, fees
        p = positions.pop(symbol)
        exit_price = price*(1-p['side']*slippage)
        exit_fee = p['quantity']*exit_price*fee
        gross_pnl = p['quantity']*p['side']*(exit_price-p['entry'])
        balance = max(0.0, p['margin'] + gross_pnl - exit_fee) if market == 'FUTURES' else p['margin']+gross_pnl-exit_fee
        # Isolated loss is bounded by posted collateral, including funding.
        cash += balance
        charged_exit_fee = min(exit_fee, max(0, p['margin']+gross_pnl)) if market == 'FUTURES' else exit_fee
        fees += charged_exit_fee
        trades.append({'symbol': symbol, 'side': 'LONG' if p['side'] == 1 else 'SHORT',
                       'opened_at': p['opened'], 'closed_at': timestamp, 'reason': reason,
                       'net_pnl': round(balance-p['original_margin']-p['entry_fee'], 8)})

    for bar_index, timestamp in enumerate(times):
        if bar_index % 64 == 0:
            check_cancel()
        opens = {s: bars[s][timestamp].open for s in bars}
        # Existing opening gaps are processed before new entries release/reuse capital.
        for symbol, p in list(positions.items()):
            price = opens[symbol]
            if market == 'FUTURES':
                mark_open = mark_bars[symbol][timestamp].open
                if p['margin']+p['quantity']*p['side']*(mark_open-p['entry']) <= p['quantity']*mark_open*(scenario.maintenance+fee):
                    close(symbol, mark_open, 'LIQUIDATION_STRESS', timestamp)
                    continue
            if p['side']*(price-p['stop']) <= 0:
                close(symbol, price, 'STOP_GAP', timestamp)
        candidates = sorted(pending.items(), key=lambda pair: (-pair[1].score, pair[0]))
        pending = {}
        for symbol, intent in candidates:
            if symbol in positions or (market == 'SPOT' and intent.side != 1):
                continue
            if len(positions) >= scenario.max_positions:
                blocked['positions'] += 1
                continue
            available_equity = max(0.0, equity(opens))
            entry = opens[symbol]*(1+intent.side*slippage)
            loss_unit = intent.distance + entry*(2*fee+2*slippage)
            gross = sum(p['quantity']*opens[s] for s, p in positions.items())
            notional = min(available_equity*scenario.risk/loss_unit*entry,
                           available_equity*scenario.position_cap,
                           max(0.0, available_equity*scenario.gross_cap-gross),
                           max(0.0, cash)/(1/scenario.leverage+fee))
            if notional <= 1e-9 or available_equity <= 0:
                blocked['capital_or_exposure'] += 1
                continue
            quantity = notional/entry
            margin = notional/scenario.leverage
            entry_fee = notional*fee
            cash -= margin+entry_fee
            fees += entry_fee
            positions[symbol] = {'quantity': quantity, 'side': intent.side, 'entry': entry,
                                 'stop': entry-intent.side*intent.distance,
                                 'target': entry+intent.side*intent.distance*intent.reward,
                                 'margin': margin, 'original_margin': margin, 'entry_fee': entry_fee,
                                 'opened': timestamp}
            max_open = max(max_open, len(positions))
            max_gross_ratio = max(max_gross_ratio, (gross+notional)/available_equity)
        for symbol, p in list(positions.items()):
            candle = bars[symbol][timestamp]
            stop_touched = candle.low <= p['stop'] if p['side'] == 1 else candle.high >= p['stop']
            target_touched = candle.high >= p['target'] if p['side'] == 1 else candle.low <= p['target']
            if market == 'FUTURES':
                left = bisect_left(funding_times[symbol], candle.open_time)
                right = bisect_right(funding_times[symbol], candle.close_time)
                for event in funding_events[symbol][left:right]:
                    if candle.open_time <= event['time'] <= candle.close_time and event['time'] >= p['opened']:
                        charge = p['quantity']*event['mark']*event['rate']*p['side']
                        # OHLC cannot establish whether an intrabar stop preceded funding.
                        if stop_touched or target_touched:
                            charge = max(0.0, charge)
                        actual = min(charge, p['margin'])
                        p['margin'] -= actual
                        funding_cost += actual
                mark = mark_bars[symbol][timestamp]
                worst = mark.low if p['side'] == 1 else mark.high
                collateral = p['margin']+p['quantity']*p['side']*(worst-p['entry'])
                if collateral <= p['quantity']*worst*(scenario.maintenance+fee):
                    # Any mark liquidation touched takes priority under unknown OHLC ordering.
                    close(symbol, worst, 'LIQUIDATION_STRESS', candle.close_time)
                    continue
            if stop_touched:
                close(symbol, p['stop'], 'STOP', candle.close_time)
            elif target_touched:
                fill = max(candle.open, p['target']) if p['side'] == 1 else min(candle.open, p['target'])
                close(symbol, fill, 'TARGET', candle.close_time)
        closes = {s: (mark_bars[s][timestamp] if market == 'FUTURES' else bars[s][timestamp]).close for s in bars}
        value = max(0.0, equity(closes))
        peak = max(peak, value)
        drawdown = max(drawdown, 1-value/peak)
        curve.append({'time': max(bars[s][timestamp].close_time for s in bars), 'equity': round(value, 6)})
        for symbol in bars:
            current = bars[symbol][timestamp]
            # Next-open entry requires genuinely adjacent bars; gaps invalidate pending signals.
            signal = intents.get(symbol, {}).get(current.close_time)
            if signal and symbol not in positions:
                pending[symbol] = signal
            previous[symbol] = current.close_time
        if timestamp != times[-1]:
            next_time = times[bar_index+1]
            pending = {s: intent for s, intent in pending.items() if previous[s]+1 == next_time}
    if times:
        for symbol in list(positions):
            candle = bars[symbol][times[-1]]
            close(symbol, candle.close, 'END_WINDOW', candle.close_time)
        curve[-1]['equity'] = round(max(0.0, cash), 6)
        drawdown = max(drawdown, 1-max(0.0, cash)/peak)
    step = max(1, math.ceil(len(curve)/120))
    sampled = curve[::step]
    if curve and (not sampled or sampled[-1] != curve[-1]):
        sampled = (sampled[:119]+[curve[-1]])
    return {'method': 'joint_execution_shared_cash', 'market': market,
            'profile': scenario.name, 'leverage': scenario.leverage, 'initial_cash': initial_cash,
            'net_return_pct': round((cash/initial_cash-1)*100, 6), 'ending_equity': round(cash, 6),
            'max_drawdown_pct': round(drawdown*100, 6), 'closed_trades': len(trades),
            'fees': round(fees, 6), 'funding_cost': round(funding_cost, 6),
            'liquidations': sum(t['reason'] == 'LIQUIDATION_STRESS' for t in trades),
            'max_open_positions': max_open, 'max_entry_gross_equity_ratio': round(max_gross_ratio, 6),
            'limits': {'positions': scenario.max_positions, 'risk_pct': scenario.risk*100,
                       'position_pct': scenario.position_cap*100, 'gross_pct': scenario.gross_cap*100},
            'blocked_entries': blocked, 'bars': len(times), 'curve': sampled,
            'trades': trades, 'automatic_promotion': False}
