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

The portal may pass its post-deployment health check at one Cloudflare edge
before the signer request reaches an edge with the same revision. When the
signer reports only `portal_and_bot_revision_must_match`, the protected
publisher retries that exact manifest and OIDC identity for a bounded period.
Other rejections fail immediately; successful signing still requires matching
deployed and bot commits. Before claiming publication, confirm the protected
job succeeded and `/v1/releases/latest` returns the expected signed version
and commit. A failed run can have deployed portal assets and uploaded an
unsigned ZIP; neither is an installable bot release. Rerunning a GitHub job
requires a new `portal-production` owner approval.

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

After installing signed 0.6.14, refresh the independent agent's
`scripts/windows_agent.py` and `trader/remote_agent.py` once from that verified
installation, with the outbound agent stopped and the originals backed up.
The signed bot's `scripts/export_paper_snapshot.py` then serves the current
PAPER dashboard from a read-only, isolated process on each sync. Subsequent
bot releases no longer require copying financial projection modules into the
supervisor. If the optional dashboard fails, the refreshed agent still sends
the PAPER heartbeat and update jobs and records `DASHBOARD_UNAVAILABLE`.
Do not copy agent files from an unverified checkout or overwrite the independent
supervisor's keys, runtime data, job journal or task definition.

Starting with signed 0.6.16, the installed Windows app exposes **Reparar
conexión del portal** in its tray menu. It checks that the independent agent's
two replacement modules exactly match the committed signed installation,
requests owner confirmation, waits for only that agent task to stop, backs up
its previous two modules and restarts that same task. Run it once after the
0.6.16 installation if the separate supervisor has not already been refreshed;
there is no need to install an intermediate version solely for this step.

After installing 0.6.17, run **Reparar conexión del portal** once more: the
independent Windows agent must receive the newly signed control module and
configuration refresh. The portal enables the model, restart and limited
Testnet actions only after the upgraded agent reports its capability. The
release and installation do not themselves submit any Testnet orders; an
authenticated owner confirmation inside Opciones → Binance Testnet does.

Starting with installed app 0.6.18, the Windows app checks the signed install
on startup and after a local update, then checks for a new installed version
every 15 seconds while it remains running. When the committed signed modules
have changed, it verifies their hashes, stops only the running outbound agent,
backs up its prior modules, refreshes them and starts the existing scheduled
task. The same check covers updates installed through the remote portal while
the 0.6.18 app is open. An intentionally stopped agent is left stopped. Failed
checks retry after five minutes; **Reparar conexión del portal** remains a
manual recovery option. A 0.6.17 app process already open while 0.6.18 is
installed still runs its old code until the app is reopened once; reopening it
enables the automatic check for future releases. No new trading process is
started by agent refresh.

Version 0.6.19 adds six selectable PAPER risk fractions below or equal to the
configured base limit. It also offers **Options → Binance Testnet → Comprobar
órdenes y saldo en Binance** to verify up to ten owned Testnet order identifiers
and read BTC/USDT balances without posting orders. A mismatch marks the local
Testnet record for review and blocks further buys and closes until a new signed
audit resolves it. Result figures for completed round trips are gross USDT
quote differences, not net returns: the earlier order ledger did not record
all commission assets. The account may contain BTC unrelated to this trial;
its total balance is not proof of the trial's owned position. A new release
does not automatically arm any Testnet strategy or authorize production trading.

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
