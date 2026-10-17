"""Offline Bronze contract, source identity and provenance tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest
from unittest.mock import PropertyMock, patch

from league_knowledge_platform import (
    BronzeConfig, BronzeContractError, BronzeIntegrationContext, ChampionTarget,
    SemanticCallMetadata, TranscriptSegment, canonical_bronze_path,
    construct_bronze_artifact, decode_bronze_artifact, select_source,
    validate_bronze_artifact,
)
from league_knowledge_platform.bronze import BronzeIntegrityError, _require_compatible
from selection_http_fixtures import TARGET, transcript_set
from test_source_selection import FakeSelection, comparison, quality

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def selected_source(*ids, rejected=(), winner=None):
    ids = ids or ("A",)
    passing = tuple(item for item in ids if item not in rejected)
    capability = FakeSelection([quality(*ids, rejected=rejected)],
                               [comparison(*passing, winner=winner)] if len(passing) > 1 else [])
    return select_source(TARGET, transcript_set(*ids), capability=capability)


class BronzeContractTests(unittest.TestCase):
    def artifact(self, selected=None, **kwargs):
        return construct_bronze_artifact(selected or selected_source(), created_at_utc=NOW, **kwargs)

    def test_complete_round_trip_preserves_raw_text_order_and_exact_decimal_timing(self):
        selected = selected_source()
        segments = (
            TranscriptSegment(0, " Raw  caption\ntext ", "Raw caption text", Decimal("0.12500"), Decimal("1.750")),
            TranscriptSegment(3, "Repeated!", "Repeated!", Decimal("0.500"), Decimal("0")),
            TranscriptSegment(4, "Repeated!", "Repeated!", Decimal("1E-8"), Decimal("2.000")),
        )
        selected = replace(selected, source=replace(selected.source, segments=segments))
        artifact = self.artifact(selected)
        decoded = decode_bronze_artifact(json.dumps(artifact, ensure_ascii=False).encode())
        self.assertEqual(decoded, artifact)
        self.assertEqual(decoded["transcript"]["text"], selected.source.text)
        for actual, original in zip(decoded["transcript"]["segments"], segments):
            self.assertEqual(actual["source_index"], original.source_index)
            self.assertEqual(actual["source_text"], original.source_text)
            self.assertEqual(actual["text"], original.text)
            self.assertEqual(actual["start_seconds"], str(original.start_seconds))
            self.assertEqual(actual["duration_seconds"], str(original.duration_seconds))

    def test_first_context_and_available_metadata_are_preserved(self):
        selected = selected_source()
        metadata = SemanticCallMetadata("fixture", "requested", "reported", "prompt-v1")
        selected = replace(selected, quality_metadata=metadata)
        context = BronzeIntegrationContext(42, NOW, TARGET)
        artifact = self.artifact(selected, context=context)
        self.assertEqual(artifact["acquisition"], {
            "target_id": TARGET.id, "target_key": TARGET.key, "target_name": TARGET.name,
            "run_id": 42, "selected_at_utc": NOW.isoformat(), "bronze_created_at_utc": NOW.isoformat(),
        })
        self.assertEqual(artifact["selection"]["quality_metadata"], {
            "provider": "fixture", "requested_model": "requested", "reported_model": "reported", "prompt_version": "prompt-v1",
        })
        candidate = selected.source.ranked_candidate.candidate
        self.assertEqual(artifact["source"]["view_count"], candidate.view_count)
        self.assertEqual(artifact["source"]["published_at_utc"], candidate.published_at_utc.isoformat())
        self.assertEqual(artifact["transcript"]["provider_version"], selected.source.track.provider_version)

    def test_missing_optional_context_is_not_invented(self):
        artifact = self.artifact()
        for name in ("run_id", "selected_at_utc", "target_name", "target_key"):
            self.assertIsNone(artifact["acquisition"][name])
        self.assertIsNone(artifact["selection"]["quality_metadata"])
        self.assertIsNone(artifact["selection"]["comparison"])
        self.assertIsNone(artifact["transcript"]["source_track_id"])

    def test_only_winner_assessments_and_no_runtime_track_handle_are_serialized(self):
        artifact = self.artifact(selected_source("A", "B", "C", rejected=("C",), winner="A"))
        encoded = json.dumps(artifact)
        self.assertEqual(artifact["selection"]["method"], "COMPARATIVE")
        self.assertEqual(artifact["selection"]["comparison"]["winner_assessment"]["video_id"], "A")
        self.assertNotIn('"B"', encoded)
        self.assertNotIn('"C"', encoded)
        self.assertNotIn("Useful target mechanics B", encoded)
        self.assertNotIn("Useful target mechanics C", encoded)
        self.assertNotIn("provider_key", encoded)
        self.assertNotIn("quality_gate_results", encoded)

    def test_canonical_url_is_derived_from_validated_id_not_discovery_format(self):
        with patch("league_knowledge_platform.models.CandidateVideo.url", new_callable=PropertyMock,
                   return_value="https://youtu.be/A?transient=1"):
            self.assertEqual(self.artifact()["source"]["url"], "https://www.youtube.com/watch?v=A")

    def test_path_mapping_preserves_case_and_avoids_reserved_names(self):
        config = BronzeConfig(Path("synthetic bronze"))
        self.assertEqual(canonical_bronze_path("A", config).name, "id-41.json")
        self.assertEqual(canonical_bronze_path("a", config).name, "id-61.json")
        self.assertEqual(canonical_bronze_path("CON", config).name, "id-434f4e.json")
        self.assertEqual(canonical_bronze_path("A", config).parent, Path(config.root).resolve() / "youtube")
        for invalid in ("", "../A", "A/B", "A\n", "é", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                canonical_bronze_path(invalid, config)

    def test_context_validation_and_mismatched_target(self):
        for run_id in (True, [], "", "  ", 1.5):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                BronzeIntegrationContext(run_id=run_id)
        with self.assertRaises(ValueError):
            BronzeIntegrationContext(selected_at_utc=datetime(2026, 1, 1))
        with self.assertRaises(BronzeContractError):
            self.artifact(context=BronzeIntegrationContext(target=ChampionTarget("Vayne", "67", "Vayne")))
        for run_id in (42, "run-42", None):
            self.assertEqual(self.artifact(context=BronzeIntegrationContext(run_id))["acquisition"]["run_id"], run_id)

    def test_non_selected_outcomes_are_not_admitted(self):
        no_selection = selected_source("A", rejected=("A",))
        for value in (no_selection, object(), None):
            with self.subTest(value=type(value).__name__), self.assertRaises(BronzeContractError):
                construct_bronze_artifact(value)

    def test_strict_artifact_validation_rejects_inconsistent_or_unsupported_material(self):
        mutations = (
            lambda a: a.update(schema_version=2),
            lambda a: a.update(schema_version=True),
            lambda a: a.update(extra="unexpected"),
            lambda a: a["source"].update(url="https://youtu.be/A"),
            lambda a: a["source"].update(view_count=True),
            lambda a: a["transcript"].update(text="truncated"),
            lambda a: a["transcript"].update(segments=[]),
            lambda a: a["transcript"]["segments"][0].update(start_seconds=0.125),
            lambda a: a["transcript"]["segments"][0].update(duration_seconds="NaN"),
            lambda a: a["transcript"]["segments"][0].update(start_seconds="-1"),
            lambda a: a["selection"]["winner_quality"].update(passed=1),
            lambda a: a["selection"]["winner_quality"].update(target_relevant=False),
            lambda a: a["selection"]["winner_quality"].update(video_id="other"),
            lambda a: a["selection"].update(attempts=[]),
            lambda a: a["selection"].update(method="COMPARATIVE"),
            lambda a: a["acquisition"].update(run_id=False),
            lambda a: a["acquisition"].update(bronze_created_at_utc="not-a-time"),
        )
        for mutation in mutations:
            artifact = self.artifact()
            mutation(artifact)
            with self.subTest(mutation=mutation), self.assertRaises(BronzeContractError):
                validate_bronze_artifact(artifact)

    def test_json_decoder_rejects_duplicate_keys_nonfinite_and_malformed_data(self):
        for content in (b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b'{', b'\xff', b'[]'):
            with self.subTest(content=content), self.assertRaises(BronzeContractError):
                decode_bronze_artifact(content)

    def test_compatibility_excludes_context_snapshots_and_decimal_scale(self):
        original = self.artifact()
        later = deepcopy(original)
        later["acquisition"].update(target_id="Vayne", run_id="later")
        later["source"].update(title="new title", channel_title="new display name", view_count=999)
        later["selection"]["winner_quality"]["rationale"] = "Later assessment"
        later["transcript"].update(provider_name="other", provider_version="2")
        later["transcript"]["segments"][0]["start_seconds"] = "0.1250000"
        validate_bronze_artifact(later)
        _require_compatible(original, later, "A")
        self.assertNotEqual(original, later)

    def test_material_source_text_timing_language_kind_and_track_conflicts(self):
        original = self.artifact()
        mutations = (
            lambda a: a["source"].update(video_id="other"),
            lambda a: a["transcript"]["segments"][0].update(source_text="changed raw source"),
            lambda a: a["transcript"]["segments"][0].update(start_seconds="0.126"),
            lambda a: a["transcript"].update(language_code="en-GB"),
            lambda a: a["transcript"].update(caption_kind="auto_generated"),
        )
        for mutation in mutations:
            later = deepcopy(original)
            mutation(later)
            with self.subTest(mutation=mutation), self.assertRaises(BronzeIntegrityError):
                _require_compatible(original, later, "A")
        later = deepcopy(original)
        original["transcript"]["source_track_id"] = "track-one"
        later["transcript"]["source_track_id"] = "track-two"
        with self.assertRaises(BronzeIntegrityError):
            _require_compatible(original, later, "A")
        later["transcript"]["source_track_id"] = None
        _require_compatible(original, later, "A")


if __name__ == "__main__":
    unittest.main()
