"""Transient source selection; this service owns stage retries and the Boolean gate."""

from dataclasses import dataclass
import math
import time
from typing import Protocol

from .defaults import RANKING_TOP_K, SELECTION_MAX_ATTEMPTS, SELECTION_RETRY_DELAYS_SECONDS
from .models import ChampionTarget, _require_video_id
from .selection_models import (
    ComparativeSelection, ComparativeSelectionRequest, NoSelection, NoSelectionReason,
    QualityAssessmentBatch, QualityAssessmentRequest, QualityGateResult, SelectedSource,
    SelectionAttempt, SelectionFailed, SelectionFailureKind, SelectionMethod, SelectionStage,
    SemanticCandidate, SourceSelectionOutcome,
)
from .transcript_models import TransientTranscriptSet


class SelectionCapabilityError(RuntimeError):
    """Sanitized provider-independent error; never attach raw requests/responses."""

    def __init__(self, kind: SelectionFailureKind, *, retryable: bool):
        if not isinstance(kind, SelectionFailureKind) or type(retryable) is not bool:
            raise ValueError("Invalid capability failure")
        self.kind = kind
        self.retryable = retryable
        super().__init__(f"Source selection capability failed: {kind.value}")


class SourceSelectionCapability(Protocol):
    def assess_quality(self, request: QualityAssessmentRequest) -> QualityAssessmentBatch:
        """Assess the complete batch absolutely, or raise SelectionCapabilityError."""

    def compare_sources(self, request: ComparativeSelectionRequest) -> ComparativeSelection:
        """Compare exactly the supplied candidates, or raise SelectionCapabilityError."""


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    max_attempts: int = SELECTION_MAX_ATTEMPTS
    retry_delays_seconds: tuple[float, float] = SELECTION_RETRY_DELAYS_SECONDS

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("Selection allows one through three total attempts per stage")
        if (not isinstance(self.retry_delays_seconds, tuple) or len(self.retry_delays_seconds) != 2
                or any(type(v) not in (int, float) or not 0 <= v <= 60 or not math.isfinite(v)
                       for v in self.retry_delays_seconds)):
            raise ValueError("Selection retry delays must be finite and bounded")


DEFAULT_SELECTION_CONFIG = SelectionConfig()


class _StageFailure(Exception):
    def __init__(self, kind, count):
        self.kind, self.count = kind, count


def _validate_quality(result, request):
    if not isinstance(result, QualityAssessmentBatch):
        raise ValueError("Expected a complete quality artifact")
    if {a.video_id for a in result.assessments} != {c.video_id for c in request.candidates}:
        raise ValueError("Quality artifact does not cover the input candidates")


def _validate_comparison(result, request):
    if not isinstance(result, ComparativeSelection):
        raise ValueError("Expected a complete comparison artifact")
    ids = {c.video_id for c in request.candidates}
    if {a.video_id for a in result.assessments} != ids or result.selected_video_id not in ids:
        raise ValueError("Comparison artifact does not cover only passing candidates")


def _run_stage(stage, request, operation, validate, config, attempts):
    for number in range(1, config.max_attempts + 1):
        try:
            result = operation(request)
            validate(result, request)
        except SelectionCapabilityError as error:
            kind, retryable = error.kind, error.retryable
        except (ValueError, TypeError, AttributeError):
            kind, retryable = SelectionFailureKind.INVALID_OUTPUT, True
        except Exception:
            # An arbitrary capability exception is not evidence of a recoverable outage.
            kind, retryable = SelectionFailureKind.PROVIDER_CONTRACT, False
        else:
            attempts.append(SelectionAttempt(stage, number))
            return result
        attempts.append(SelectionAttempt(stage, number, kind))
        if not retryable or number == config.max_attempts:
            raise _StageFailure(kind, number) from None
        time.sleep(config.retry_delays_seconds[number - 1])


def select_source(
    target: ChampionTarget,
    transcripts: TransientTranscriptSet,
    *,
    capability: SourceSelectionCapability,
    config: SelectionConfig = DEFAULT_SELECTION_CONFIG,
) -> SourceSelectionOutcome:
    """Select at most one source, retaining its full original transcript and provenance.

    No discovery, ranking, transcript acquisition, persistence, or catalog access is
    reachable here. Operational failures are typed results; invalid caller arguments
    raise ValueError before any semantic call.
    """
    if (not isinstance(target, ChampionTarget) or not isinstance(transcripts, TransientTranscriptSet)
            or not isinstance(config, SelectionConfig)
            or transcripts.shortlist.target_id != target.id
            or len(transcripts.transcripts) > RANKING_TOP_K):
        raise ValueError("Selection requires a completed transcript set for its Champion")
    transcripts.__post_init__()
    originals = {}
    for transcript in transcripts.transcripts:
        candidate = transcript.ranked_candidate.candidate
        _require_video_id(candidate.video_id)
        if candidate.target_id != target.id or candidate.video_id in originals:
            raise ValueError("Selection input must preserve unique target-bound identities")
        originals[candidate.video_id] = transcript
    if not originals:
        return NoSelection(target.id, NoSelectionReason.NO_TRANSCRIPTS, (), ())
    if (not callable(getattr(capability, "assess_quality", None))
            or not callable(getattr(capability, "compare_sources", None))):
        raise ValueError("Selection requires both semantic capabilities")

    # Explicit allowlist: do not serialize ranked objects or retain them in these DTOs.
    projected = tuple(SemanticCandidate(video_id, originals[video_id].text)
                      for video_id in sorted(originals))
    request = QualityAssessmentRequest(target.id, target.name, projected)
    attempts = []
    try:
        quality = _run_stage(SelectionStage.QUALITY, request, capability.assess_quality,
                             _validate_quality, config, attempts)
    except _StageFailure as failure:
        return SelectionFailed(target.id, SelectionStage.QUALITY, failure.kind, failure.count,
                               (), tuple(attempts))

    by_id = {assessment.video_id: assessment for assessment in quality.assessments}
    gates = tuple(QualityGateResult(by_id[video_id]) for video_id in originals)
    passing = {gate.video_id for gate in gates if gate.passed}
    if not passing:
        return NoSelection(target.id, NoSelectionReason.ALL_REJECTED, gates,
                           tuple(attempts), quality.metadata)
    if len(passing) == 1:
        winner = next(iter(passing))
        return SelectedSource(target.id, originals[winner], gates,
                              SelectionMethod.ONLY_PASSING_CANDIDATE, None,
                              tuple(attempts), quality.metadata)

    # Fresh DTO and fresh semantic call: no Stage 1 artifact or message history.
    comparison_request = ComparativeSelectionRequest(
        target.id, target.name,
        tuple(SemanticCandidate(video_id, originals[video_id].text) for video_id in sorted(passing)),
    )
    try:
        comparison = _run_stage(SelectionStage.COMPARISON, comparison_request,
                                capability.compare_sources, _validate_comparison, config, attempts)
    except _StageFailure as failure:
        return SelectionFailed(target.id, SelectionStage.COMPARISON, failure.kind, failure.count,
                               gates, tuple(attempts), quality.metadata)
    return SelectedSource(target.id, originals[comparison.selected_video_id], gates,
                          SelectionMethod.COMPARATIVE, comparison, tuple(attempts), quality.metadata)
