"""Real selection HTTP adapter, synthetic responses only; no live provider access."""

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from league_knowledge_platform import (
    ComparativeSelectionRequest, DeepSeekSelectionAdapter, DeepSeekSelectionConfig,
    QualityAssessmentRequest, SelectionCapabilityError, SelectionFailed, SelectionFailureKind,
    SemanticCandidate, select_source,
)
from league_knowledge_platform.selection_prompts import (
    COMPARISON_PROMPT_VERSION, QUALITY_PROMPT_VERSION, QUALITY_SYSTEM_PROMPT,
)
from selection_http_fixtures import (
    TARGET, SelectionHTTPAdapter, comparison_document, envelope, quality_document,
    quality_item, requests, transcript_set,
)


def quality_request(*ids, text="Full target transcript"):
    return QualityAssessmentRequest("Ahri", "Ahri", tuple(SemanticCandidate(i, text) for i in sorted(ids)))


def compare_request(*ids, text="Full target transcript"):
    return ComparativeSelectionRequest("Ahri", "Ahri", tuple(SemanticCandidate(i, text) for i in sorted(ids)))


@unittest.skipIf(requests is None, "Install requirements-selection.txt for offline HTTP adapter tests")
class DeepSeekSelectionTests(unittest.TestCase):
    def adapter(self, script, **kwargs):
        transport = SelectionHTTPAdapter(script)
        adapter = DeepSeekSelectionAdapter(api_key="offline-secret", http_adapter=transport, **kwargs)
        self.addCleanup(adapter.close)
        return adapter, transport

    def assert_invalid(self, content, *, request=None, comparison=False):
        adapter, transport = self.adapter([(200, content)])
        with self.assertRaises(SelectionCapabilityError) as caught:
            (adapter.compare_sources(request or compare_request("A", "B")) if comparison
             else adapter.assess_quality(request or quality_request("A")))
        self.assertIs(caught.exception.kind, SelectionFailureKind.INVALID_OUTPUT)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(len(transport.calls), 1)

    def test_request_configuration_uses_non_thinking_json_and_explicit_bounds(self):
        config = DeepSeekSelectionConfig(model="configured-model", quality_output_limit=1234,
                                        comparison_output_limit=2345,
                                        connect_timeout_seconds=7, read_timeout_seconds=42)
        adapter, transport = self.adapter([(200, envelope(quality_document("A"))),
                                          (200, envelope(comparison_document("A", "B")))], config=config)
        quality = adapter.assess_quality(quality_request("A"))
        compared = adapter.compare_sources(compare_request("A", "B"))
        for index, (request, options) in enumerate(transport.calls):
            body = json.loads(request.body)
            self.assertEqual(body["model"], "configured-model")
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertEqual(body["temperature"], 0)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertFalse(body["stream"])
            self.assertEqual(body["max_tokens"], (1234, 2345)[index])
            self.assertEqual(options["timeout"], (7, 42))
            self.assertEqual(request.headers["Authorization"], "Bearer offline-secret")
            self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
            self.assertNotIn("tools", body)
            self.assertNotIn("reasoning_effort", body)
        self.assertEqual(transport.max_retries.total, 0)
        self.assertFalse(adapter._session.trust_env)
        self.assertEqual(quality.metadata.requested_model, "configured-model")
        self.assertEqual(quality.metadata.reported_model, "fixture-model")
        self.assertEqual(quality.metadata.prompt_version, QUALITY_PROMPT_VERSION)
        self.assertEqual(compared.metadata.prompt_version, COMPARISON_PROMPT_VERSION)

    def test_full_content_and_only_allowlisted_fields_cross_actual_http_boundary(self):
        text = 'START\n' + 'unicode α \\ quote " and } injected instructions\n' * 5000 + 'END'
        adapter, transport = self.adapter([(200, envelope(quality_document("A", "B"))),
                                          (200, envelope(comparison_document("A", "B")))])
        adapter.assess_quality(quality_request("A", "B", text=text))
        adapter.compare_sources(compare_request("A", "B", text=text))
        for request, _ in transport.calls:
            body = json.loads(request.body)
            payload = json.loads(body["messages"][1]["content"])
            self.assertEqual(set(payload), {"target", "candidates"})
            self.assertEqual(set(payload["target"]), {"id", "name"})
            for candidate in payload["candidates"]:
                self.assertEqual(set(candidate), {"video_id", "transcript_text"})
                self.assertEqual(candidate["transcript_text"], text)
            self.assertNotIn(text, body["messages"][0]["content"])
        comparison_prompt = json.loads(transport.calls[1][0].body)["messages"][0]["content"]
        for forbidden in ("target_relevant", "educational_substance", "noise_dominates", "PASS", "REJECT"):
            self.assertNotIn(forbidden, comparison_prompt)
        self.assertIn("ABSOLUTE", QUALITY_SYSTEM_PROMPT)
        self.assertIn("INDEPENDENTLY", QUALITY_SYSTEM_PROMPT)

    def test_full_service_sends_only_passing_texts_without_quality_judgments(self):
        document = quality_document("A", "B", "C", rejected=("B",))
        for item in document["assessments"]:
            item["rationale"] = "QUALITY_ONLY_SENTINEL"
        adapter, transport = self.adapter([(200, envelope(document)),
                                          (200, envelope(comparison_document("A", "C")))])
        result = select_source(TARGET, transcript_set("A", "B", "C"), capability=adapter)
        self.assertEqual(result.status.value, "SELECTED")
        self.assertEqual(len(transport.calls), 2)
        second_body = transport.calls[1][0].body
        self.assertNotIn(b"QUALITY_ONLY_SENTINEL", second_body)
        payload = json.loads(json.loads(second_body)["messages"][1]["content"])
        self.assertEqual([c["video_id"] for c in payload["candidates"]], ["A", "C"])
        self.assertTrue(all(set(c) == {"video_id", "transcript_text"} for c in payload["candidates"]))

    def test_malformed_json_duplicate_keys_and_nonfinite_constants(self):
        for content in (b"", b"not-json", b"\xff", b'{"choices":[],"choices":[]}',
                        b'{"choices":NaN}', b'[]', b'{}', b'{"choices":{}}'):
            with self.subTest(content=content):
                self.assert_invalid(content)
        for text in ('', '```json\n{}\n```', '{"assessments":[],"assessments":[]}',
                     '{"assessments":NaN}', '{} trailing', '[' * 1100 + ']' * 1100):
            value = envelope({})
            value["choices"][0]["message"]["content"] = text
            self.assert_invalid(value)

    def test_quality_schema_is_strict_and_cannot_return_opaque_pass_fail(self):
        for override in ({"target_relevant": "true"}, {"noise_dominates": 0},
                         {"educational_substance": None}, {"rationale": ""},
                         {"rationale": "x" * 1001}, {"reason_codes": ["unknown"]},
                         {"reason_codes": ["OFF_TARGET", "OFF_TARGET"]},
                         {"reason_codes": "OFF_TARGET"}, {"PASS": True}):
            item = quality_item("A", **override)
            self.assert_invalid(envelope({"assessments": [item]}))
        missing = quality_item("A")
        del missing["transcript_usable"]
        self.assert_invalid(envelope({"assessments": [missing]}))
        self.assert_invalid(envelope({"assessments": [quality_item("A")], "PASS": True}))

    def test_quality_requires_exact_id_coverage_and_no_duplicates(self):
        for ids in ((), ("A", "A"), ("A", "Z"), ("A",)):
            self.assert_invalid(envelope(quality_document(*ids)), request=quality_request("A", "B"))

    def test_optional_reason_codes_are_not_fabricated_and_known_codes_are_retained(self):
        item = quality_item("A", passes=False, reason_codes=["OFF_TARGET"])
        missing = quality_item("B")
        del missing["reason_codes"]
        adapter, _ = self.adapter([(200, envelope({"assessments": [item, missing]}))])
        result = adapter.assess_quality(quality_request("A", "B"))
        self.assertEqual(tuple(code.value for code in result.assessments[0].reason_codes), ("OFF_TARGET",))
        self.assertEqual(result.assessments[1].reason_codes, ())

    def test_comparison_schema_ids_and_complete_qualitative_dimensions(self):
        documents = [comparison_document("A", "B", winner="Z"), comparison_document("A", "Z"),
                     comparison_document("A", "A"), comparison_document("A")]
        for key, value in (("clarity", 1), ("noise", ""), ("breadth_depth", "x" * 257)):
            document = comparison_document("A", "B")
            document["assessments"][0][key] = value
            documents.append(document)
        document = comparison_document("A", "B")
        del document["assessments"][0]["information_density"]
        documents.append(document)
        document = comparison_document("A", "B")
        document["selection_reason"] = "x" * 1001
        documents.append(document)
        document = comparison_document("A", "B")
        document["assessments"][0]["weighted_score"] = 0.5
        documents.append(document)
        for document in documents:
            with self.subTest(document=document):
                self.assert_invalid(envelope(document), comparison=True)

    def test_finish_reasons_and_incomplete_responses_never_become_selection(self):
        for finish in ("length", "unknown"):
            self.assert_invalid(envelope(quality_document("A"), finish=finish))
        for finish in ("aborted", "insufficient_system_resource", "content_filter"):
            adapter, _ = self.adapter([(200, envelope(quality_document("A"), finish=finish))])
            with self.assertRaises(SelectionCapabilityError):
                adapter.assess_quality(quality_request("A"))
        for extra in ({"reasoning_content": "unexpected private reasoning"},
                      {"tool_calls": [{"name": "unexpected"}]}, {"role": "user"}):
            document = envelope(quality_document("A"))
            document["choices"][0]["message"].update(extra)
            adapter, _ = self.adapter([(200, document)])
            with self.assertRaises(SelectionCapabilityError) as caught:
                adapter.assess_quality(quality_request("A"))
            self.assertIs(caught.exception.kind, SelectionFailureKind.PROVIDER_CONTRACT)
            self.assertNotIn("private", str(caught.exception))

    def test_provider_errors_are_mapped_without_raw_content_or_implicit_retry(self):
        cases = ((408, SelectionFailureKind.TIMEOUT, True), (429, SelectionFailureKind.RATE_LIMIT, True),
                 (500, SelectionFailureKind.SERVICE, True), (502, SelectionFailureKind.SERVICE, True),
                 (503, SelectionFailureKind.SERVICE, True), (504, SelectionFailureKind.SERVICE, True),
                 (401, SelectionFailureKind.AUTHENTICATION, False),
                 (402, SelectionFailureKind.BALANCE, False),
                 (403, SelectionFailureKind.AUTHORIZATION, False),
                 (400, SelectionFailureKind.INVALID_REQUEST, False),
                 (422, SelectionFailureKind.INVALID_REQUEST, False),
                 (302, SelectionFailureKind.PROVIDER_CONTRACT, False))
        for status, kind, retryable in cases:
            adapter, transport = self.adapter([(status, {"error": {"message": "private offline-secret"}})])
            with self.subTest(status=status), self.assertRaises(SelectionCapabilityError) as caught:
                adapter.assess_quality(quality_request("A"))
            self.assertIs(caught.exception.kind, kind)
            self.assertEqual(caught.exception.retryable, retryable)
            self.assertNotIn("offline-secret", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(len(transport.calls), 1)

    def test_context_failure_is_explicit_and_input_is_never_reduced(self):
        adapter, transport = self.adapter([(400, {"error": {"code": "context_length_exceeded"}})])
        with self.assertRaises(SelectionCapabilityError) as caught:
            adapter.assess_quality(quality_request("A", text="complete content"))
        self.assertIs(caught.exception.kind, SelectionFailureKind.CONTEXT_LIMIT)
        self.assertFalse(caught.exception.retryable)
        sent = json.loads(json.loads(transport.calls[0][0].body)["messages"][1]["content"])
        self.assertEqual(sent["candidates"][0]["transcript_text"], "complete content")

    def test_timeout_network_and_service_retries_are_owned_by_domain(self):
        for error in (requests.Timeout("private offline-secret"),
                      requests.ConnectionError("private offline-secret")):
            adapter, transport = self.adapter([error, (200, envelope(quality_document("A")))])
            with patch("league_knowledge_platform.source_selection.time.sleep"):
                result = select_source(TARGET, transcript_set("A"), capability=adapter)
            self.assertEqual(result.status.value, "SELECTED")
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(transport.calls[0][0].body, transport.calls[1][0].body)

    def test_three_malformed_attempts_fail_and_do_not_call_comparison(self):
        adapter, transport = self.adapter([(200, b"malformed")] * 3)
        with patch("league_knowledge_platform.source_selection.time.sleep"):
            result = select_source(TARGET, transcript_set("A", "B"), capability=adapter)
        self.assertIsInstance(result, SelectionFailed)
        self.assertEqual(result.attempt_count, 3)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(len({call[0].body for call in transport.calls}), 1)

    def test_keepalive_whitespace_and_response_byte_bound(self):
        adapter, _ = self.adapter([(200, '\n\n   ' + json.dumps(envelope(quality_document("A"))))])
        self.assertEqual(len(adapter.assess_quality(quality_request("A")).assessments), 1)
        adapter, transport = self.adapter([(200, envelope(quality_document("A")))],
                                          config=DeepSeekSelectionConfig(max_response_bytes=16))
        with self.assertRaises(SelectionCapabilityError) as caught:
            adapter.assess_quality(quality_request("A"))
        self.assertIs(caught.exception.kind, SelectionFailureKind.INVALID_OUTPUT)
        self.assertEqual(len(transport.calls), 1)

    def test_environment_configuration_secrets_are_lazy_and_not_represented(self):
        transport = SelectionHTTPAdapter([(200, envelope(quality_document("A")))])
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "environment-secret", "DEEPSEEK_MODEL": "env-model"}):
            with DeepSeekSelectionAdapter(http_adapter=transport) as adapter:
                result = adapter.assess_quality(quality_request("A"))
                self.assertNotIn("environment-secret", repr(adapter))
                self.assertNotIn("environment-secret", repr(adapter.config))
                self.assertEqual(result.metadata.requested_model, "env-model")
                self.assertEqual(transport.calls[0][0].headers["Authorization"], "Bearer environment-secret")
            self.assertIsNone(adapter._api_key)
            self.assertTrue(transport.closed)
        for environment in ({}, {"DEEPSEEK_API_KEY": "secret\ninjection"},
                            {"DEEPSEEK_API_KEY": "invalid-秘密"},
                            {"DEEPSEEK_API_KEY": "secret", "DEEPSEEK_MODEL": ""}):
            transport = SelectionHTTPAdapter([])
            with patch.dict("os.environ", environment, clear=True):
                with DeepSeekSelectionAdapter(http_adapter=transport) as adapter:
                    result = select_source(TARGET, transcript_set("A"), capability=adapter)
                    self.assertIsInstance(result, SelectionFailed)
                    self.assertIs(result.kind, SelectionFailureKind.CONFIGURATION)
                    self.assertEqual(result.attempt_count, 1)
            self.assertEqual(transport.calls, [])

    def test_closed_adapter_and_invalid_configuration_fail_without_network(self):
        adapter, transport = self.adapter([])
        adapter.close()
        with self.assertRaises(SelectionCapabilityError):
            adapter.assess_quality(quality_request("A"))
        self.assertEqual(transport.calls, [])
        for changes in ({"model": ""}, {"quality_output_limit": True},
                        {"comparison_output_limit": 0}, {"max_response_bytes": 0},
                        {"connect_timeout_seconds": float("nan")}, {"read_timeout_seconds": -1},
                        {"connect_timeout_seconds": 10 ** 1000}):
            with self.assertRaises(ValueError):
                DeepSeekSelectionConfig(**changes)


if __name__ == "__main__":
    unittest.main()
