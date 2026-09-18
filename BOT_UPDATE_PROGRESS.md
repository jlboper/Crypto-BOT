# Bot updates: implementation and deployment status

Version prepared: **0.6.3**. Source proposal: PR #3,
`work/supervised-bot-updates`. This document distinguishes implemented code from
production activation. See BOT_RELEASE_OPERATIONS.md for the owner workflow.

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

## Provisioned but not equivalent to deployment

- Cloudflare secret `BOT_SIGNING_KEY` and local/repository public trust anchors.
- D1 migration `0004_bot_releases.sql`, with a private pre-migration backup.
- The trusted Windows channel points to the existing portal. Installation is
  disabled until the owner-approved first transition has succeeded.

## Completion gates

1. CI on the final PR revision, merge, owner approval in the existing
   `portal-production` environment, successful portal and signed-package
   publication, then download/verification of that actual package.
2. Explicit owner permission for the first legacy-engine stop/restart. This is
   required to respect the earlier instruction to leave the current instance
   unaffected during development. No live trading mode will be enabled.
3. Successful initial activation, enable the trusted channel, restart only the
   outgoing agent, and verify the deployed UI and heartbeat.

Do not describe remote updates as active until these gates are recorded as
completed. No Android app or push-notification delivery is implemented here.
