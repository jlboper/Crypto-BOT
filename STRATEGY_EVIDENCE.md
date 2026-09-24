# Strategy evidence and route toward real capital (PAPER 0.6.10)

## What the system actually does

The operating engine is a single long-only Binance Spot **PAPER** strategy:
EMA 20/50 trend, RSI, breakout, volume and momentum score, with a BTC regime
penalty. AI can reject or shrink candidates; ATR stops and portfolio caps
remain in force. The five historical profiles are research comparisons, not
five operating bots. No profile is promoted or reparameterized automatically.

The owner has separately inspected the installed Windows PAPER scorecard in
read-only mode. This source copy still contains **no operating account history**.
The observed historical study did not qualify any of its five assets, and its
five-asset universe does not cover every PAPER trade. The 30-day observation
and matched BTC benchmark windows need additional genuinely new data.

## Evidence informing this iteration

- [Drogen, Hoffstein and Otte, Cross-sectional Momentum in Cryptocurrency
  Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4322637):
  motivation for comparing momentum across crypto assets. Their setting and
  universe differ from this single account; reported returns are not a forecast.
- [Zarattini, Pagani and Barbon, Catching Crypto Trends](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907):
  trend following and transaction costs over a broad historical crypto universe.
  Survivorship and selection assumptions need checking for our smaller universe.
- [Bysik and Ślepaczuk, Machine Learning-Based Bitcoin Trading Under Transaction
  Costs](https://arxiv.org/abs/2606.00060): hourly walk-forward forecasting;
  naive signals can fail after costs while cost-aware filters work for selected
  configurations. Its model and timeframe do not validate this 4-hour bot.
- [Binance Spot symbol filters](https://developers.binance.com/docs/binance-spot-api-docs/filters):
  real order quantities and notionals must satisfy dynamic exchange filters.
  The current PAPER simulator does not execute or reconcile exchange orders.

Books, videos and social posts are useful for ideas, but popularity and
unverified performance screenshots cannot prove an advantage after costs. The
research profiles already cover trend, momentum, pullback and mean reversion;
we are measuring these before expanding the search space.

## Changes and interpretation

Historical candidates must now beat cash **and** a matched, net-of-costs
buy-and-hold of the **same asset** in their development out-of-sample windows,
and beat that asset in the reserved last window. Existing requirements for trade count, cost doubling,
stability and data quality still apply. Repeatedly inspecting that last window
consumes its independence; future PAPER observations are still necessary.

The portal computes an additional matched BTC comparison using the PAPER fee
and slippage on entry and exit. It does not rebalance BTC or measure equal risk:
BTC is invested 100%, while the bot can hold cash. Historic periods before
BTC quotes were recorded are not fabricated. Cash deposits and withdrawals
have no dedicated ledger, so even a positive comparison is not conclusive.

The daily 90-day cleanup covers only signals, AI reviews, events and entry
attempt claims (plus, since 0.6.11, candidate order preflight diagnostics).
It also runs during a kill switch or risk halt once prices and
portfolio state have been checked. Equity, BTC observations, trades, open
positions, backups and signed releases are not deleted by this change.

The 0.6.11 PAPER preflight checks already fetched Binance exchangeInfo filters
for candidate quantity steps and minimum/maximum estimated MARKET notional.
It **does not** change PAPER quantity, allow exchange orders, or certify that
an order will be accepted. MARKET notional can depend on a reference or
weighted average price unavailable to this check; account balances, latency,
duplicate protection and fills still require separate Testnet work.

## Decision gates still open

1. Verify the actually installed signed version and the portal's entire PAPER
   scorecard, including how many of the 30 days and 30 closed trades exist.
   If there are too few trades, wait for genuinely new observations; do not
   reduce thresholds merely to reach a launch date.
2. Compare net PAPER change with cash and matched BTC, inspect drawdown, cost
   sensitivity and performance by asset. Treat a historical backtest as a
   hypothesis, even when every research gate passes.
3. Test exchange symbol filters, fees, order lifecycle, restarts, duplicate
   protection and account reconciliation on Spot Testnet with read-only and
   synthetic checks before enabling any orders. Neither Testnet execution nor
   live order placement is implemented by this release.
4. Set a separate explicit authorization and a small capital cap only after
   the above evidence and operational checks. No result guarantees returns.
