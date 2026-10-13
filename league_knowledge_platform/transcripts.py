"""Sequential transient acquisition; normal absence continues, technical failure aborts."""

from enum import Enum
import re
from typing import Protocol

from .defaults import RANKING_TOP_K, TRANSCRIPT_ENGLISH_LOCALE_PREFERENCE
from .models import RankedCandidate, RankedCandidateSet, _require_video_id
from .transcript_models import (
    CaptionKind, CaptionTrack, ProviderTranscript, TranscriptOutcome, TranscriptSegment,
    TranscriptStatus, TranscriptUnavailableReason, TransientTranscript, TransientTranscriptSet,
)


class TranscriptFailureKind(str, Enum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    BLOCKED = "blocked"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    SERVICE = "service"
    MALFORMED_RESPONSE = "malformed_response"
    PARSING = "parsing"
    CONTRACT = "contract"
    CONFIGURATION = "configuration"


class CaptionProviderError(RuntimeError):
    def __init__(self, kind: TranscriptFailureKind):
        self.kind = kind
        super().__init__(f"Caption provider failed: {kind.value}")


class CaptionUnavailable(Exception):
    """Only confirmed normal absence, never a general provider-error catch-all."""

    def __init__(self, reason: TranscriptUnavailableReason):
        self.reason = reason
        super().__init__(f"Caption unavailable: {reason.value}")


class TranscriptAcquisitionError(RuntimeError):
    """No transcript content or successful partial result is attached to a failure."""

    def __init__(self, kind: TranscriptFailureKind, video_id: str, position: int, phase: str):
        self.kind = kind
        self.video_id = video_id
        self.shortlist_position = position
        self.phase = phase
        super().__init__(f"Transcript acquisition failed for {video_id}: {kind.value} ({phase})")


class CaptionProvider(Protocol):
    def list_tracks(self, video_id: str) -> tuple[CaptionTrack, ...]:
        """List source tracks or raise CaptionUnavailable/CaptionProviderError."""

    def fetch_track(self, track: CaptionTrack) -> ProviderTranscript:
        """Return complete timed source content or an explicit absence/failure."""


def _locale(code: str) -> str:
    return code.replace("_", "-").casefold()


def _is_english(code: str) -> bool:
    return re.fullmatch(r"en(?:-[a-z0-9]{2,8})*", _locale(code)) is not None


def _ordered_english_tracks(tracks: tuple[CaptionTrack, ...]) -> tuple[CaptionTrack, ...]:
    def key(entry):
        index, track = entry
        locale = _locale(track.language_code)
        preference = (TRANSCRIPT_ENGLISH_LOCALE_PREFERENCE.index(locale)
                      if locale in TRANSCRIPT_ENGLISH_LOCALE_PREFERENCE
                      else len(TRANSCRIPT_ENGLISH_LOCALE_PREFERENCE))
        return (track.kind is CaptionKind.AUTO_GENERATED, preference, locale, index)

    return tuple(track for _, track in sorted(
        ((index, track) for index, track in enumerate(tracks) if _is_english(track.language_code)),
        key=key,
    ))


def acquire_transcripts(
    shortlist: RankedCandidateSet, *, provider: CaptionProvider
) -> TransientTranscriptSet:
    """Acquire exactly the supplied shortlist; no partial success on technical failure."""
    if not isinstance(shortlist, RankedCandidateSet) or len(shortlist.candidates) > RANKING_TOP_K:
        raise ValueError("Transcript acquisition requires a completed ranked shortlist")
    ids = []
    for entry in shortlist.candidates:
        if not isinstance(entry, RankedCandidate) or entry.candidate.target_id != shortlist.target_id:
            raise ValueError("Shortlist entries must preserve their target and ranked candidate")
        _require_video_id(entry.candidate.video_id)
        ids.append(entry.candidate.video_id)
    if len(set(ids)) != len(ids):
        raise ValueError("A ranked shortlist cannot repeat source identities")

    outcomes = []
    acquired = []
    for position, entry in enumerate(shortlist.candidates):
        video_id = entry.candidate.video_id
        phase = "list"
        try:
            tracks = provider.list_tracks(video_id)
            if not isinstance(tracks, tuple) or any(
                not isinstance(track, CaptionTrack) or track.video_id != video_id for track in tracks
            ):
                raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
            if not tracks:
                raise CaptionUnavailable(TranscriptUnavailableReason.NO_CAPTIONS)
            english = _ordered_english_tracks(tracks)
            if not english:
                raise CaptionUnavailable(TranscriptUnavailableReason.NO_ENGLISH)
            reason = TranscriptUnavailableReason.EMPTY
            transcript = None
            for track in english:
                phase = "fetch"
                try:
                    fetched = provider.fetch_track(track)
                except CaptionUnavailable as absence:
                    reason = absence.reason
                    continue
                if not isinstance(fetched, ProviderTranscript) or fetched.track != track:
                    raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
                phase = "normalize"
                segments = []
                last_index = -1
                for segment in fetched.segments:
                    if segment.source_index <= last_index:
                        raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
                    last_index = segment.source_index
                    text = " ".join(segment.source_text.split())
                    if text:
                        segments.append(TranscriptSegment(
                            segment.source_index, segment.source_text, text,
                            segment.start_seconds, segment.duration_seconds,
                        ))
                if segments:
                    transcript = TransientTranscript(entry, position, track, tuple(segments))
                    break
            if transcript is None:
                raise CaptionUnavailable(reason)
            acquired.append(transcript)
            outcomes.append(TranscriptOutcome(entry, position, TranscriptStatus.ACQUIRED, transcript))
        except CaptionUnavailable as absence:
            outcomes.append(TranscriptOutcome(
                entry, position, TranscriptStatus.UNAVAILABLE, unavailable_reason=absence.reason,
            ))
        except CaptionProviderError as failure:
            acquired.clear()
            outcomes.clear()
            raise TranscriptAcquisitionError(failure.kind, video_id, position, phase) from None
        except Exception:
            acquired.clear()
            outcomes.clear()
            raise TranscriptAcquisitionError(
                TranscriptFailureKind.CONTRACT, video_id, position, phase
            ) from None
    return TransientTranscriptSet(shortlist, tuple(acquired), tuple(outcomes))
