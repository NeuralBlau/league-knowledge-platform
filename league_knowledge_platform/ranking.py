"""Pure metadata ranking; duration is eligibility only, with no persistence or I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from .defaults import (
    MAX_VIDEO_DURATION_SECONDS,
    MIN_VIDEO_DURATION_SECONDS,
    POPULARITY_WEIGHT,
    RANKING_SCORE_PRECISION,
    RANKING_TOP_K,
    RECENCY_HALF_LIFE_DAYS,
    RECENCY_WEIGHT,
)
from .models import RankedCandidate, RankedCandidateSet, UnseenCandidateSet


@dataclass(frozen=True, slots=True)
class RankingConfig:
    """Non-secret scoring inputs; eligibility bounds and Top-K are service defaults."""

    popularity_weight: float = POPULARITY_WEIGHT
    recency_weight: float = RECENCY_WEIGHT
    recency_half_life_days: float = RECENCY_HALF_LIFE_DAYS
    score_precision: int = RANKING_SCORE_PRECISION

    def __post_init__(self) -> None:
        values = (self.popularity_weight, self.recency_weight, self.recency_half_life_days)
        try:
            valid = all(type(value) in (int, float) and math.isfinite(value) and value > 0
                        for value in values)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("Ranking weights and half-life must be finite and positive")
        if (not 0 < self.recency_weight < self.popularity_weight < 1
                or not math.isclose(math.fsum(values[:2]), 1.0, rel_tol=0, abs_tol=1e-12)):
            raise ValueError("Ranking weights must sum to one with popularity strongest")
        if type(self.score_precision) is not int or not 0 <= self.score_precision <= 15:
            raise ValueError("Score precision must be an integer between zero and 15")


DEFAULT_RANKING_CONFIG = RankingConfig()


def rank_candidates(
    candidates: UnseenCandidateSet,
    *,
    reference_time: datetime,
    config: RankingConfig = DEFAULT_RANKING_CONFIG,
) -> RankedCandidateSet:
    """Return exactly min(Top-K, eligible count), preserving original candidates.

    All time-dependent calculations use the caller's explicit reference time.
    Missing signals have zero contribution without weight redistribution. Equal
    rounded scores retain the original discovery order, including after filtering.
    """
    if not isinstance(candidates, UnseenCandidateSet):
        raise ValueError("Ranking requires a completed unseen candidate set")
    if not isinstance(reference_time, datetime) or reference_time.utcoffset() is None:
        raise ValueError("Ranking requires an explicit timezone-aware reference time")
    if not isinstance(config, RankingConfig):
        raise ValueError("Ranking requires an immutable RankingConfig")
    try:
        reference_utc = reference_time.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("Ranking reference time cannot be represented in UTC") from None

    eligible = tuple(
        (index, candidate) for index, candidate in enumerate(candidates.candidates)
        if candidate.duration_seconds is None
        or MIN_VIDEO_DURATION_SECONDS <= candidate.duration_seconds <= MAX_VIDEO_DURATION_SECONDS
    )
    maximum_views = max(
        (candidate.view_count for _, candidate in eligible if candidate.view_count is not None),
        default=0,
    )
    # log(integer + 1) implements ln(1 + views) without converting huge counts
    # to floats first. The normalization considers only duration-eligible videos.
    popularity_denominator = math.log(maximum_views + 1) if maximum_views else 0.0
    ranked = []
    for index, candidate in eligible:
        popularity = None
        if candidate.view_count is not None:
            popularity = (math.log(candidate.view_count + 1) / popularity_denominator
                          if popularity_denominator else 0.0)
        recency = None
        if candidate.published_at_utc is not None:
            age_days = max(0.0, (reference_utc - candidate.published_at_utc).total_seconds() / 86400)
            recency = 2.0 ** (-age_days / config.recency_half_life_days)
        popularity_contribution = (config.popularity_weight * popularity
                                   if popularity is not None else 0.0)
        recency_contribution = config.recency_weight * recency if recency is not None else 0.0
        score = round(math.fsum((popularity_contribution, recency_contribution)),
                      config.score_precision)
        ranked.append(RankedCandidate(
            candidate, index, popularity, recency,
            popularity_contribution, recency_contribution, score,
        ))
    ranked.sort(key=lambda item: (-item.score, item.discovery_index))
    return RankedCandidateSet(
        target_id=candidates.target_id,
        candidates=tuple(ranked[:RANKING_TOP_K]),
        reference_time_utc=reference_utc,
        config=config,
        input_count=len(candidates.candidates),
        eligible_count=len(eligible),
        input_exhausted=candidates.exhausted,
    )
