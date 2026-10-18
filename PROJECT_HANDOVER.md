# Project Handover — Crypto AI Trader

This is the durable context entry point for a future engineer or AI model taking over this repository.

## Read first

Read, in this order:

1. `AGENTS.md`
2. `PROJECT_HANDOVER.md` (this file)
3. `WORK_CONTEXT.md`
4. `UPDATE_NOTES.md`
5. `BOT_RELEASE_OPERATIONS.md`
6. `BOT_UPDATE_PROGRESS.md`
7. `README.md`
8. `RESEARCH_METHODOLOGY.md` and `STRATEGY_EVIDENCE.md` when changing financial logic

Then inspect current `main`, recent commits, open PRs/issues and CI. Documentation is historical context, not proof that a release is currently published or installed.

## Mission

### Current continuation — 0.10.41 Command Center foundation

Start from main `81ba4366cf587c16cae20d403974a340080c4d10`, 0.10.40,
[PR #117](https://github.com/jlboper/Crypto-BOT/pull/117). Its publication
[39089416208](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416208)
and safety [39089416215](https://github.com/jlboper/Crypto-BOT/actions/runs/39089416215)
succeeded; signed installation was verified 178/178 hashes at 2026-10-18 02:27 UTC.
That is predecessor evidence, not proof of 0.10.41 publication or installation.

Read [COMMAND_CENTER_2_0.md](COMMAND_CENTER_2_0.md) for the audited component map,
typed future contracts, authority levels and phase checkpoints. Candidate 41
reorganizes existing shared-web/Windows presentation only. Seven views retain
current authenticated controls and environment-scoped financial evidence. No new
AI request, capital allocator, reservation or trading admission hook is added.
Guardian Intelligence (phase 2), Capital Manager Shadow (phase 3) and expressly
authorized future Guardian Control are separate from today's pure Observer.
The `ExposureCoordinator` prototype has no production caller; it does not protect
shared account capital. Never enable shared Spot/Pulse funds from that scaffold.

Phase-2 blocker: Guardian's pure function has no E/S, but current snapshot
acquisition constructs `FuturesTestnetLedger`, which can initialize/migrate the
database and set WAL. Implement an explicit ≤1 s read-only adapter before frequent
Guardian supervision; preserve each source timestamp because multi-ledger reads
are not one atomic transaction. Do not claim an exact cross-engine decision view.

Preserve `AIAdvisor`: Spot ALLOW/REJECT/REDUCE, Futures ALLOW/REJECT. Individual
review and all existing deterministic limits remain; protection/recovery must not
depend on Guardian or AI. No autonomy level, risk state, NL query service, LIVE
executor or counterfactual effectiveness claim is implemented by this foundation.
Each later phase needs its own implementation, tests, publication/signature,
installed inventory and operating evidence. Future level changes require owner
authorization and validation; routine signed-release policy remains unchanged.

### 0.10.40 closed-minute diagnostics — historical preparation record

Based on verified signed/installed 0.10.39 main
`2328f2959dc9b4fb939e889519b59a19e5a58423`, 176/176 hashes. Publication
39070205949 and safety 39070205944 succeeded; agent matched 11/11 modules and
four observed Quant ticks stayed fresh (maximum observed age 60.85 s).
Candidate 0.10.40 addresses observed gapped
StatArb snapshot history with a separate append-only store of up to 500 closed
Spot minute bars per BTC/ETH/SOL refresh. Preserve each bar's first actual receipt
and decision-cutoff availability. Never interpolate old snapshots, rewrite their
gaps, use an open bar or treat its earlier close as earlier local knowledge.
These are retrospective diagnostics, not prospective OOS/backtest validation.
StatArb entries stay blocked; Shadow, risk and Guardian Observer authority remain.
Batch premium-index requests retain the existing 15-request/minute ceiling.
Full suites/CI, publication/signature and installed evidence for 0.10.40 are pending.

### 0.10.39 signer availability — preparation record

Main 0.10.38 `a94f1124d57439e90620f4b2d5c02cbb07f53f58` passed CI, but
publication attempts 1/2 failed with 403 `publisher_revision_unavailable`.
No signed/installed 0.10.38 is verified; Windows remains on verified 0.10.37,
176/176 hashes. The underlying GitHub HTTP cause, including quota, is unconfirmed.
Candidate 0.10.39 adds sanitized diagnostics and bounded availability retries
using the same manifest/OIDC token with at most 105 seconds of cumulative backoff
and seven requests with 30-second timeouts. All OIDC,
authorized workflow, exact current-main and deployed-revision checks remain.
Superseded or invalid identities never become retryable authorization successes.
Retain the 0.10.38 cadence fix and all financial state. Full checks, CI, protected
publication/signature and installed audit of 0.10.39 are pending separately.

### 0.10.38 cadence — preparation record

Version 0.10.37 main `3b02326c435acf3c9c666940a90923908e9bab64` was observed
signed and installed with 176/176 hashes. Post-install observation found Quant's
start-anchored scheduler could hit its strict 60-second reference cache slightly
early and reuse aging data. Version 0.10.38 schedules 60 seconds after completion;
it does not weaken the 90-second freshness gate or increase the API budget.
Slow/failed sources still degrade explicitly. Preserve all ledgers/journals and
existing protections; this changes no strategy, risk or execution authority.
Full checks, CI, publication/signature and installation of 0.10.38 remain pending.

### 0.10.37 implementation — preparation record, four engines

Verified predecessor: 0.10.36 main `1bb77fad1a490472907ce29591e0b1075d3e7ba3`,
PR #113, signed and installed 167/167 hashes. Version 0.10.37 is preparation only
until its own full suites, CI, main publication, signature and installed audit pass.
See `FOUR_ENGINE_EXPANSION.md` for Quant's independent Shadow ledger/service,
two-leg costs, funding provenance, entry-loss latches and strict execution block.
Funding Carry may open hypothetical pairs; StatArb remains an exploratory screen
with entries blocked pending independent calibration. Guardian remains Observer
without veto/reservations. Public Futures prices are reference observations, never
Demo fills. No trading-account client, paid provider or AI call is added by Quant.

Keep `data/quant-shadow.db`, source evidence, journals, hypotheses and pause/kill
state across updates/recovery. Unknown or late funding must not become income or
a zero valuation. Global and per-engine data remain separate; no actual shared
capital is allocated. Pause controls carry empty authenticated requests through
the existing agent; remote Quant capability is distinct from Spot control rights.
Never start another trading process to refresh the four-card Windows indicator.

### Third engine introduced by 0.10.31

Version 0.10.34 expands the reviewed Shadow observation universe to ten eligible
nonstable Binance Spot USDT assets with a frozen dated cap selection, five primary
RSS providers and deterministic candidate priority. Old journal/wallet survives an
audited additive hypothesis transition; risk/cost changes remain rejected. Native
folds compact long portal sections. The owner next requested Guardian Observer
and Quant Arbitrage; see `FOUR_ENGINE_EXPANSION.md`, with no veto/promotion implied.

AI Market Pulse observes public BTC/ETH/SOL trades, depth and bounded official
events inside the existing supervised process, after signed activation. It owns
`data/market-pulse.db` and an independent pause marker; `market-pulse-ai.db`
persists its separately capped model attempts. It is strictly SHADOW with no
broker or execution/promotion toggle. See `MARKET_PULSE.md` for hypotheses,
financial limitations, provider costs, research and promotion requirements.
Never combine its hypothetical capital/results with Spot Testnet or Futures Demo.
The shared-account coordinator is preparation only; existing Spot does not use
its reservation protocol. Therefore sharing Testnet capital remains blocked.
The optional remote projection and controls must evolve with the Worker validator.
Release 0.10.31 was observed signed and installed with 160/160 hashes on 2026-10-16.
Version 0.10.32 corrects the Ethereum RSS URL to its official direct `/en/feed.xml`
destination; redirected feeds remain rejected. Always verify the current release,
installation and source freshness independently.

Crypto-BOT is a safety-first crypto trading research and execution project. Its purpose is to test systematic strategies with explicit risk controls and strong recoverability before any consideration of production capital.

The current architecture intentionally separates:

- **Spot Testnet**: primary multi-asset test environment.
- **Futures Demo**: separate LONG/SHORT forward test with its own ledger, journal, risk controls and kill switch. Version 0.10.27 observes fifteen USDT perpetuals, allows up to ten positions, and sizes against 300 USDT gross exposure and 7.5 USDT estimated loss-to-stop (including cost reserve). Confirmed entries alternate 1x/2x/3x without multiplying quantities; actual fills/gaps can exceed pre-submit estimates. Expanded open state prevents incompatible code restoration.
- **PAPER**: regression, CI and technical fallback.
- **Market Pulse / Quant SHADOW**: separate hypothetical ledgers; no exchange
  execution. Quant's 0.10.40 foundation is installed/verified; current liveness
  and data quality still require fresh runtime evidence. StatArb remains blocked.
- **LIVE**: intentionally not implemented. Never infer that observed profitability authorizes production trading.

## Architectural invariants

- One supervised trading process; do not create a second engine accidentally.
- Spot and Futures remain financially and operationally separate.
- SQLite ledgers, journals, kill switches and rollback state are persistent assets; visual cleanup must never delete them.
- OpenAI acts only as a final risk gate for candidate entries. It must never create a trade by itself, increase risk, remove stops, or block protective exits/recovery.
- Secrets stay outside Git and outside shared backups.
- Local and remote portal use the same `web/` assets.
- Signed updates, anti-downgrade sequence, health checks and rollback are part of the safety architecture, not optional convenience.
- Release state is always distinguished as **prepared → merged → published/signed → installed/verified**.
- Changes to strategy/risk require evidence; operational/security fixes may happen immediately.

## Why the project looks this way

The project evolved from PAPER-only experimentation into a supervised Windows installation with a private remote portal, signed updates, Spot Testnet and a separate Futures Demo forward test. Several design choices exist because earlier approaches exposed failure modes:

- Remote-agent continuity used to depend too heavily on a Windows/PowerShell chain. The current 0.8.13 architecture runs the scheduled remote agent directly with `pythonw.exe` and requires repeated healthy heartbeats after self-heal.
- Runtime ambiguity previously caused updater/agent import failures. The updater now reuses the supervisor's Python runtime.
- Portal/local UI divergence was deliberately removed; there should be one shared interface.
- Testnet and PAPER histories are intentionally separate to avoid contaminating financial interpretation.
- Futures was promoted from smoke testing into a persistent forward test but remains isolated from Spot and from any LIVE path.

See `UPDATE_NOTES.md` for the detailed chronological record.

## Mandatory check after the 0.10.14 agent incident

Read the 2026-10-03 incident in `PROJECT_HISTORY.md` before changing the independent supervisor. The signed bot installation and the scheduled agent's `WorkingDirectory` are separate roots: a dependency present in the bot can still be absent from the agent. New supervisor imports must appear in both `scripts/refresh_independent_agent.py::MODULES` and `scripts/windows_agent.py::SUPERVISOR_MODULES`. Preserve the inventory-parity test and the real refresh/import test in `tests/test_agent_refresh.py`; imports must succeed from the refreshed root under isolated Python without the source checkout.

For a connection failure, inspect the existing scheduled task's root and `data/remote-status.json` (`sync_ok`, `error_type`, `at`, `last_success`). Task state `Running`, copied files and a version label do not prove connectivity. Repair success requires two distinct fresh successful syncs and no `SUPERVISOR_UNAVAILABLE` degradation. A dependency failure may block startup recovery before optional-metadata fallback runs; restarting the same incomplete agent cannot repair its files.

Recover missing code only from a committed signed installation with matching version, anti-downgrade sequence and expected SHA-256 inventory. Stop/restart only the existing agent task; preserve the engine, journals, credentials and financial data. Fail closed if those checks disagree. Two tray icons are not proof of two trading engines. An already running old indicator keeps old code after an update; use **Salir del indicador**, then reopen it once to load the 0.10.15 ownership guard.

Protected publication of 0.10.15 was verified in GitHub. After the verified dependency recovery, the owner reported installation of 0.10.15 and restored connection. That report does not independently verify two fresh heartbeats, a single indicator or native exchange protection; collect those separately when operational evidence is available.

## Current decision posture

Version 0.10.14 implements native protection in both Testnet motors. `native_protection.py` owns durable Spot OCO and Futures conditional-order journals, queries ambiguous submissions by client identity, reconciles native executions before ordinary close/open logic, and retains journals until sibling cleanup is confirmed. Integration support is separate from per-position ARMED evidence. Preserve journals across updates; code lacking native protocol 1 must not resume while native reconciliation remains pending. Trailing OCO replacement is cancel/confirm/create, not atomic. Existing histories remain; `native_protection_started_at` marks the new observation phase. LIVE remains blocked and real Demo behavior must be observed after installation.

The present phase is observation, stability and evidence collection. Avoid changing strategy, leverage or risk because of a few days of results. The project should accumulate enough clean forward-test data to support a later review.

A future decision to use real funds must be a separate project phase with explicit design and safety review. It must not be activated by a version bump, a configuration toggle, an AI recommendation or a good backtest.

## Future ideas already considered

These are ideas, not commitments:

- Longer Spot vs Futures forward-test comparison with comparable scorecards.
- Observe native protection during Demo operation, including offline fills and reconnection.
- Continued hardening of Windows supervisor/recovery and host portability.
- Migration to another Windows PC, Linux host or managed environment without changing trading semantics.
- Android/mobile experience for monitoring and alerts, with independent mobile authentication; never reuse the Windows device credential.
- Better notifications and operational alerting.
- Research strategy promotion only through the existing evidence pipeline.
- Eventual production-capital architecture only after explicit review, with separate credentials, limits and deployment path.

When implementing any old idea, first verify it is still appropriate against current code and current owner intent.

## Handover checklist for a future AI

Before proposing changes:

1. Identify the exact current version and commit on `main`.
2. Inspect the most recent release notes and recent commits.
3. State what is code, what is published, and what is actually installed separately.
4. Inspect tests and CI before changing architecture.
5. Preserve all safety invariants above.
6. Do not expose or request secrets in chat if a secure local configuration path exists.
7. Prefer a small reversible PR over a broad rewrite.
8. Record meaningful architectural decisions in this file or `PROJECT_HISTORY.md`, and implementation details in `UPDATE_NOTES.md`.

## Reconstructing elsewhere

See `PORTABILITY.md` and the bootstrap scripts. A new host should be reproducible from:

- approved GitHub code/release,
- separately transferred secrets,
- separately restored persistent state if desired,
- host-specific supervisor setup.

The current machine must never be the only place where knowledge required to operate or recover the project exists.
# 0.10.35 prepared — Guardian Observer

Main0.10.34 (06de9109a0ae49ffbdb5f94bc6310a9239f421fc) was published/signed and
installed162/162 with native Futures protections and fresh authenticated device
sync. Next PR adds pure read-only Guardian diagnostics and optional four-engine
contracts. Quant remains NOT_STARTED; four-card UI and Quant Shadow follow in
separate PRs. Do not call Observer from financial cycles or treat it as allocation
enforcement. Verify prepared/merged/published/installed independently.
# 0.10.36 prepared — four-card shared UI and Windows

Based on merged0.10.35 maincf3eec5a9e310f4162e0b9edcd2c9a2f4dc2f9e6. Portal and
Windows now represent four identities plus a separate Observer, with no invented
Quant performance. Quant simulation and Guardian Control remain future stages.
Reload only the indicator after installed signed-inventory verification; never
start another trading engine to update its appearance. Keep release states explicit.
