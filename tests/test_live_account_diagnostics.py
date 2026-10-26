"""Synthetic coverage for bounded account diagnostics; no real keys or network."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

from trader.live_transport import (LiveCredentials, LiveError, LiveHTTPError,
                                   LiveReadOnlyTransport, MAX_ERROR_RESPONSE)
from trader.live_account import LiveAccountAudit

NOW = 1_700_000_000_000
KEY = "SyntheticKeyNeverSentToProvider"
SECRET = "SyntheticSecretNeverSentToProvider"


def pair(suffix=""):
    return LiveCredentials(KEY + suffix, SECRET + suffix)


class Body(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.sizes = []

    def read(self, size=-1):
        self.sizes.append(size)
        return super().read(size)


class Response:
    status = 200

    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.raw[:size]


class Opener:
    def __init__(self, value):
        self.value, self.requests = value, []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.value, Exception):
            raise self.value
        return Response(self.value)


class LiveHTTPDiagnosticsTests(unittest.TestCase):
    def transport(self):
        return LiveReadOnlyTransport({"FUTURES_LIVE": pair()}, max_calls=3)

    def caught_http(self, raw, status=401):
        body = Body(raw)
        error = urllib.error.HTTPError("https://example.invalid/?signature=" + SECRET,
                                       status, KEY + SECRET, {"Secret": SECRET}, body)
        opener = Opener(error)
        transport = self.transport()
        with patch.object(transport, "_opener", return_value=opener):
            with self.assertRaises(LiveHTTPError) as caught:
                transport.get("FUTURES_LIVE", "/fapi/v1/time")
        self.assertIsInstance(caught.exception, LiveError)
        self.assertTrue(body.closed)
        self.assertEqual(body.sizes, [MAX_ERROR_RESPONSE + 1])
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(opener.requests[0].get_method(), "GET")
        for text in (str(caught.exception), repr(caught.exception),
                     json.dumps(caught.exception.diagnostics())):
            self.assertNotIn(KEY, text)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("signature=", text)
        return caught.exception

    def test_authentication_error_retains_only_numerical_facts(self):
        for code in (-2014, -2015, -1022):
            with self.subTest(code=code):
                error = self.caught_http(json.dumps({"code": code, "msg": KEY + SECRET}).encode())
                self.assertEqual(str(error), "LIVE_HTTP_UNAVAILABLE")
                self.assertEqual(error.diagnostics(), {"http_status": 401, "provider_code": code})

    def test_rate_limits_keep_closed_code_and_do_not_retry(self):
        for status in (418, 429):
            with self.subTest(status=status):
                error = self.caught_http(b'{"code":-1003,"msg":"do not retry"}', status)
                self.assertEqual(str(error), "LIVE_RATE_LIMITED")
                self.assertEqual(error.diagnostics(), {"http_status": status, "provider_code": -1003})

    def test_malformed_or_oversized_error_does_not_leak_or_invent_provider_code(self):
        bodies = (b"not-json", b'{"code":-2015,"code":-2014}', b'{"code":NaN}',
                  b'{"code":true}', b'{"code":"-2015"}', b'{"code":0}',
                  b'{"code":-2147483649}', b'\xff', b'[1,2,3]',
                  b'{"code":-2015}' + b" " * MAX_ERROR_RESPONSE)
        for body in bodies:
            with self.subTest(body_length=len(body)):
                self.assertEqual(self.caught_http(body).diagnostics(), {"http_status": 401})

    def test_error_exactly_at_size_limit_is_parsed(self):
        body = b'{"code":-2015}'
        body += b" " * (MAX_ERROR_RESPONSE - len(body))
        self.assertEqual(self.caught_http(body).diagnostics()["provider_code"], -2015)

    def test_provider_error_in_success_response_has_bounded_diagnostics(self):
        transport = self.transport()
        opener = Opener({"code": -2015, "msg": KEY + SECRET})
        with patch.object(transport, "_opener", return_value=opener):
            with self.assertRaises(LiveHTTPError) as caught:
                transport.get("FUTURES_LIVE", "/fapi/v1/time")
        self.assertEqual(str(caught.exception), "LIVE_PROVIDER_REJECTED")
        self.assertEqual(caught.exception.diagnostics(), {"http_status": 200, "provider_code": -2015})
        self.assertNotIn(SECRET, repr(caught.exception))

    def test_diagnostic_constructor_and_mutations_cannot_add_unbounded_values(self):
        error = LiveHTTPError(SECRET, http_status=True, provider_code="secret")
        self.assertEqual(str(error), "LIVE_HTTP_UNAVAILABLE")
        self.assertEqual(error.diagnostics(), {})
        for status, code in ((600, -2**40), (99, 3), ("401", False), (None, None)):
            error.http_status, error.provider_code = status, code
            self.assertEqual(error.diagnostics(), {})

    def test_observation_preserves_numeric_error_and_unknown_state_without_provider_text(self):
        transport = self.transport()
        transport.get = lambda *args: (_ for _ in ()).throw(
            LiveHTTPError("LIVE_HTTP_UNAVAILABLE", http_status=401, provider_code=-2015))
        audit = LiveAccountAudit(transport, symbols=["BTCUSDT"], start_utc_ms=NOW-1000,
                                end_utc_ms=NOW, clock=lambda: NOW/1000)
        self.assertIsNone(audit._get("FUTURES_LIVE", "account", "/fapi/v3/account"))
        observation = audit.observations[0]
        self.assertEqual(observation["status"], "UNKNOWN")
        self.assertEqual(observation["code"], "LIVE_HTTP_UNAVAILABLE")
        self.assertEqual(observation["http_status"], 401)
        self.assertEqual(observation["provider_code"], -2015)
        self.assertEqual(audit._errors, ["LIVE_HTTP_UNAVAILABLE"])
        self.assertNotIn(SECRET, json.dumps(observation))
        self.assertNotIn("msg", observation)

    def test_plain_network_error_has_no_http_facts(self):
        transport = self.transport()
        with patch.object(transport, "_opener", return_value=Opener(urllib.error.URLError(SECRET))):
            with self.assertRaises(LiveError) as caught:
                transport.get("FUTURES_LIVE", "/fapi/v1/time")
        self.assertEqual(type(caught.exception), LiveError)
        self.assertEqual(str(caught.exception), "LIVE_NETWORK_UNAVAILABLE")


class TransferEnvelopeTests(unittest.TestCase):
    def history(self, envelope, **kwargs):
        transport = LiveReadOnlyTransport({"SPOT_LIVE": pair()})
        transport.get = lambda *args: envelope
        audit = LiveAccountAudit(transport, symbols=["BTCUSDT"], start_utc_ms=NOW-1000,
                                end_utc_ms=NOW, clock=lambda: NOW/1000, **kwargs)
        return audit._history("SPOT_LIVE", "MAIN_UMFUTURE", "/sapi/v1/asset/transfer",
                              {"type": "MAIN_UMFUTURE"}, pagination="current", row_key="rows")

    def test_exact_observed_empty_envelope_is_bounded_empty_window(self):
        for envelope in ({"total": 0}, {"total": 0, "rows": []}):
            with self.subTest(envelope=envelope):
                result = self.history(envelope)
                self.assertEqual(result["status"], "OBSERVED_WINDOW")
                self.assertEqual(result["rows"], 0)
                self.assertTrue(result["window_complete"])
                self.assertFalse(result["account_history_complete"])
                self.assertIsNone(result["cursor"])

    def test_missing_unknown_and_contradictory_envelopes_are_never_zero(self):
        envelopes = (None, [], {}, {"total": "0"}, {"total": False}, {"total": None},
                     {"total": -1}, {"total": 1}, {"total": 10**12+1},
                     {"total": 0, "rows": None}, {"total": 0, "rows": [{}]},
                     {"total": 1, "rows": []}, {"total": 0, "unexpected": 1},
                     {"total": 0, "code": -2015}, {"total": 0, "rows": [], "msg": SECRET})
        for envelope in envelopes:
            with self.subTest(envelope_type=type(envelope).__name__):
                result = self.history(envelope)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertFalse(result["window_complete"])
                self.assertNotIn("account_history_complete", result)
                self.assertNotIn(SECRET, json.dumps(result))

    def test_nonempty_total_must_match_observed_short_page(self):
        result = self.history({"total": 1, "rows": [{"time": NOW-500}]})
        self.assertEqual(result["status"], "OBSERVED_WINDOW")
        self.assertEqual(result["rows"], 1)
        self.assertFalse(result["account_history_complete"])

    def test_resumed_prior_rows_cannot_be_erased_by_empty_total(self):
        first = self.history({"total": 2, "rows": [{"time": NOW-500}]}, page_size=1, max_pages=1)
        self.assertFalse(first["window_complete"])
        result = self.history({"total": 0}, page_size=1,
                              cursors={"SPOT_LIVE:MAIN_UMFUTURE": first["cursor"]})
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "LIVE_HISTORY_CONTRADICTION")

    def test_empty_envelope_cannot_substitute_for_other_history_sources(self):
        transport = LiveReadOnlyTransport({"SPOT_LIVE": pair()})
        transport.get = lambda *args: {"total": 0}
        audit = LiveAccountAudit(transport, symbols=["BTCUSDT"], start_utc_ms=NOW-1000,
                                end_utc_ms=NOW, clock=lambda: NOW/1000)
        result = audit._history("SPOT_LIVE", "trades_BTCUSDT", "/api/v3/myTrades", {"symbol": "BTCUSDT"})
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["window_complete"])


class AuditScopeCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1]/"scripts/audit_live_account.py"
        spec = importlib.util.spec_from_file_location("isolated_audit_cli_diagnostics", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def invoke(self, credentials, scope=None):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/"private-output"
            argv = ["--ack-read-only", "--output-dir", str(output)]
            if scope is not None:
                argv += ["--scope", scope]
            captured = io.StringIO()
            selected = []
            def make_audit(transport, **kwargs):
                return SimpleNamespace(run=lambda: {"status":"SCOPED_OBSERVATION",
                    "wallets": {key:{} for key in selected[0]}, "calls":0})
            def make_transport(pairs, **kwargs):
                selected.append(pairs)
                return SimpleNamespace()
            with patch.object(self.module, "os", SimpleNamespace(name="nt", environ={})), \
                    patch.object(self.module, "credentials_from_environment", return_value=credentials), \
                    patch.object(self.module, "EncryptedAuditStore") as store, \
                    patch.object(self.module, "LiveReadOnlyTransport", side_effect=make_transport) as transport, \
                    patch.object(self.module, "LiveAccountAudit", side_effect=make_audit), \
                    contextlib.redirect_stdout(captured):
                code = self.module.main(argv)
            self.assertFalse(output.exists())
            self.assertNotIn(KEY, captured.getvalue())
            self.assertNotIn(SECRET, captured.getvalue())
            return code, json.loads(captured.getvalue()), selected, store.call_count, transport.call_count

    def test_explicit_scope_uses_only_its_own_pair(self):
        credentials = {"SPOT_LIVE":pair("spot"), "FUTURES_LIVE":pair("futures")}
        for scope in credentials:
            code, report, selected, _, _ = self.invoke(credentials, scope)
            self.assertEqual(code, 0)
            self.assertEqual(selected, [{scope:credentials[scope]}])
            self.assertEqual(report["scopes"], [scope])
            self.assertFalse(report["execution_enabled"])
            self.assertFalse(report["financial_authorization"])

    def test_default_preserves_both_configured_scopes(self):
        credentials = {"SPOT_LIVE":pair("spot"), "FUTURES_LIVE":pair("futures")}
        code, report, selected, _, _ = self.invoke(credentials)
        self.assertEqual(code, 0)
        self.assertEqual(selected, [credentials])
        self.assertEqual(report["scopes"], sorted(credentials))

    def test_missing_requested_scope_fails_before_artifacts_or_network(self):
        code, report, selected, store_calls, transport_calls = self.invoke({"SPOT_LIVE":pair()}, "FUTURES_LIVE")
        self.assertEqual(code, 2)
        self.assertEqual(report["code"], "LIVE_REQUESTED_SCOPE_NOT_CONFIGURED")
        self.assertEqual(selected, [])
        self.assertEqual(store_calls, 0)
        self.assertEqual(transport_calls, 0)

    def test_malformed_argv_never_repeats_supplied_values(self):
        marker = "SYNTHETIC_ARGUMENT_VALUE_MUST_NOT_BE_LOGGED"
        cases = (["--api-key", marker], ["--scope", marker], ["--max-calls", marker])
        for extra in cases:
            with self.subTest(option=extra[0]):
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(self.module, "LiveReadOnlyTransport") as network, \
                        patch.object(self.module, "EncryptedAuditStore") as store, \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as caught:
                        self.module.main(["--ack-read-only", "--output-dir", "synthetic-unused", *extra])
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(stderr.getvalue(), "LIVE_AUDIT_ARGUMENTS_INVALID\n")
                self.assertEqual(stdout.getvalue(), "")
                self.assertNotIn(marker, stderr.getvalue())
                network.assert_not_called()
                store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
