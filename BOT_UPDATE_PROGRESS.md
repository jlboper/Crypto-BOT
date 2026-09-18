# Bot updates: implementation and deployment status

Production baseline confirmed by the owner on 18 September 2026: **0.6.4** is
installed on Windows and running in PAPER. The outgoing HTTPS agent is connected,
and the local and remote portals use the shared `web/` interface. The first signed
installation was verified locally. A later end-to-end update initiated with the
remote portal button still needs to be demonstrated. This document distinguishes
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
- 91 offline Python tests and 43 Node tests passed locally, including workerd/D1
  signing, synthetic Windows child processes, bootstrap success/failure and
  exact remote approval. No operating bot was started/stopped by those tests.

## Production baseline

- Cloudflare holds `BOT_SIGNING_KEY`; Windows and the repository use the public
  trust anchor. D1 migration `0004_bot_releases.sql` is active.
- The trusted Windows channel points to the existing portal and version 0.6.4 was
  installed through the signed update path after explicit owner approval.

## Completion gates

1. Prepare the next version on an isolated branch, pass CI and merge it.
2. Obtain owner approval in the existing `portal-production` environment and
   verify successful portal and signed-package publication.
3. From the authenticated portal, find that exact signed release, approve its
   manifest hash, install it remotely and verify version, health and heartbeat.

Do not describe a new version as installed until all three gates are recorded as
completed. No Android app or push-notification delivery is implemented here.
