# Bot updates: implementation and deployment status

Version 0.6.13 was published and signed for commit
`4df7ca199cd5148c205dcf499493c24ff7515a5b` after protected run
`36079566679` succeeded on its second attempt. The owner subsequently reported
a successful 0.6.13 installation from the authenticated portal. An independent
Windows version/health capture was not available in this source checkout. The
first protected attempt deployed a healthy portal but failed at signing with
`portal_and_bot_revision_must_match`: different
Cloudflare edges briefly served different deployed revisions. Version 0.6.14
prepares a bounded retry for only that exact fixed rejection, in the same
protected run and with the same OIDC identity, signed manifest and package.
The retry does not change signer validation or skip the owner environment gate.
It also keeps the core HTTPS heartbeat and update jobs alive when the optional
financial projection raises locally, and lets a refreshed independent agent
read the current installed bot's PAPER projection in a separate, short-lived
process. Refreshing the independent agent's `scripts/windows_agent.py` and
`trader/remote_agent.py` from the verified signed installation remains a
one-time Windows step after 0.6.14 is installed; upgrading the bot alone cannot
replace files in the separate supervisor directory.

The protected main release run for 0.6.15 succeeded at commit
`f6921b7f3247fcb54b983bf7c9f9ee019d36928c`; the owner reports completing
its Windows update. Independent Windows identity, effective OpenAI model and
supervisor module hashes are not available in this source checkout. Version
0.6.16 prepares a one-time assisted independent-agent refresh from a committed
signed installation. The local and remote portals expose the same PAPER position
closing and risk fractions. The remote portal requires a fresh Windows heartbeat,
queues a single exact request and reports its confirmed or failed result; the
local portal executes the same validation immediately. A protected additive D1
migration creates the request ledger before publication. The signed Windows
installation must be followed by the assisted independent-agent refresh before
the remote controls become available. It introduces no Testnet or production
order placement; publication and Windows installation remain pending.

Version 0.6.13 is a minimal signed update exercise: only the packaged version
and the shared portal's visible version label change. The owner confirmed the
previous 0.6.12 Windows installation and a healthy outbound sync after repairing
the independent agent's dashboard projection. Installation required separate
approval of the exact release through the authenticated portal and a Windows
health check.

The owner's portal screenshot on 24 September 2026 shows **0.6.8** installed
after request #15, with startup and local PAPER portal checks completed. Its
signed package was published separately after the PR #11 merge. A subsequent
documentation-only PR #12 does not change the installed bot. The voluntary
restoration remains available only when Windows offers a previous verified
version; it was not executed in that screenshot.
The outgoing HTTPS agent was connected,
and the local and remote portals use the shared `web/` interface. The first signed
installation and a later end-to-end update initiated with the remote portal button
were verified. This document distinguishes
implemented code, publication and installation. See `BOT_RELEASE_OPERATIONS.md`
for the owner workflow.

Subsequently, 0.6.9 was published through the protected job for commit
`1ccccbbe5605fb9111c728ea8c9ab33040a778cc`; the owner replied "listo" after
the handoff, but no authenticated Windows version/health snapshot was captured
here. At that point 0.6.9 installation was unverified and version 0.6.10 was
only a proposed PAPER evidence and UI update; see the subsequent inspection below.

Later the owner reported a read-only inspection of the supervised Windows
process, local PAPER portal and installed 0.6.10 identity. The protected
publication run for commit `bfdb89ece5673985351829676ad234cfbcde9989`
completed successfully. This is owner-reported installation evidence, not
direct access to the operating database from this source checkout. PR #15 for
0.6.11 was subsequently merged and its protected publication reported as
successful; its installation on Windows has not been verified in this copy.

Version 0.6.12 kept GPT-5.6 Luna as the API review model at that time, adds a
read-only Testnet planner and synthetic order reconciliation, and exposes the
unified research promotion gates in the portal. It is not published or
installed until its PR and protected release complete. The official OpenAI API
now documents `gpt-6-luna`; proposed 0.6.15 uses it in config, subject to an
explicit `check-ai-model` probe on the Windows account. Existing `.env.local`
overrides persist across signed updates and may still select 5.6 Luna. The
0.6.15 portal emphasizes operational PAPER status and hides research in a
diagnostics panel. It adds a separate signed `/api/v3/order/test` request on the
fixed Binance Spot Testnet host for local validation; this endpoint does not
enter the matching engine. No Testnet or live order submission is introduced.
The owner's 24 September Windows screenshot shows the scheduled outbound agent
running but `sync_ok: false` with `HTTPError:400`, so the portal cannot deliver
update jobs. A separate manual supervisor refresh attempt ended with
`FileNotFoundError`; the exact missing path was not captured. The newer agent
now reports allowlisted server validation reasons and can retry one rejected
optional dashboard projection without dropping the heartbeat. The app now
supports direct signed local installation through the independent supervisor,
including a previously staged package when offline. Neither change has yet
been observed on the operating PC.

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
  local read-only installation report shows 0.6.10 in PAPER.
- The portal update center already uses one options menu and one combined search.
  The voluntary restoration action and full-history PAPER financial scorecard
  were included in the subsequent release. Restoration requires a retained,
  verified previous code copy; do not count an offered restore as an executed one.
  The 0.6.8 installation includes per-asset diagnostics, quote freshness and
  historical research comparisons. Published version 0.6.9 adds a three-item activity
  summary, private 90-day paginated history, historical analysis within the
  financial panel and forward synchronized BTC spot comparisons. Historical
  equity is not backfilled; no Testnet or LIVE execution is implemented.

## Completion gates

1. Prepare the next version on an isolated branch, pass CI and merge it.
2. Obtain owner approval in the existing `portal-production` environment and
   verify successful portal and signed-package publication.
3. From the authenticated portal, find that exact signed release, approve its
   manifest hash, install it remotely and verify version, health and heartbeat.

Do not describe a new version as installed until all three gates are recorded as
completed. No Android app or push-notification delivery is implemented here.
