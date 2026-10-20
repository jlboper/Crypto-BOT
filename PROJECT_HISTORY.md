# Project History and Decision Log

## 2026-10-19 — Guardian acquisition verified; synthetic capital protocol separated

43 main `e61dd2a6f617cd39e8bd1c69728dc6f63b800401`,
[PR #120](https://github.com/jlboper/Crypto-BOT/pull/120), passed Linux and Windows,
was [published/signed](https://github.com/jlboper/Crypto-BOT/actions/runs/39254593562)
and installed **188/188** at 12:53:08 UTC. At 12:54:49 UTC Guardian observed all
four ledgers FRESH/complete; three frozen
replays matched and no authority was enabled. Historical financial rows and
existing Guardian records/two legacy AI attempts remained intact in a 721-record
prefix. Unknown costs and failed AI causes stay unknown; daily 2/2 claims were
preserved, never reset.

44 prepares Capital Protocol Lab as closed synthetic research, separately from
Capital Manager on actual proposals. It uses new SIM cohorts, integer micro-USDT,
transactional reservations and an explicit CLI. GET/sync reads bounded JSON only.
Independent review caught terminal orders reviving after UNKNOWN, balances older
than a financial mutation, and an extra-check parser escape. Prototype fixes have
regressions. This is not global market risk, account reconciliation, financial
authorization or F3 runtime. See [CAPITAL_PROTOCOL_LAB.md](CAPITAL_PROTOCOL_LAB.md).
Before the later mobile compacting change, local44 checks passed 850/850 offline Python (181.531 s in TEST_RESULTS,
2026-10-19 13:19:52.904728 UTC), 202/202 Node (69.325 s), 84 focused UI tests
(13.643 s), PS5.1 lifecycle/view, build and diff. Draft
[PR #121](https://github.com/jlboper/Crypto-BOT/pull/121), head
`5138e51a1f37001629ac1420e3b0d7e48a439170`, passed CI 39259777367/39259777360.
Initial IAB mobile inspection prompted a later local compacting change: 47 folds,
audit initially closed and per-case details folded, with synthetic identity,
date and result still visible. Focused UI 84/84 (7.046 s) and diff passed for
that change. Visual QA passed on the isolated synthetic preview at 360/768/1366px
with seven cases, no overflow and working keyboard/details/audit. Audit collapsed
height fell from 815.9px to 42.53px, bringing the first case from about 1215px to
534px. Final local checks after compacting passed 850/850 Python
(171.844 s TEST_RESULTS at 2026-10-19 17:56:01.749748 UTC; runner 171.835 s),
202/202 Node (37.430 s), build and diff, without failures/errors/skips.
New head/CI remain pending. Earlier CI is not evidence for subsequent
changes, nor preview QA for merge/publication/signature/install44.

The RO preservation audit at 13:18:23 UTC compared all 80 Spot trade rows and 48
receipt rows from the verified 43 backup: zero missing/changed, backup SHA intact
(`append-only-backup43-verification.json`). That updater backed up Spot only.
Prior Futures/Pulse/Quant sampled-prefix matches do not establish preservation of
every pre-43 row; no 43 multiledger backup exists for those sources.

## 2026-10-19 — installed Guardian exposes an idle-WAL acquisition assumption

PR #119 merged as main `b1e065b1c4934eef80cf4a6d39c52bafa1abb5de`.
[Publication 39181606398](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606398)
and [safety 39181606401](https://github.com/jlboper/Crypto-BOT/actions/runs/39181606401)
succeeded. At 00:42:33 UTC, 42 had Ed25519 verification, 188/188 installed hashes,
five matching web assets and engine PID 3680 retaining protected Spot 1/Futures 5,
with zero observed unprotected quantity. Agent inventory 9/11 then awaited signed
refresh. At **00:54:20 UTC**, signed refresh was verified: agent 21344, **11/11**,
sync_ok and two fresh healthy heartbeats; engine 3680 unchanged and Spot 1/Futures
5 remained native ARMED with zero observed unprotected quantity.

Guardian's first real record replays MATCH, but report acquisition is PARTIAL:
all four sources UNKNOWN/WAL_SIDECARS_UNAVAILABLE. Requiring pre-existing WAL/SHM
files was too strict for normal idle SQLite cleanup. No filled-in zero balances
or full operating success is claimed. One actual AI attempt FAILED with unknown
usage/cause; synthetic tests and an unknown error do not diagnose exhausted quota.

Corrective candidate 43 keeps normal mode=ro/query_only transactions, permits
SQLite transient sidecar metadata without financial DML, and rejects immutable
copies or stale snapshot workarounds. Preserve financial data/causal gates and
test concurrent writers. An all-UNKNOWN deterministic gate must avoid unjustified
model calls; diagnostics expose only safe bounded codes. PR/main CI/publication/
installation of 43 are pending. External Capital Protocol Lab work remains
synthetic and separate; it grants no shared-capital or execution authority.

At 00:47:04 UTC a separate candidate43 check read temporary standard SQLite RO
backups of the four operating schemas: all FRESH/complete (Spot 1/Futures 5/Pulse 1/
Quant 0), descriptive SIDEWAYS, without engine/provider/credential initialization.
Temporary copies were removed. Focused capture/service 87 and isolated no-AI 1
tests passed. Additional candidate 43 validation passed AI 35 (6.961 s), Node
180/180 (106.485 s), Windows PowerShell 5.1 lifecycle/view, build and diff. Full
offline Python subsequently passed **777/777, 238.609 s**, without failures/errors/
skips, with external network blocked and no bot started (`TEST_RESULTS.json`,
00:55:17 UTC). These checks do not prove installed 43 acquisition or release.

## 2026-10-18 — Guardian observation gains memory without financial authority (preparation)

The verified 0.10.41 main `022fb9135d165d5c52f12b65aa9628ab8c1436af`
(PR #118) is published/signed/installed 178/178 after successful publication
39134814222 and Linux/Windows safety 39134814202. Its 14:16:30 UTC continuity
audit retained native-protected Spot/Futures positions, fresh independent-agent
sync and compared financial rows without missing/changed records.

Candidate 0.10.42 implements a separate Shadow Level-0 Guardian service. Reusing
the old dashboard helper would instantiate/migrate the Futures ledger, so the
new observer instead uses explicit bounded read-only adapters for all four
sources. First availability, source timestamps and frozen causal evidence remain
distinct; several ledger transactions never become one exact pre-submit view.
Deterministic BTC regime/conflict/risk diagnostics use uncalibrated descriptive
hypotheses and cannot admit orders, allocate capital or certify a complete account.

The owner's Guardian-AI request plus authorized existing-key reuse permits its
own bounded observational budget (up to two attempts/day, also gated by global
AI enablement). Failed/unknown requests keep durable claims; historical cache
annotations remain tied to their original evidence and never alter reports.
This closes the earlier future service-budget checkpoint, not a financial
autonomy transition. Eight closed browser intents now explain the displayed
assessment with cutoff/journal evidence: summary, regime, scoped risk, conflicts,
quality, original review, limitations and unknown counterfactuals. Their six-entry
tab history is ephemeral, not durable audit; no API, SQL or tool is invoked.
General server-side NL/journal queries, Capital Manager and Guardian Control
remain separate phases. No model upgrade, new paid service, LIVE or promotion.

Complete local validation passed 767/767 offline Python tests (361.510 s), 180/180
Node tests (85.515 s), Windows PowerShell 5.1 lifecycle/view checks, portal build
and diff checks. Integration exposed UTC rounding, numeric heartbeat parsing and
integer/SQLite-REAL digest edge cases, now covered without weakening causal checks.
Browser QA at 1366/360/768 px found no horizontal overflow and one Guardian workspace.
The 19:10 UTC predecessor audit again verified 178/178 hashes, engine 19240/agent
13056 and native-protected Spot 1/Futures 9 with zero unprotected quantity observed.
42's PR/main CI, publication/signature and actual installation/usage remain pending.

## 2026-10-17 — Command Center separates intelligence from execution authority

The owner requested CRYPTO-BOT 2.0 with four engines, Guardian Intelligence,
separate Guardian Control and Central Risk & Capital Management. Begin with the
verified 0.10.40 main `81ba4366cf587c16cae20d403974a340080c4d10` (PR #117),
published/signed and installed 178/178 hashes at 2026-10-18 02:27 UTC after
successful publication 39089416208 and safety 39089416215.

Candidate 0.10.41 audits and reorganizes the existing shared interface/Windows
presentation. It introduces no financial hook or Guardian model call. Guardian
Observer remains pure read-only; its capital projection is not an allocator.
The exposure-reservation prototype is not integrated with operating accounts and
cannot establish common admission. Preserve individual Spot/Futures AI semantics,
deterministic risk, native protection, recovery and all persistent state.

Record later Intelligence and Capital Manager as separate Shadow phases before
considering expressly authorized Testnet Control. Every autonomy transition needs
owner authorization, validation and reversible fallback; no level implies LIVE.
Counterfactual outcomes require preregistered comparable evidence, never the sum
of later losses on rejected trades. Architecture and typed design contracts live
in `COMMAND_CENTER_2_0.md`; designed, implemented, tested, published, signed,
installed and operatively verified are independent checkpoints.

## 2026-10-17 — Closed-bar research is not reconstructed forward evidence

Observed Quant snapshot history had persistent gaps: a large total row count did
not establish the contiguous minute window required by StatArb. Waiting alone
would not repair those earlier gaps. The 0.10.40 candidate imports official closed
Spot minute bars into a separate append-only evidence store, preserving first
receipt and replay cutoff. It does not backfill snapshot journals or imply that
the bot knew a historical bar before receiving it. Retrospective train/holdout
diagnostics remain unvalidated research, not prospective OOS or proven profit.
StatArb admission stays blocked; batch reference reads preserve the API ceiling,
Shadow-only authority and existing risk. Based on 0.10.39 main
`2328f2959dc9b4fb939e889519b59a19e5a58423`, subsequently verified signed and
installed 176/176 after successful publication 39070205949 and safety 39070205944.
That predecessor evidence does not establish publication or installation of 0.10.40.

## 2026-10-17 — Signer availability must not weaken source identity

Version 0.10.38 main `a94f1124d57439e90620f4b2d5c02cbb07f53f58` passed CI,
then publication attempts 1/2 failed with `publisher_revision_unavailable` (403).
Its cadence fix is merged but not verified signed or installed; verified Windows
remains 0.10.37 (176/176 hashes). The failure does not yet establish GitHub quota
exhaustion or another specific HTTP cause. Add only sanitized bounded diagnostics
and same-manifest/token availability retries with at most 105 seconds of cumulative
backoff, seven requests and a 30-second timeout per request.
Exact current-main, deployed revision, OIDC and workflow validation still fail
closed on unavailable evidence; superseded or unauthorized publishers remain
rejected. This candidate is 0.10.39, with publication/install verification pending.

## 2026-10-17 — Quant scheduling respects completed reference refresh

After verified signed installation of 0.10.37 main
`3b02326c435acf3c9c666940a90923908e9bab64` (176/176 hashes), actual observation
exposed intermittent aging references. The next tick had been anchored before
the preceding refresh finished, allowing the strict 60-second cache to be reused
just before expiry. The 0.10.38 candidate schedules after completion, preserving
freshness and request limits rather than treating old data as current. Financial
hypotheses, persistent state, protective paths and Shadow-only authority remain
unchanged. This entry is not evidence of 0.10.38 publication or installation.

## 2026-10-17 — Quant enters Shadow; statistical admission stays blocked

After Guardian Observer and the four-card portal/Windows stages, the owner asked
to continue with functional Quant research. The verified 0.10.36 predecessor is
main `1bb77fad1a490472907ce29591e0b1075d3e7ba3`, PR #113, installed 167/167 hashes.
The 0.10.37 candidate adds one supervised optional service and an independent
virtual ledger. It never shares Spot Testnet/Futures Demo funds or submits orders.

Funding Carry may simulate two legs only after deterministic cost, liquidity,
timing, collateral and stress gates. Observed/projected funding is not settled
income; missing authoritative due events keep valuation unknown. Per-leg failures,
loss-latched entry pauses and virtual-margin stress have conservative accounting
without claiming atomic hedging or actual exchange-liquidation fidelity.
Quant's own 1% daily/2% weekly latches use first valid equity within a UTC period,
not a fabricated midnight baseline. Protective hypothetical exits continue.

Statistical pair screens are insufficient to establish cointegration or an edge.
Independent calibration, historical/OOS research and longer forward evidence are
required before even StatArb hypothetical admission is enabled. Frozen-evidence
replay verifies reproducibility, not profitability. Guardian remains read-only;
Control, shared reservations and new Testnet promotion require separate authority.
Publication/signature/installation of 0.10.37 are not implied by this decision log.

## 2026-10-16 — Dated ten-asset observation and broader primary sources

The owner chose ten largest eligible Binance Spot USDT assets by market cap,
excluding stablecoins and duplicate exposures. Freeze the verified selection with
its date; do not silently claim an always-current ranking or retrospectively
reinterpret the earlier three-asset cohort. Additive expansion retains financial
state and records prior/current hypotheses; financial changes remain rejected.
Five permitted public primary/regulatory RSS sources replace the narrow two-feed
coverage. Company commentary is not primary evidence for third-party predictions.
AI remains a separately capped interpreter; deterministic opportunity ordering
does not claim statistically optimal weights or guaranteed profitability.
The owner subsequently requested Quant Arbitrage and Portfolio Guardian. Complete
this pending expansion first, then implement observational coordination with no
veto on existing trading and no new account execution. Preserve one supervised
process and separate fictitious/Testnet/Demo scopes. See `FOUR_ENGINE_EXPANSION.md`.

## 2026-10-15 — Three engines, event-driven Shadow observation

The owner requested a third event/news/market-anomaly engine and a unified
three-bot portal. Version 0.10.31 starts AI Market Pulse only in Shadow inside
the existing supervised process after the signed activation barrier. Independent
ledger, hypothesis cohort and pause preserve Spot/Futures capital and protections.
Public market-data-only endpoints cannot submit account orders. Initial score
weights are explicit unvalidated hypotheses, and frozen-evidence replay is not
claimed as independent OOS evidence. Missing historical news/ticks require
prospective accumulation, not hindsight reconstruction.

The owner explicitly authorized reuse of the current OpenAI key with a Pulse-only
durable cap of six attempts/day. Interpretation is bounded and never on the
protective path. No additional paid service or external credential is introduced.
Official RSS is a limited starting source, not comprehensive social/news coverage.
Sharing Spot Testnet funds requires a later reviewed common reservation protocol,
fresh account/filter checks and separate promotion approval; it is blocked now.
The preparatory coordinator is synthetic-tested, not silently connected to Spot.
Local/remote UI and the optional bounded Worker contract change together, preserving
older snapshots and authentication. No LIVE implementation is added.

This file preserves project-level intent so future maintainers and AI models can understand not only what changed, but why.

## 2026-09 — Foundation

The project began as a Python crypto trading bot focused on PAPER trading, backtesting and conservative risk controls. The initial goal was to create a researchable system rather than a black-box profit generator.

Key principles established early:

- deterministic quantitative signal first;
- AI only as a secondary review gate;
- explicit risk limits and kill switch;
- persistent logs/ledgers;
- no automatic transition to real funds.

## 2026-09 — Remote monitoring and private portal

A remote portal was added so the bot could be observed without exposing inbound ports on the Windows PC. The architecture evolved toward outbound HTTPS from a Windows agent to a private Cloudflare-backed portal.

Important decision: the remote agent must not become a second trading engine. It observes, reports and carries a narrow set of authorized controls.

## 2026-09 — Signed update architecture

Updates moved from manual local replacement toward signed packages with:

- Ed25519 verification,
- hash validation,
- anti-downgrade sequence,
- supervised stop/start,
- health check,
- rollback/recovery,
- protected publication flow.

Reason: remote convenience must not make arbitrary code installation easier.

## 2026-09 — Unified portal

Local and remote portal experiences were consolidated around shared `web/` assets. This was chosen to prevent two interfaces from drifting and giving contradictory operational states.

## 2026-09 — Binance Testnet migration

The project moved from PAPER as the main operational environment toward Binance Spot Testnet. PAPER was retained for CI, regression and fallback.

This separation is deliberate: PAPER results and exchange-Testnet behavior are different evidence classes and should not be merged casually.

## 2026-09 — Futures Demo

Futures began as manual infrastructure/smoke testing (including 1x–3x checks) and later became an independent persistent BTCUSDT forward test.

Permanent separation rules:

- own ledger and journal;
- own kill switch;
- maximum one position in the initial forward-test design;
- isolated margin / one-way mode;
- no automatic inheritance of Spot risk or financial history;
- no implication that Futures Demo enables LIVE.

## 2026-09 — Observation phase

After reaching parallel Spot Testnet + Futures Demo, the project intentionally shifted from rapid feature addition toward observation and data quality.

Decision: do not overfit strategy/risk to a few days of results. Operational and safety defects can still be fixed immediately.

## 2026-09 — Windows supervisor hardening

Repeated work on versions 0.8.8–0.8.13 hardened the independent remote agent and updater.

Lessons preserved:

- do not rely on ambiguous Python runtimes;
- do not modify the scheduled-task host while it is the process keeping the agent alive;
- direct `pythonw.exe` execution is simpler than a persistent PowerShell host for the normal agent path;
- one heartbeat after repair is not enough evidence of stability;
- a remote-visibility failure must degrade monitoring, not corrupt trading state.

## 2026-09 — Remote snapshot contract compatibility

A production incident after 0.9.6 exposed an important integration rule: the Windows agent began emitting a new bounded Futures `pause_diagnostics.incident` field while the Cloudflare Worker still enforced the previous allowlist. The bot update itself completed, but every device heartbeat was rejected with HTTP 400 and the portal appeared stuck.

Permanent lesson and invariant:

- the Windows snapshot producer and Cloudflare snapshot validator are one versioned contract even though they run in different places;
- any new remote snapshot field must update the Worker validator and compatibility tests in the same PR;
- the Worker must continue accepting the immediately previous compatible shape when the field is optional, so rollout order cannot break monitoring;
- CI must include both the current shape and the legacy shape before a portal release can be merged/published;
- a heartbeat/schema failure must remain a monitoring failure only; it must never mutate trading state, credentials or ledgers.

This class of mismatch is now covered by regression tests for Futures pause diagnostics and should be treated as a release-blocking contract failure in future changes.

## 2026-09 — Futures durable-journal recovery invariant

A paused Futures Demo incident exposed a second integration edge case: a confirmed `reduceOnly` close could leave the durable forward-order journal populated after both exchange exposure and local position accounting were already flat. Because automatic recovery treated any pending journal as an unconditional blocker, the motor could remain safely paused forever even though there was no remaining exposure.

Permanent recovery rules:

- a durable pending order is evidence to reconcile, not evidence by itself that exposure still exists;
- recovery must query the exact recorded client order identity before clearing or acting;
- a FILLED close with local + exchange state already flat may clear only the stale journal and continue;
- if exposure remains after a FILLED close, never resubmit blindly; retain the journal and re-check identity/state;
- manual pauses never auto-resume;
- automatic pauses may auto-resume only after journal reconciliation, position identity checks, required Futures configuration and account reads all pass.

## 2026-09 — Flat reduce-only journal rule

A follow-up to the Futures recovery work showed that querying an old Binance order first can itself block recovery, even when the only remaining durable record is a `reduceOnly` close and both local accounting and current exchange exposure are already flat.

Permanent rule: a reduce-only close journal may be cleared without historical-order lookup only when local position state is absent and a fresh Binance position read confirms zero exposure for that exact symbol. This cannot be generalized to opening orders or any non-flat state. No order is resent during this cleanup.

## 2026-09 — Futures recovery must be state-machine based

The prolonged FUT-0001 incident demonstrated that durable order journals, exchange positions and local accounting cannot be recovered correctly by treating any one of them as the sole source of truth. A crash may occur after the exchange fill but before local commit, after local commit but before journal cleanup, or while Binance still exposes a temporarily inconsistent configuration. Historical order lookup can also expire.

Permanent invariants introduced by the 0.10.0 audit:

- classify recovery from the tuple **pending journal + local position + current exchange exposure + durable open plan**;
- current exchange exposure is authoritative for financial risk, while the journal is authoritative for write identity;
- never resend an uncertain write merely because local accounting is incomplete;
- a confirmed/matching opening exposure may be reconstructed locally before repair;
- if a reconstructed opening exposure is CROSS, close it exactly once with a new durable reduce-only journal before returning to flat ISOLATED 1x;
- an expired historical order lookup may only be quarantined automatically when current exposure is zero; preserve an explicit evidence-gap marker;
- owner resume is a supervised reconciliation operation, never a raw kill-switch delete;
- repeated protection attempts for the same root cause are one incident with bounded log emission, not hundreds of independent incidents.

Spot Testnet was reviewed against the same failure classes and retains its separate client-order journal/reconciliation path; no equivalent state-machine defect was found in that path during this audit.

## 2026-10 — Execution evidence and accounting audit

Version 0.10.13 corrects two assumptions that survived the earlier recovery audit. PositionRisk V3 is authoritative for exposure but omits symbol margin/leverage; configuration must come from symbolConfig. Absent fields never prove CROSS. Spot accounting also needs an atomic fill receipt: durable intent alone does not prevent cash duplication if the accounting commit and applied marker are separate transactions. The receipt, cash, position, trade and marker now commit together.

Forward decisions are consumed durably once per symbol and closed USD-M Demo candle before AI/execution. A crash may skip that opportunity, but must not repeat it. AI reviews have a separate durable daily cap. Futures uses its own financial history for daily/weekly loss gates; protective monitoring continues independently. Financial history is retained, while bounded dashboard projections remain separate.

Technical recovery closes do not qualify as strategy evidence. Shadow v2 starts separately because the prior threshold and SHORT arithmetic were invalid; old records remain available as legacy evidence and are never silently rewritten. Shadow sums are gross per-trade diagnostics, not portfolio returns. Missing costs and deleted historical samples remain explicit limitations. Full funding/commission attribution and exposure-matched portfolio research remain prerequisites for future advancement.

At that stage, validation and protected publication ran on same-repository `release/*` PRs with owner review. The 2026-10-04 automatic-main decision below supersedes that trigger; older approval and empty-push recovery instructions remain historical.

## 2026-10-03 — Native Testnet protection and recovery ownership

PC availability is no longer the intended source of stop/target execution for confirmed Testnet positions. Spot uses an OCO pair of conditional MARKET sells; Futures uses close-position STOP_MARKET/TAKE_PROFIT_MARKET with MARK_PRICE. Strategy and risk boundaries remain unchanged. Exchange identity and execution evidence, not inferred flatness, determine native accounting.

Each network write has a durable identity before submission. Unknown POST outcomes are queried and never blindly resent. Native journals outlive accounting until siblings are terminal, and unique Spot receipts prevent duplicate proceeds after crashes. Owned orders must be cleaned before a new exposure or local close. Explicit validation rejections preserve local protective closes; ambiguous outcomes block conflicting writes. Per-position confirmation is visible separately from feature support.

Restoration to code without native support is blocked while native journals remain, including a second check after cooperative stop. Spot trailing replacements have a non-atomic cancellation/creation gap; offline operation preserves only the last confirmed levels. Demo verification and a fresh observation window remain required before claiming installed behavior; no LIVE permission is introduced.

## 2026-10-03 — Independent supervisor dependency closure and UI ownership

An isolated reproduction of the 0.10.14 refresh found that the signed bot contained `native_protection_compat.py`, while the independent-agent refresh inventory omitted it. Updating the supervisor without that dependency could break recovery/restore imports and block heartbeat delivery. The refresh and capability inventories must match, and CI must import the actual refreshed modules in a separate process without access to the source checkout. Optional updater metadata failure withdraws update/restore capabilities and automatic rollout while preserving the basic heartbeat; installation safety gates remain mandatory.

The Windows indicator has separate ownership from the trading engine. A per-install/session mutex prevents duplicate indicators and their repair timers, and an OS file lock serializes signed agent refresh against other repairs and the app watchdog. Repair success requires new HTTPS evidence; a running process or copied files alone cannot prove reconnection. These protections cannot recover a powered-off PC or fix rejected credentials. An affected old independent supervisor may require a locally verified dependency recovery before remote rollout becomes available again.

### Confirmed incident and recovery record

The owner's PowerShell output confirmed that task `Crypto Paper Portal Agent` was `Running`, but `trader/native_protection_compat.py` did not exist in its actual `WorkingDirectory`. `data/remote-status.json` showed `sync_ok=False`, `error_type=ModuleNotFoundError` and no `last_success`. The 0.10.14 photo also showed two indicator icons; it did not establish two trading engines.

The root cause was an incomplete independent refresh, not an unsigned bot package: `trader/update_supervisor.py` imported `.native_protection_compat`; the signed installation and `scripts/windows_agent.py::SUPERVISOR_MODULES` contained the helper, but `scripts/refresh_independent_agent.py::MODULES` omitted it. A real refresh into an empty agent directory followed by isolated Python imports reproduced `ModuleNotFoundError: No module named 'trader.native_protection_compat'`. Earlier protections verified the signed target and restarted the agent, but did not prove that the separately copied dependency inventory was complete. Testing inside the source checkout could hide this defect.

The successful local recovery derived the agent root from the existing task, checked the committed signed installation journal against installed version and sequence, and verified the helper's SHA-256 against that inventory. It stopped only the agent task, copied the already installed verified helper through a temporary file, rechecked the hash, moved it into the missing destination and restarted that same task in `finally`. It refused mismatched inventories, an existing destination or update maintenance. Do not turn this incident-specific procedure into blind copying from GitHub or a development checkout.

The owner pasted `Módulo verificado recuperado.` and subsequently reported that Windows had updated to 0.10.15 and the connection was visible again. This is owner-reported runtime recovery, not a direct development-session capture of the operating PC. Single-indicator state, two fresh authenticated syncs and native exchange orders remain separate evidence requirements.

### Preventive requirements for future maintainers and AI

- Treat the signed target and independent supervisor as separate installations. Update both inventories whenever adding an agent/supervisor dependency. Preserve `test_refresh_inventory_matches_supervisor_capability_inventory` and `test_refreshed_independent_agent_imports_without_source_checkout` in `tests/test_agent_refresh.py`; the latter exercises actual signed-module refresh and `python -I -B` imports in a clean root.
- Preserve optional updater-metadata isolation in `trader/remote_agent.py`: withdraw update/restore offers and automatic rollout when unavailable, retain the basic heartbeat where startup permits, and report `SUPERVISOR_UNAVAILABLE:<ExceptionClass>`. Never weaken signature, sequence, native compatibility or restore checks to reconnect.
- Preserve indicator ownership in `scripts/manager_windows.ps1`, shared repair exclusion in `scripts/agent_self_heal.ps1` and the manager watchdog, and the real PowerShell child-process checks in `tests/windows_manager_lifecycle.ps1`. Old indicator processes require **Salir del indicador** and one reopening to load the new guard; hiding a window is insufficient.
- Diagnose sync evidence before repeating restart/repair. Two distinct increasing `last_success` values with `sync_ok=True`, a running task and no supervisor degradation are required for a successful repair notice. A missing dependency, offline PC and rejected credentials need different remedies.
- Preserve observation data and trading state during monitoring recovery. Do not change strategy, leverage, risk or financial journals to fix agent connectivity, and never start another trading engine.

The correction is PR [#91](https://github.com/jlboper/Crypto-BOT/pull/91), merged as `2e73c67b68e422bc236fe3e66323e1034b9c2b7a`. Protected publication [37168205095](https://github.com/jlboper/Crypto-BOT/actions/runs/37168205095) succeeded and signed version 0.10.15 for source `4286f185719d080efce4da97f41ef8302b252e0d`. Release validation passed 271 offline Python tests, 75 Node tests and Windows PowerShell lifecycle checks. GitHub timestamps are 2026-10-04 UTC; the incident date above follows the owner's 3 October report. Publication success alone never proves Windows installation. These checks address the reproduced failure class; they do not guarantee that every future connection failure is impossible.

## 2026-10-04 — Authenticated portal audit and evidence semantics

The authenticated portal reported the installed 0.10.15 bot and a connected Windows agent during the menu/statistics audit. This independently confirms the portal's version/connection projection after the owner's recovery report; it does not prove native protection with no exposed positions or permanent continuity.

Several UI summaries mixed technical recovery closes with strategy closes even though the ledger already separated them. Account-wide unrealized P&L was also being used to infer one contract's price. Version 0.10.16 prepares corrections: strategy evidence stays separate from operational diagnostics; wallet plus unrealized P&L defines account equity; account totals are never attributed to individual contracts without quote evidence. Missing samples remain missing, historical AI reviews carry their timestamp, and aggregate coverage cannot hide a stale latest cycle.

The audit does not justify tuning strategy from a short or technically dominated history. Preserve the existing observation period, execution rules and risk controls, and reassess strategy only with sufficient attributable forward evidence and complete cost accounting. Regression fixtures cover zero-P&L closes, stale high-coverage cycles, multiple contracts, chronological AI reviews and pending update checks. Publication and Windows installation are separate from these source changes.

Verification completed later in the same audit: PR [#93](https://github.com/jlboper/Crypto-BOT/pull/93) merged; protected [37170161112](https://github.com/jlboper/Crypto-BOT/actions/runs/37170161112) published signed TESTNET 0.10.16 for source `614dc45a9f62a89682fbb6c32b74b28f5ba58053`. CI passed 273 Python tests on Linux/Windows, 76 Node tests and Windows manager/repair lifecycle checks. The authenticated portal then reported a completed supervised installation/startup check, installed 0.10.16, Windows connected and both motors operational. No native order execution was exercised during this read-only audit; this point-in-time evidence is not a guarantee of future uptime.

## 2026-10-03 — Owner-authorized Futures universe and Demo leverage trials

The owner requested more Futures assets and explicitly selected actual Binance Demo orders over a simulated comparison for 2x/3x. Candidate 0.10.17 activates the already supported BNBUSDT/XRPUSDT alongside BTC/ETH/SOL, retaining three simultaneous positions. Confirmed new entries rotate through 1x/2x/3x at the same quantity and fixed notional ceiling (100 USDT); leverage never multiplies the budget. This tests configuration, margin, execution and native protection, not leveraged strategy profitability.

Position leverage is durable identity for configuration recovery. The open plan records the exact trial/index before submission; accounting and rotation advancement commit atomically, and reconstructed fills advance idempotently. Existing 1x positions remain 1x. Restoring code without this protocol is blocked while a 2x/3x position or open plan remains. Native journals, daily/weekly loss gates, signal thresholds, closed-candle deduplication, AI caps and LIVE prohibition are retained.

The trial has its own dated results, excludes technical closes and retains prior financial history. Gross results from different entry opportunities are not an exposure-matched comparison and omit fees/funding. More observed assets or reduced margin cannot establish a trading edge. This changes the Futures observation regime; collect new evidence with that date rather than treating the earlier three-asset 1x period as equivalent. Prepared, signed/published and installed remain separate states.

## 2026-10-03 — Owner-authorized fifteen-asset Futures portfolio

The owner approved fifteen monitored Futures contracts and up to five open positions after discussing a 300 USDT aggregate ceiling instead of five full 100 USDT entries. Candidate 0.10.18 also reserves at most 7.5 USDT of estimated movement to stops, including a 0.5% cost/slippage allowance. Exposure is gross: opposite contracts never cancel each other's budgets. Existing positions are reconciled and protected even when they already exceed a new cap; only new entries are blocked. Live account marks and refreshed Demo references are required, budgets are recalculated after AI review, and unknown exposure blocks new entries.

Replace forward smoke-size seeds with exchange-filter-based sizing, preserving the separate manual smoke lab. Entry quantity is limited by both remaining budgets, exchange minima and the original 100 USDT ceiling; leverage does not multiply it. A 2% price-movement reserve helps pre-submit sizing but cannot guarantee a MARKET fill or gap-loss cap. The low-level submit path previously reset leverage to 1x before entry; it now confirms the durable plan's chosen 1x/2x/3x before submitting. Regression tests observe leverage at the actual mocked order endpoint.

A portfolio compatibility marker prevents returning to code unable to manage expanded assets, more than three positions or an expanded pending plan. Portal producer, bounded Worker contract and shared UI advance together; legacy snapshots remain accepted. Preserve histories and assess this expanded observation regime separately. PR #95 merged and protected run 37172747885 completed successfully for 0.10.17; Windows installation of that release has not been observed here.

## 2026-10-03 — Stale supervisor validator after a committed configuration upgrade

The owner reported a failed 0.10.18 update. The authenticated portal subsequently showed installed 0.10.18, connected Windows and fifteen Futures assets, while the install job at 21:26:06 Mexico City said only `Trabajo detenido: ValueError`. A new signed update check completed as current 0.10.18. An isolated reproduction confirmed that 0.10.17's validator rejects 0.10.18's expanded symbol list. The remote job called that already imported validator after the supervisor had committed and verified the new running engine; it could mark a completed upgrade as failed merely while formatting its completion message. The generic portal error does not independently identify every Windows stack frame.

Candidate 0.10.19 removes trading-schema reads from update and restore jobs and derives success only from the supervisor's checked outcome, exact approved identity and expected version. Research still loads trading settings. Do not relax signed-package checks, health barriers, anti-replay, dependency inventory or financial-data recovery, and do not relabel arbitrary failed jobs from a version badge. Regressions must cross old-process/new-config boundaries rather than testing only refreshed current imports. No new trading or UI behavior is introduced.

## 2026-10-04 — Authorized laboratory expansion, isolated from execution

The owner authorized all proposed research improvements. Version 0.10.20 makes the laboratory daily while the Windows app is running, broadens Spot to the current liquid universe (up to 30) and studies the configured 15 Futures assets with public USD-M candles, mark and funding history. Research has its own low-priority process and durable lock/status, cancels cooperatively during update maintenance, and remote jobs invoke the installed research entry point rather than importing a potentially stale supervisor module. Do not start analysis inside the trading cycle or add research-only modules to independent-supervisor imports.

The earlier equal-weight fold aggregation remains an explicitly labeled illustration. A new event simulator uses one shared wallet, timestamp alignment, five positions, marked gross exposure, next-open execution, costs, LONG/SHORT, funding and isolated-mark liquidation stress. Three preregistered risk profiles and orthogonal Futures leverage levels 1/2/3/5/10 explore risk without adjusting operating order limits. The assumed 1% maintenance is not exchange/account bracket calibration: Futures research remains unqualified, even when simulated performance is positive. No model, profile or leverage is promoted automatically.

Full runs and data fingerprints are retained separately from bounded portal summaries. Repeated daily holdouts are monitoring, not independent validation. A small Spot cohort (up to five) and configured Futures cohort freeze rules at registration and observe only bars opening afterward; artificial terminal closes are excluded from forward close counts, missing cohort data invalidates that observation, and a settings change starts a new retained cohort. This remains public-data PAPER observation, not Demo execution evidence. Broader strategy automation and LIVE remain deferred.

## 2026-10-04 — Owner-authorized automatic publication after main validation

The owner asked to remove repetitive GitHub approvals, removed `Required reviewers` from `portal-production`, then asked to continue with the proposed main-only flow. GitHub canceled the older 28 September run 36486941944 with `Required reviewers protection rule deleted`, producing a failure email on 4 October; it was unrelated to successful signed/installed 0.10.21. Do not rerun obsolete publication jobs to address that notification.

PRs now validate without deploying. A main push validates the exact merged SHA on Linux and Windows before the environment-scoped publisher runs automatically. Keep environment credentials, pinned Actions, version preflight, migration rejection, deployment health/rollback, OIDC identity, Ed25519 verification, anti-downgrade sequence and supervised Windows installation. Deployment/package scripts and the signer reject PR identities and superseded main revisions. Review remains mandatory if the owner restores it in GitHub; no approval token or administration credential is added to the portal.

This authorizes routine code publication and signed rollout, not LIVE, risk changes or automatic research/strategy promotion. The independent Windows agent and both financial engines retain their existing behavior. Version 0.10.22 packages the release helper/documentation; actual CI, publication and installation must be observed separately.

## Ideas intentionally deferred

The following have been discussed but should remain deferred until their prerequisites are met:

- Binance production/LIVE execution;
- further Demo evidence for native protective orders and offline/reconnection behavior;
- mobile/Android monitoring and notifications;
- broader strategy automation;
- automated strategy promotion;
- production hosting migration.

Deferral is not rejection. A future maintainer should reassess these ideas against current evidence and architecture instead of implementing them merely because they appear here.

## How to maintain this log

Add entries for architectural decisions, abandoned approaches, major safety lessons and future-direction changes. Do not duplicate every patch note; detailed release-by-release implementation belongs in `UPDATE_NOTES.md`.

## 2026-10-12 — Owner-authorized ten-position observation

The owner requested ten positions per operating bot to increase Testnet observation. Spot and Futures caps rise from five to ten; portfolio exposure/loss budgets, signal thresholds, leverage and native protection remain fixed. Futures distributes its unchanged 300 USDT gross budget across ten slots, targeting 30 USDT for new entries before exchange filters and remaining-risk checks. Existing positions retain their quantities. More slots are capacity, not an instruction to force entries or evidence of strategy profitability. Research scenarios remain separately frozen at five positions.

The signed release must preserve the operational repairs already active locally from 8–11 October (net Futures costs, clock synchronization, native-fill reconciliation and resolved-incident diagnostics). Replacing them with the older GitHub baseline would undo the stability being observed. Independent-agent config parsing and the Worker snapshot position-array bound must support ten together; never patch the running bot's count alone and leave its monitor rejecting the new state.
## 2026-10-14 — Protective preflight and remote history budgets

A GNS Spot Testnet buy at 08:02 UTC was followed by a definitive -1013 PERCENT_PRICE_BY_SIDE rejection of its OCO. Existing preflight checked only ticks/order support, so it could buy an asset whose proposed protection was outside the exchange's percentage band. Preflight must check both rounded protective prices against the matching-engine reference or the exact configured VWAP window before any entry. Never silently change risk levels. A confirmed old OCO must survive an invalid trailing replacement. Only definite percent-filter rejections may receive a new identity after fresh position/filter/balance checks, bounded to three repairs; ambiguous writes remain query-only. Unconfirmed quantities must never be shown as covered.

Separately the Futures remote view reached 80,545 characters and caused the entire authenticated heartbeat to fail. Growing history cannot disable monitoring and signed recovery. Bound optional history views below the receiver's budget while preserving live safety evidence and aggregates; retain financial SQLite history. Keep a bounded legacy receive allowance and a visibly degraded heartbeat/update fallback for known optional projection rejections. The remote outage had no evidence of an unauthorized trade or credential change.

Futures protection latched a pause after an uncertain signed READ at 10:48 UTC. Its owned native orders later confirmed successfully, but that exact automatic reason was not recoverable. Re-audit journals, positions, native orders, flat configuration and account before automatic release; manual pauses and uncertain writes must remain blocked. No strategy promotion or risk expansion is authorized by this repair.



## 2026-10-15 — Clock validation pauses require audited recovery

A slow Demo time response correctly blocked the signed request before submission, but its exact diagnostic was absent from the automatic recovery reasons. Protection continued and native orders confirmed while new entries stayed paused for over ten hours. Do not relax the two-second clock-sample check or retry signed writes to cure this operational latch. Slow/unavailable Demo clock pauses may use the same complete reconciliation gate as timestamp rejection; any pending write, identity/configuration/protection/account failure or manual pause still blocks release. The owner-authorized supervisor recovered the current installation without a second engine. Spot's lack of current entries was independently traced to all 60 scores below 70, not a technical halt. Capacity and a request for movement do not justify forced trades or lowering risk gates.

## 2026-10-15 — Strategy review, price plans and comparable evidence

The owner requested better returns and more dynamic Testnet observation using the existing integration. Operating Spot was down about 7.76% with 7 winning strategic closes out of 34; Futures had 5 winners in 20 strategic closes and -8.836844 USDT gross, separately from 38 technical closes. These short, changed-regime and partly Testnet-distorted samples do not establish an edge. Frozen exploratory RSI and extension filters lost consistency across development/final/cost stress, so no strategy was promoted and no risk/leverage limit was expanded.

An execution defect was demonstrated: replacing only Spot signal.price changed the intended stop fraction and reward/risk before AI and sizing. New entry plans preserve their fractions and original admission bounds; observed and executable prices stay explicit. Initial ATR scales with the confirmed fill. This does not retroactively widen stops or resolve all public/Testnet volatility or slippage differences. Futures sizing could stay valid after price crossed the original or reviewed setup; entries now reject that condition without blocking recovery or exits.

Research had used Spot 4h for Futures despite the operating 1h cadence. Interval identity must be checked rather than inferred from internally consistent OHLC. Caches remain separate, old cohort registration is archived and only the changed market starts a new observation. Exact configured signal references share production signal functions, but must never be described as an execution-profitability replay: AI, fill/fee/funding details, exits, filters and portfolio state need independent modeling. Historical five-slot proportional scenarios remain distinct from the operating ten-slot and absolute Futures budgets. Do not relax income attribution to conceal small unmatched realized amounts without authoritative fill precision.
# 2026-10-16 — Four-engine expansion begins with read-only Guardian

The owner requested finishing Pulse's ten-asset/five-source expansion before
adding Quant Arbitrage and Portfolio Guardian in four reversible stages. Signed
0.10.34 main06de9109a0ae49ffbdb5f94bc6310a9239f421fc was observed installed with
162/162 hashes and fresh HTTPS sync; retained trade/decision journal rows matched.
The first Guardian is a pure projection of existing dashboard evidence, outside
trading cycles. It observes separate ledgers without netting Testnet/Demo/Shadow
capital or claiming verified cross-account hedges. Nominal stop distance excludes
costs/gaps/funding and is not a hard loss bound. Existing inclusive Futures budget
is reported separately. Native protection does not depend on Guardian availability.

Control/veto, common reservation admission and allocation journals are deliberately
absent until compatibility is validated. Unknown risk metrics must remain unknown.
Quant has a NOT_STARTED identity, with no fake wallet/performance and no execution.
Follow FOUR_ENGINE_EXPANSION.md for the separate UI, Quant Shadow and evaluation
stages. Signed rollout, anti-downgrade/recovery and existing financial state remain
mandatory; authorization does not extend to new Testnet execution or LIVE.
