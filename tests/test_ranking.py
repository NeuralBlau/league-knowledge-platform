"""Offline tests for eligibility, reproducible metadata scores, and shortlists."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import math
import unittest
from unittest.mock import patch

from league_knowledge_platform import (
    CandidateVideo,
    DEFAULT_RANKING_CONFIG,
    RankingConfig,
    UnseenCandidateSet,
    rank_candidates,
)

REFERENCE = datetime(2026, 10, 13, tzinfo=timezone.utc)


def video(video_id, *, views=None, age_days=None, duration=None):
    published = None if age_days is None else REFERENCE - timedelta(days=age_days)
    return CandidateVideo("Ahri", video_id, "Original title", "Original channel",
                          published, views, duration)


def pool(*candidates, exhausted=True):
    return UnseenCandidateSet("Ahri", candidates, exhausted)


class RankingTests(unittest.TestCase):
    def rank(self, *candidates, **kwargs):
        return rank_candidates(pool(*candidates), reference_time=REFERENCE, **kwargs)

    def test_duration_boundaries_and_missing_duration(self):
        for duration, eligible in ((0, False), (179, False), (180, True), (600, True),
                                   (1500, True), (1800, True), (1801, False), (None, True)):
            with self.subTest(duration=duration):
                candidate = video("candidate", duration=duration)
                result = self.rank(candidate)
                self.assertEqual(result.eligible_count, int(eligible))
                self.assertEqual(len(result.candidates), int(eligible))
                if eligible:
                    self.assertIs(result.candidates[0].candidate, candidate)

    def test_duration_never_changes_an_eligible_candidate_score(self):
        scores = []
        for duration in (180, 600, 1500, 1800, None):
            result = self.rank(video("candidate", views=100, age_days=100, duration=duration))
            scores.append(result.candidates[0].score)
        self.assertEqual(len(set(scores)), 1)
        first = video("z-first", views=100, age_days=100, duration=1500)
        second = video("a-second", views=100, age_days=100, duration=600)
        third = video("missing-duration", views=100, age_days=100)
        result = self.rank(first, second, third)
        self.assertEqual([item.candidate for item in result.candidates], [first, second, third])
        self.assertEqual(len({item.score for item in result.candidates}), 1)

    def test_duration_exclusion_precedes_popularity_normalization(self):
        result = self.rank(video("short", views=10**9, duration=179),
                           video("long", views=10**10, duration=1801),
                           video("eligible", views=100, duration=180))
        self.assertEqual(result.input_count, 3)
        self.assertEqual(result.eligible_count, 1)
        item = result.candidates[0]
        self.assertEqual(item.discovery_index, 2)
        self.assertEqual(item.popularity, 1.0)
        self.assertEqual(item.score, 0.7)

    def test_exact_shortlist_size_including_empty_and_excluded_pools(self):
        for count in (0, 1, 2, 3, 4, 20):
            with self.subTest(count=count):
                result = self.rank(*(video(f"v-{i}", views=i) for i in range(count)))
                self.assertEqual(len(result.candidates), min(3, count))
                self.assertEqual(result.eligible_count, count)
        result = self.rank(video("short", duration=1), video("long", duration=1801))
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.eligible_count, 0)

    def test_empty_shortlist_does_not_fabricate_search_exhaustion(self):
        candidates = pool(*(video(f"v-{i}", duration=1) for i in range(20)), exhausted=False)
        result = rank_candidates(candidates, reference_time=REFERENCE)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.input_count, 20)
        self.assertFalse(result.input_exhausted)

    def test_logarithmic_popularity_and_known_zero_views(self):
        result = self.rank(video("small", views=9), video("large", views=99),
                           video("zero", views=0))
        by_id = {item.candidate.video_id: item for item in result.candidates}
        self.assertAlmostEqual(by_id["small"].popularity, 0.5)
        self.assertEqual(by_id["large"].popularity, 1)
        self.assertEqual(by_id["zero"].popularity, 0)
        self.assertEqual(by_id["small"].score, 0.35)
        self.assertEqual(by_id["large"].score, 0.7)

    def test_all_known_views_zero_is_valid(self):
        result = self.rank(video("first", views=0), video("second", views=0))
        self.assertEqual([item.popularity for item in result.candidates], [0, 0])
        self.assertEqual([item.score for item in result.candidates], [0, 0])

    def test_large_integer_view_counts_do_not_overflow_normalization(self):
        result = self.rank(video("huge", views=10**1000), video("ordinary", views=100))
        self.assertEqual(result.candidates[0].popularity, 1)
        self.assertTrue(math.isfinite(result.candidates[1].score))

    def test_missing_signals_are_absent_with_zero_unredistributed_contributions(self):
        result = self.rank(video("views-only", views=100),
                           video("date-only", age_days=0), video("neither"))
        views, date, neither = result.candidates
        self.assertIsNone(views.recency)
        self.assertEqual(views.recency_contribution, 0)
        self.assertEqual(views.score, 0.7)
        self.assertIsNone(date.popularity)
        self.assertEqual(date.popularity_contribution, 0)
        self.assertEqual(date.score, 0.3)
        self.assertIsNone(neither.popularity)
        self.assertIsNone(neither.recency)
        self.assertEqual(neither.score, 0)

    def test_unknown_and_observed_zero_views_remain_distinguishable(self):
        result = self.rank(video("unknown"), video("zero", views=0))
        unknown, zero = result.candidates
        self.assertIsNone(unknown.popularity)
        self.assertIsNone(unknown.candidate.view_count)
        self.assertEqual(zero.popularity, 0)
        self.assertEqual(zero.candidate.view_count, 0)
        self.assertEqual(unknown.score, zero.score)

    def test_all_missing_signals_preserve_discovery_order_over_video_id(self):
        result = self.rank(*(video(name) for name in ("z-first", "y-second", "b-third", "a-fourth")))
        self.assertEqual([item.candidate.video_id for item in result.candidates],
                         ["z-first", "y-second", "b-third"])

    def test_popularity_has_greater_maximum_influence_than_recency(self):
        result = self.rank(video("recent", views=0, age_days=0),
                           video("popular", views=100, age_days=36500))
        self.assertEqual(result.candidates[0].candidate.video_id, "popular")
        self.assertEqual(result.candidates[0].popularity_contribution, 0.7)
        self.assertEqual(result.candidates[1].recency_contribution, 0.3)

    def test_recency_half_life_and_fractional_days(self):
        for age, expected in ((0, 1), (365, 0.5), (730, 0.25), (182.5, 2**-0.5)):
            with self.subTest(age=age):
                item = self.rank(video("candidate", age_days=age)).candidates[0]
                self.assertAlmostEqual(item.recency, expected)
                self.assertAlmostEqual(item.recency_contribution, 0.3 * expected)

    def test_future_publication_is_capped_without_changing_original_metadata(self):
        candidate = video("future", age_days=-1)
        item = self.rank(candidate).candidates[0]
        self.assertEqual(item.recency, 1)
        self.assertEqual(item.score, 0.3)
        self.assertIs(item.candidate, candidate)
        self.assertEqual(candidate.published_at_utc, REFERENCE + timedelta(days=1))

    def test_equivalent_reference_timezones_produce_identical_results(self):
        candidates = pool(video("candidate", views=100, age_days=10))
        offset_reference = REFERENCE.astimezone(timezone(timedelta(hours=2)))
        utc = rank_candidates(candidates, reference_time=REFERENCE)
        offset = rank_candidates(candidates, reference_time=offset_reference)
        self.assertEqual(utc, offset)
        self.assertEqual(offset.reference_time_utc, REFERENCE)

    def test_same_inputs_repeat_identically_and_reference_time_controls_recency(self):
        candidates = pool(video("candidate", views=100, age_days=0))
        first = rank_candidates(candidates, reference_time=REFERENCE)
        self.assertEqual(first, rank_candidates(candidates, reference_time=REFERENCE))
        later = rank_candidates(candidates, reference_time=REFERENCE + timedelta(days=365))
        self.assertEqual(first.candidates[0].score, 1)
        self.assertEqual(later.candidates[0].score, 0.85)

    def test_rounded_final_scores_define_discovery_order_ties(self):
        older_first = video("z-first", age_days=0.001)
        newer_second = video("a-second", age_days=0)
        result = self.rank(older_first, newer_second, config=RankingConfig(score_precision=3))
        self.assertNotEqual(result.candidates[0].recency, result.candidates[1].recency)
        self.assertEqual(result.candidates[0].score, result.candidates[1].score)
        self.assertIs(result.candidates[0].candidate, older_first)

    def test_reference_input_is_required_and_invalid_contracts_fail_explicitly(self):
        with self.assertRaises(TypeError):
            rank_candidates(pool())
        for reference in (None, "2026-10-13", REFERENCE.replace(tzinfo=None),
                          datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                rank_candidates(pool(), reference_time=reference)
        for candidates in ((), [], None):
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                rank_candidates(candidates, reference_time=REFERENCE)
        with self.assertRaises(ValueError):
            self.rank(config=None)

    def test_immutable_config_and_results_preserve_original_identity_and_metadata(self):
        original = video("candidate", views=123, age_days=5, duration=1500)
        result = self.rank(original)
        self.assertIs(result.candidates[0].candidate, original)
        self.assertEqual(result.target_id, original.target_id)
        self.assertEqual(result.candidates[0].candidate.url, original.url)
        self.assertIs(result.config, DEFAULT_RANKING_CONFIG)
        for obj, field, value in ((result, "eligible_count", 0),
                                  (result.candidates[0], "score", 0),
                                  (result.config, "popularity_weight", 1)):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(obj, field, value)

    def test_config_rejects_invalid_weights_half_life_and_precision(self):
        invalid = (
            {"popularity_weight": 0.5, "recency_weight": 0.5},
            {"popularity_weight": 0.3, "recency_weight": 0.7},
            {"popularity_weight": 0.8},
            {"recency_weight": 0}, {"popularity_weight": True},
            {"recency_half_life_days": 0}, {"recency_half_life_days": -1},
            {"recency_half_life_days": float("nan")},
            {"popularity_weight": float("inf")}, {"recency_weight": "0.3"},
            {"recency_half_life_days": 10**1000}, {"popularity_weight": 10**1000},
            {"popularity_weight": 1e308, "recency_weight": 1e308},
            {"score_precision": -1}, {"score_precision": 16},
            {"score_precision": True}, {"score_precision": 1.5},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                RankingConfig(**changes)

    def test_explicit_config_is_recorded_and_changes_only_scoring(self):
        config = RankingConfig(popularity_weight=0.8, recency_weight=0.2,
                               recency_half_life_days=100)
        result = self.rank(video("candidate", views=10, age_days=100), config=config)
        self.assertIs(result.config, config)
        self.assertEqual(result.candidates[0].recency, 0.5)
        self.assertEqual(result.candidates[0].score, 0.9)

    def test_ranker_performs_no_network_file_or_database_io(self):
        candidates = pool(video("candidate", views=100, age_days=0))
        with patch("builtins.open", side_effect=AssertionError("File I/O")), \
                patch("sqlite3.connect", side_effect=AssertionError("Database I/O")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("Network I/O")):
            result = rank_candidates(candidates, reference_time=REFERENCE)
        self.assertEqual(result.candidates[0].score, 1)

    def test_approved_formula_example(self):
        specs = (
            ("A", 1000000, 730, 600), ("B", 100000, 0, 600),
            ("C", 10000, 30, 1500), ("D", None, 0, 900),
            ("E", 100000, None, None), ("F", None, None, None),
            ("G", 100000, 0, 1500), ("H", 10000000, 0, 120),
            ("I", 2000000, 0, 2400),
        )
        result = self.rank(*(video(name, views=views, age_days=age, duration=duration)
                             for name, views, age, duration in specs))
        self.assertEqual(result.eligible_count, 7)
        self.assertEqual([item.candidate.video_id for item in result.candidates], ["B", "G", "A"])
        self.assertEqual(result.candidates[0].score, 0.883333797785)
        self.assertEqual(result.candidates[0].score, result.candidates[1].score)
        self.assertEqual(result.candidates[2].score, 0.775)


if __name__ == "__main__":
    unittest.main()
