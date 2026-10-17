# Four engines and Portfolio Guardian — approved staged continuation

Owner request received 2026-10-16 after installed 0.10.33. Finish the pending
ten-asset/five-source Pulse and collapsible portal release before starting this
work from updated main. Existing Spot Testnet/Futures Demo and Pulse Shadow remain
separate and supervised; no duplicate engine, data reset or risk increase.

1. Guardian Observer and extensible four-engine contracts: scoped gross/net
   exposure, capital/reservations, concentration/conflicts, data freshness and
   deterministic alerts. Observer cannot veto or raise existing limits. Missing
   evidence remains unknown, not zero. Independent environments never form one
   real portfolio. Native stops/reconciliation never depend on Guardian/AI.
2. Four cards, Guardian view, Quant Funding Carry/Statistical Arbitrage sections,
   shared responsive web assets and Windows states. Until initialized, Quant must
   explicitly show NOT_STARTED, with no invented performance or enabled execution.
3. Quant Shadow only: separate virtual capital/journal, coherent two-leg costs and
   residual risk; observed funding is distinct from projected/settled simulation.
   Funding/hedge timing, basis, margin, liquidity and adverse sign changes matter.
   BTC/ETH/SOL pair research must test cointegration/stability/structural breaks;
   correlation alone never qualifies convergence. No claimed atomic exchange hedge.
4. Historical/OOS/forward evaluation, conservative stress and restart/update
   recovery. No automatic promotion or Guardian control activation. Both require
   separate review/authorization and verified common reservation/reconciliation.

Each stage requires Python/Node/Windows/Linux checks, normal PR/main publication,
Ed25519 signature, installed inventory and current operating-health evidence.
Document implemented/tested/pending states separately. LIVE remains absent.

## Stage 1 — 0.10.35 implementation

Pure bounded Observer consumes the existing credential-free dashboard evidence;
it has no broker, database, filesystem or network dependencies. Four separate
scopes retain environment identity, gross/net notional, priced/unpriced inventory,
nominal distance to stop, capital freshness, descriptive concentration, native
protection status and overlap alerts. Leverage does not multiply notional.
Futures cost-inclusive existing budget stays distinct from nominal stop distance.
Unknown or stale observations remain null; no aggregate real-wallet total exists.

The optional remote contract includes `portfolio_guardian`, `engine_catalog` and
`quant`. Quant is strictly NOT_STARTED; no wallet, worker or orders are created.
Authenticated local/remote `GET /api/platform` returns these identities and
diagnostics. Local projection caches for ten seconds to bound refresh cost.
Optional failures degrade diagnostics while preserving the existing heartbeat,
signed updater and financial engines. Guardian is never called by trading cycles.

Reservations/admission, correlation, daily/weekly losses, drawdown and liquidation
modeling are explicitly unavailable at this stage. Observer does not implement
shared-capital enforcement or allocation journals; those require a separately
validated Control phase. It cannot veto, reserve capital or increase permissions.
The four-card web/Windows view, Quant Shadow and statistical evaluation remain
separate subsequent PRs. No automatic strategy promotion or Testnet activation.

Observed Pulse freshness fix in the same continuity stage: provider timestamps
can lead Windows within the already accepted five seconds. Receipt must precede
decision and expire independently; the selected price must also be recent.
Future buckets are excluded and the existing 80% time coverage gate remains.
Sparse trading can therefore keep an asset incomplete; no forced entry or
fabricated statistical confidence fills that gap.

## Stage 2 — 0.10.36 shared portal and Windows app

Four consistent overview cards preserve the existing identity and use a responsive
4/2/1 layout. Guardian has scoped exposure/budget, overlap/alert and data-quality
folds. Quant has Funding Carry and Statistical Arbitrage folds, explicitly not
started, with unknown finances and unavailable execution/promotion controls.
The comparison includes a fourth unavailable cohort, never an invented return.
Twenty-one long detail groups can collapse; navigation opens the correct group.

