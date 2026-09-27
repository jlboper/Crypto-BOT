# Portability, migration and recovery

Crypto-BOT should be reconstructable on another PC or future host without depending on the current machine.

## Four portable layers

A complete migration has four separate layers:

1. **Versioned code** — current approved `main` or a signed release.
2. **Private secrets** — `.env.local`, device token and external credentials. Never commit them.
3. **Persistent state** — selected SQLite databases, journals and recovery state.
4. **Host supervisor** — Windows Task Scheduler, systemd or another process manager.

Do not bundle all four into a casually shared ZIP.

## Source of truth

For a new installation, prefer cloning the approved repository/release over copying an old working folder. Verify `pyproject.toml` and the current commit before restoring any state.

## Windows bootstrap

From a fresh checkout:

```powershell
.\scripts\bootstrap_new_host.ps1
```

This creates a local virtual environment, installs the project plus portal/update dependencies, preserves an existing `.env.local`, creates one from the template only when absent, and runs a read-only portability preflight.

Only after reviewing the environment and runtime should you install the remote-agent autostart task:

```powershell
.\scripts\bootstrap_new_host.ps1 -InstallAgentAutostart
```

The script does **not** start LIVE trading and does not invent credentials.

## Linux bootstrap

```bash
chmod +x scripts/bootstrap_new_host.sh
./scripts/bootstrap_new_host.sh
```

A Linux host still needs an explicit process-supervisor design. Do not treat the sample portal service as a drop-in replacement for the Windows trading supervisor without review.

## Persistent state

Decide explicitly whether the new host starts clean or carries forward historical state.

Potential state includes:

- `data/trader.db`
- `data/testnet-trader.db`
- `data/futures-testnet.db`
- durable order journals / rollback metadata
- kill-switch state when operationally appropriate

Never merge ledgers across environments.

Before transferring SQLite state, stop the relevant writer cleanly and create a consistent backup. Validate restore before deleting the source copy.

## Secrets

Secrets are intentionally excluded by `.gitignore`.

Examples:

- OpenAI API key
- Binance Spot Testnet credentials
- Binance Futures Demo/Testnet credentials
- dashboard/portal secrets
- Windows device token

Transfer them through a secure channel and recreate host-local ACLs. A code backup is not a secrets backup.

## Migration validation order

1. Run `python scripts/portability_check.py`.
2. Confirm exact version and environment.
3. Validate configuration parsing without trading.
4. Validate local dashboard.
5. Validate remote-agent connectivity separately.
6. Validate Spot Testnet read/write behavior with bounded diagnostics.
7. Validate Futures Demo diagnostics separately.
8. Start the supervised engine only in the intended non-LIVE environment.
9. Observe health, ledgers and journals before considering the migration complete.

## Hosting migration

A future VPS/container/cloud migration must preserve the same invariants:

- one engine;
- one canonical persistent state location per environment;
- explicit secrets injection;
- supervised restart policy;
- durable storage;
- outbound/inbound network rules reviewed explicitly;
- signed update or equivalent controlled deployment;
- rollback and health checks;
- no implicit LIVE enablement.

Containerization is optional. Do not introduce Docker merely for appearance; use it only if it simplifies reproducibility without weakening durable storage or operational visibility.

## Future AI handover

A future AI should start from `PROJECT_HANDOVER.md`, then inspect current Git history and CI. The migration system exists to make the host replaceable; the project history exists to make the human/AI maintainer replaceable.
