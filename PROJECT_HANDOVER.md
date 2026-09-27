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

Crypto-BOT is a safety-first crypto trading research and execution project. Its purpose is to test systematic strategies with explicit risk controls and strong recoverability before any consideration of production capital.

The current architecture intentionally separates:

- **Spot Testnet**: primary multi-asset test environment.
- **Futures Demo**: separate BTCUSDT LONG/SHORT forward test with its own ledger, journal, risk controls and kill switch.
- **PAPER**: regression, CI and technical fallback.
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

## Current decision posture

The present phase is observation, stability and evidence collection. Avoid changing strategy, leverage or risk because of a few days of results. The project should accumulate enough clean forward-test data to support a later review.

A future decision to use real funds must be a separate project phase with explicit design and safety review. It must not be activated by a version bump, a configuration toggle, an AI recommendation or a good backtest.

## Future ideas already considered

These are ideas, not commitments:

- Longer Spot vs Futures forward-test comparison with comparable scorecards.
- Stronger exchange-native protection for scenarios where the PC or Internet is unavailable.
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