The Windows indicator uses four compact cards in two rows, read-only asynchronous
optional platform diagnostics, Guardian status and direct portal links. Process
ownership, startup, watchdogs, update/recovery and engine controls are preserved.
PAPER labels simulated protections; Testnet retains native confirmation evidence.
Source installation and a running indicator are distinct: verify the signed hashes
before reopening the existing indicator to load its new layout. No extra trading
process is created. Missing/stale optional evidence does not imply engine failure.

Stage 2 was observed signed and installed as 0.10.36, main
`1bb77fad1a490472907ce29591e0b1075d3e7ba3`, PR #113, with 167/167 file hashes.
This is source-installation evidence; an offscreen synthetic component render
does not prove the actual desktop window was captured.

## Stage 3 — 0.10.37 Quant Shadow candidate

`trader/quant_shadow.py` runs as one optional service inside the existing signed,
supervised process. It has no account-executor dependency or exchange-order path.
It persists its own `data/quant-shadow.db`, hypotheses, virtual wallet, two-leg
positions, costs, decisions, source evidence, funding receipts, equity and journal.
Lease/ownership recovery, idempotent events, independent pause/kill and isolated
provider failures preserve the other engines. A missing database stays NOT_STARTED;
an unreadable ledger is unavailable, never a fabricated zero wallet.

Anonymous allowlisted Binance Spot/Futures reference GETs observe BTC/ETH/SOL,
depth, basis, premium/funding and historical funding schedules. Public production
prices are reference data, never Testnet/Demo fills. Evaluation is once per minute,
freshness is 90 seconds, transport/history are bounded and rate limits back off.
No new credential, paid subscription, model call or GPU dependency is introduced.

Funding Carry evaluates hypothetical Spot LONG/Futures SHORT pairs against
independent quantity, spread, depth, timing, basis, historical adverse funding,
fees/slippage, collateral and stress checks. An observed rate and a conditional
projection are distinct from an authoritative historical event applied once as
`SETTLED_SIMULATION`; none is real income. Missing due funding evidence makes net
valuation/statistics unavailable. Each leg has costs; failure of a second leg has
a conservative simulated unwind. The hedge is never claimed atomic.

Initial virtual capital is 1,000 USDT, at most two pairs/four legs, 15% gross
exposure and 0.25% estimated risk per pair, subordinate to existing global bounds.
Quant's own daily/weekly entry-loss latches are 1%/2%; baselines use the first valid
ledger equity within each UTC period, possibly after midnight. Unknown valuation
blocks entries. Pauses and loss latches preserve hypothetical protective exits.
The 80% virtual-collateral stress exit and extra simulated stress cost are research
proxies, not a Binance liquidation model, maximum-loss or intrabar-fill guarantee.
Spot/Futures risk settings are unchanged; no actual shared capital is allocated.

StatArb calculates aligned BTC/ETH/SOL pair diagnostics, train/holdout stability,
z-score, residual unit-root screen, correlation/volatility and structural-break
checks. These are exploratory hypotheses, not independent cointegration proof:
its entries remain blocked, even if a screen looks favorable. Frozen-source replay
uses only information received by the decision cutoff; matching a replay does not
validate profitability, OOS performance or statistical significance.

The shared local/remote portal and Windows app show actual initialized Shadow
state, hypothetical pairs/legs, costs, decisions/journal, market/funding and data
quality. Stale projections mask current valuations. Authenticated pause/resume
uses the existing agent with a dedicated Quant capability; it cannot change mode,
risk or promotion. Guardian observes the fourth separate ledger and still has no
veto, reservations or allocation authority.

Focused checks recorded: 70 core, 59 contract, 31 UI and 20 Windows-asset tests;
PowerShell 5.1 view/render checks also passed. The complete offline/Node suites,
Linux/Windows CI, exact main publication, signature and installed audit are still
pending for this candidate. Prepared is not published or installed.

Stage 4 independent historical/OOS calibration, matched net benchmarks and longer
forward evidence remain pending. Guardian Control and new Testnet execution still
require separate validation and explicit owner authorization; LIVE remains absent.
