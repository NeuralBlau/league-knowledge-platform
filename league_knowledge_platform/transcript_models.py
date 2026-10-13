"""Immutable, provider-independent transient caption and transcript contracts."""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .models import RankedCandidate, RankedCandidateSet, _require_video_id


class CaptionKind(str, Enum):
    MANUAL = "manual"
    AUTO_GENERATED = "auto_generated"


class TranscriptStatus(str, Enum):
    ACQUIRED = "acquired"
    UNAVAILABLE = "unavailable"


class TranscriptUnavailableReason(str, Enum):
    NO_CAPTIONS = "no_captions"
    CAPTIONS_DISABLED = "captions_disabled"
    NO_ENGLISH = "no_english"
    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    video_id: str
    language_code: str
    kind: CaptionKind
    provider_key: str = field(repr=False)
    provider_name: str
    provider_version: str
    source_track_id: str | None = None

    def __post_init__(self) -> None:
        _require_video_id(self.video_id)
        if (not isinstance(self.kind, CaptionKind)
                or any(not isinstance(value, str) or not value.strip() for value in
                       (self.language_code, self.provider_key, self.provider_name, self.provider_version))):
            raise ValueError("A caption track requires usable source and provider metadata")


def _require_segment(index: int, text: str, start: Decimal, duration: Decimal) -> None:
    if type(index) is not int or index < 0 or not isinstance(text, str):
        raise ValueError("A segment requires its source position and text")
    if any(not isinstance(value, Decimal) or not value.is_finite() or value < 0
           for value in (start, duration)):
        raise ValueError("Source segment timing must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class CaptionSegment:
    source_index: int
    source_text: str = field(repr=False)
    start_seconds: Decimal
    duration_seconds: Decimal

    def __post_init__(self) -> None:
        _require_segment(self.source_index, self.source_text, self.start_seconds, self.duration_seconds)


@dataclass(frozen=True, slots=True)
class ProviderTranscript:
    track: CaptionTrack
    segments: tuple[CaptionSegment, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.track, CaptionTrack) or not isinstance(self.segments, tuple)
                or any(not isinstance(segment, CaptionSegment) for segment in self.segments)):
            raise ValueError("Provider transcripts require a track and immutable timed segments")


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    source_index: int
    source_text: str = field(repr=False)
    text: str = field(repr=False)
    start_seconds: Decimal
    duration_seconds: Decimal

    def __post_init__(self) -> None:
        _require_segment(self.source_index, self.source_text, self.start_seconds, self.duration_seconds)
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("An acquired segment requires nonempty normalized text")


@dataclass(frozen=True, slots=True)
class TransientTranscript:
    ranked_candidate: RankedCandidate
    shortlist_position: int
    track: CaptionTrack
    segments: tuple[TranscriptSegment, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.ranked_candidate, RankedCandidate)
                or type(self.shortlist_position) is not int or self.shortlist_position < 0
                or not isinstance(self.track, CaptionTrack)
                or self.track.video_id != self.ranked_candidate.candidate.video_id
                or not isinstance(self.segments, tuple) or not self.segments
                or any(not isinstance(segment, TranscriptSegment) for segment in self.segments)):
            raise ValueError("A transient transcript requires original identity and immutable content")

    @property
    def text(self) -> str:
        """Derived text; the ordered segments retain source timing and provenance."""
        return "\n".join(segment.text for segment in self.segments)


@dataclass(frozen=True, slots=True)
class TranscriptOutcome:
    ranked_candidate: RankedCandidate
    shortlist_position: int
    status: TranscriptStatus
    transcript: TransientTranscript | None = field(default=None, repr=False)
    unavailable_reason: TranscriptUnavailableReason | None = None

    def __post_init__(self) -> None:
        acquired = self.status is TranscriptStatus.ACQUIRED
        unavailable = self.status is TranscriptStatus.UNAVAILABLE
        if not ((acquired and isinstance(self.transcript, TransientTranscript)
                 and self.unavailable_reason is None
                 and self.transcript.ranked_candidate is self.ranked_candidate
                 and self.transcript.shortlist_position == self.shortlist_position)
                or (unavailable and self.transcript is None
                    and isinstance(self.unavailable_reason, TranscriptUnavailableReason))):
            raise ValueError("A candidate outcome must distinguish acquired and unavailable")


@dataclass(frozen=True, slots=True)
class TransientTranscriptSet:
    shortlist: RankedCandidateSet
    transcripts: tuple[TransientTranscript, ...] = field(repr=False)
    outcomes: tuple[TranscriptOutcome, ...]

    def __post_init__(self) -> None:
        if (not isinstance(self.shortlist, RankedCandidateSet)
                or not isinstance(self.outcomes, tuple) or not isinstance(self.transcripts, tuple)
                or len(self.outcomes) != len(self.shortlist.candidates)):
            raise ValueError("A completed transcript set requires an outcome for every candidate")
        for position, (candidate, outcome) in enumerate(zip(self.shortlist.candidates, self.outcomes)):
            if (not isinstance(outcome, TranscriptOutcome) or outcome.ranked_candidate is not candidate
                    or outcome.shortlist_position != position):
                raise ValueError("Transcript outcomes must preserve original ranking and identity")
        expected = tuple(outcome.transcript for outcome in self.outcomes
                         if outcome.status is TranscriptStatus.ACQUIRED)
        if len(expected) != len(self.transcripts) or any(
            actual is not original for actual, original in zip(self.transcripts, expected)
        ):
            raise ValueError("The downstream set must contain only acquired transcripts in rank order")
