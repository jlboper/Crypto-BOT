# Project Handover — Crypto AI Trader

This is the durable context entry point for a future engineer or AI model taking over this repository.

### Current checkpoint: installed 43 / Capital Protocol Lab 44 in preparation

Main 43 `e61dd2a6f617cd39e8bd1c69728dc6f63b800401`,
[PR #120](https://github.com/jlboper/Crypto-BOT/pull/120),
[publication 39254593562](https://github.com/jlboper/Crypto-BOT/actions/runs/39254593562)
and [safety 39254593565](https://github.com/jlboper/Crypto-BOT/actions/runs/39254593565)
succeeded on Linux/Windows. Signed installation **188/188** was verified at
2026-10-19 12:53:08 UTC: engine 21084, Spot 2/Futures 4 native ARMED, zero observed
unprotected quantity; agent 21344 synchronized with 11/11 modules. Guardian at
12:54:49 UTC: OBSERVING, four FRESH/complete sources, three distinct assessments
with **3/3 causal replays MATCH**, zero errors and LEVEL 0/all authority false.
Regime was insufficient at that cut. Two legacy FAILED AI attempts have unknown
causes/costs and consume the daily 2/2 budget; never reset them for testing.
Compared financial prefixes/settings and the prefix of 721 existing Guardian
records/two attempts were preserved.

44 adds only the synthetic [Capital Protocol Lab](CAPITAL_PROTOCOL_LAB.md): closed
recipes, new SIM accounts, CLI, bounded RO JSON and shared Research Lab display.
No existing capital, engine candidate hooks, trading or Guardian Control. F3
runtime/common proposal/account adapters remain work, not authorization gates for
routine simulation development. Activating financial control still requires its
separate owner authorization. Before the later mobile compacting change,
local checks passed **850/850 Python**
(181.531 s in `TEST_RESULTS.json`, 2026-10-19 13:19:52.904728 UTC; no failures/errors/
skips, external network blocked, no bot started), **202/202 Node** (69.325 s),
focused UI hardening 84 tests (13.643 s), Windows PowerShell 5.1 lifecycle/view,
portal build and diff. [Draft PR #121](https://github.com/jlboper/Crypto-BOT/pull/121)
exists at head `5138e51a1f37001629ac1420e3b0d7e48a439170`; CI
39259777367/39259777360 passed for that head. A later local UI change keeps
47 folds, with audit initially closed and compact case details; LAB SIM, date,
outcome and essential warnings stay visible. Focused UI 84/84 (7.046 s) and diff
passed after compacting. Visual QA passed on the isolated synthetic preview at
360/768/1366px: no overflow, seven cases, audit/details/keyboard and negative book
verified. Artifacts/measurements are recorded in CAPITAL_PROTOCOL_LAB.md. Final
local suites passed 850/850 Python (171.844 s TEST_RESULTS at
2026-10-19 17:56:01.749748 UTC; runner 171.835 s), 202/202 Node (37.430 s),
build and diff, without failures/errors/skips. New head/CI remain pending;
preview QA is not installed44 evidence. Do not attribute
earlier CI to later changes.
No merge/main CI, publication/signature/install/runtime44 success is claimed.

At 13:18:23 UTC a RO audit verified all **80/80 trade rows and 48/48 receipt rows**
from the signed-43 Spot backup, with zero missing/changed rows and unchanged backup
SHA. See `append-only-backup43-verification.json`. The 43 updater backed up Spot
only; Futures/Pulse/Quant have no corresponding 43 multiledger backup. Earlier
sampled-prefix comparisons remain valid but are not exhaustive pre-43 row checks.

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

### Historical preparation — 0.10.43 Guardian RO WAL corrective

Start from installed main 42 `b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`,
[PR #119](https://github.com/jlboper/Crypto-BOT/pull/119).
[Publication 39181606398](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606398)
and [safety 39181606401](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606401)
succeeded. Audit 2026-10-19 00:42:33 UTC verified Ed25519, 188/188 installed hashes
and five web assets. Engine 3680: Spot 1/Futures 5, native ARMED, zero observed
unprotected quantity. Agent inventory was 9/11 at that cut. Signed refresh at
**00:54:20 UTC** verified agent 21344, **11/11 modules**, sync_ok and two fresh
healthy heartbeats; engine 3680 unchanged, Spot 1/Futures 5 ARMED, zero unprotected
quantity observed.

42 Guardian actual status: PARTIAL, 0/4 sources valid, all UNKNOWN with
WAL_SIDECARS_UNAVAILABLE. One real journal record replays MATCH. A real AI attempt
FAILED without known usage or classified cause. Do not infer quota/credit issues
or claim full acquisition success from installation, replay or synthetic tests.

Corrective branch `fix/guardian-readonly-wal-v01043` must allow normal SQLite
mode=ro/query_only observation when WAL/SHM sidecars have been normally cleaned.
Transient WAL/SHM metadata is allowed; financial DML, constructors, migrations,
immutable copies, stale snapshots and relaxed causal/freshness checks are not.
Test quiet DB/WAL financial preservation and current commits under concurrent
writers. Add a deterministic all-UNKNOWN prefilter before any AI call and safe
bounded error classifications, never provider bodies/headers/secrets. 43 full
Python passed; PR/main CI/publication/signature/install/runtime are pending. 42 test
counts remain historical.

At 00:47:04 UTC, candidate43 read standard SQLite RO backups of all four actual
schemas from temporary copies: FRESH/complete, Spot 1/Futures 5/Pulse 1/Quant 0 and
descriptive SIDEWAYS. No engine/provider/credential loader ran. Copies were removed;
this is actual-schema candidate proof, not installed 43. Focused capture/service
87 PASS and isolated all-UNKNOWN no-AI 1 PASS. Additional 43 results: AI 35 PASS
(6.961 s), Node 180/180 PASS (106.485 s), Windows PowerShell 5.1 lifecycle/view,
portal build and diff PASS. Full offline Python **777/777 PASS**, no failures/
errors/skips, **238.609 s** (`TEST_RESULTS.json`, 00:55:17 UTC), external network
blocked and no bot started. These local results do not establish installed 43.

Keep the four financial ledgers, controls and protections intact. Capital Protocol
Lab remains an external synthetic prototype, excluded from 43. It does not observe
common immutable engine proposals, reserve existing funds or complete phase 3.

### 0.10.42 Guardian Intelligence Shadow — historical preparation record

Start from main `022fb9135d165d5c52f12b65aa9628ab8c1436af`, 0.10.41,
[PR #118](https://github.com/jlboper/Crypto-BOT/pull/118). Its publication
[39134814222](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814222)
and safety [39134814202](https://github.com/jlboper/Crypto-BOT/actions/runs/39134814202)
succeeded; signature/installation matched 178/178 hashes. At 2026-10-18
14:16:30 UTC engine PID 19240 retained one Spot/nine Futures positions, native
protections ARMED and no observed unprotected quantity. Agent PID 9372 had fresh
HTTPS sync and 11/11 modules. Compared existing financial rows had zero missing/
changed rows; secrets, risk and hypotheses were preserved. This is dated 41 evidence.

Candidate 42 implements observational Guardian Intelligence inside that process,
strictly SHADOW LEVEL 0. Four read-only acquisition adapters avoid all financial
ledger constructors/migrations; incomplete inventories stay unknown. Each source
keeps its own timestamps, so this is not a globally atomic pre-submit snapshot.
Pure deterministic diagnostics, a descriptive BTC 60m/61-close proxy and a
separate append-only `guardian-shadow.db` journal/replay have no order hooks,
capital reservations, veto or financial control. Preserve `guardian-ai.db` too.

The owner requested Guardian AI and authorized existing-key reuse with a separate
consumption limit. The optional advisory client is wired up to two attempts/day,
one-hour minimum interval, historical 900 s cache, 4,096-byte input, 512 output
tokens and eight-second HTTP timeout, subject to global `ai.enabled`. Its own
durable claims remain consumed after failures/unknown outcomes. Pricing estimates
use the existing verified model; incomplete usage stays unknown and estimated
reserves are not hard billing caps. No actual installed 42 model request has been
verified yet; focused checks used fake transport/credentials. This authorization
is for observation only, not level 1/Control or capital sharing.

Eight closed local browser query intents now explain summary, regime, scoped risk,
conflicts, data quality, original review, limitations and unknown counterfactuals.
They read the displayed assessment, cite its cutoff and included journal identity,
and invoke no API/SQL/tool. Six browser-tab query identities are ephemeral, not
durable audit. General server-side NL/history queries remain pending.

Complete local validation passed **767/767 offline Python tests (361.510 s)**,
**180/180 Node tests (85.515 s)**, Windows PowerShell 5.1 lifecycle/view, portal
build and diff checks. Regressions cover UTC precision, numeric heartbeat metadata
and canonical integer/SQLite-REAL journal hashing without relaxing causal checks.
Browser QA at 1366/360/768 px found no horizontal overflow and exactly one Guardian
workspace; counterfactual queries stayed UNKNOWN and cited real journal identities.
Local logs are `python-full-v01042.log`, `node-full-v01042-final.log` and
`windows-v01042.log` in the isolated command-center work directory.

The 19:10 UTC baseline audit again verified installed 41's 178/178 hashes, engine
19240, agent 13056, one Spot/nine Futures positions, native protections ARMED and
zero observed unprotected quantity. See `COMMAND_CENTER_2_0.md` for typed reports
and future phase-3 design. PR/main CI, publication/signature, installation and
operative verification of 42 remain pending. Individual Spot/Futures AI,
protection, budgets and signed recovery remain authoritative.

### 0.10.41 Command Center foundation — historical preparation record

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
