# Publication and installation

1. Work changes this repository, updates the bot version if packaged files
   changed, runs tests, and opens a PR. `web/` is shared by both portals.
2. After merge, the `portal-release.yml` validation job runs. The existing
   `portal-production` environment requires the owner's GitHub review.
3. One protected publication job deploys the portal, then uploads the bot ZIP
   to `bot-releases/packages/<source commit>.zip`. Only allowlisted tracked
   source files are packaged. Configurations, databases and secrets are excluded.
4. The job obtains a short-lived GitHub OIDC identity and asks the portal to
   sign its manifest. The portal validates issuer, signature, audience, repository
   ID, environment, workflow, main ref, expiry and matching deployed commit.
   The Ed25519 private key remains a Cloudflare secret. The public trust anchor
   is `release-signing.pub` (hexadecimal raw Ed25519 key).
5. The owner chooses **Buscar actualizaciones** in the remote portal. The same
   action checks the portal publication and asks Windows to download and verify
   the signed bot manifest and ZIP. The portal then shows
   the exact version and commit. **Instalar versión verificada** submits its
   manifest hash; neither the portal nor Windows may substitute a newer package.
6. The supervisor stops a compatible PAPER engine cooperatively, backs up files
   and SQLite, starts a candidate without financial cycles, checks its PID and
   local HTTP identity, commits and authorizes operation. Before commit, failure
   restores files and database. After commit, recovery preserves current balances.

Before requesting the owner's environment approval, verify an actual
`portal-release.yml` run for the exact `main` commit with a `push` event. A PR
validation run and a successful merge by themselves do not publish anything.
After PR #11, a merge through an API did not yield a visible push run for the
merged commit. A narrow follow-up PR merged by the owner in GitHub's web UI is
the recovery path for this release: check that its merge starts the `main` push
run, then review the protected `portal-production` job for that exact commit.
Do not bypass the PR or environment review, reuse a PR run as a publication,
or claim an installation from a workflow result alone.

The Windows app uses the independent supervisor for a local signed update
center, with an online check or offline installation of a previously staged,
still-valid signed package. It requires exact local owner confirmation and
does not need a portal heartbeat for an offline install. The local web portal
retains its authenticated remote update link. Neither path needs incoming PC
ports, VPNs or tunnels. A publication is not an installation.

The installer retains the immediately previous code for automatic recovery.
With an updated independent Windows supervisor, **Options → Restore previous
version** becomes available after a signed installation captured the preceding
code and its hashes. Exact restore approval stops the PAPER engine cooperatively,
checks its previous code, starts the restored code behind a candidate barrier,
and verifies health before financial cycles resume. Financial SQLite data and
the signed release sequence remain current; a restore may expose code/database
incompatibility and is never an authorization to place real orders. Failed or
interrupted precommit restoration recovers current code without rewinding data.
This offer is one time and disappears after a successful restore.

Version 0.6.7 requires a one-time refresh of the independent Windows agent and
supervisor before installing the new signed bot release. The agent runs outside
the signed target, so installing the target alone cannot update that supervisor;
an older agent neither advertises nor accepts the voluntary restore job. Review
the running scheduled task and its root, stop **only** the outbound agent with
`scripts/stop_portal_agent.ps1`, verify its process exited, and refresh its
allowlisted code from the signed 0.6.7 package after signature verification.
Keep `data/`, `cloudflare/.secrets/`, the trusted public key and task definition
intact. Restart the existing task and verify the portal heartbeat before requesting
the signed installation. Do not assume the PC was refreshed because this PR was
merged or the portal was published.

## One-time Windows transition

The original v0.6.2 engine does not support cooperative maintenance. Preserve it
until the package is published and verified. `bootstrap_bot_update.py` requires
the exact release hash and an already stopped engine; it never kills a process.
An explicit owner-approved initial stop/restart is needed. The staged signed
package is verified again before changes. If initial activation fails, files and
SQLite are restored and the legacy engine remains stopped for review.

After successful transition, enable the locally provisioned trusted channel
and restart only the outgoing agent. Future updates need no local Codex session.
The existing agent task performs recovery when it starts after an interruption.

## Scope and costs

This uses the existing Workers/D1 deployment and GitHub Actions/repository.
No paid plan or new paid service is activated. Quotas and future provider pricing
still apply. Old package history remains in GitHub; review retention if frequent
large releases approach repository limits. Android can later use the same HTTPS
API; no Android app or push notifications are claimed by this implementation.

The private key and pre-migration database backups are only in the restricted
local `.secrets` directory. Do not publish them. Key rotation requires updating
the local trust anchor deliberately; changing the portal password does not
rotate signing or provider credentials.
