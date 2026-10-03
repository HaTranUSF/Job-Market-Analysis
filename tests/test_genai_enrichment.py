import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from genai_enrichment import CREATE_RISK_SCHEMA_SQL, GEMINI_RESPONSE_SCHEMA
from genai_enrichment import (
    EvidenceField,
    RiskEvidenceExtraction,
    SYSTEM_INSTRUCTION,
    UPSERT_RISK_SQL,
    extract_with_gemini,
    _retry_delay,
    run_enrichment,
    store_result,
    validate_response,
)


class RiskEvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.description = (
            "Access financial records in the Treasury system. "
            "Maintain audit controls and protect personal information."
        )

    def test_parses_valid_structured_response_and_evidence(self):
        response = {
            "mentions_financial_data": True,
            "mentions_audit_or_controls": True,
            "risk_relevant_terms": ["financial records", "audit controls"],
            "evidence_snippets": [
                {"field": "mentions_financial_data", "quote": "financial records"},
                {"field": "mentions_audit_or_controls", "quote": "audit controls"},
            ],
            "systems_mentioned": ["Treasury system"],
            "confidence": 0.91,
        }

        result = validate_response(response, self.description)

        self.assertTrue(result.mentions_financial_data)
        self.assertTrue(result.mentions_audit_or_controls)
        self.assertEqual(result.systems_mentioned, ["Treasury system"])
        self.assertEqual(len(result.evidence_snippets), 2)
        self.assertEqual(result.confidence, 0.91)

    def test_malformed_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_response("{not valid json", self.description)

    def test_missing_fields_default_to_no_claim(self):
        result = validate_response('{"confidence": 0.5}', self.description)

        self.assertFalse(result.mentions_sensitive_data)
        self.assertFalse(result.mentions_personal_information)
        self.assertEqual(result.risk_relevant_terms, [])
        self.assertEqual(result.evidence_snippets, [])
        self.assertEqual(result.confidence, 0.5)

    def test_missing_confidence_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_response("{}", self.description)

    def test_boolean_fields_normalize_explicit_string_values(self):
        result = RiskEvidenceExtraction.model_validate(
            {
                "mentions_financial_data": "true",
                "mentions_health_data": "false",
                "confidence": 0.8,
            }
        )

        self.assertTrue(result.mentions_financial_data)
        self.assertFalse(result.mentions_health_data)

    def test_confidence_must_be_between_zero_and_one(self):
        for confidence in (-0.01, 1.01, True):
            with self.subTest(confidence=confidence):
                with self.assertRaises(ValueError):
                    RiskEvidenceExtraction.model_validate({"confidence": confidence})

    def test_unquoted_claim_and_unmatched_evidence_are_removed(self):
        result = validate_response(
            {
                "mentions_health_data": True,
                "mentions_personal_information": True,
                "risk_relevant_terms": ["personal information", "patient records"],
                "evidence_snippets": [
                    {
                        "field": "mentions_health_data",
                        "quote": "patient records are reviewed",
                    },
                    {
                        "field": "mentions_personal_information",
                        "quote": "personal information",
                    },
                ],
                "confidence": 0.7,
            },
            self.description,
        )

        self.assertFalse(result.mentions_health_data)
        self.assertTrue(result.mentions_personal_information)
        self.assertEqual(result.risk_relevant_terms, ["personal information"])
        self.assertEqual(
            [snippet.field for snippet in result.evidence_snippets],
            [EvidenceField.MENTIONS_PERSONAL_INFORMATION],
        )


