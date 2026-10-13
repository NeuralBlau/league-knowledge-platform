"""Central defaults preserve existing discovery and collection behavior."""

import inspect
import unittest
from unittest.mock import patch

from league_knowledge_platform import DEFAULT_RANKING_CONFIG, YouTubeDiscovery
from league_knowledge_platform import defaults, models


class DefaultsTests(unittest.TestCase):
    def test_service_defaults_are_discoverable_and_keep_existing_contracts(self):
        self.assertEqual(defaults.MIN_VIDEO_DURATION_SECONDS, 180)
        self.assertEqual(defaults.MAX_VIDEO_DURATION_SECONDS, 1800)
        self.assertEqual(defaults.RANKING_TOP_K, 3)
        self.assertEqual(defaults.UNSEEN_CANDIDATE_LIMIT, 20)
        self.assertEqual(models.UNSEEN_CANDIDATE_LIMIT, defaults.UNSEEN_CANDIDATE_LIMIT)
        self.assertEqual(defaults.DISCOVERY_PAGE_SIZE, 25)
        self.assertEqual(defaults.DISCOVERY_TIMEOUT_SECONDS, 15)
        parameters = inspect.signature(YouTubeDiscovery).parameters
        self.assertEqual(parameters["page_size"].default, defaults.DISCOVERY_PAGE_SIZE)
        self.assertEqual(parameters["timeout_seconds"].default, defaults.DISCOVERY_TIMEOUT_SECONDS)
        self.assertEqual(DEFAULT_RANKING_CONFIG.popularity_weight, defaults.POPULARITY_WEIGHT)
        self.assertEqual(DEFAULT_RANKING_CONFIG.recency_weight, defaults.RECENCY_WEIGHT)
        self.assertEqual(DEFAULT_RANKING_CONFIG.recency_half_life_days, defaults.RECENCY_HALF_LIFE_DAYS)
        self.assertEqual(DEFAULT_RANKING_CONFIG.score_precision, defaults.RANKING_SCORE_PRECISION)

    def test_discovery_still_uses_runtime_key_with_central_nonsecret_defaults(self):
        class Transport:
            def __init__(self):
                self.calls = []

            def get_json(self, endpoint, params, timeout):
                self.calls.append((params, timeout))
                return {"items": []}

        transport = Transport()
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "offline-runtime-key"}):
            discovery = YouTubeDiscovery(transport=transport)
        target = models.ChampionTarget("Ahri", "103", "Ahri")
        discovery.discover_page(target)
        params, timeout = transport.calls[0]
        self.assertEqual(params["key"], "offline-runtime-key")
        self.assertEqual(params["maxResults"], str(defaults.DISCOVERY_PAGE_SIZE))
        self.assertEqual(timeout, defaults.DISCOVERY_TIMEOUT_SECONDS)
        self.assertFalse(any("KEY" in name or "SECRET" in name or "TOKEN" in name
                             for name in vars(defaults)))


if __name__ == "__main__":
    unittest.main()
