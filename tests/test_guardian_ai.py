"""Guardian advisory-client tests: fake transport/key/clock, synthetic DBs only.

Pricing assertions freeze the official 2026-10-18 standard short-context rates;
tests never verify account access or make a real API request.
"""
import copy
from contextlib import closing
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from trader import guardian_ai as ai
from trader.guardian_intelligence import build_intelligence
from tests.test_guardian_intelligence import NOW, capture

FAKE_KEY = "synthetic-test-credential-never-a-real-key"


def report(at=NOW, identity=None):
    result = build_intelligence(capture())
    result["captured_at"] = datetime.fromtimestamp(at, UTC).isoformat()
    if identity is not None:
        result["assessment_id"] = hashlib.sha256(str(identity).encode()).hexdigest()
    return result


def advisory(identity):
    return {"summary": "Observación simulada; revisar la evidencia disponible.", "posture": "OBSERVE",
            "cautions": ["El alcance no certifica una cuenta reconciliada."], "evidence_ids": [identity]}


def response_body(request, *, usage=True):
    context = json.loads(json.loads(request.data)["input"])
    result = {"status": "completed", "output_text": json.dumps(advisory(context["assessment_id"]))}
    if usage:
        result["usage"] = {"input_tokens": 120, "output_tokens": 40,
                           "input_tokens_details": {"cached_tokens": 20}}
    return result


class Clock:
    def __init__(self, now=NOW):
        self.now = now
    def __call__(self):
        return self.now


class Response:
    def __init__(self, raw):
        self.raw, self.read_limit = raw, None
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        self.read_limit = limit
        return self.raw[:limit]


class FakeOpener:
    def __init__(self, behavior=None):
        self.behavior = behavior or response_body
        self.calls, self.responses = [], []
        self.lock = threading.Lock()
    def __call__(self, request, *, timeout):
        with self.lock:
            self.calls.append((request, timeout))
        value = self.behavior(request)
        if isinstance(value, Exception):
            raise value
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        result = Response(raw)
        self.responses.append(result)
        return result


class GuardianAITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": FAKE_KEY})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.transport_guard = patch("urllib.request.urlopen", side_effect=AssertionError("real transport forbidden"))
        self.transport_guard.start()
        self.addCleanup(self.transport_guard.stop)
        self.count = 0

    def reviewer(self, *, opener=None, cap=2, folder=None, model="gpt-6-luna"):
        self.count += 1
        directory = self.root/(folder or str(self.count))
        return ai.GuardianAIReviewer(directory, model=model, daily_cap=cap, clock=self.clock,
                                     opener=opener or FakeOpener())

    def rows(self, reviewer):
        with closing(sqlite3.connect(reviewer.path)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM guardian_ai_attempts ORDER BY id")]

    def write_attempt(self, reviewer, *, at=None, outcome="CLAIMED", reserved=.001, cost=None):
        at = self.clock()-4000 if at is None else at
        day = datetime.fromtimestamp(at, UTC).date().isoformat()
        with closing(sqlite3.connect(reviewer.path)) as db, db:
            db.execute("INSERT INTO guardian_ai_attempts(at,day,fingerprint,assessment_id,model,outcome,reserved_estimate_usd,estimated_cost_usd) VALUES(?,?,?,?,?,?,?,?)",
                       (at, day, "synthetic", "a"*64, reviewer.model, outcome, reserved, cost))

    def test_default_zero_and_missing_key_never_call_provider_or_consume_budget(self):
        opener = FakeOpener()
        default = ai.GuardianAIReviewer(self.root/"default", clock=self.clock, opener=opener)
        self.assertEqual(default(report())["reason"], "AI_DISABLED_OR_UNAVAILABLE")
        self.assertEqual(default.health()["daily_cap"], 0)
        self.assertEqual(self.rows(default), [])
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            no_key = self.reviewer(opener=opener)
        self.assertEqual(no_key(report())["reason"], "AI_DISABLED_OR_UNAVAILABLE")
        self.assertEqual(opener.calls, [])

    def test_request_is_strict_bounded_no_tools_no_storage_no_fast_or_arbitrary_urls(self):
        opener = FakeOpener()
        reviewer = self.reviewer(opener=opener)
        value = report()
        before = copy.deepcopy(value)
        result = reviewer(value)
        self.assertEqual(result["state"], "COMPLETED")
        request, timeout = opener.calls[0]
        payload = json.loads(request.data)
        context = json.loads(payload["input"])
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, 8)
        self.assertIs(payload["store"], False)
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["max_output_tokens"], 512)
        self.assertIs(payload["text"]["format"]["strict"], True)
        self.assertIs(payload["text"]["format"]["schema"]["additionalProperties"], False)
        self.assertEqual(set(payload["text"]["format"]["schema"]["required"]), {"summary", "posture", "cautions", "evidence_ids"})
        for field in ("tools", "tool_choice", "service_tier", "background", "previous_response_id"):
            self.assertNotIn(field, payload)
        self.assertEqual(context["evidence_ids"], [value["assessment_id"]])
        self.assertNotIn(FAKE_KEY, request.data.decode())
        self.assertLessEqual(len(payload["input"].encode()), reviewer.MAX_INPUT_BYTES)
        self.assertEqual(value, before)

    def test_nested_output_text_is_supported_without_using_other_output_types(self):
        def body(request):
            value = response_body(request)
            text = value.pop("output_text")
            value["output"] = [{"type": "message", "content": [{"type": "output_text", "text": text}]}]
            return value
        result = self.reviewer(opener=FakeOpener(body))(report())
        self.assertEqual(result["state"], "COMPLETED")

    def test_refusal_incomplete_and_invalid_json_fail_closed_and_consume_attempt(self):
        def mixed(request):
            value = response_body(request)
            value["output"] = [{"type": "message", "content": [{"type": "refusal", "refusal": "Synthetic refusal"}]}]
            return value
        cases = [lambda request: b"{", lambda request: [],
                 lambda request: {"status": "incomplete", "output_text": "{}"},
                 lambda request: {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Synthetic"}]}]},
                 mixed]
        for behavior in cases:
            opener = FakeOpener(behavior)
            reviewer = self.reviewer(opener=opener)
            with self.subTest(behavior=cases.index(behavior)):
                result = reviewer(report())
                self.assertEqual(result["state"], "UNAVAILABLE")
                rows = self.rows(reviewer)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["outcome"], "FAILED")
                self.assertGreater(rows[0]["reserved_estimate_usd"], 0)
                self.assertIsNone(rows[0]["estimated_cost_usd"])
                self.assertFalse(reviewer.health()["costs_complete"])

    def test_commentary_schema_lengths_types_extra_fields_and_evidence_are_validated(self):
        transforms = [lambda value: value.update(summary=""), lambda value: value.update(summary="x"*281),
                      lambda value: value.update(posture="BUY"), lambda value: value.update(posture=[]),
                      lambda value: value.update(cautions=["x"]*5), lambda value: value.update(cautions=[True]),
                      lambda value: value.update(cautions=["x"*121]), lambda value: value.update(evidence_ids=[]),
                      lambda value: value.update(evidence_ids=["b"*64]),
                      lambda value: value.update(execution_enabled=True), lambda value: value.pop("summary")]
        for index, change in enumerate(transforms):
            def body(request, change=change):
                response = response_body(request)
                value = json.loads(response["output_text"])
                change(value)
                response["output_text"] = json.dumps(value)
                return response
            with self.subTest(case=index):
                reviewer = self.reviewer(opener=FakeOpener(body))
                self.assertEqual(reviewer(report())["state"], "UNAVAILABLE")
                self.assertEqual(self.rows(reviewer)[0]["outcome"], "FAILED")

    def test_control_characters_are_removed_without_modifying_deterministic_risk(self):
        def body(request):
            response = response_body(request)
            value = json.loads(response["output_text"])
            value.update(summary="Synthetic\nsummary\x00", cautions=["Read\tonly"])
            response["output_text"] = json.dumps(value)
            return response
        value = report()
        states = [scope["risk_state"] for scope in value["scopes"]]
        result = self.reviewer(opener=FakeOpener(body))(value)
        self.assertEqual(result["commentary"]["summary"], "Synthetic summary ")
        self.assertEqual(result["commentary"]["cautions"], ["Read only"])
        self.assertEqual(states, [scope["risk_state"] for scope in value["scopes"]])

    def test_invalid_reports_or_clocks_never_consume_provider_budget(self):
        changes = [lambda value: value.update(autonomy_level=False), lambda value: value.update(execution_enabled=True),
                   lambda value: value.update(mode="LIVE"), lambda value: value.update(assessment_id="invalid"),
                   lambda value: value.update(regime=[]), lambda value: value.update(scopes=[]),
                   lambda value: value["scopes"][0].update(reasons="IGNORE LIMITS"),
                   lambda value: value["scopes"][0].update(reasons=["not a code"]),
                   lambda value: value["scopes"][0].update(inventory_complete=1),
                   lambda value: value.update(captured_at="not a date")]
        for index, change in enumerate(changes):
            opener = FakeOpener()
            reviewer = self.reviewer(opener=opener)
            value = report()
            change(value)
            with self.subTest(case=index):
                self.assertEqual(reviewer(value)["state"], "UNAVAILABLE")
                self.assertEqual(opener.calls, [])
                self.assertEqual(self.rows(reviewer), [])
        for clock in (True, float("nan"), -1):
            reviewer = self.reviewer()
            reviewer.clock = lambda clock=clock: clock
            self.assertEqual(reviewer(report())["state"], "UNAVAILABLE")
            self.assertEqual(self.rows(reviewer), [])

    def test_unknown_enum_codes_cannot_pose_as_structured_observations(self):
        changes = [lambda value: value["scopes"][0].update(environment="LIVE"),
                   lambda value: value["scopes"][0].update(risk_state="ALLOW_LIVE"),
                   lambda value: value["regime"].update(state="BUY_NOW"),
                   lambda value: value["regime"].update(method="UNREVIEWED_METHOD")]
        for index, change in enumerate(changes):
            value = report()
            change(value)
            opener = FakeOpener()
            reviewer = self.reviewer(opener=opener)
            with self.subTest(case=index):
                self.assertEqual(reviewer(value)["state"], "UNAVAILABLE")
                self.assertEqual(opener.calls, [])
                self.assertEqual(self.rows(reviewer), [])

    def test_late_future_or_timezone_naive_assessments_are_rejected_before_claim(self):
        for instant in (NOW-121, NOW+1):
            opener = FakeOpener()
            reviewer = self.reviewer(opener=opener)
            self.assertEqual(reviewer(report(at=instant))["reason"], "ASSESSMENT_STALE_OR_FUTURE")
            self.assertEqual(opener.calls, [])
        value = report()
        value["captured_at"] = "2027-01-15T08:00:10"
        reviewer = self.reviewer()
        self.assertEqual(reviewer(value)["reason"], "ASSESSMENT_STALE_OR_FUTURE")
        self.assertEqual(self.rows(reviewer), [])

    def test_durable_failed_and_unknown_claims_are_not_released_or_retried_after_restart(self):
        opener = FakeOpener(lambda request: TimeoutError("synthetic request may have reached provider"))
        first = self.reviewer(opener=opener, cap=1, folder="restart")
        self.assertEqual(first(report())["state"], "UNAVAILABLE")
        self.clock.now += 3601
        restarted = self.reviewer(opener=opener, cap=1, folder="restart")
        self.assertEqual(restarted(report(at=self.clock(), identity="new"))["reason"], "AI_BUDGET_OR_INTERVAL")
        self.assertEqual(len(opener.calls), 1)
        unknown = self.reviewer(opener=opener, cap=1)
        self.write_attempt(unknown, outcome="CLAIMED")
        self.assertEqual(unknown(report(at=self.clock()))["reason"], "AI_BUDGET_OR_INTERVAL")
        self.assertEqual(self.rows(unknown)[0]["outcome"], "CLAIMED")
        self.assertFalse(unknown.health()["costs_complete"])

    def test_concurrent_instances_commit_one_claim_before_transport(self):
        entered, release = threading.Event(), threading.Event()
        def body(request):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("synthetic transport gate")
            return response_body(request)
        opener = FakeOpener(body)
        first = self.reviewer(opener=opener, folder="concurrent")
        second = self.reviewer(opener=opener, folder="concurrent")
        output = []
        thread = threading.Thread(target=lambda: output.append(first(report())))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            rows = self.rows(first)
            self.assertEqual((len(rows), rows[0]["outcome"]), (1, "CLAIMED"))
            other = second(report(identity="competing"))
            self.assertEqual(other["state"], "UNAVAILABLE")
            self.assertEqual(len(opener.calls), 1)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(output[0]["state"], "COMPLETED")

    def test_cache_is_historical_pinned_and_never_consumes_an_extra_attempt(self):
        opener = FakeOpener()
        reviewer = self.reviewer(opener=opener)
        first = reviewer(report())
        self.clock.now += 30
        cached = reviewer(report(at=self.clock(), identity="different-current-assessment"))
        self.assertEqual(cached["state"], "CACHED_HISTORICAL")
        self.assertEqual(cached["assessment_id"], first["assessment_id"])
        self.assertEqual(cached["commentary"]["evidence_ids"], [first["assessment_id"]])
        self.assertEqual(cached["at"], first["at"])
        self.assertEqual(cached["cache_age_seconds"], 30)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(len(self.rows(reviewer)), 1)

    def test_expired_cache_obeys_interval_and_daily_budget_and_day_rollover(self):
        opener = FakeOpener()
        reviewer = self.reviewer(opener=opener)
        self.assertEqual(reviewer(report())["state"], "COMPLETED")
        self.clock.now += 901
        self.assertEqual(reviewer(report(at=self.clock()))["reason"], "AI_BUDGET_OR_INTERVAL")
        self.clock.now = NOW+3601
        self.assertEqual(reviewer(report(at=self.clock()))["state"], "COMPLETED")
        self.clock.now = NOW+7202
        self.assertEqual(reviewer(report(at=self.clock()))["reason"], "AI_BUDGET_OR_INTERVAL")
        self.clock.now = NOW+86400
        self.assertEqual(reviewer(report(at=self.clock()))["state"], "COMPLETED")
        self.assertEqual(len(self.rows(reviewer)), 3)
        self.assertEqual(reviewer.health()["used_today"], 1)

    def test_policy_schema_or_price_changes_invalidate_historical_cache(self):
        opener = FakeOpener()
        reviewer = self.reviewer(opener=opener)
        reviewer(report())
        self.clock.now += 30
        for target, value in (("INSTRUCTIONS", ai.INSTRUCTIONS+" New policy revision."),
                              ("SCHEMA", {**ai.SCHEMA, "description": "new schema revision"}),
                              ("PRICE", {**ai.PRICE, "verified_at": "new-verification"})):
            with patch.object(ai, target, value):
                self.assertEqual(reviewer(report(at=self.clock()))["state"], "UNAVAILABLE")
        self.assertEqual(len(opener.calls), 1)

    def test_tampered_cached_authority_model_identity_schema_and_evidence_are_rejected(self):
        reviewer = self.reviewer()
        original = reviewer(report())
        self.clock.now += 30
        transforms = [lambda value: value.update(execution_enabled=True), lambda value: value.update(controls_enabled=0),
                      lambda value: value.update(advisory_only=1), lambda value: value.update(model="invalid-model"),
                      lambda value: value.update(assessment_id="b"*64), lambda value: value.update(state="OPEN_ORDER"),
                      lambda value: value["commentary"].update(evidence_ids=["b"*64]),
                      lambda value: value["commentary"].update(order="BUY")]
        for index, change in enumerate(transforms):
            value = copy.deepcopy(original)
            change(value)
            with closing(sqlite3.connect(reviewer.path)) as db, db:
                db.execute("UPDATE guardian_ai_attempts SET result=?", (json.dumps(value),))
            with self.subTest(case=index):
                result = reviewer(report(at=self.clock()))
                self.assertEqual(result["state"], "UNAVAILABLE")
                self.assertIs(result["execution_enabled"], False)

    def test_cache_selection_is_bound_to_original_model_column(self):
        opener = FakeOpener()
        reviewer = self.reviewer(opener=opener)
        reviewer(report())
        with closing(sqlite3.connect(reviewer.path)) as db, db:
            db.execute("UPDATE guardian_ai_attempts SET model='other-model'")
        self.clock.now += 30
        self.assertEqual(reviewer(report(at=self.clock()))["state"], "UNAVAILABLE")
        self.assertEqual(len(opener.calls), 1)

    def test_unknown_cached_fields_cannot_leak_private_values(self):
        reviewer = self.reviewer()
        original = reviewer(report())
        original["private_internal_value"] = "synthetic-private-content-not-for-projection"
        with closing(sqlite3.connect(reviewer.path)) as db, db:
            db.execute("UPDATE guardian_ai_attempts SET result=?", (json.dumps(original),))
        self.clock.now += 30
        result = reviewer(report(at=self.clock()))
        self.assertNotIn("private_internal_value", result)
        self.assertNotIn("synthetic-private-content-not-for-projection", json.dumps(result))

    def test_cached_invalid_usage_and_future_record_time_are_not_current_facts(self):
        reviewer = self.reviewer()
        original = reviewer(report())
        self.clock.now += 30
        transforms = [lambda value: value["usage"].update(estimated_cost_usd=-1),
                      lambda value: value["usage"].update(input_tokens=True),
                      lambda value: value.update(at="invalid-time"),
                      lambda value: value.update(at=datetime.fromtimestamp(NOW+900, UTC).isoformat())]
        for index, change in enumerate(transforms):
            value = copy.deepcopy(original)
            change(value)
            with closing(sqlite3.connect(reviewer.path)) as db, db:
                db.execute("UPDATE guardian_ai_attempts SET result=?", (json.dumps(value),))
            with self.subTest(case=index):
                self.assertEqual(reviewer(report(at=self.clock()))["state"], "UNAVAILABLE")

    def test_http_and_parse_errors_never_persist_or_return_secret_response_bodies(self):
        behaviors = [lambda request: URLError("synthetic error "+FAKE_KEY),
                     lambda request: HTTPError(request.full_url, 401, FAKE_KEY, {}, None),
                     lambda request: ("invalid-json "+FAKE_KEY).encode()]
        for behavior in behaviors:
            reviewer = self.reviewer(opener=FakeOpener(behavior))
            result = reviewer(report())
            self.assertEqual(result["state"], "UNAVAILABLE")
            self.assertNotIn(FAKE_KEY, json.dumps(result))
            self.assertNotIn(FAKE_KEY, reviewer.path.read_bytes().decode("latin1"))

    def test_reflected_credential_in_valid_commentary_is_not_persisted_or_exposed(self):
        def body(request):
            response = response_body(request)
            value = json.loads(response["output_text"])
            value["summary"] = "Provider reflection: "+FAKE_KEY
            response["output_text"] = json.dumps(value)
            return response
        reviewer = self.reviewer(opener=FakeOpener(body))
        result = reviewer(report())
        self.assertNotIn(FAKE_KEY, json.dumps(result))
        self.assertNotIn(FAKE_KEY, reviewer.path.read_bytes().decode("latin1"))

    def test_response_byte_limit_timeout_and_redirect_refusal_are_enforced(self):
        opener = FakeOpener(lambda request: b"x"*(ai.GuardianAIReviewer.MAX_RESPONSE_BYTES+10))
        reviewer = self.reviewer(opener=opener)
        self.assertEqual(reviewer(report())["state"], "UNAVAILABLE")
        self.assertEqual(opener.responses[0].read_limit, reviewer.MAX_RESPONSE_BYTES+1)
        self.assertEqual(opener.calls[0][1], 8)
        with self.assertRaises(HTTPError):
            ai._NoRedirect().redirect_request(opener.calls[0][0], None, 302, "redirect", {}, "https://untrusted.invalid")

    def test_verified_model_prices_and_constructor_caps_never_select_or_upgrade_model(self):
        self.assertEqual({key: ai.PRICE[key] for key in ("model", "input_per_million_usd", "cached_input_per_million_usd", "cache_write_per_million_usd", "output_per_million_usd")},
                         {"model": "gpt-6-luna", "input_per_million_usd": .10, "cached_input_per_million_usd": .01, "cache_write_per_million_usd": .125, "output_per_million_usd": .50})
        self.assertEqual(ai.PRICE["source"], "https://developers.openai.com/api/docs/models/gpt-6-luna")
        for cap in (True, -1, 3, 2.0):
            with self.assertRaises(ValueError):
                self.reviewer(cap=cap)
        opener = FakeOpener()
        unverified = self.reviewer(model="gpt-unverified", opener=opener)
        self.assertEqual(unverified(report())["reason"], "MODEL_PRICING_NOT_VERIFIED")
        self.assertEqual(opener.calls, [])

    def test_usage_estimates_use_reported_cached_tokens_without_claiming_invoice_accuracy(self):
        reviewer = self.reviewer()
        result = reviewer(report())
        expected = (100*.10+20*.01+40*.50)/1_000_000
        self.assertAlmostEqual(result["usage"]["estimated_cost_usd"], expected)
        self.assertEqual(result["usage"]["cached_tokens"], 20)
        self.assertAlmostEqual(reviewer.health()["known_estimated_cost_usd"], expected)
        self.assertTrue(reviewer.health()["costs_complete"])
        self.assertGreater(self.rows(reviewer)[0]["reserved_estimate_usd"], expected)

    def test_missing_or_malformed_usage_keeps_costs_unknown_without_fabricating_zero(self):
        for usage in (None, {}, {"input_tokens": True, "output_tokens": 10},
                      {"input_tokens": -1, "output_tokens": 20}, {"input_tokens": 100, "output_tokens": "20"}):
            def body(request, usage=usage):
                value = response_body(request, usage=False)
                if usage is not None:
                    value["usage"] = usage
                return value
            reviewer = self.reviewer(opener=FakeOpener(body))
            result = reviewer(report())
            self.assertEqual(result["state"], "COMPLETED")
            self.assertIsNone(result["usage"]["estimated_cost_usd"])
            self.assertIsNone(reviewer.health()["known_estimated_cost_usd"])
            self.assertFalse(reviewer.health()["costs_complete"])

    def test_unknown_cached_token_details_do_not_silently_assume_zero_cached_usage(self):
        for details in (None, [], {"cached_tokens": True}, {"cached_tokens": -1}, {"cached_tokens": 121}):
            def body(request, details=details):
                value = response_body(request)
                value["usage"]["input_tokens_details"] = details
                return value
            reviewer = self.reviewer(opener=FakeOpener(body))
            result = reviewer(report())
            self.assertEqual(result["state"], "COMPLETED")
            self.assertIsNone(result["usage"]["cached_tokens"])
            self.assertIsNone(result["usage"]["estimated_cost_usd"])
            self.assertFalse(reviewer.health()["costs_complete"])

    def test_mixed_known_and_unknown_costs_never_claim_complete_billing_evidence(self):
        reviewer = self.reviewer()
        reviewer(report())
        self.write_attempt(reviewer, outcome="FAILED")
        health = reviewer.health()
        self.assertEqual(health["used_today"], 2)
        self.assertIsNotNone(health["known_estimated_cost_usd"])
        self.assertFalse(health["costs_complete"])

    def test_estimated_reserve_rejects_admission_but_is_not_released_when_outcome_unknown(self):
        reviewer = self.reviewer()
        self.write_attempt(reviewer, reserved=.0099)
        before = reviewer.health()["reserved_estimate_usd"]
        self.assertEqual(reviewer(report())["reason"], "AI_BUDGET_OR_INTERVAL")
        self.assertEqual(reviewer.health()["reserved_estimate_usd"], before)
        self.assertEqual(self.rows(reviewer)[0]["outcome"], "CLAIMED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
