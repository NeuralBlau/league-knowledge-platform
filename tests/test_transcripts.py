"""Provider-independent acquisition and real-ranking integration, entirely offline."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch

from league_knowledge_platform import (
    CandidateVideo, CaptionKind, CaptionProviderError, CaptionSegment, CaptionTrack,
    CaptionUnavailable, ProviderTranscript, TranscriptAcquisitionError, TranscriptConfig,
    TranscriptFailureKind, TranscriptStatus, TranscriptUnavailableReason,
    UnseenCandidateSet, YouTubeCaptionProvider, acquire_transcripts, rank_candidates,
)

REFERENCE = datetime(2026, 10, 13, tzinfo=timezone.utc)


def shortlist(*ids):
    candidates = tuple(CandidateVideo("Ahri", name, "Title", "Creator", None, None, None)
                       for name in ids)
    return rank_candidates(UnseenCandidateSet("Ahri", candidates, True), reference_time=REFERENCE)


def track(video_id, *, language="en", kind=CaptionKind.MANUAL, key=None):
    return CaptionTrack(video_id, language, kind, key or f"{video_id}-{language}-{kind.value}",
                        "fake-caption-provider", "fixture")


def segment(text="Original caption", *, index=0, start="0.125", duration="1.25"):
    return CaptionSegment(index, text, Decimal(start), Decimal(duration))


class FakeProvider:
    def __init__(self, tracks, contents=None):
        self.tracks = tracks
        self.contents = contents or {}
        self.calls = []

    def list_tracks(self, video_id):
        self.calls.append(("list", video_id))
        value = self.tracks[video_id]
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_track(self, selected):
        self.calls.append(("fetch", selected.provider_key))
        value = self.contents.get(selected.provider_key, (segment(),))
        if isinstance(value, Exception):
            raise value
        if isinstance(value, ProviderTranscript):
            return value
        return ProviderTranscript(selected, value)


class TranscriptTests(unittest.TestCase):
    def test_zero_one_two_and_three_candidates(self):
        for count in range(4):
            with self.subTest(count=count):
                ranked = shortlist(*(f"video-{i}" for i in range(count)))
                provider = FakeProvider({entry.candidate.video_id: (track(entry.candidate.video_id),)
                                         for entry in ranked.candidates})
                result = acquire_transcripts(ranked, provider=provider)
                self.assertIs(result.shortlist, ranked)
                self.assertEqual(len(result.transcripts), count)
                self.assertEqual(len(result.outcomes), count)
                self.assertEqual(len(provider.calls), count * 2)

    def test_empty_shortlist_does_not_load_or_call_optional_provider(self):
        with patch("builtins.__import__", side_effect=AssertionError("Unexpected dependency import")):
            with YouTubeCaptionProvider() as provider:
                result = acquire_transcripts(shortlist(), provider=provider)
        self.assertEqual(result.transcripts, ())
        self.assertEqual(result.outcomes, ())

    def test_manual_locale_variant_beats_auto_generic_english(self):
        manual = track("A", language="en-GB")
        auto = track("A", kind=CaptionKind.AUTO_GENERATED)
        provider = FakeProvider({"A": (auto, manual)})
        result = acquire_transcripts(shortlist("A"), provider=provider)
        self.assertIs(result.transcripts[0].track, manual)
        self.assertEqual(provider.calls, [("list", "A"), ("fetch", manual.provider_key)])

    def test_locale_matching_and_deterministic_preference(self):
        for language in ("en", "en-US", "en-GB", "EN_us", "en-AU", "en-Latn-US"):
            with self.subTest(language=language):
                selected = track("A", language=language)
                result = acquire_transcripts(shortlist("A"), provider=FakeProvider({"A": (selected,)}))
                self.assertEqual(result.transcripts[0].track.language_code, language)
        candidates = tuple(track("A", language=language) for language in ("en-AU", "en-GB", "en-US", "en"))
        result = acquire_transcripts(shortlist("A"), provider=FakeProvider({"A": candidates}))
        self.assertEqual(result.transcripts[0].track.language_code, "en")

    def test_nonenglish_tracks_are_not_fetched_or_translated(self):
        for language in ("de", "fr", "eng", "enough", "en-", "en--US"):
            with self.subTest(language=language):
                provider = FakeProvider({"A": (track("A", language=language),)})
                result = acquire_transcripts(shortlist("A"), provider=provider)
                self.assertEqual(result.transcripts, ())
                self.assertEqual(result.outcomes[0].unavailable_reason, TranscriptUnavailableReason.NO_ENGLISH)
                self.assertEqual(provider.calls, [("list", "A")])

    def test_empty_manual_track_falls_back_to_auto_english(self):
        manual, auto = track("A"), track("A", kind=CaptionKind.AUTO_GENERATED)
        provider = FakeProvider({"A": (auto, manual)}, {manual.provider_key: (segment(" \n\t "),)})
        result = acquire_transcripts(shortlist("A"), provider=provider)
        self.assertIs(result.transcripts[0].track, auto)
        self.assertEqual(provider.calls, [("list", "A"), ("fetch", manual.provider_key), ("fetch", auto.provider_key)])

    def test_empty_manual_variant_does_not_skip_other_manual_variants(self):
        generic = track("A")
        manual_gb = track("A", language="en-GB")
        auto = track("A", kind=CaptionKind.AUTO_GENERATED)
        provider = FakeProvider({"A": (auto, manual_gb, generic)}, {generic.provider_key: ()})
        result = acquire_transcripts(shortlist("A"), provider=provider)
        self.assertIs(result.transcripts[0].track, manual_gb)
        self.assertNotIn(("fetch", auto.provider_key), provider.calls)

    def test_normal_absence_continues_in_rank_order_with_explicit_outcomes(self):
        ranked = shortlist("A", "B", "C")
        provider = FakeProvider({"A": (track("A"),), "B": CaptionUnavailable(
            TranscriptUnavailableReason.CAPTIONS_DISABLED), "C": (track("C"),)})
        result = acquire_transcripts(ranked, provider=provider)
        self.assertEqual([item.ranked_candidate.candidate.video_id for item in result.transcripts], ["A", "C"])
        self.assertEqual([item.status for item in result.outcomes],
                         [TranscriptStatus.ACQUIRED, TranscriptStatus.UNAVAILABLE, TranscriptStatus.ACQUIRED])
        self.assertIs(result.outcomes[1].ranked_candidate, ranked.candidates[1])
        self.assertEqual(result.transcripts[1].shortlist_position, 2)

    def test_all_normally_unavailable_is_successfully_empty(self):
        manual = track("C")
        provider = FakeProvider({"A": (), "B": (track("B", language="de"),), "C": (manual,)},
                                {manual.provider_key: (segment(" \t "),)})
        result = acquire_transcripts(shortlist("A", "B", "C"), provider=provider)
        self.assertEqual(result.transcripts, ())
        self.assertEqual([outcome.unavailable_reason for outcome in result.outcomes],
                         [TranscriptUnavailableReason.NO_CAPTIONS, TranscriptUnavailableReason.NO_ENGLISH,
                          TranscriptUnavailableReason.EMPTY])

    def test_technical_failure_in_any_position_has_no_success_payload_or_later_requests(self):
        for kind in TranscriptFailureKind:
            for position in range(3):
                with self.subTest(kind=kind, position=position):
                    names = ("A", "B", "C")
                    contents = {track(names[position]).provider_key: CaptionProviderError(kind)}
                    provider = FakeProvider({name: (track(name),) for name in names}, contents)
                    with self.assertRaises(TranscriptAcquisitionError) as failure:
                        acquire_transcripts(shortlist(*names), provider=provider)
                    error = failure.exception
                    self.assertEqual(error.kind, kind)
                    self.assertEqual(error.video_id, names[position])
                    self.assertEqual(error.shortlist_position, position)
                    self.assertFalse(hasattr(error, "transcripts"))
                    self.assertFalse(hasattr(error, "outcomes"))
                    self.assertEqual(len(provider.calls), (position + 1) * 2)

    def test_manual_technical_failure_does_not_fall_back_to_auto(self):
        manual, auto = track("A"), track("A", kind=CaptionKind.AUTO_GENERATED)
        provider = FakeProvider({"A": (manual, auto)},
                                {manual.provider_key: CaptionProviderError(TranscriptFailureKind.TIMEOUT)})
        with self.assertRaises(TranscriptAcquisitionError):
            acquire_transcripts(shortlist("A"), provider=provider)
        self.assertNotIn(("fetch", auto.provider_key), provider.calls)

    def test_list_failure_is_explicit_and_does_not_expose_provider_messages(self):
        provider = FakeProvider({"A": RuntimeError("provider-url?secret=private-transcript")})
        with self.assertRaises(TranscriptAcquisitionError) as failure:
            acquire_transcripts(shortlist("A"), provider=provider)
        self.assertEqual(failure.exception.kind, TranscriptFailureKind.CONTRACT)
        self.assertEqual(failure.exception.phase, "list")
        self.assertNotIn("private-transcript", str(failure.exception))

    def test_normalization_preserves_complete_source_and_exact_timing(self):
        selected = track("A")
        raw = (segment("  Keep\nall words & punctuation.  ", index=0, start="0.123456789123456789"),
               segment(" \t ", index=1), segment("Repeated caption", index=2, start="0.1", duration="0"),
               segment("Repeated caption", index=3, start="0.1"))
        result = acquire_transcripts(shortlist("A"), provider=FakeProvider({"A": (selected,)}, {selected.provider_key: raw}))
        acquired = result.transcripts[0]
        self.assertEqual(acquired.text, "Keep all words & punctuation.\nRepeated caption\nRepeated caption")
        self.assertEqual([item.source_index for item in acquired.segments], [0, 2, 3])
        self.assertEqual(acquired.segments[0].source_text, raw[0].source_text)
        self.assertEqual(acquired.segments[0].start_seconds, Decimal("0.123456789123456789"))
        self.assertEqual(acquired.segments[1].duration_seconds, Decimal("0"))
        self.assertNotIn("Keep", repr(acquired))

    def test_long_and_duplicate_content_is_neither_truncated_nor_deduplicated(self):
        contents = "Complete content. " * 20000
        provider = FakeProvider({name: (track(name),) for name in ("A", "B")},
                                {track(name).provider_key: (segment(contents),) for name in ("A", "B")})
        result = acquire_transcripts(shortlist("A", "B"), provider=provider)
        self.assertEqual(len(result.transcripts), 2)
        self.assertEqual(result.transcripts[0].text, contents.strip())
        self.assertEqual(result.transcripts[1].text, contents.strip())

    def test_provider_identity_mismatch_is_a_technical_contract_failure(self):
        requested, other = track("A"), track("B")
        for provider in (FakeProvider({"A": (other,)}),
                         FakeProvider({"A": (requested,)},
                                      {requested.provider_key: ProviderTranscript(other, (segment(),))})):
            with self.assertRaises(TranscriptAcquisitionError) as failure:
                acquire_transcripts(shortlist("A"), provider=provider)
            self.assertEqual(failure.exception.kind, TranscriptFailureKind.CONTRACT)

    def test_real_ranker_to_fake_provider_integration_preserves_original_metadata(self):
        candidates = (
            CandidateVideo("Ahri", "older", "Older title", "Older creator", REFERENCE - timedelta(days=730), 1000, 1500),
            CandidateVideo("Ahri", "recent", "Recent title", "Recent creator", REFERENCE, 100, 600),
            CandidateVideo("Ahri", "missing", None, None, None, None, None),
            CandidateVideo("Ahri", "excluded", "Short", "Creator", REFERENCE, 10000000, 1),
        )
        ranked = rank_candidates(UnseenCandidateSet("Ahri", candidates, True), reference_time=REFERENCE)
        provider = FakeProvider({entry.candidate.video_id: (track(entry.candidate.video_id),) for entry in ranked.candidates})
        with patch("builtins.open", side_effect=AssertionError("File I/O")), \
                patch("sqlite3.connect", side_effect=AssertionError("Database I/O")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("Discovery I/O")):
            result = acquire_transcripts(ranked, provider=provider)
        self.assertIs(result.shortlist, ranked)
        for index, acquired in enumerate(result.transcripts):
            self.assertIs(acquired.ranked_candidate, ranked.candidates[index])
            self.assertIs(acquired.ranked_candidate.candidate, ranked.candidates[index].candidate)
            self.assertEqual(acquired.ranked_candidate.score, ranked.candidates[index].score)
        self.assertNotIn(("list", "excluded"), provider.calls)
        with self.assertRaises(FrozenInstanceError):
            result.transcripts = ()

    def test_invalid_input_is_rejected_before_provider_calls(self):
        provider = FakeProvider({})
        for invalid in (None, (), []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                acquire_transcripts(invalid, provider=provider)
        ranked = shortlist("A", "B")
        duplicate = replace(ranked, candidates=(ranked.candidates[0], ranked.candidates[0]))
        with self.assertRaises(ValueError):
            acquire_transcripts(duplicate, provider=provider)
        self.assertEqual(provider.calls, [])

    def test_invalid_timing_or_source_order_fails_without_synthesis(self):
        for value in (Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 0.1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CaptionSegment(0, "Content", value, Decimal("1"))
        selected = track("A")
        provider = FakeProvider({"A": (selected,)},
                                {selected.provider_key: (segment(index=1), segment(index=0))})
        with self.assertRaises(TranscriptAcquisitionError) as failure:
            acquire_transcripts(shortlist("A"), provider=provider)
        self.assertEqual(failure.exception.kind, TranscriptFailureKind.CONTRACT)

    def test_transcript_config_rejects_unusable_timeouts(self):
        for value in (0, -1, True, "5", float("nan"), float("inf"), 10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TranscriptConfig(connect_timeout_seconds=value)


if __name__ == "__main__":
    unittest.main()
