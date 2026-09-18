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
5. The owner chooses **Buscar actualización del bot** in the remote portal.
   Windows downloads and verifies the manifest and ZIP. The portal then shows
   the exact version and commit. **Instalar versión verificada** submits its
   manifest hash; neither the portal nor Windows may substitute a newer package.
6. The supervisor stops a compatible PAPER engine cooperatively, backs up files
   and SQLite, starts a candidate without financial cycles, checks its PID and
   local HTTP identity, commits and authorizes operation. Before commit, failure
   restores files and database. After commit, recovery preserves current balances.

The Windows app and local portal open the same authenticated remote update
center. They never need incoming PC ports, VPNs or tunnels. An online Windows
agent is required for installation. A publication is not an installation.

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
