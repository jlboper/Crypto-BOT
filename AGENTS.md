# Crypto AI Trader: instructions for Work and local development

This repository is the source for the same Windows PAPER bot and private portal
at https://crypto-paper-private-portal.jlboper.workers.dev/. Work prepares changes;
the validated main GitHub workflow publishes them under the owner's automatic
release policy; the Windows agent installs only the exact verified signed version.

- Before each update, start from current `main`, use an isolated branch, and read
  `PROJECT_HANDOVER.md`, `PROJECT_HISTORY.md`, `WORK_CONTEXT.md`, this file,
  `README.md`, `pyproject.toml`, `BOT_RELEASE_OPERATIONS.md` and
  `BOT_UPDATE_PROGRESS.md`. Then inspect recent commits, open PRs/issues and
  GitHub Actions. Treat documentation as context, not proof of what is currently
  published or installed.
- Preserve project memory. When a change introduces a new architectural decision,
  permanently abandons an approach, changes the safety model, or materially alters
  the future roadmap, update `PROJECT_HISTORY.md` or `PROJECT_HANDOVER.md`.
  Release-specific implementation details belong in `UPDATE_NOTES.md`.
- Finish each update with a PR and relevant test results. If checks pass and no
  conflicts remain, merge through the repository's normal flow. Verify the new
  main publication run, its exact source and both platform validations, then
  publication/signature and the authenticated installed status. Provide the actual
  run URL; ask for review only if GitHub really has an environment review pending.
  Keep prepared, merged, published and installed states explicit.

- Keep PAPER. Never enable live orders, start a second engine, or touch operating
  credentials/data during development. Use an isolated copy and synthetic tests.
- Read BOT_UPDATE_PROGRESS.md and BOT_RELEASE_OPERATIONS.md before changing the
  updater. Do not claim deployment just because a PR or documentation exists.
- Before changing independent-agent imports or refresh logic, read the 2026-10-03
  dependency incident in PROJECT_HISTORY.md. Keep refresh MODULES and Windows
  SUPERVISOR_MODULES equal and pass the isolated refreshed-agent import regression
  in tests/test_agent_refresh.py. A Running task is not evidence of HTTPS health.
- The shared UI is `web/`. Run `python scripts/build_unified_portal.py`; do not
  implement different local and remote layouts. Local update actions open the
  authenticated remote update center; they never put credentials in URLs.
- Increment the stable version in `pyproject.toml` for every change to bundled
  bot files, including the shared web UI. The publisher rejects changed files
  with an already published version. Do not edit `release-signing.pub` without
  the owner's explicit key rotation request.
- Run `python scripts/test_offline.py` and, for portal/shared UI changes,
  `node --test tests/*.test.mjs` from `cloudflare/`. CI covers Windows and Linux.
- Make changes through PRs against `main`. On 2026-10-04 the owner removed required
  reviewers and authorized automatic publication after merge and validation.
  PRs cannot publish; credentials remain scoped to `portal-production`, and the
  signer accepts only the current main push/workflow identity. Do not bypass any
  restored environment review, make approval tokens or give the portal repo admin.
- Never commit `.env*`, `.secrets`, databases, logs, runtime state, private keys,
  or data backups. `bot-releases` contains only allowlisted signed-package code;
  do not upload a complete installation or working-folder ZIP.
- The signer accepts only GitHub OIDC identities for this repository's protected
  main publication job and matching deployed commit. Routine publication uses no
  signing secret in GitHub. The signature key is a Cloudflare secret.
- A code update may change strategies and behavior, but must preserve risk
  boundaries, data recovery and the owner's release policy. LIVE and strategy
  promotion still require separate explicit authorization. Never promise returns.
