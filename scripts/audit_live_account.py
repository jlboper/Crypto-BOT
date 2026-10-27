"""Explicit production GET-only audit; no activation or trading command."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hmac
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trader.live_account import (LiveAccountAudit, EncryptedAuditStore, audit_directory,
    credentials_from_environment, publish_connection_status)
from trader.live_transport import LiveError, LiveReadOnlyTransport


class ClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # An accidentally pasted credential must not be repeated in an argv error.
        self.exit(2, "LIVE_AUDIT_ARGUMENTS_INVALID\n")


def main(argv=None):
    parser = ClosedArgumentParser(description="LIVE account observation: GET only, no orders or allocation")
    parser.add_argument("--ack-read-only", action="store_true", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--vault", type=Path, help="Explicit current-user Windows DPAPI LIVE credential vault")
    parser.add_argument("--scope", choices=("SPOT_LIVE", "FUTURES_LIVE"),
                        help="Audit only this explicitly configured scope; never substitute another key")
    parser.add_argument("--verify-account-link", action="store_true",
                        help="Explicit global UID/key-rights GETs with both distinct credential origins; no wallet pooling")
    parser.add_argument("--publish-connection-status", action="store_true",
                        help="With --verify-account-link and --vault: write bounded observation cache, never financial readiness")
    parser.add_argument("--start-utc-ms", type=int)
    parser.add_argument("--end-utc-ms", type=int)
    parser.add_argument("--max-calls", type=int, default=80)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--resume", type=Path, help="Previous sanitized audit.json with matching scope/window")
    args = parser.parse_args(argv)
    try:
        if args.publish_connection_status and not args.verify_account_link:
            raise LiveError("LIVE_ACCOUNT_LINK_REQUIRED_FOR_STATUS")
        if args.publish_connection_status and args.vault is None:
            raise LiveError("LIVE_ACCOUNT_STATUS_REQUIRES_VAULT")
        if args.verify_account_link and args.scope is not None:
            raise LiveError("LIVE_ACCOUNT_LINK_REQUIRES_BOTH_SCOPES")
        if os.name != "nt":
            raise LiveError("WINDOWS_DPAPI_REQUIRED_FOR_RAW_RETENTION")
        if args.vault:
            from trader.live_credentials import LiveCredentialVault
            vault = LiveCredentialVault(args.vault)
            credentials = vault.read()
        else:
            credentials = credentials_from_environment(os.environ)
        if args.verify_account_link:
            if set(credentials) != {"SPOT_LIVE", "FUTURES_LIVE"}:
                raise LiveError("LIVE_ACCOUNT_LINK_REQUIRES_BOTH_SCOPES")
            if len({pair.fingerprint() for pair in credentials.values()}) != 2:
                raise LiveError("LIVE_ACCOUNT_LINK_REQUIRES_DISTINCT_KEYS")
        if args.scope is not None:
            if args.scope not in credentials:
                raise LiveError("LIVE_REQUESTED_SCOPE_NOT_CONFIGURED")
            credentials = {args.scope: credentials[args.scope]}
        cursors = {}
        prior_window = None
        if args.resume:
            if args.resume.stat().st_size > 4_194_304:
                raise LiveError("LIVE_RESUME_SIZE_LIMIT")
            previous = json.loads(args.resume.read_text(encoding="utf-8"))
            if type(previous) is not dict or previous.get("schema") != "live-account-audit/v1":
                raise LiveError("LIVE_RESUME_INVALID")
            prior_window = previous.get("history_window")
            if type(prior_window) is not dict:
                raise LiveError("LIVE_RESUME_INVALID")
            for scope, wallet in previous.get("wallets", {}).items():
                for name, item in wallet.get("history", {}).items():
                    if item.get("cursor") is not None:
                        cursors[scope + ":" + name] = item["cursor"]
        def utc_ms(value):
            if type(value) is not str or not value.endswith("Z"):
                raise LiveError("LIVE_RESUME_INVALID")
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        end = args.end_utc_ms if args.end_utc_ms is not None else (utc_ms(prior_window["end_utc"]) if prior_window else int(time.time() * 1000))
        start = args.start_utc_ms if args.start_utc_ms is not None else (utc_ms(prior_window["start_utc"]) if prior_window else end - 86_400_000)
        symbols = args.symbols.split(",") if args.symbols is not None else (prior_window["symbols"] if prior_window else ["BTCUSDT", "ETHUSDT"])
        directory = audit_directory(args.output_dir)
        store = EncryptedAuditStore(directory)
        audit = LiveAccountAudit(LiveReadOnlyTransport(credentials, max_calls=args.max_calls),
            symbols=symbols, start_utc_ms=start, end_utc_ms=end,
            max_pages=args.max_pages, page_size=args.page_size, cursors=cursors, raw_store=store,
            verify_account_link=args.verify_account_link)
        report = audit.run()
        connection = None
        if args.publish_connection_status:
            # Credential replacement invalidates this cache under the same vault
            # lock. Keep VAULT -> CACHE order and reject any audit of old pairs,
            # including a secret-only replacement with an unchanged API key.
            with vault._write_lock():
                current = vault.read()
                unchanged = set(current) == set(credentials) and all([
                    hmac.compare_digest(current[scope].api_key, credentials[scope].api_key)
                    & hmac.compare_digest(current[scope].api_secret, credentials[scope].api_secret)
                    for scope in credentials])
                if not unchanged:
                    raise LiveError("LIVE_CREDENTIALS_CHANGED_DURING_AUDIT")
                connection = publish_connection_status(report, ROOT/"data")
        print(json.dumps({"status": report["status"], "report": str(directory / "audit.json"),
            "scopes": sorted(report["wallets"]), "calls": report["calls"], "account_history_complete": False,
            "execution_enabled": False, "financial_authorization": False,
            **({"account_link_status":report["account_link"]["status"]} if args.verify_account_link else {}),
            **({"connection_status":connection["state"]} if connection is not None else {})}, ensure_ascii=True))
        return 0
    except (LiveError, ValueError, OSError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, LiveError) else "LIVE_AUDIT_LOCAL_INPUT_ERROR"
        print(json.dumps({"status": "BLOCKED", "code": code, "execution_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
