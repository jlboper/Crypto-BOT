# Project History and Decision Log

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

The checked-in release workflow currently runs validation and protected publication on same-repository `release/*` PRs. Older main-push handoff notes are historical, not the current trigger. Verify the actual run and source SHA; owner approval of `portal-production` remains mandatory.

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
