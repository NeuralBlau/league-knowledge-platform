"""Immutable contracts shared by Champion loading and YouTube discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote


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
