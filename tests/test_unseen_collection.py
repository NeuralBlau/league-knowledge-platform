"""Offline collector behavior and integration with real one-page discovery."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest

from league_knowledge_platform import (
    CandidateVideo,
    ChampionTarget,
    CollectionFailureKind,
    DiscoveryCursor,
    DiscoveryError,
    DiscoveryFailureKind,
    DiscoveryPage,
    SQLiteSourceCatalog,
    UnseenCandidateSet,
    UnseenCollectionError,
    YouTubeDiscovery,
    collect_unseen_candidates,
    initialize_source_catalog,
)
from league_knowledge_platform.youtube import HttpStatusFailure

TARGET = ChampionTarget("Ahri", "103", "Ahri")
OTHER = ChampionTarget("Aatrox", "266", "Aatrox")


def candidate(video_id, *, target=TARGET, view_count=None):
    return CandidateVideo(target.id, video_id, "Guide", None, None, view_count, None)


def page(video_ids=(), *, token=None, target=TARGET):
    videos = tuple(value if isinstance(value, CandidateVideo)
                   else candidate(value, target=target) for value in video_ids)
    cursor = DiscoveryCursor(target.id, token) if token is not None else None
    return DiscoveryPage(target.id, videos, cursor, token is None)


class FakeDiscovery:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def discover_page(self, target, cursor=None):
        self.calls.append((target, cursor))
        if not self.responses:
            raise AssertionError("Unexpected discovery request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response()
        return response


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


class CountingReader:
    def __init__(self, catalog):
        self.catalog = catalog
        self.calls = 0

    def load_integrated_ids(self):
        self.calls += 1
        return self.catalog.load_integrated_ids()


class UnseenCollectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalog.sqlite3"
        self.catalog = initialize_source_catalog(self.path)

    def collect(self, *responses, target=TARGET):
        discovery = FakeDiscovery(*responses)
        result = collect_unseen_candidates(
            target, discovery=discovery, catalog_reader=self.catalog
        )
        return result, discovery

    def test_integrated_identity_is_excluded_across_champion_targets(self):
        self.catalog.register_integrated("integrated")
        before = self.path.read_bytes()
        result, _ = self.collect(page(("integrated", "new"), target=OTHER), target=OTHER)
        self.assertEqual([item.video_id for item in result.candidates], ["new"])
        self.assertEqual(result.target_id, OTHER.id)
        self.assertEqual(self.path.read_bytes(), before)

    def test_cross_page_duplicates_keep_first_candidate_and_discovery_order(self):
        first = candidate("video-A", view_count=None)
        repeated = candidate("video-A", view_count=900)
        result, discovery = self.collect(
            page((first, "video-B"), token="next"),
            page((repeated, "video-C", "video-B")),
        )
        self.assertEqual([item.video_id for item in result.candidates],
                         ["video-A", "video-B", "video-C"])
        self.assertIs(result.candidates[0], first)
        self.assertIsNone(result.candidates[0].view_count)
        self.assertEqual(discovery.calls, [(TARGET, None), (TARGET, DiscoveryCursor("Ahri", "next"))])

    def test_first_page_overflow_is_truncated_without_requesting_another_page(self):
        result, discovery = self.collect(page(tuple(f"video-{i}" for i in range(25)), token="next"))
        self.assertEqual([item.video_id for item in result.candidates],
                         [f"video-{i}" for i in range(20)])
        self.assertTrue(result.target_reached)
        self.assertFalse(result.exhausted)
        self.assertEqual(len(discovery.calls), 1)

    def test_refill_overflow_retains_only_first_required_unseen_candidates(self):
        self.catalog.register_integrated("integrated")
        result, discovery = self.collect(
            page(tuple(f"video-{i}" for i in range(18)), token="next"),
            page(("video-3", "integrated", "video-18", "video-19", "video-20", "video-21"),
                 token="unused"),
        )
        self.assertEqual([item.video_id for item in result.candidates],
                         [f"video-{i}" for i in range(20)])
        self.assertEqual(len(discovery.calls), 2)
        self.assertFalse(result.exhausted)

    def test_target_reached_and_exhaustion_can_both_be_true(self):
        result, _ = self.collect(page(tuple(f"video-{i}" for i in range(20))))
        self.assertTrue(result.target_reached)
        self.assertTrue(result.exhausted)

    def test_zero_progress_pages_with_cursors_do_not_stop_refill(self):
        self.catalog.register_integrated("integrated")
        result, discovery = self.collect(
            page(("integrated",), token="second"),
            page((), token="third"),
            page(("integrated", "unseen")),
        )
        self.assertEqual([item.video_id for item in result.candidates], ["unseen"])
        self.assertEqual(len(discovery.calls), 3)
        self.assertTrue(result.exhausted)

    def test_duplicate_only_page_with_cursor_does_not_stop_refill(self):
        result, discovery = self.collect(
            page(("video-A",), token="second"),
            page(("video-A", "video-A"), token="third"),
            page(("video-B",)),
        )
        self.assertEqual([item.video_id for item in result.candidates], ["video-A", "video-B"])
        self.assertEqual(len(discovery.calls), 3)

    def test_empty_exhaustion_is_a_successful_empty_result(self):
        result, discovery = self.collect(page())
        self.assertEqual(result.candidates, ())
        self.assertTrue(result.exhausted)
        self.assertFalse(result.target_reached)
        self.assertEqual(len(discovery.calls), 1)

    def test_all_integrated_results_can_exhaust_successfully(self):
        self.catalog.register_integrated("integrated")
        result, _ = self.collect(page(("integrated",), token="next"), page(("integrated",)))
        self.assertEqual(result.candidates, ())
        self.assertTrue(result.exhausted)

    def test_success_does_not_persist_transient_candidates_or_modify_database(self):
        self.catalog.register_integrated("integrated")
        before = self.path.read_bytes()
        result, _ = self.collect(page(("integrated", "candidate-A", "candidate-B")))
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(self.catalog.load_integrated_ids(), frozenset({"integrated"}))
        self.assertEqual(self.path.read_bytes(), before)
        # A later collection may rediscover a candidate that was never admitted.
        later, _ = self.collect(page(("candidate-A",)))
        self.assertEqual(later.candidates[0].video_id, "candidate-A")

    def test_first_or_later_discovery_failure_has_no_success_pool_or_catalog_writes(self):
        before = self.path.read_bytes()
        for kind in DiscoveryFailureKind:
            for later in (False, True):
                with self.subTest(kind=kind, later=later):
                    error = DiscoveryError(kind, "Sanitized upstream failure")
                    responses = [page(("video-A",), token="next"), error] if later else [error]
                    discovery = FakeDiscovery(*responses)
                    with self.assertRaises(UnseenCollectionError) as failure:
                        collect_unseen_candidates(
                            TARGET, discovery=discovery, catalog_reader=self.catalog
                        )
                    self.assertEqual(failure.exception.kind, CollectionFailureKind.DISCOVERY)
                    self.assertEqual(failure.exception.discovery_failure_kind, kind)
                    self.assertIs(failure.exception.__cause__, error)
                    self.assertFalse(hasattr(failure.exception, "candidates"))
                    self.assertEqual(len(discovery.calls), 2 if later else 1)
                    self.assertEqual(self.path.read_bytes(), before)

    def test_missing_catalog_fails_before_discovery_without_creating_database(self):
        missing = Path(self.directory.name) / "missing" / "catalog.sqlite3"
        discovery = FakeDiscovery()
        with self.assertRaises(UnseenCollectionError) as failure:
            collect_unseen_candidates(
                TARGET, discovery=discovery, catalog_reader=SQLiteSourceCatalog(missing)
            )
        self.assertEqual(failure.exception.kind, CollectionFailureKind.CATALOG)
        self.assertEqual(discovery.calls, [])
        self.assertFalse(missing.parent.exists())

    def test_snapshot_is_loaded_once_and_sql_is_closed_before_discovery(self):
        reader = CountingReader(self.catalog)

        def externally_register_after_snapshot():
            self.catalog.register_integrated("video-A")
            return page(("video-A",), token="next")

        discovery = FakeDiscovery(externally_register_after_snapshot, page(("video-B",)))
        result = collect_unseen_candidates(TARGET, discovery=discovery, catalog_reader=reader)
        self.assertEqual(reader.calls, 1)
        self.assertEqual([item.video_id for item in result.candidates], ["video-A", "video-B"])
        self.assertTrue(self.catalog.is_integrated("video-A"))

    def test_invalid_reader_snapshot_is_a_contract_failure(self):
        class InvalidReader:
            def __init__(self, value):
                self.value = value

            def load_integrated_ids(self):
                return self.value

        for value in (set(), frozenset({"bad,id"})):
            discovery = FakeDiscovery()
            with self.subTest(value=value), self.assertRaises(UnseenCollectionError) as failure:
                collect_unseen_candidates(
                    TARGET, discovery=discovery, catalog_reader=InvalidReader(value)
                )
            self.assertEqual(failure.exception.kind, CollectionFailureKind.CONTRACT)
            self.assertEqual(discovery.calls, [])

    def test_wrong_target_or_nonpage_result_fails_instead_of_returning_candidates(self):
        for response in (page(("video-A",), target=OTHER), None):
            with self.subTest(response=response), self.assertRaises(UnseenCollectionError) as failure:
                self.collect(response)
            self.assertEqual(failure.exception.kind, CollectionFailureKind.CONTRACT)

    def test_invalid_discovered_identity_is_a_contract_failure(self):
        with self.assertRaises(UnseenCollectionError) as failure:
            self.collect(page((candidate("bad,id"),)))
        self.assertEqual(failure.exception.kind, CollectionFailureKind.CONTRACT)

    def test_cursor_cycle_is_an_error_and_not_normal_exhaustion(self):
        discovery = FakeDiscovery(page(token="A"), page(token="B"), page(token="A"))
        with self.assertRaises(UnseenCollectionError) as failure:
            collect_unseen_candidates(TARGET, discovery=discovery, catalog_reader=self.catalog)
        self.assertEqual(failure.exception.kind, CollectionFailureKind.CONTRACT)
        self.assertEqual(len(discovery.calls), 3)

    def test_result_is_immutable_and_rejects_incomplete_or_duplicate_sets(self):
        result = UnseenCandidateSet(TARGET.id, (candidate("video-A"),), True)
        with self.assertRaises(FrozenInstanceError):
            result.exhausted = False
        invalid = (
            ("", (), True),
            (TARGET.id, [], True),
            (TARGET.id, (), 1),
            (TARGET.id, (candidate("video-A"),), False),
            (TARGET.id, (candidate("video-A"), candidate("video-A")), True),
            (TARGET.id, (candidate("video-A", target=OTHER),), True),
            (TARGET.id, (candidate("bad,id"),), True),
            (TARGET.id, tuple(candidate(f"video-{i}") for i in range(21)), True),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                UnseenCandidateSet(*values)

    def test_discovery_collection_integration_preserves_cursor_metadata_and_read_only_state(self):
        self.catalog.register_integrated("integrated")
        before = self.path.read_bytes()
        transport = FakeTransport(
            {"items": [
                {"id": {"videoId": "integrated"}},
                {"id": {"videoId": "video-A"}},
                {"id": {"videoId": "video-B"}},
            ], "nextPageToken": "second-page"},
            {"items": [{"id": "video-A", "snippet": {"title": "Detailed guide"},
                        "statistics": {"viewCount": "1200"},
                        "contentDetails": {"duration": "PT10M"}}]},
            {"items": [
                {"id": {"videoId": "video-A"}},
                {"id": {"videoId": "integrated"}},
                {"id": {"videoId": "video-C"}},
            ]},
            {"items": [{"id": "video-A", "statistics": {"viewCount": "9999"}}]},
        )
        discovery = YouTubeDiscovery(api_key="offline-test-key", transport=transport)
        result = collect_unseen_candidates(TARGET, discovery=discovery, catalog_reader=self.catalog)
        self.assertEqual([item.video_id for item in result.candidates],
                         ["video-A", "video-B", "video-C"])
        self.assertTrue(result.exhausted)
        self.assertEqual(result.candidates[0].title, "Detailed guide")
        self.assertEqual(result.candidates[0].view_count, 1200)
        self.assertEqual(result.candidates[0].duration_seconds, 600)
        self.assertIsNone(result.candidates[1].view_count)
        self.assertNotIn("pageToken", transport.calls[0][1])
        self.assertEqual(transport.calls[2][1]["pageToken"], "second-page")
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(self.path.read_bytes(), before)

    def test_discovery_collection_integration_discards_pool_after_later_quota_failure(self):
        before = self.path.read_bytes()
        transport = FakeTransport(
            {"items": [{"id": {"videoId": "video-A"}}], "nextPageToken": "next"},
            {"items": []},
            HttpStatusFailure(403, "quotaExceeded"),
        )
        discovery = YouTubeDiscovery(api_key="offline-test-key", transport=transport)
        with self.assertRaises(UnseenCollectionError) as failure:
            collect_unseen_candidates(TARGET, discovery=discovery, catalog_reader=self.catalog)
        self.assertEqual(failure.exception.kind, CollectionFailureKind.DISCOVERY)
        self.assertEqual(failure.exception.discovery_failure_kind, DiscoveryFailureKind.QUOTA)
        self.assertIsInstance(failure.exception.__cause__, DiscoveryError)
        self.assertFalse(hasattr(failure.exception, "candidates"))
        self.assertNotIn("offline-test-key", str(failure.exception))
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
