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
