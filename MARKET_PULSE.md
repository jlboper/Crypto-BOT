# AI Market Pulse — 0.10.34

## Scope and safety

Market Pulse is a third observer inside the existing owned TradingEngine process.
It starts in `run_forever` after the signed updater's activation barrier. It never
imports a broker or accepts account credentials. There is no order submission,
SHORT execution, PAPER activation, Testnet promotion or LIVE implementation.
`config.market_pulse.mode` accepts only `SHADOW`. Existing Spot/Futures signals,
position limits, leverage, recovery and native exchange protections are preserved.

`data/market-pulse.db` is an independent WAL SQLite wallet and journal. Its initial
1,000 USDT is hypothetical; it is never added to Spot Testnet or Futures Demo cash.
The signed package excludes data and credentials. An older restored release ignores
the new ledger; it does not convert or delete it. Normal updates retain journals.
No Windows scheduled task, listener exposed to the Internet or paid infrastructure
is added. Threads perform observation only, owned by the one supervised process.

## Initial observation

BTC, ETH, BNB, XRP, SOL, TRX, ZEC, HYPE, DOGE and LINK use one combined anonymous Binance market-data-only
WebSocket: aggregate trades and top-five partial order books. TLS and WebSocket
upgrade/control frames are verified. Connection interruption uses bounded backoff;
REST aggregate-trade/depth reads recover observations when possible. A recovery
page does not prove missing history was complete. Trade-ID/time gaps, stale depth,
missing BTC context and incomplete baseline block hypothetical entries.

Indicators use at most 601 one-second buckets per asset: 1/5-minute price change,
relative volume, standardized anomaly, momentum/acceleration, realized volatility,
spread, partial liquidity and imbalance. Evaluation is throttled to five seconds;
protective simulation is checked directly on market arrivals. Public production
quotes are observation data, never permission to use a production account.

Score contributions (momentum 25, participation 25, anomaly 15, BTC context 10,
liquidity 10, event agreement 15) and score 65 are preregistered hypotheses. They
are neither fitted nor statistically validated. Independent price/volume/liquidity
confirmation, cost coverage and anti-chasing gates remain authoritative. News alone
cannot create a BUY. Negative, uncertain and rumor information cannot override gates.

Ethereum Foundation, Bitcoin Core, Kraken, Federal Reserve monetary releases and
SEC press releases are bounded anonymous RSS sources, one request/minute overall
and approximately five minutes per source. Individual health and failures remain
visible. Primary/regulatory publications are not comprehensive breaking news;
CryptoPanic, CoinGlass and LunarCrush are not configured. Publisher attribution is
not proof that an article's economic prediction is true. Titles are normalized,
deduplicated and classified conservatively; older than 30 minutes, future-dated,
unverified reports and rumors cannot supply positive confirmation. Publication,
receipt, review and decision evidence are retained. External text never runs code,
controls settings, supplies tools, changes hosts or creates order instructions.
Kraken opinion/promotions/third-party reports cannot provide official directional
confirmation. Fed macro context is retained as MARKET and never an asset order.
Cointelegraph, CoinDesk and Decrypt were excluded after current use-term review.

The ten-asset selection uses CoinGecko capitalizations dated 2026-10-16T14:42:58Z,
cross-checked against anonymous Binance Spot USDT TRADING symbols. Stablecoins and
duplicate exposures are excluded; FIGR_HELOC and XMR lack an eligible Spot pair.
This is a frozen, dated selection rather than an automatically changing rank.
Compatible additive expansion records old/new hypotheses without resetting the
ledger or old evidence. Financial hypothesis changes still fail closed. Mixed
three/ten-asset history must not be claimed as an unchanged-universe backtest.
Candidates are ordered by quantitative score, confidence, liquidity and symbol
before allocating the existing three hypothetical slots. Frozen decisions record
rank/pool/rule. Pending model events are bounded and prioritized independently;
this is an initial allocation rule, not proof of an optimal market opportunity.

The owner authorized reuse of the existing OpenAI key for this engine. Only
prefiltered promising/ambiguous credible events enter a separate bounded queue.
The existing configured model interprets `impact/confidence/reason` through the
Responses API strict JSON schema, with local validation and fail-uncertain behavior.
No account details or key values enter model input. `market-pulse-ai.db` claims each
attempt durably BEFORE HTTP: at most six per UTC day, at least 300 seconds apart,
4,096 input-data bytes and 512 output tokens, eight-second timeout, no retries.
Failed/uncertain attempts count. Model interpretation cannot delay protective exits.
AI costs are separate from trading P&L; limits bound calls/tokens, not a provider
billing guarantee. Changing the configured model changes its applicable price.

## Financial evidence and research

