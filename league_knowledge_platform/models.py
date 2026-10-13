"""Immutable acquisition contracts preserving source identity and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from .defaults import RANKING_TOP_K, UNSEEN_CANDIDATE_LIMIT

if TYPE_CHECKING:
    from .ranking import RankingConfig

_SOURCE_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def _require_video_id(video_id: str) -> None:
    if not isinstance(video_id, str) or _SOURCE_VIDEO_ID.fullmatch(video_id) is None:
        raise ValueError("A source requires a usable stable YouTube video ID")


@dataclass(frozen=True, slots=True)
class ChampionTarget:
    id: str
    key: str
    name: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.id, self.key, self.name)):
            raise ValueError("A Champion target requires an ID, key, and name")


@dataclass(frozen=True, slots=True)
class DiscoveryCursor:
    target_id: str
    page_token: str

    def __post_init__(self) -> None:
        if (not isinstance(self.target_id, str) or not self.target_id.strip()
                or not isinstance(self.page_token, str) or not self.page_token.strip()):
            raise ValueError("A discovery cursor requires a target and page token")


@dataclass(frozen=True, slots=True)
class CandidateVideo:
    target_id: str
    video_id: str
    title: str | None
    channel_title: str | None
    published_at_utc: datetime | None
    view_count: int | None
    duration_seconds: int | None

    def __post_init__(self) -> None:
        if (not isinstance(self.target_id, str) or not self.target_id.strip()
                or not isinstance(self.video_id, str) or not self.video_id.strip()):
            raise ValueError("A candidate requires a target and stable video ID")
        if self.published_at_utc is not None and (
            self.published_at_utc.utcoffset() != timezone.utc.utcoffset(None)
        ):
            raise ValueError("Candidate publication time must be UTC")
        for value in (self.view_count, self.duration_seconds):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Candidate counts and duration must be nonnegative integers")

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={quote(self.video_id, safe='')}"


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    target_id: str
    candidates: tuple[CandidateVideo, ...]
    next_cursor: DiscoveryCursor | None
    exhausted: bool

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("A discovery page requires a target")
        if not isinstance(self.candidates, tuple) or type(self.exhausted) is not bool:
            raise ValueError("A discovery page requires immutable candidates and a Boolean state")
        if self.exhausted != (self.next_cursor is None):
            raise ValueError("Exhaustion and continuation cursor disagree")
        if self.next_cursor is not None and self.next_cursor.target_id != self.target_id:
            raise ValueError("Continuation cursor belongs to another target")
        if any(candidate.target_id != self.target_id for candidate in self.candidates):
            raise ValueError("A candidate belongs to another target")


@dataclass(frozen=True, slots=True)
class UnseenCandidateSet:
    """A completed collection; failed or incomplete pools are not results."""

    target_id: str
    candidates: tuple[CandidateVideo, ...]
    exhausted: bool

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("An unseen candidate set requires a target")
        if not isinstance(self.candidates, tuple) or type(self.exhausted) is not bool:
            raise ValueError("A candidate set requires immutable candidates and Boolean exhaustion")
        if len(self.candidates) > UNSEEN_CANDIDATE_LIMIT:
            raise ValueError("An unseen candidate set cannot exceed 20 candidates")
        if len(self.candidates) < UNSEEN_CANDIDATE_LIMIT and not self.exhausted:
            raise ValueError("A smaller candidate set requires normal search exhaustion")
        seen_ids: set[str] = set()
        for candidate in self.candidates:
            if not isinstance(candidate, CandidateVideo) or candidate.target_id != self.target_id:
                raise ValueError("A candidate belongs to another target or has an invalid type")
            _require_video_id(candidate.video_id)
            if candidate.video_id in seen_ids:
                raise ValueError("An unseen candidate set cannot repeat a video ID")
            seen_ids.add(candidate.video_id)

    @property
    def target_reached(self) -> bool:
        return len(self.candidates) == UNSEEN_CANDIDATE_LIMIT


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """An original candidate plus transient, explainable ranking information."""

    candidate: CandidateVideo
    discovery_index: int
    popularity: float | None
    recency: float | None
    popularity_contribution: float
    recency_contribution: float
    score: float


@dataclass(frozen=True, slots=True)
class RankedCandidateSet:
    """A shortlist; input exhaustion remains distinct from duration eligibility."""

    target_id: str
    candidates: tuple[RankedCandidate, ...]
    reference_time_utc: datetime
    config: RankingConfig
    input_count: int
    eligible_count: int
    input_exhausted: bool

    def __post_init__(self) -> None:
        if (type(self.input_count) is not int or type(self.eligible_count) is not int
                or not 0 <= self.eligible_count <= self.input_count <= UNSEEN_CANDIDATE_LIMIT):
            raise ValueError("Ranking counts must describe a valid unseen candidate pool")
        if (not isinstance(self.candidates, tuple)
                or len(self.candidates) != min(RANKING_TOP_K, self.eligible_count)
                or type(self.input_exhausted) is not bool):
            raise ValueError("A ranked set requires an immutable, complete shortlist")
        if (not isinstance(self.target_id, str) or not self.target_id.strip()
                or any(not isinstance(item, RankedCandidate)
                       or item.candidate.target_id != self.target_id
                       for item in self.candidates)):
            raise ValueError("Ranked candidates must belong to the result target")
