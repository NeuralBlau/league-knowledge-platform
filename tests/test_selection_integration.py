"""Real ranker/acquisition/selection contracts, using fake semantic capabilities."""

import unittest
from unittest.mock import patch

from league_knowledge_platform import SelectedSource, SelectionFailed, SelectionStage, select_source
from selection_http_fixtures import TARGET, transcript_set
from test_source_selection import FakeSelection, comparison, quality


class SelectionIntegrationTests(unittest.TestCase):
    def test_ranker_acquisition_selection_preserve_provenance_without_persistence(self):
        inputs = transcript_set("A", "B", "C", unavailable=("B",))
        fake = FakeSelection([quality("A", "C")], [comparison("A", "C", winner="A")])
        original = next(t for t in inputs.transcripts if t.track.video_id == "A")
        with patch("sqlite3.connect", side_effect=AssertionError("SQL forbidden")), \
                patch("builtins.open", side_effect=AssertionError("Filesystem forbidden")), \
                patch("socket.create_connection", side_effect=AssertionError("Network forbidden")), \
                patch("league_knowledge_platform.SQLiteSourceCatalog.register_integrated",
                      side_effect=AssertionError("Registration forbidden")), \
                patch("league_knowledge_platform.YouTubeDiscovery.discover_page",
                      side_effect=AssertionError("Discovery forbidden")), \
                patch("league_knowledge_platform.rank_candidates",
                      side_effect=AssertionError("Ranking forbidden")), \
                patch("league_knowledge_platform.acquire_transcripts",
                      side_effect=AssertionError("Acquisition forbidden")):
            result = select_source(TARGET, inputs, capability=fake)
        self.assertIsInstance(result, SelectedSource)
        self.assertIs(result.source, original)
        self.assertIs(result.source.ranked_candidate, original.ranked_candidate)
        self.assertIs(result.source.segments, original.segments)
        self.assertEqual(str(result.source.segments[0].start_seconds), "0.125")
        self.assertEqual(tuple(c.video_id for c in fake.quality_requests[0].candidates), ("A", "C"))
        self.assertEqual(len(inputs.outcomes), 3)

    def test_invalid_stage_two_never_falls_back_to_ranked_winner(self):
        inputs = transcript_set("A", "B", "C")
        fake = FakeSelection([quality("A", "B", "C", rejected=("C",))],
                             [comparison("A", "C", winner="C")] * 3)
        with patch("league_knowledge_platform.source_selection.time.sleep"), \
                patch("sqlite3.connect", side_effect=AssertionError("SQL forbidden")), \
                patch("builtins.open", side_effect=AssertionError("Filesystem forbidden")):
            result = select_source(TARGET, inputs, capability=fake)
        self.assertIsInstance(result, SelectionFailed)
        self.assertIs(result.stage, SelectionStage.COMPARISON)
        self.assertFalse(hasattr(result, "source"))
        self.assertEqual(len(fake.quality_requests), 1)


if __name__ == "__main__":
    unittest.main()