class GeminiClientTests(unittest.TestCase):
    def test_gemini_response_schema_omits_unsupported_additional_properties(self):
        def find_values(value, key):
            if isinstance(value, dict):
                matches = [value[key]] if key in value else []
                for nested in value.values():
                    matches.extend(find_values(nested, key))
                return matches
            if isinstance(value, list):
                return [match for nested in value for match in find_values(nested, key)]
            return []

        schema = GEMINI_RESPONSE_SCHEMA

        self.assertEqual(find_values(schema, "additionalProperties"), [])
        self.assertNotIn("$defs", schema)
        self.assertEqual(schema["type"], "OBJECT")

    def test_uses_official_sdk_structured_generation_and_system_guardrails(self):
        description = "Maintain audit controls."
        response = SimpleNamespace(
            text=json.dumps(
                {
                    "mentions_audit_or_controls": True,
                    "evidence_snippets": [
                        {
                            "field": "mentions_audit_or_controls",
                            "quote": "audit controls",
                        }
                    ],
                    "confidence": 0.9,
                }
            ),
            parsed=None,
        )
        client = Mock()
        client.models.generate_content.return_value = response

        result = extract_with_gemini(client, description, "test-model")

        self.assertTrue(result.mentions_audit_or_controls)
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(json.loads(request["contents"]), {"job_description": description})
        self.assertIn("Never decide or state", request["config"].system_instruction)
        self.assertEqual(request["config"].response_mime_type, "application/json")
        self.assertEqual(request["config"].response_json_schema, GEMINI_RESPONSE_SCHEMA)
        self.assertEqual(request["config"].temperature, 0)

    def test_retries_transient_api_failures(self):
        class TemporaryAPIError(Exception):
            code = 503

        client = Mock()
        client.models.generate_content.side_effect = [
            TemporaryAPIError("temporary service error"),
            SimpleNamespace(text='{"confidence": 0.5}', parsed=None),
        ]
        sleeps = []

        result = extract_with_gemini(
            client,
            "Job description text.",
            "test-model",
            sleep=sleeps.append,
        )

        self.assertFalse(result.mentions_sensitive_data)
        self.assertEqual(client.models.generate_content.call_count, 2)
        self.assertEqual(sleeps, [5])

    def test_retry_delay_honors_retry_after_header(self):
        error = RuntimeError("rate limited")
        error.response = SimpleNamespace(headers={"Retry-After": "17"})

        self.assertEqual(_retry_delay(error, attempt=0), 17)

    def test_permanent_bad_request_is_not_retried(self):
        class BadRequest(Exception):
            code = 400

        client = Mock()
        client.models.generate_content.side_effect = BadRequest("invalid request")

        with self.assertRaises(BadRequest):
            extract_with_gemini(
                client,
                "A job description.",
                "test-model",
                sleep=lambda _seconds: None,
            )

        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_exhausted_quota_stops_without_retrying(self):
        class QuotaError(Exception):
            code = 429
            message = "Quota exceeded for free_tier_requests; check your plan and billing."

        client = Mock()
        client.models.generate_content.side_effect = QuotaError("quota exhausted")
        sleeps = []

        with self.assertRaisesRegex(RuntimeError, "project quota is exhausted"):
            extract_with_gemini(
                client,
                "A job description.",
                "test-model",
                sleep=sleeps.append,
            )

        self.assertEqual(client.models.generate_content.call_count, 1)
        self.assertEqual(sleeps, [])

    def test_api_failure_isolated_and_batch_continues(self):
        client = Mock()
        client.models.generate_content.side_effect = [
            RuntimeError("API unavailable"),
            SimpleNamespace(text='{"confidence": 0.5}', parsed=None),
        ]
        rows = [
            {"posting_id": "1", "description": "First description."},
            {"posting_id": "2", "description": "Second description."},
        ]
        with (
            patch("genai_enrichment.ensure_risk_schema"),
            patch("genai_enrichment.fetch_pending_postings", return_value=rows),
            patch("genai_enrichment.store_result") as store,
            self.assertLogs("job_market_genai_enrichment", level="ERROR") as logs,
        ):
            counts = run_enrichment(
                Mock(),
                api_key="test-only-key",
                limit=2,
                request_interval=0,
                client=client,
                sleep=lambda _seconds: None,
            )

        self.assertEqual(counts, (2, 1, 1))
        self.assertEqual(store.call_count, 1)
        self.assertIn("posting 1", logs.output[0])


class IdempotentStorageTests(unittest.TestCase):
    def test_storage_uses_posting_key_upsert_for_repeat_runs(self):
        connection = Mock()
        transaction = MagicMock()
        transaction.__enter__.return_value = connection
        engine = Mock()
        engine.begin.return_value = transaction
        result = validate_response('{"confidence": 0.5}', "Description")

        for _ in range(2):
            store_result(
                engine,
                posting_id="posting-1",
                description="Description",
                result=result,
                model_name="test-model",
            )

        self.assertEqual(connection.execute.call_count, 2)
        statement, first_params = connection.execute.call_args_list[0].args
        self.assertIn("ON CONFLICT (posting_id) DO UPDATE", str(statement))
        self.assertEqual(first_params["posting_id"], "posting-1")
        self.assertEqual(
            first_params["description_hash"],
            connection.execute.call_args_list[1].args[1]["description_hash"],
        )
        self.assertIn("posting_id TEXT PRIMARY KEY REFERENCES job_skills(id)", CREATE_RISK_SCHEMA_SQL)
        self.assertIn("Never decide or state", SYSTEM_INSTRUCTION)
        self.assertTrue(UPSERT_RISK_SQL.strip().startswith("INSERT INTO"))


if __name__ == "__main__":
    unittest.main()
