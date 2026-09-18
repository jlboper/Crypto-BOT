# Crypto AI Trader: instructions for Work and local development

This repository is the source for the same Windows PAPER bot and private portal
at https://crypto-paper-private-portal.jlboper.workers.dev/. Work prepares changes;
the protected GitHub workflow publishes them; the Windows agent installs only
the exact signed version approved by the owner through the portal or app.

- Keep PAPER. Never enable live orders, start a second engine, or touch operating
  credentials/data during development. Use an isolated copy and synthetic tests.
- Read BOT_UPDATE_PROGRESS.md and BOT_RELEASE_OPERATIONS.md before changing the
  updater. Do not claim deployment just because a PR or documentation exists.
- The shared UI is `web/`. Run `python scripts/build_unified_portal.py`; do not
  implement different local and remote layouts. Local update actions open the
  authenticated remote update center; they never put credentials in URLs.
- Increment the stable version in `pyproject.toml` for every change to bundled
  bot files, including the shared web UI. The publisher rejects changed files
  with an already published version. Do not edit `release-signing.pub` without
  the owner's explicit key rotation request.
- Run `python scripts/test_offline.py` and, for portal/shared UI changes,
  `node --test tests/*.test.mjs` from `cloudflare/`. CI covers Windows and Linux.
- Make changes through PRs against `main`. Do not bypass `portal-production`
  review, make approval tokens, or grant repository administration to the portal.
- Never commit `.env*`, `.secrets`, databases, logs, runtime state, private keys,
  or data backups. `bot-releases` contains only allowlisted signed-package code;
  do not upload a complete installation or working-folder ZIP.
- The signer accepts only GitHub OIDC identities for this repository's protected
  main publication job and matching deployed commit. Routine publication uses no
  signing secret in GitHub. The signature key is a Cloudflare secret.
- A code update may change strategies and behavior, but must preserve risk
  boundaries, data recovery and explicit owner approval. Never promise returns.
