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

Technical recovery closes do not qualify as strategy evidence. Shadow v2 starts separately because the prior threshold and SHORT arithmetic were invalid; old records remain available as legacy evidence and are never silently rewritten. Shadow sums are gross per-trade diagnostics, not portfolio returns. Missing costs and deleted historical samples remain explicit limitations. Native protective orders, full funding/commission attribution and exposure-matched portfolio research remain prerequisites for future advancement.

The checked-in release workflow currently runs validation and protected publication on same-repository `release/*` PRs. Older main-push handoff notes are historical, not the current trigger. Verify the actual run and source SHA; owner approval of `portal-production` remains mandatory.

## Ideas intentionally deferred

The following have been discussed but should remain deferred until their prerequisites are met:

- Binance production/LIVE execution;
- exchange-native protective orders for full PC/network outage resilience;
- mobile/Android monitoring and notifications;
- broader strategy automation;
- automated strategy promotion;
- production hosting migration.

Deferral is not rejection. A future maintainer should reassess these ideas against current evidence and architecture instead of implementing them merely because they appear here.

## How to maintain this log

Add entries for architectural decisions, abandoned approaches, major safety lessons and future-direction changes. Do not duplicate every patch note; detailed release-by-release implementation belongs in `UPDATE_NOTES.md`.
