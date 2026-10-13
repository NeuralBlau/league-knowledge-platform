"""Real public SDK exercised exclusively through synthetic HTTP responses."""

from decimal import Decimal
import unittest
from unittest.mock import patch

from league_knowledge_platform import (
    CaptionKind, CaptionProviderError, TranscriptAcquisitionError, TranscriptConfig,
    TranscriptFailureKind, TranscriptUnavailableReason, YouTubeCaptionProvider, acquire_transcripts,
)
from caption_http_fixtures import VIDEO, SyntheticHTTPAdapter, caption_fixture, listing_script
from test_transcripts import shortlist

try:
    import defusedxml
    import requests
    import youtube_transcript_api as sdk
except ImportError:
    sdk = None


@unittest.skipIf(sdk is None, "Install requirements-transcripts.txt to run offline SDK adapter tests")
class YouTubeCaptionProviderTests(unittest.TestCase):
    def acquire(self, script, *, config=TranscriptConfig()):
        adapter = SyntheticHTTPAdapter(script)
        with YouTubeCaptionProvider(config=config, http_adapter=adapter) as provider:
            result = acquire_transcripts(shortlist(VIDEO), provider=provider)
        self.assertTrue(adapter.closed)
        return result, adapter

    def test_manual_variant_priority_uses_public_sdk_and_preserves_source_timing(self):
        script = listing_script((("auto", "en", True), ("manual", "en-GB", False)))
        script.append(("GET", "fixture=manual", caption_fixture("manual-en.xml"), 200))
        with patch.object(sdk.Transcript, "translate", side_effect=AssertionError("Translation")):
            result, adapter = self.acquire(script)
        transcript = result.transcripts[0]
        self.assertEqual(transcript.track.kind, CaptionKind.MANUAL)
        self.assertEqual(transcript.track.language_code, "en-GB")
        self.assertEqual(transcript.track.provider_version, "1.2.4")
        self.assertIsNone(transcript.track.source_track_id)
        self.assertEqual(transcript.segments[0].start_seconds, Decimal("0.123456789123456789"))
        self.assertEqual(transcript.segments[0].duration_seconds, Decimal("1.250"))
        self.assertEqual(transcript.segments[1].duration_seconds, Decimal("0"))
        self.assertEqual(transcript.text, "Keep & all words.\n[Music]\nRepeated overlapping caption.\nRepeated overlapping caption.")
        self.assertEqual(len(adapter.calls), 3)
        self.assertTrue(all(call[2]["timeout"] == (5.0, 15.0) for call in adapter.calls))
        self.assertFalse(any("tlang=" in call[1] for call in adapter.calls))

    def test_valid_empty_manual_response_falls_back_to_existing_auto_track(self):
        script = listing_script((("auto", "en", True), ("manual", "en", False)))
        script.extend((("GET", "fixture=manual", caption_fixture("empty.xml"), 200),
                       ("GET", "fixture=auto", caption_fixture("auto-en.xml"), 200)))
        result, adapter = self.acquire(script)
        self.assertEqual(result.transcripts[0].track.kind, CaptionKind.AUTO_GENERATED)
        self.assertIn("café ✓", result.transcripts[0].text)
        self.assertEqual(len(adapter.calls), 4)

    def test_no_english_or_no_tracks_is_normal_and_does_not_fetch(self):
        for specs, reason in (((("german", "de", False),), TranscriptUnavailableReason.NO_ENGLISH),
                              ((), TranscriptUnavailableReason.NO_CAPTIONS)):
            with self.subTest(specs=specs):
                result, adapter = self.acquire(listing_script(specs))
                self.assertEqual(result.transcripts, ())
                self.assertEqual(result.outcomes[0].unavailable_reason, reason)
                self.assertEqual(len(adapter.calls), 2)

    def test_sdk_disabled_captions_is_normal_candidate_unavailability(self):
        result, _ = self.acquire(listing_script(player={"playabilityStatus": {"status": "OK"}}))
        self.assertEqual(result.transcripts, ())
        self.assertEqual(result.outcomes[0].unavailable_reason, TranscriptUnavailableReason.CAPTIONS_DISABLED)

    def test_empty_or_whitespace_xml_is_normal_unavailability(self):
        for content in (b"<transcript/>", caption_fixture("empty.xml")):
            with self.subTest(content=content):
                script = listing_script((("manual", "en", False),))
                script.append(("GET", "fixture=manual", content, 200))
                result, _ = self.acquire(script)
                self.assertEqual(result.transcripts, ())
                self.assertEqual(result.outcomes[0].unavailable_reason, TranscriptUnavailableReason.EMPTY)

    def test_missing_duration_is_detected_before_sdk_can_fabricate_zero(self):
        script = listing_script((("manual", "en", False), ("auto", "en", True)))
        script.append(("GET", "fixture=manual", caption_fixture("missing-duration.xml"), 200))
        adapter = SyntheticHTTPAdapter(script)
        with YouTubeCaptionProvider(http_adapter=adapter) as provider:
            with self.assertRaises(TranscriptAcquisitionError) as failure:
                acquire_transcripts(shortlist(VIDEO), provider=provider)
        self.assertEqual(failure.exception.kind, TranscriptFailureKind.PARSING)
        self.assertEqual(len(adapter.calls), 3)
        self.assertFalse(any("fixture=auto" in call[1] for call in adapter.calls))

    def test_malformed_missing_or_invalid_timing_never_becomes_unavailability(self):
        contents = (
            caption_fixture("malformed.xml"), b"", b"plain text without timing",
            b'<transcript><text dur="1">Missing start</text></transcript>',
            b'<transcript><text>Text-only caption</text></transcript>',
            b'<transcript><text start="-1" dur="1">Negative start</text></transcript>',
            b'<transcript><text start="0" dur="-1">Negative duration</text></transcript>',
            b'<transcript><text start="NaN" dur="1">NaN</text></transcript>',
            b'<transcript><text start="0" dur="Infinity">Infinity</text></transcript>',
            b'<transcript><text start="0" dur="1">Nested <b>words</b></text></transcript>',
            b'<unknown><text start="0" dur="1">Unsupported format</text></unknown>',
            b'<!DOCTYPE transcript [<!ENTITY x SYSTEM "file:///not-a-real-fixture">]><transcript><text start="0" dur="1">&x;</text></transcript>',
        )
        for content in contents:
            with self.subTest(content=content):
                script = listing_script((("manual", "en", False),))
                script.append(("GET", "fixture=manual", content, 200))
                adapter = SyntheticHTTPAdapter(script)
                with YouTubeCaptionProvider(http_adapter=adapter) as provider:
                    with self.assertRaises(TranscriptAcquisitionError) as failure:
                        acquire_transcripts(shortlist(VIDEO), provider=provider)
                self.assertIn(failure.exception.kind,
                              (TranscriptFailureKind.PARSING, TranscriptFailureKind.MALFORMED_RESPONSE))

    def test_http_errors_and_partial_response_are_technical_with_no_retries(self):
        for status, kind in ((206, TranscriptFailureKind.MALFORMED_RESPONSE),
                             (401, TranscriptFailureKind.AUTHENTICATION),
                             (403, TranscriptFailureKind.AUTHORIZATION),
                             (429, TranscriptFailureKind.RATE_LIMIT),
                             (500, TranscriptFailureKind.SERVICE)):
            with self.subTest(status=status):
                script = listing_script((("manual", "en", False),))
                script.append(("GET", "fixture=manual", caption_fixture("manual-en.xml"), status))
                adapter = SyntheticHTTPAdapter(script)
                with YouTubeCaptionProvider(http_adapter=adapter) as provider:
                    with self.assertRaises(TranscriptAcquisitionError) as failure:
                        acquire_transcripts(shortlist(VIDEO), provider=provider)
                self.assertEqual(failure.exception.kind, kind)
                self.assertEqual(len(adapter.calls), 3)
                self.assertNotIn("fixture=", str(failure.exception))

    def test_transport_failures_are_explicit_and_release_provider_resources(self):
        for error, kind in ((requests.exceptions.Timeout("synthetic timeout"), TranscriptFailureKind.TIMEOUT),
                            (requests.exceptions.ConnectionError("synthetic URL?private=value"), TranscriptFailureKind.NETWORK),
                            (requests.exceptions.ChunkedEncodingError("partial content"), TranscriptFailureKind.MALFORMED_RESPONSE)):
            with self.subTest(kind=kind):
                script = listing_script((("manual", "en", False),))
                script.append(("GET", "fixture=manual", error, 200))
                adapter = SyntheticHTTPAdapter(script)
                with YouTubeCaptionProvider(http_adapter=adapter) as provider:
                    with self.assertRaises(TranscriptAcquisitionError) as failure:
                        acquire_transcripts(shortlist(VIDEO), provider=provider)
                self.assertEqual(failure.exception.kind, kind)
                self.assertTrue(adapter.closed)
                self.assertNotIn("private=value", str(failure.exception))

    def test_public_sdk_errors_are_not_caught_as_general_unavailability(self):
        errors = (
            (sdk.RequestBlocked(VIDEO), TranscriptFailureKind.BLOCKED),
            (sdk.IpBlocked(VIDEO), TranscriptFailureKind.BLOCKED),
            (sdk.AgeRestricted(VIDEO), TranscriptFailureKind.AUTHORIZATION),
            (sdk.PoTokenRequired(VIDEO), TranscriptFailureKind.AUTHORIZATION),
            (sdk.YouTubeDataUnparsable(VIDEO), TranscriptFailureKind.PARSING),
            (sdk.VideoUnavailable(VIDEO), TranscriptFailureKind.SERVICE),
            (sdk.VideoUnplayable(VIDEO, "synthetic", []), TranscriptFailureKind.SERVICE),
            (sdk.CouldNotRetrieveTranscript(VIDEO), TranscriptFailureKind.SERVICE),
        )
        for error, kind in errors:
            with self.subTest(kind=kind, error=type(error).__name__):
                with patch.object(sdk.YouTubeTranscriptApi, "list", side_effect=error):
                    with YouTubeCaptionProvider(http_adapter=SyntheticHTTPAdapter([])) as provider:
                        with self.assertRaises(CaptionProviderError) as failure:
                            provider.list_tracks(VIDEO)
                self.assertEqual(failure.exception.kind, kind)

    def test_real_sdk_fetch_metadata_and_completeness_are_cross_checked(self):
        original_fetch = sdk.Transcript.fetch
        for changed in ("video_id", "snippets", "language_code", "is_generated"):
            with self.subTest(changed=changed):
                def mutate(selected, **kwargs):
                    fetched = original_fetch(selected, **kwargs)
                    if changed == "snippets":
                        fetched.snippets = fetched.snippets[:1]
                    else:
                        setattr(fetched, changed, True if changed == "is_generated" else "incorrect")
                    return fetched
                script = listing_script((("manual", "en", False),))
                script.append(("GET", "fixture=manual", caption_fixture("manual-en.xml"), 200))
                with patch.object(sdk.Transcript, "fetch", mutate):
                    with YouTubeCaptionProvider(http_adapter=SyntheticHTTPAdapter(script)) as provider:
                        with self.assertRaises(TranscriptAcquisitionError) as failure:
                            acquire_transcripts(shortlist(VIDEO), provider=provider)
                self.assertEqual(failure.exception.kind, TranscriptFailureKind.CONTRACT)

    def test_sdk_formatting_preservation_and_complete_large_track(self):
        body = b'<transcript><text start="0" dur="1">&lt;b&gt;Keep wording&lt;/b&gt;</text>'
        body += b'<text start="1" dur="1">Complete repeated section.</text>' * 5000 + b'</transcript>'
        script = listing_script((("manual", "en", False),))
        script.append(("GET", "fixture=manual", body, 200))
        result, _ = self.acquire(script)
        self.assertEqual(len(result.transcripts[0].segments), 5001)
        self.assertEqual(result.transcripts[0].segments[0].text, "<b>Keep wording</b>")

    def test_provider_close_invalidates_handles_without_network(self):
        adapter = SyntheticHTTPAdapter(listing_script((("manual", "en", False),)))
        provider = YouTubeCaptionProvider(http_adapter=adapter)
        selected = provider.list_tracks(VIDEO)[0]
        provider.close()
        with self.assertRaises(CaptionProviderError) as failure:
            provider.fetch_track(selected)
        self.assertEqual(failure.exception.kind, TranscriptFailureKind.CONFIGURATION)
        self.assertEqual(len(adapter.calls), 2)

    def test_timeout_configuration_is_applied_to_actual_http_boundary(self):
        script = listing_script((("manual", "en", False),))
        script.append(("GET", "fixture=manual", caption_fixture("manual-en.xml"), 200))
        _, adapter = self.acquire(script, config=TranscriptConfig(2, 7))
        self.assertTrue(all(call[2]["timeout"] == (2, 7) for call in adapter.calls))

    def test_provider_rejects_unapproved_sdk_version_before_requests(self):
        adapter = SyntheticHTTPAdapter([])
        with patch("league_knowledge_platform.youtube_caption_provider.version", return_value="9.0"):
            with YouTubeCaptionProvider(http_adapter=adapter) as provider:
                with self.assertRaises(CaptionProviderError) as failure:
                    provider.list_tracks(VIDEO)
        self.assertEqual(failure.exception.kind, TranscriptFailureKind.CONFIGURATION)
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
