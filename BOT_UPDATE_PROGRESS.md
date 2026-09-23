# Bot updates: implementation and deployment status

Last Windows baseline confirmed by the owner in the portal after the 0.6.7 update:
**0.6.7** installed with startup and local PAPER portal checks completed. The
voluntary restoration of 0.6.6 was offered but not executed. Version 0.6.8 is
development work: it is not yet published or installed.
The outgoing HTTPS agent was connected,
and the local and remote portals use the shared `web/` interface. The first signed
installation and a later end-to-end update initiated with the remote portal button
were verified. This document distinguishes
implemented code, publication and installation. See `BOT_RELEASE_OPERATIONS.md`
for the owner workflow.

## Implemented and tested

- Shared portal buttons for finding a signed release and approving its exact
  manifest hash. The app/local UI open the same authenticated remote center.
- CSRF/session protection, fresh Windows heartbeat, enabled/expiry checks,
  idempotent requests and propagation of `release_id` into durable Windows jobs.
- Deterministic allowlisted source ZIP, version increase requirement and a
  protected GitHub publication step after portal deployment.
- GitHub OIDC validation and Ed25519 signing in the portal. The private signing
  key is held as a Cloudflare secret; GitHub receives no permanent signing key.
- Windows signature/hash verification, replay/downgrade rejection, cooperative
  stop, startup barrier, owned-process and loopback HTTP health checks, durable
  commit, code/SQLite recovery and reconciliation of interrupted remote jobs.
- Windows exclusive HTTP port binding and bytecode invalidation on rollback.
- One-time bootstrap for an already stopped legacy engine. It refuses to stop
  a discovered process or install while the original engine lock is occupied.
- Historical release tests covered workerd/D1 signing, synthetic Windows child
  processes, bootstrap and exact remote approval. Current test counts must be
  taken from the 0.6.8 PR/CI, not reused from an older release. No operating bot
  is started or stopped by the offline tests.

## Production baseline

- Cloudflare holds `BOT_SIGNING_KEY`; Windows and the repository use the public
  trust anchor. D1 migration `0004_bot_releases.sql` is active.
- The trusted Windows channel points to the existing portal; the owner's latest
  verified installation report is 0.6.7 through the signed path in PAPER.
- The portal update center already uses one options menu and one combined search.
  The voluntary restoration action and full-history PAPER financial scorecard
  were included in the subsequent release. Restoration requires a retained,
  verified previous code copy; do not count an offered restore as an executed one.
  The 0.6.8 changes add per-asset diagnostics, quote freshness and development
  research comparisons, subject to this version's review and publication gates.

## Completion gates

1. Prepare the next version on an isolated branch, pass CI and merge it.
2. Obtain owner approval in the existing `portal-production` environment and
   verify successful portal and signed-package publication.
3. From the authenticated portal, find that exact signed release, approve its
   manifest hash, install it remotely and verify version, health and heartbeat.

Do not describe a new version as installed until all three gates are recorded as
completed. No Android app or push-notification delivery is implemented here.
