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
