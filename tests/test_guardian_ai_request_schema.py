"""Advisory schema regression: synthetic DBs, fake credential and transport only.

No provider acceptance or successful operational commentary is inferred from
these tests. String lengths stay strictly enforced by the local validator.
"""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trader import guardian_ai as ai
from trader import guardian_shadow
from tests.test_guardian_ai import FAKE_KEY, FakeOpener, NOW, report, response_body


class GuardianAIRequestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.counter = 0
        environment = patch.dict(os.environ, {"OPENAI_API_KEY": FAKE_KEY}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        transport = patch("socket.create_connection", side_effect=AssertionError("REAL_NETWORK_FORBIDDEN"))
        transport.start()
        self.addCleanup(transport.stop)

    def invoke(self, change=None, *, assessment=None, folder=None, clock=NOW):
        def body(request):
            response = response_body(request)
            value = json.loads(response.pop("output_text"))
            if change is not None:
                change(value)
            response["output"] = [
                {"type": "reasoning", "summary": []},
                {"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": json.dumps(value)}]},
            ]
            return response
        self.counter += 1
        opener = FakeOpener(body)
        reviewer = ai.GuardianAIReviewer(self.root/(folder or str(self.counter)),
            daily_cap=2, clock=lambda: clock, opener=opener)
        assessed = report(at=clock) if assessment is None else copy.deepcopy(assessment)
        result = reviewer(assessed)
        with closing(sqlite3.connect(reviewer.path)) as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("SELECT * FROM guardian_ai_attempts ORDER BY id")]
        return result, rows, opener, reviewer

    def test_provider_schema_binds_evidence_and_numeric_limits_without_authority_changes(self):
        assessed = report()
        before = copy.deepcopy(assessed)
        result, _, opener, reviewer = self.invoke(assessment=assessed)
        self.assertEqual(result["state"], "COMPLETED")
        request, timeout = opener.calls[0]
        payload = json.loads(request.data)
        context = json.loads(payload["input"])
        schema = payload["text"]["format"]["schema"]
        self.assertEqual(schema["properties"]["evidence_ids"]["items"]["enum"], [assessed["assessment_id"]])
        self.assertEqual(context["evidence_ids"], [assessed["assessment_id"]])
        self.assertEqual(schema["properties"]["evidence_ids"]["minItems"], 1)
        self.assertEqual(schema["properties"]["evidence_ids"]["maxItems"], 4)
        self.assertEqual(schema["properties"]["cautions"]["maxItems"], 4)
        self.assertIn("280", schema["properties"]["summary"]["description"])
        self.assertIn("120", schema["properties"]["cautions"]["items"]["description"])
        self.assertIn("280", payload["instructions"])
        self.assertIn("120", payload["instructions"])
        self.assertEqual(timeout, 8)
        self.assertEqual(payload["max_output_tokens"], 512)
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertIs(payload["store"], False)
        self.assertIs(payload["text"]["format"]["strict"], True)
        self.assertNotIn("tools", payload)
        self.assertIs(result["execution_enabled"], False)
        self.assertIs(result["controls_enabled"], False)
        self.assertEqual(assessed, before)
        self.assertEqual(reviewer.MAX_INPUT_BYTES, 4096)
        self.assertEqual(reviewer.MAX_RESPONSE_BYTES, 32768)
        self.assertEqual(reviewer.MAX_REVIEWS_PER_DAY, 2)
        self.assertEqual(reviewer.MIN_INTERVAL_SECONDS, 3600)
        self.assertEqual(reviewer.CACHE_TTL_SECONDS, 900)

    def test_schema_uses_only_documented_subset_without_ambiguous_length_patterns(self):
        allowed = {"type", "properties", "required", "additionalProperties", "description",
                   "enum", "items", "minItems", "maxItems"}
        def check(schema):
            self.assertTrue(set(schema).issubset(allowed))
            for value in schema.get("properties", {}).values():
                check(value)
            if "items" in schema:
                check(schema["items"])
        check(ai._request_schema([report()["assessment_id"]]))

    def test_invalid_empty_duplicate_or_excess_request_evidence_is_never_repaired(self):
        identities = ["a"*64, "b"*64, "c"*64, "d"*64]
        for supplied in ([], (), [""], [0], [True], ["not-an-assessment"],
                         ["a"*64, "a"*64], identities+["e"*64]):
            with self.subTest(supplied=supplied):
                before = copy.deepcopy(supplied)
                with self.assertRaises(ValueError):
                    ai._request_schema(supplied)
                self.assertEqual(supplied, before)
        schema = ai._request_schema(identities)
        identities.pop()
        self.assertEqual(len(schema["properties"]["evidence_ids"]["items"]["enum"]), 4)
        self.assertNotIn("enum", ai.SCHEMA["properties"]["evidence_ids"]["items"])

    def test_schema_is_per_assessment_and_does_not_mutate_or_reuse_previous_ids(self):
        schemas = []
        for identity in ("a"*64, "b"*64):
            assessed = report()
            assessed["assessment_id"] = identity
            result, _, opener, _ = self.invoke(assessment=assessed)
            schemas.append(json.loads(opener.calls[0][0].data)["text"]["format"]["schema"])
            self.assertEqual(result["commentary"]["evidence_ids"], [identity])
        self.assertEqual(schemas[0]["properties"]["evidence_ids"]["items"]["enum"], ["a"*64])
        self.assertEqual(schemas[1]["properties"]["evidence_ids"]["items"]["enum"], ["b"*64])
        self.assertNotIn("enum", ai.SCHEMA["properties"]["evidence_ids"]["items"])

    def test_oversize_or_unbound_model_output_is_still_rejected_and_usage_preserved(self):
        changes = [lambda v: v.update(summary=""), lambda v: v.update(summary="x"*281),
            lambda v: v.update(cautions=["x"]*5), lambda v: v.update(cautions=["x"*121]),
            lambda v: v.update(evidence_ids=[]), lambda v: v.update(evidence_ids=["b"*64]),
            lambda v: v.update(evidence_ids=[report()["assessment_id"]]*5)]
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                result, rows, opener, _ = self.invoke(change)
                self.assertEqual(result["reason"], "AI_COMMENTARY_INVALID")
                self.assertEqual((len(rows), len(opener.calls)), (1, 1))
                self.assertEqual(rows[0]["outcome"], "FAILED")
                self.assertIsNone(rows[0]["result"])
                self.assertEqual((rows[0]["input_tokens"], rows[0]["output_tokens"]), (120, 40))
                self.assertIsNotNone(rows[0]["estimated_cost_usd"])

    def test_unicode_and_newline_limits_use_code_points_and_preserve_existing_sanitization(self):
        for summary in ("x"*280, "é"*280, "😀"*280, "e\u0301"*140, "x"*278+"\r\n"):
            with self.subTest(summary_length=len(summary)):
                result = self.invoke(lambda v, text=summary: v.update(summary=text, cautions=[]))[0]
                self.assertEqual(result["state"], "COMPLETED")
                self.assertEqual(len(result["commentary"]["summary"]), 280)
                self.assertNotIn("\r", result["commentary"]["summary"])
                self.assertNotIn("\n", result["commentary"]["summary"])
        for summary in ("x"*281, "é"*281, "😀"*281, "e\u0301"*140+"e", "x"*280+"\n"):
            with self.subTest(rejected_length=len(summary)):
                self.assertEqual(self.invoke(lambda v, text=summary: v.update(summary=text))[0]["reason"], "AI_COMMENTARY_INVALID")
        for caution in ("é"*120, "😀"*120, "e\u0301"*60, "x"*118+"\r\n"):
            self.assertEqual(self.invoke(lambda v, text=caution: v.update(cautions=[text]))[0]["state"], "COMPLETED")
        for caution in ("é"*121, "😀"*121, "x"*120+"\n"):
            self.assertEqual(self.invoke(lambda v, text=caution: v.update(cautions=[text]))[0]["reason"], "AI_COMMENTARY_INVALID")

    def test_missing_or_zero_assessment_identity_never_creates_claim_or_transport_call(self):
        for identity in (None, 0, "", "not-an-assessment"):
            assessed = report()
            assessed["assessment_id"] = identity
            result, rows, opener, _ = self.invoke(assessment=assessed)
            self.assertEqual(result["state"], "UNAVAILABLE")
            self.assertEqual(rows, [])
            self.assertEqual(opener.calls, [])

    def test_no_source_evidence_prefilter_runs_before_ai_health_hook_or_journal(self):
        class ForbiddenHook:
            def __call__(self, value):
                raise AssertionError("EMPTY_CONTEXT_MUST_NOT_REACH_REVIEWER")
            def health(self):
                raise AssertionError("EMPTY_CONTEXT_MUST_NOT_QUERY_HEALTH")
        observer = SimpleNamespace(context_hook=ForbiddenHook(),
            config=SimpleNamespace(context_max_calls_per_day=2))
        assessed = report()
        assessed["regime"]["state"] = "INSUFFICIENT_DATA"
        for scope in assessed["scopes"]:
            scope["data_state"] = "UNKNOWN"
        result = guardian_shadow.GuardianShadowService._context(observer, assessed)
        self.assertEqual(result["reason"], "INSUFFICIENT_VERIFIED_CONTEXT")
        self.assertEqual(list(self.root.iterdir()), [])
        context, _, _ = ai.GuardianAIReviewer._context(assessed)
        self.assertEqual(context["evidence_ids"], [assessed["assessment_id"]])

    def test_historical_cache_keeps_original_assessment_without_fabricating_new_evidence(self):
        first = report()
        first["assessment_id"] = "a"*64
        original = self.invoke(folder="historical", assessment=first)
        later = report(at=NOW+60)
        later["assessment_id"] = "b"*64
        cached = self.invoke(folder="historical", clock=NOW+60, assessment=later)
        self.assertEqual(original[0]["state"], "COMPLETED")
        self.assertEqual(cached[0]["state"], "CACHED_HISTORICAL")
        self.assertEqual(cached[0]["assessment_id"], "a"*64)
        self.assertEqual(cached[0]["commentary"]["evidence_ids"], ["a"*64])
        self.assertEqual(len(cached[1]), 1)
        self.assertEqual(cached[2].calls, [])

    def test_two_failed_claims_still_consume_budget_after_restart_without_retry(self):
        bad = lambda v: v.update(summary="x"*281)
        first = self.invoke(bad, folder="budget")
        second = self.invoke(bad, folder="budget", clock=NOW+3601)
        third = self.invoke(folder="budget", clock=NOW+7202)
        self.assertEqual(first[0]["reason"], "AI_COMMENTARY_INVALID")
        self.assertEqual(second[0]["reason"], "AI_COMMENTARY_INVALID")
        self.assertEqual(third[0]["reason"], "AI_BUDGET_OR_INTERVAL")
        self.assertEqual(len(third[1]), 2)
        self.assertEqual(third[2].calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
