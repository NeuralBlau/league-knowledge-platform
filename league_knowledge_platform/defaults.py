"""Central non-secret service defaults; credentials belong to runtime configuration."""

from typing import Final

UNSEEN_CANDIDATE_LIMIT: Final = 20
DISCOVERY_PAGE_SIZE: Final = 25
DISCOVERY_TIMEOUT_SECONDS: Final = 15.0

MIN_VIDEO_DURATION_SECONDS: Final = 180
MAX_VIDEO_DURATION_SECONDS: Final = 1800
RANKING_TOP_K: Final = 3
POPULARITY_WEIGHT: Final = 0.70
RECENCY_WEIGHT: Final = 0.30
RECENCY_HALF_LIFE_DAYS: Final = 365.0
RANKING_SCORE_PRECISION: Final = 12
