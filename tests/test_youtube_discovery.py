"""Offline tests for one-page YouTube candidate discovery."""

import io
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.error import HTTPError

from league_knowledge_platform import (
    CandidateVideo,
    ChampionTarget,
    DiscoveryCursor,
    DiscoveryError,
    DiscoveryFailureKind,
    DiscoveryPage,
    YouTubeDiscovery,
)
from league_knowledge_platform.youtube import HttpStatusFailure, UrllibJsonTransport

TARGET = ChampionTarget(id="Ahri", key="103", name="Ahri")
OTHER = ChampionTarget(id="Aatrox", key="266", name="Aatrox")


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get_json(self, endpoint, params, timeout):
        self.calls.append((endpoint, dict(params), timeout))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def search_item(video_id, **snippet):
    return {"id": {"kind": "youtube#video", "videoId": video_id}, "snippet": snippet}


class YouTubeDiscoveryTests(unittest.TestCase):
    def client(self, transport):
        return YouTubeDiscovery(api_key="test-secret", transport=transport)

    def test_one_page_per_call_with_continuation_and_metadata(self):
        transport = FakeTransport(
            {
                "items": [
                    search_item("video-A", title="Ahri guide", channelTitle="Teacher",
                                publishedAt="2026-10-01T12:00:00Z"),
                    search_item("video-B", title="Another guide"),
                ],
                "nextPageToken": "second-page",
            },
            {"items": [
                {"id": "video-A", "snippet": {"title": "Detailed Ahri guide"},
                 "statistics": {"viewCount": "1200"},
                 "contentDetails": {"duration": "PT1H2M3S"}},
            ]},
            {"items": [search_item("video-C", title="Final guide")]},
            {"items": []},
        )
        client = self.client(transport)

        first = client.discover_page(TARGET)
        self.assertFalse(first.exhausted)
        self.assertEqual(first.next_cursor, DiscoveryCursor("Ahri", "second-page"))
        self.assertEqual([video.video_id for video in first.candidates], ["video-A", "video-B"])
        self.assertEqual(first.candidates[0].title, "Detailed Ahri guide")
        self.assertEqual(first.candidates[0].channel_title, "Teacher")
        self.assertEqual(first.candidates[0].published_at_utc,
                         datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(first.candidates[0].view_count, 1200)
        self.assertEqual(first.candidates[0].duration_seconds, 3723)
        self.assertEqual(first.candidates[1].view_count, None)
        self.assertEqual(first.candidates[1].duration_seconds, None)
        self.assertEqual(first.candidates[1].title, "Another guide")

        second = client.discover_page(TARGET, first.next_cursor)
        self.assertTrue(second.exhausted)
        self.assertIsNone(second.next_cursor)
        self.assertEqual([video.video_id for video in second.candidates], ["video-C"])
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(transport.calls[0][1]["q"], "League of Legends Ahri guide")
        self.assertEqual(transport.calls[0][1]["type"], "video")
        self.assertEqual(transport.calls[0][1]["maxResults"], "25")
        self.assertEqual(transport.calls[1][1]["id"], "video-A,video-B")
        self.assertNotIn("pageToken", transport.calls[0][1])
        self.assertEqual(transport.calls[2][1]["pageToken"], "second-page")

    def test_empty_or_short_page_can_be_exhausted(self):
        empty = self.client(FakeTransport({"items": []})).discover_page(TARGET)
        self.assertEqual(empty.candidates, ())
        self.assertTrue(empty.exhausted)
        self.assertIsNone(empty.next_cursor)

        short_transport = FakeTransport({"items": [search_item("video-A")]}, {"items": []})
        short = self.client(short_transport).discover_page(TARGET)
        self.assertEqual(len(short.candidates), 1)
        self.assertTrue(short.exhausted)
        self.assertEqual(short.candidates[0].view_count, None)

    def test_short_page_with_continuation_is_not_exhausted(self):
        transport = FakeTransport(
            {"items": [search_item("video-A")], "nextPageToken": "next"},
            {"items": []},
        )
        page = self.client(transport).discover_page(TARGET)
        self.assertEqual(len(page.candidates), 1)
        self.assertFalse(page.exhausted)
        self.assertEqual(page.next_cursor.page_token, "next")

    def test_missing_identity_is_not_emitted_and_duplicates_are_removed(self):
        transport = FakeTransport(
            {"items": [
                {"id": {"kind": "youtube#video"}, "snippet": {"title": "No ID"}},
                {"id": {"kind": "youtube#channel", "videoId": "wrong-kind"}},
                search_item("bad,id"),
                search_item("video-A"),
                search_item("video-A"),
            ]},
            {"items": [{"id": "video-A"}]},
        )
        page = self.client(transport).discover_page(TARGET)
        self.assertEqual([video.video_id for video in page.candidates], ["video-A"])
        self.assertEqual(transport.calls[1][1]["id"], "video-A")

    def test_cursor_cannot_be_used_for_another_target(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(ValueError, "another Champion"):
            self.client(transport).discover_page(OTHER, DiscoveryCursor("Ahri", "next"))
        self.assertEqual(transport.calls, [])

    def test_page_state_and_target_invariants(self):
        with self.assertRaises(ValueError):
            DiscoveryPage("Ahri", (), None, False)
        with self.assertRaises(ValueError):
            DiscoveryPage("Ahri", (), DiscoveryCursor("Ahri", "next"), True)
        with self.assertRaises(ValueError):
            DiscoveryPage("Ahri", (), DiscoveryCursor("Aatrox", "next"), False)
        with self.assertRaises(ValueError):
            DiscoveryPage("Ahri", [], None, True)
        with self.assertRaises(ValueError):
            DiscoveryPage("Ahri", (), None, 1)
        with self.assertRaises(ValueError):
            DiscoveryCursor("Ahri", " ")
        candidate = CandidateVideo("Aatrox", "video-A", None, None, None, None, None)
        with self.assertRaises(ValueError):
            DiscoveryPage("Ahri", (candidate,), None, True)

    def test_failure_on_requested_page_returns_no_successful_page(self):
        transport = FakeTransport(
            {"items": [search_item("video-A")], "nextPageToken": "next"},
            {"items": []},
            HttpStatusFailure(403, "quotaExceeded"),
        )
        client = self.client(transport)
        first = client.discover_page(TARGET)
        self.assertEqual(first.candidates[0].video_id, "video-A")
        with self.assertRaises(DiscoveryError) as failure:
            client.discover_page(TARGET, first.next_cursor)
        self.assertEqual(failure.exception.kind, DiscoveryFailureKind.QUOTA)
        self.assertNotIn("test-secret", str(failure.exception))
        self.assertEqual(len(transport.calls), 3)

    def test_metadata_failure_discards_requested_page(self):
        transport = FakeTransport(
            {"items": [search_item("video-A")]},
            HttpStatusFailure(500),
        )
        with self.assertRaises(DiscoveryError) as failure:
            self.client(transport).discover_page(TARGET)
        self.assertEqual(failure.exception.kind, DiscoveryFailureKind.SERVICE)
        self.assertEqual(len(transport.calls), 2)

    def test_malformed_responses_fail_instead_of_signaling_exhaustion(self):
        cases = [
            ({"items": "not-a-list"}, None),
            ({"items": [], "nextPageToken": 7}, None),
            ({"items": [search_item("video-A")]}, {"items": "not-a-list"}),
            ({"items": [search_item("video-A")]},
             {"items": [{"id": "video-A", "statistics": {"viewCount": "bad"}}]}),
            ({"items": [search_item("video-A")]},
             {"items": [{"id": "video-A", "contentDetails": {"duration": "invalid"}}]}),
        ]
        for search, details in cases:
            with self.subTest(search=search, details=details):
                transport = FakeTransport(*(response for response in (search, details)
                                            if response is not None))
                with self.assertRaises(DiscoveryError) as failure:
                    self.client(transport).discover_page(TARGET)
                self.assertEqual(failure.exception.kind, DiscoveryFailureKind.MALFORMED_RESPONSE)

    def test_error_categories_and_no_automatic_retry(self):
        cases = [
            (HttpStatusFailure(401), DiscoveryFailureKind.AUTHENTICATION),
            (HttpStatusFailure(403, "forbidden"), DiscoveryFailureKind.AUTHORIZATION),
            (HttpStatusFailure(403, "quotaExceeded"), DiscoveryFailureKind.QUOTA),
            (HttpStatusFailure(403, "dailyLimitExceeded"), DiscoveryFailureKind.QUOTA),
            (TimeoutError(), DiscoveryFailureKind.TIMEOUT),
            (OSError(), DiscoveryFailureKind.NETWORK),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                transport = FakeTransport(error)
                with self.assertRaises(DiscoveryError) as failure:
                    self.client(transport).discover_page(TARGET)
                self.assertEqual(failure.exception.kind, expected)
                self.assertEqual(len(transport.calls), 1)

    def test_missing_api_key_fails_before_network(self):
        transport = FakeTransport()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(DiscoveryError) as failure:
                YouTubeDiscovery(transport=transport)
        self.assertEqual(failure.exception.kind, DiscoveryFailureKind.CONFIGURATION)
        self.assertEqual(transport.calls, [])

    def test_standard_library_transport_uses_encoded_parameters_and_sanitizes_errors(self):
        transport = UrllibJsonTransport()
        with patch("league_knowledge_platform.youtube.urlopen", return_value=io.BytesIO(b'{"items":[]}')) as open_url:
            self.assertEqual(
                transport.get_json("https://example.test/search",
                                   {"q": "Ahri guide", "key": "test-secret"}, 5),
                {"items": []},
            )
            request = open_url.call_args.args[0]
            self.assertIn("q=Ahri+guide", request.full_url)
            self.assertEqual(open_url.call_args.kwargs["timeout"], 5)

        error = HTTPError(
            "https://example.test/search?key=test-secret", 403, "Forbidden", {},
            io.BytesIO(b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'),
        )
        with patch("league_knowledge_platform.youtube.urlopen", side_effect=error):
            with self.assertRaises(HttpStatusFailure) as failure:
                transport.get_json("https://example.test/search", {"key": "test-secret"}, 5)
        self.assertEqual(failure.exception.reason, "quotaExceeded")
        self.assertNotIn("test-secret", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
