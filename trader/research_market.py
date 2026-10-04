"""Public historical Futures data, with no signed requests or Demo substitution."""
from __future__ import annotations

import math

from .exchange import BinanceClient, ExchangeError
from .research_runtime import check_cancel


class ResearchClient(BinanceClient):
    def __init__(self, base_url='https://api.binance.com'):
        super().__init__(base_url)
        self.api_key = self.api_secret = ''

    def _request(self, method, path, params=None, signed=False):
        if signed or method != 'GET':
            raise ExchangeError('Research permits unsigned public GET only')
        check_cancel()
        result = super()._request(method, path, params, signed=False)
        check_cancel()
        return result


class FuturesHistory:
    def __init__(self):
        self.client = ResearchClient('https://fapi.binance.com')
        # Historical research never needs the user's account credentials.
        self.client.api_key = self.client.api_secret = ''

    def candles(self, symbol, interval, limit, *, mark=False):
        result = {}
        end = None
        path = '/fapi/v1/markPriceKlines' if mark else '/fapi/v1/klines'
        while len(result) < limit:
            size = min(1000, limit-len(result))
            params = {'symbol': symbol, 'interval': interval, 'limit': size}
            if end is not None:
                params['endTime'] = end
            payload = self.client._request('GET', path, params)
            rows = self.client._parse_candles(payload)
            if not rows:
                break
            result.update((c.open_time, c) for c in rows)
            new_end = min(c.open_time for c in rows)-1
            if end is not None and new_end >= end:
                raise ExchangeError('Futures pagination failed to advance')
            end = new_end
            if len(payload) < size:
                break
        return sorted(result.values(), key=lambda c: c.open_time)[-limit:]

    def funding(self, symbol, start, end):
        events = []
        cursor = start
        while cursor <= end:
            rows = self.client._request('GET', '/fapi/v1/fundingRate',
                                        {'symbol': symbol, 'startTime': cursor, 'endTime': end, 'limit': 1000})
            if not rows:
                break
            for row in rows:
                timestamp, rate, mark = int(row['fundingTime']), float(row['fundingRate']), float(row['markPrice'])
                if not cursor <= timestamp <= end or not math.isfinite(rate) or not math.isfinite(mark) or mark <= 0:
                    raise ExchangeError('Invalid funding event')
                events.append({'time': timestamp, 'rate': rate, 'mark': mark})
            next_cursor = max(e['time'] for e in events)+1
            if next_cursor <= cursor:
                raise ExchangeError('Funding pagination failed to advance')
            cursor = next_cursor
            if len(rows) < 1000:
                break
        if not events:
            raise ExchangeError('Funding history unavailable')
        # Missing large stretches invalidate financial evidence (not replaced with zero).
        if events[0]['time']-start > 24*3600_000 or end-events[-1]['time'] > 24*3600_000 or any(
                b['time']-a['time'] > 24*3600_000 for a, b in zip(events, events[1:])):
            raise ExchangeError('Incomplete funding history')
        return events