Hypothetical BUY/SELL positions and the decision record commit transactionally.
Stops/targets, fees, slippage, spread, exposure, cash and existing positions gate
entries. Estimated risk is at most 0.25% per entry, subordinated to lower existing
global settings; Pulse's exposure/position ceilings are 15%/5% of its fictional
wallet, at most three positions. Exchange matching, latency impact and price gaps
can be worse than the simulation. Pausing entries keeps hypothetical protections
observed. Stale quotes cannot invent protective fills.

The portal exposes archived contemporaneous evidence, a net simulation scorecard,
cash reference and per-asset buy-and-hold diagnostics with explicit comparability
limits. Statistics without qualifying closes are null. Different environments,
periods, capital and methodologies never form one aggregate return.

`replay_decisions(data_dir)` rechecks frozen quantitative scores and timestamps
without any network or later news. It is an audit, not independent OOS validation
or a complete portfolio backtest. Historical tick/news data sufficient to claim an
event backtest are absent. Accumulate prospective evidence first; separate frozen
development/final windows, cost stress, enough closes, overfitting assessment and
the existing promotion pipeline remain required. No positive result auto-promotes.

`exposure_coordinator.py` prepares durable shared-account reservations, explicit
environment/account scopes, duplicate-asset refusal and aggregate cash/risk caps.
It is tested with synthetic reservations and deliberately NOT wired into the
existing Spot broker. Sharing Spot Testnet funds stays blocked until both brokers
use one reviewed reservation/reconciliation protocol, fresh exchange balances and
filters, and the owner separately authorizes promotion. Current Shadow cannot
compete for Spot funds. This is Phase D preparation, not Testnet execution readiness.

## Portal and operations

The same `web/` assets provide three summary cards, seven navigation anchors,
Pulse market/events/opportunities/decisions/financial/health sections and individual
pause/resume controls. The optional remote snapshot is allowlisted, timestamped
and limited to 20,000 characters; old two-engine snapshots remain supported.
History projection can be thinned, never the SQLite history or live safety evidence.
Remote synchronization failure is distinct from observer or trading failure.
Long sections use accessible native folds; navigation opens the target and all
ancestors. Only allowlisted presentation preferences persist in localStorage.
Controls retain authentication, CSRF, fresh-heartbeat, idempotence and Windows job
validation. They cannot change modes, budgets or promotion status.

The Windows manager uses the same three-engine identities in its native overview,
with independent financial/environment labels and bounded asynchronous local API
polling. Existing indicator ownership, process launch/recovery and signed update
actions are preserved. An indicator process already open when code is installed
keeps its old loaded UI: exit the indicator and reopen it once to load this view.
That is separate from the engine's automatic signed rollout.

## Sources and cost review (2026-10-16)

- [Binance market-data-only hosts](https://developers.binance.com/en/docs/products/spot/faqs/market_data_only)
  and [WebSocket streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams):
  anonymous public market data, no new subscription; exchange limits apply.
- [Ethereum Foundation](https://blog.ethereum.org/en/feed.xml) and
  [Bitcoin Core](https://bitcoincore.org/en/rss.xml): public RSS, no new subscription.
- [Kraken Blog](https://blog.kraken.com/feed), [Federal Reserve RSS](https://www.federalreserve.gov/feeds/feeds.htm)
  and [SEC RSS](https://www.sec.gov/files/about/secrss.shtml): direct anonymous feeds
  probed successfully; headlines/attribution only, no full-article scraping.
- [CoinGecko ranking](https://www.coingecko.com/): dated capitalizations cross-checked
  with Binance public exchangeInfo; no new runtime paid ranking service.
- [Cointelegraph terms](https://cointelegraph.com/terms-and-privacy),
  [CoinDesk terms](https://www.coindesk.com/terms) and
  [Decrypt terms](https://decrypt.co/en-US/terms-of-service): current automated/AI
  restrictions exclude these sources from this implementation.
- [OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
  and [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna):
  consulted standard price $0.10/$0.50 per million input/output tokens. Six small
  reviews/day at these limits are approximately below $1/month; actual usage,
  schema overhead, model changes and current billing determine charges.
- [CoinGlass pricing](https://www.coinglass.com/pricing): optional paid API,
  advertised Hobbyist from about $29/month depending on billing. Not activated.
- [CryptoPanic API](https://cryptopanic.com/developers/api/) and
  [LunarCrush API](https://lunarcrush.com/developers/api/pricing): optional account/API
  access; publicly retrieved pages did not establish a reliable applicable price.
  Do not assume free access or create credentials/subscriptions automatically.

Offline tests cover synthetic outages, duplicates, stale data, isolated pauses,
restart/ledger consistency, review errors, caps and portal security/contracts.
Public endpoint probes and CI/runtime installation evidence are recorded separately
in the final delivery. A synthetic restart is not proof of a physical Windows reboot;
long-duration resource/uptime observations and statistical advantage remain pending.
