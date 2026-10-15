"""Domain control flow, isolation, and stage retries, without provider dependencies."""

from dataclasses import FrozenInstanceError, asdict, replace
from itertools import product
import unittest
from unittest.mock import patch

from league_knowledge_platform import (
    CandidateQualityAssessment, ComparativeCandidateAssessment, ComparativeSelection,
    DeepSeekSelectionAdapter, NoSelection, NoSelectionReason, QualityAssessmentBatch,
    QualityGateResult, QualityReasonCode, SelectedSource, SelectionCapabilityError,
    SelectionConfig, SelectionFailed, SelectionFailureKind, SelectionMethod, SelectionStage,
    SelectionStatus, SemanticCandidate, select_source,
)
from selection_http_fixtures import TARGET, comparison_item, quality_item, transcript_set


def quality(*ids, rejected=()):
    return QualityAssessmentBatch(tuple(CandidateQualityAssessment(
        **{k: v for k, v in quality_item(video_id, passes=video_id not in rejected).items()
           if k != "reason_codes"}) for video_id in ids))


def comparison(*ids, winner=None):
    return ComparativeSelection(winner or ids[-1],
        tuple(ComparativeCandidateAssessment(**comparison_item(video_id)) for video_id in ids),
        "Strongest source explanation.")


class FakeSelection:
    def __init__(self, quality_results=(), comparisons=()):
        self.quality_results = list(quality_results)
        self.comparisons = list(comparisons)
        self.quality_requests = []
        self.comparison_requests = []

    def assess_quality(self, request):
        self.quality_requests.append(request)
        result = self.quality_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def compare_sources(self, request):
        self.comparison_requests.append(request)
        result = self.comparisons.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class SourceSelectionTests(unittest.TestCase):
    def select(self, inputs, capability, **kwargs):
        with patch("league_knowledge_platform.source_selection.time.sleep") as sleep:
            result = select_source(TARGET, inputs, capability=capability, **kwargs)
        self.sleeps = sleep.call_args_list
        return result

    def test_empty_and_all_unavailable_make_no_capability_call(self):
        for inputs in (transcript_set(), transcript_set("A", "B", unavailable=("A", "B"))):
            fake = FakeSelection()
            result = self.select(inputs, fake)
            self.assertIsInstance(result, NoSelection)
            self.assertIs(result.reason, NoSelectionReason.NO_TRANSCRIPTS)
            self.assertEqual(result.attempts, ())
            self.assertEqual(fake.quality_requests + fake.comparison_requests, [])

    def test_zero_input_needs_no_optional_library_or_credentials(self):
        inputs = transcript_set()
        with patch("builtins.__import__", side_effect=AssertionError("Unexpected dependency")):
            with DeepSeekSelectionAdapter() as adapter:
                result = self.select(inputs, adapter)
        self.assertIs(result.status, SelectionStatus.NO_SELECTION)

    def test_all_sixteen_boolean_combinations_have_exact_gate(self):
        for relevant, substance, usable, noise in product((False, True), repeat=4):
            with self.subTest(values=(relevant, substance, usable, noise)):
                assessment = CandidateQualityAssessment("A", relevant, substance, usable, noise, "Reason")
                gate = QualityGateResult(assessment)
                self.assertEqual(gate.passed, relevant and substance and usable and not noise)
                self.assertEqual(len(gate.rejection_reasons),
                                 sum((not relevant, not substance, not usable, noise)))

    def test_llm_reason_codes_never_override_boolean_gate(self):
        good = CandidateQualityAssessment("A", True, True, True, False, "Reason",
                                          (QualityReasonCode.OFF_TARGET,))
        bad = replace(good, target_relevant=False, reason_codes=())
        self.assertTrue(QualityGateResult(good).passed)
        self.assertFalse(QualityGateResult(bad).passed)

    def test_one_pass_is_direct_and_original_transcript_identity_is_retained(self):
        inputs = transcript_set("A")
        fake = FakeSelection([quality("A")])
        result = self.select(inputs, fake)
        self.assertIsInstance(result, SelectedSource)
        self.assertIs(result.source, inputs.transcripts[0])
        self.assertIs(result.source.segments, inputs.transcripts[0].segments)
        self.assertIs(result.method, SelectionMethod.ONLY_PASSING_CANDIDATE)
        self.assertIsNone(result.comparison)
        self.assertEqual(fake.comparison_requests, [])

    def test_one_rejected_and_multiple_all_rejected_are_normal_no_selection(self):
        for ids in (("A",), ("A", "B"), ("A", "B", "C")):
            fake = FakeSelection([quality(*ids, rejected=ids)])
            result = self.select(transcript_set(*ids), fake)
            self.assertIsInstance(result, NoSelection)
            self.assertIs(result.reason, NoSelectionReason.ALL_REJECTED)
            self.assertEqual(len(result.quality_gate_results), len(ids))
            self.assertEqual(fake.comparison_requests, [])

    def test_multiple_candidates_with_one_pass_skip_comparison(self):
        for ids in (("A", "B"), ("A", "B", "C")):
            result = self.select(transcript_set(*ids), FakeSelection([quality(*ids, rejected=ids[1:])]))
            self.assertIs(result.method, SelectionMethod.ONLY_PASSING_CANDIDATE)
            self.assertEqual(result.source.track.video_id, "A")

    def test_two_pass_and_three_pass_invoke_separate_comparison(self):
        for rejected in (("C",), ()):
            passing = tuple(video_id for video_id in ("A", "B", "C") if video_id not in rejected)
            fake = FakeSelection([quality("A", "B", "C", rejected=rejected)], [comparison(*passing)])
            inputs = transcript_set("A", "B", "C")
            result = self.select(inputs, fake)
            self.assertIs(result.method, SelectionMethod.COMPARATIVE)
            self.assertEqual(result.source.track.video_id, passing[-1])
            self.assertEqual(len(fake.quality_requests), 1)
            self.assertEqual(len(fake.comparison_requests), 1)
            self.assertEqual(tuple(c.video_id for c in fake.comparison_requests[0].candidates), passing)

    def test_projected_requests_omit_rank_and_stage_one_metadata_structurally(self):
        inputs = transcript_set("A", "B", "C")
        fake = FakeSelection([quality("A", "B", "C", rejected=("B",))], [comparison("A", "C")])
        self.select(inputs, fake)
        self.assertNotEqual(tuple(t.track.video_id for t in inputs.transcripts), ("A", "B", "C"))
        for request in (fake.quality_requests[0], fake.comparison_requests[0]):
            value = asdict(request)
            self.assertEqual(set(value), {"target_id", "target_name", "candidates"})
            for candidate in value["candidates"]:
                self.assertEqual(set(candidate), {"video_id", "transcript_text"})
            ids = tuple(c.video_id for c in request.candidates)
            self.assertEqual(ids, tuple(sorted(ids)))
            self.assertFalse(hasattr(request, "__dict__"))
        self.assertEqual(tuple(c.video_id for c in fake.comparison_requests[0].candidates), ("A", "C"))

    def test_full_transcript_is_unchanged_in_both_requests_and_output(self):
        text = "BEGIN\n" + ("α Ahri mechanics \"nested\" \\ data\n" * 10000) + "END"
        inputs = transcript_set("A", "B", texts={"A": text})
        fake = FakeSelection([quality("A", "B")], [comparison("A", "B", winner="A")])
        result = self.select(inputs, fake)
        original = next(t for t in inputs.transcripts if t.track.video_id == "A")
        for request in (fake.quality_requests[0], fake.comparison_requests[0]):
            self.assertEqual(next(c.transcript_text for c in request.candidates if c.video_id == "A"),
                             original.text)
        self.assertIs(result.source, original)
        self.assertEqual(original.segments[0].source_text, text)

    def test_quality_retry_success_on_second_and_third_attempt(self):
        for failures in (1, 2):
            error = SelectionCapabilityError(SelectionFailureKind.TIMEOUT, retryable=True)
            fake = FakeSelection([error] * failures + [quality("A")])
            result = self.select(transcript_set("A"), fake)
            self.assertIsInstance(result, SelectedSource)
            self.assertEqual(len(fake.quality_requests), failures + 1)
            self.assertTrue(all(r is fake.quality_requests[0] for r in fake.quality_requests))
            self.assertEqual(len(self.sleeps), failures)

    def test_quality_exhaustion_returns_technical_failure_without_partial_gate(self):
        fake = FakeSelection([quality("A"), quality("A"), quality("A")])
        result = self.select(transcript_set("A", "B"), fake)
        self.assertIsInstance(result, SelectionFailed)
        self.assertEqual(result.attempt_count, 3)
        self.assertIs(result.kind, SelectionFailureKind.INVALID_OUTPUT)
        self.assertEqual(result.quality_gate_results, ())
        self.assertEqual(len(fake.quality_requests), 3)

    def test_invalid_nonpassing_comparative_winner_retries_only_stage_two(self):
        bad = comparison("B", "C", winner="C")
        fake = FakeSelection([quality("A", "B", "C", rejected=("C",))], [bad, bad, bad])
        result = self.select(transcript_set("A", "B", "C"), fake)
        self.assertIsInstance(result, SelectionFailed)
        self.assertIs(result.stage, SelectionStage.COMPARISON)
        self.assertEqual(len(result.quality_gate_results), 3)
        self.assertEqual(len(fake.quality_requests), 1)
        self.assertEqual(len(fake.comparison_requests), 3)
        self.assertTrue(all(r is fake.comparison_requests[0] for r in fake.comparison_requests))

    def test_comparison_retry_can_succeed_without_reassessing_quality(self):
        error = SelectionCapabilityError(SelectionFailureKind.SERVICE, retryable=True)
        fake = FakeSelection([quality("A", "B")], [error, error, comparison("A", "B")])
        result = self.select(transcript_set("A", "B"), fake)
        self.assertIsInstance(result, SelectedSource)
        self.assertEqual(len(fake.quality_requests), 1)
        self.assertEqual(len(fake.comparison_requests), 3)
        self.assertEqual(len(result.attempts), 4)

    def test_both_stages_have_independent_three_attempt_limits(self):
        error = SelectionCapabilityError(SelectionFailureKind.SERVICE, retryable=True)
        fake = FakeSelection([error, error, quality("A", "B")], [error, error, error])
        result = self.select(transcript_set("A", "B"), fake)
        self.assertIsInstance(result, SelectionFailed)
        self.assertEqual(result.attempt_count, 3)
        self.assertEqual(len(result.attempts), 6)
        self.assertEqual(len(fake.quality_requests), 3)
        self.assertEqual(len(fake.comparison_requests), 3)
        self.assertEqual([call.args[0] for call in self.sleeps], [1, 2, 1, 2])

    def test_permanent_failure_is_not_retried_or_no_selection(self):
        for kind in (SelectionFailureKind.CONFIGURATION, SelectionFailureKind.CONTEXT_LIMIT,
                     SelectionFailureKind.AUTHENTICATION):
            fake = FakeSelection([SelectionCapabilityError(kind, retryable=False)])
            result = self.select(transcript_set("A"), fake)
            self.assertIsInstance(result, SelectionFailed)
            self.assertEqual(result.attempt_count, 1)
            self.assertEqual(self.sleeps, [])

    def test_invalid_quality_type_and_unexpected_provider_exception(self):
        for value, kind, count in ((None, SelectionFailureKind.INVALID_OUTPUT, 3),
                                  (RuntimeError("private raw response"),
                                   SelectionFailureKind.PROVIDER_CONTRACT, 1)):
            fake = FakeSelection([value] * count)
            result = self.select(transcript_set("A"), fake)
            self.assertIsInstance(result, SelectionFailed)
            self.assertIs(result.kind, kind)
            self.assertNotIn("private raw response", repr(result))

    def test_configuration_limits_and_invalid_caller_input_fail_explicitly(self):
        for value in (0, 4, True, 1.5):
            with self.assertRaises(ValueError):
                SelectionConfig(max_attempts=value)
        for delay in ((1,), [1, 2], (float("nan"), 1), (1, 61)):
            with self.assertRaises(ValueError):
                SelectionConfig(retry_delays_seconds=delay)
        with self.assertRaises(ValueError):
            select_source(replace(TARGET, id="Other"), transcript_set("A"), capability=FakeSelection())
        with self.assertRaises(ValueError):
            select_source(TARGET, transcript_set("A"), capability=object())
        fake = FakeSelection([None])
        result = self.select(transcript_set("A"), fake, config=SelectionConfig(max_attempts=1))
        self.assertIsInstance(result, SelectionFailed)
        self.assertEqual(result.attempt_count, 1)

    def test_models_reject_coercions_duplicates_and_are_immutable(self):
        for invalid in ("true", 1, None):
            with self.assertRaises(ValueError):
                CandidateQualityAssessment("A", invalid, True, True, False, "Reason")
        with self.assertRaises(ValueError):
            QualityAssessmentBatch((quality("A").assessments[0],) * 2)
        with self.assertRaises(ValueError):
            ComparativeSelection("Z", comparison("A", "B").assessments, "Reason")
        candidate = SemanticCandidate("A", "content")
        with self.assertRaises(FrozenInstanceError):
            candidate.transcript_text = "changed"
        self.assertNotIn("content", repr(candidate))
        result = self.select(transcript_set("A"), FakeSelection([quality("A")]))
        with self.assertRaises(ValueError):
            replace(result, attempts=list(result.attempts))
        with self.assertRaises(ValueError):
            replace(result, attempts=())


if __name__ == "__main__":
    unittest.main()
