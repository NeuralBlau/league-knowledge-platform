"""Immutable selection artifacts; semantic requests never contain ranked objects."""

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from .defaults import (
    RANKING_TOP_K, SELECTION_MAX_DIMENSION_CHARACTERS, SELECTION_MAX_RATIONALE_CHARACTERS,
)
from .models import _require_video_id
from .transcript_models import TransientTranscript


def _text(value: str, limit: int | None = None) -> None:
    if not isinstance(value, str) or not value.strip() or (limit is not None and len(value) > limit):
        raise ValueError("Selection text is empty, invalid, or exceeds its contract")


class QualityReasonCode(str, Enum):
    OFF_TARGET = "OFF_TARGET"
    INSUFFICIENT_EDUCATIONAL_SUBSTANCE = "INSUFFICIENT_EDUCATIONAL_SUBSTANCE"
    UNUSABLE_TRANSCRIPT = "UNUSABLE_TRANSCRIPT"
    DOMINANT_NOISE = "DOMINANT_NOISE"


class SelectionStage(str, Enum):
    QUALITY = "QUALITY"
    COMPARISON = "COMPARISON"


class SelectionFailureKind(str, Enum):
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    RATE_LIMIT = "RATE_LIMIT"
    SERVICE = "SERVICE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    CONTEXT_LIMIT = "CONTEXT_LIMIT"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    BALANCE = "BALANCE"
    CONFIGURATION = "CONFIGURATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_CONTRACT = "PROVIDER_CONTRACT"


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    NO_SELECTION = "NO_SELECTION"
    SELECTION_FAILED = "SELECTION_FAILED"


class NoSelectionReason(str, Enum):
    NO_TRANSCRIPTS = "NO_TRANSCRIPTS"
    ALL_REJECTED = "ALL_REJECTED"


class SelectionMethod(str, Enum):
    ONLY_PASSING_CANDIDATE = "ONLY_PASSING_CANDIDATE"
    COMPARATIVE = "COMPARATIVE"


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    video_id: str
    transcript_text: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_video_id(self.video_id)
        _text(self.transcript_text)


def _request(target_id, target_name, candidates, minimum):
    _text(target_id)
    _text(target_name)
    if (not isinstance(candidates, tuple) or not minimum <= len(candidates) <= RANKING_TOP_K
            or any(not isinstance(item, SemanticCandidate) for item in candidates)):
        raise ValueError("Semantic requests require a complete immutable candidate set")
    ids = tuple(item.video_id for item in candidates)
    if ids != tuple(sorted(set(ids))):
        raise ValueError("Semantic candidates must have unique IDs in canonical ID order")


@dataclass(frozen=True, slots=True)
class QualityAssessmentRequest:
    target_id: str
    target_name: str
    candidates: tuple[SemanticCandidate, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _request(self.target_id, self.target_name, self.candidates, 1)


@dataclass(frozen=True, slots=True)
class ComparativeSelectionRequest:
    target_id: str
    target_name: str
    candidates: tuple[SemanticCandidate, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _request(self.target_id, self.target_name, self.candidates, 2)


@dataclass(frozen=True, slots=True)
class CandidateQualityAssessment:
    video_id: str
    target_relevant: bool
    educational_substance: bool
    transcript_usable: bool
    noise_dominates: bool
    rationale: str = field(repr=False)
    reason_codes: tuple[QualityReasonCode, ...] = ()

    def __post_init__(self) -> None:
        _require_video_id(self.video_id)
        if any(type(value) is not bool for value in (
            self.target_relevant, self.educational_substance, self.transcript_usable,
            self.noise_dominates,
        )):
            raise ValueError("Quality attributes must be actual booleans")
        _text(self.rationale, SELECTION_MAX_RATIONALE_CHARACTERS)
        if (not isinstance(self.reason_codes, tuple)
                or any(not isinstance(code, QualityReasonCode) for code in self.reason_codes)
                or len(set(self.reason_codes)) != len(self.reason_codes)):
            raise ValueError("Quality reason codes must be unique defined codes")


@dataclass(frozen=True, slots=True)
class SemanticCallMetadata:
    provider: str
    requested_model: str
    reported_model: str | None
    prompt_version: str

    def __post_init__(self) -> None:
        for value in (self.provider, self.requested_model, self.prompt_version):
            _text(value, 256)
        if self.reported_model is not None:
            _text(self.reported_model, 256)


def _artifacts(items, expected_type):
    if (not isinstance(items, tuple) or not 1 <= len(items) <= RANKING_TOP_K
            or any(not isinstance(item, expected_type) for item in items)
            or len({item.video_id for item in items}) != len(items)):
        raise ValueError("Assessments must cover unique candidates immutably")


@dataclass(frozen=True, slots=True)
class QualityAssessmentBatch:
    assessments: tuple[CandidateQualityAssessment, ...]
    metadata: SemanticCallMetadata | None = None

    def __post_init__(self) -> None:
        _artifacts(self.assessments, CandidateQualityAssessment)
        if self.metadata is not None and not isinstance(self.metadata, SemanticCallMetadata):
            raise ValueError("Invalid semantic call metadata")


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    assessment: CandidateQualityAssessment

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, CandidateQualityAssessment):
            raise ValueError("The quality gate requires a semantic assessment")

    @property
    def video_id(self) -> str:
        return self.assessment.video_id

    @property
    def rejection_reasons(self) -> tuple[QualityReasonCode, ...]:
        a = self.assessment
        conditions = (
            (not a.target_relevant, QualityReasonCode.OFF_TARGET),
            (not a.educational_substance, QualityReasonCode.INSUFFICIENT_EDUCATIONAL_SUBSTANCE),
            (not a.transcript_usable, QualityReasonCode.UNUSABLE_TRANSCRIPT),
            (a.noise_dominates, QualityReasonCode.DOMINANT_NOISE),
        )
        return tuple(code for rejected, code in conditions if rejected)

    @property
    def passed(self) -> bool:
        return not self.rejection_reasons


@dataclass(frozen=True, slots=True)
class ComparativeCandidateAssessment:
    video_id: str
    target_relevance: str = field(repr=False)
    educational_usefulness: str = field(repr=False)
    information_density: str = field(repr=False)
    clarity: str = field(repr=False)
    breadth_depth: str = field(repr=False)
    noise: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_video_id(self.video_id)
        for value in (self.target_relevance, self.educational_usefulness, self.information_density,
                      self.clarity, self.breadth_depth, self.noise):
            _text(value, SELECTION_MAX_DIMENSION_CHARACTERS)


@dataclass(frozen=True, slots=True)
class ComparativeSelection:
    selected_video_id: str
    assessments: tuple[ComparativeCandidateAssessment, ...]
    selection_reason: str = field(repr=False)
    metadata: SemanticCallMetadata | None = None

    def __post_init__(self) -> None:
        _require_video_id(self.selected_video_id)
        _artifacts(self.assessments, ComparativeCandidateAssessment)
        if len(self.assessments) < 2 or self.selected_video_id not in {
            item.video_id for item in self.assessments
        }:
            raise ValueError("A comparative winner must belong to its comparison set")
        _text(self.selection_reason, SELECTION_MAX_RATIONALE_CHARACTERS)
        if self.metadata is not None and not isinstance(self.metadata, SemanticCallMetadata):
            raise ValueError("Invalid semantic call metadata")


@dataclass(frozen=True, slots=True)
class SelectionAttempt:
    stage: SelectionStage
    number: int
    failure_kind: SelectionFailureKind | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.stage, SelectionStage) or type(self.number) is not int
                or not 1 <= self.number <= 3 or (self.failure_kind is not None
                    and not isinstance(self.failure_kind, SelectionFailureKind))):
            raise ValueError("Invalid selection attempt")


@dataclass(frozen=True, slots=True)
class SelectedSource:
    target_id: str
    source: TransientTranscript = field(repr=False)
    quality_gate_results: tuple[QualityGateResult, ...]
    method: SelectionMethod
    comparison: ComparativeSelection | None
    attempts: tuple[SelectionAttempt, ...]
    quality_metadata: SemanticCallMetadata | None = None
    status: SelectionStatus = field(default=SelectionStatus.SELECTED, init=False)

    def __post_init__(self) -> None:
        _text(self.target_id)
        if (not isinstance(self.source, TransientTranscript)
                or self.source.ranked_candidate.candidate.target_id != self.target_id
                or not isinstance(self.method, SelectionMethod)):
            raise ValueError("Selected sources must retain their original target and transcript")
        _gate_results(self.quality_gate_results)
        _attempt_history(self.attempts, self.quality_metadata)
        passing = {gate.video_id for gate in self.quality_gate_results if gate.passed}
        winner = self.source.ranked_candidate.candidate.video_id
        if winner not in passing:
            raise ValueError("Selected source did not pass quality validation")
        if self.method is SelectionMethod.ONLY_PASSING_CANDIDATE:
            if len(passing) != 1 or self.comparison is not None:
                raise ValueError("Direct selection requires exactly one passing candidate")
        elif (not isinstance(self.comparison, ComparativeSelection)
              or self.comparison.selected_video_id != winner
              or {a.video_id for a in self.comparison.assessments} != passing):
            raise ValueError("Comparative selection must cover exactly the passing set")
        expected_stage = (SelectionStage.QUALITY if self.method is SelectionMethod.ONLY_PASSING_CANDIDATE
                          else SelectionStage.COMPARISON)
        if (not self.attempts or self.attempts[-1].stage is not expected_stage
                or self.attempts[-1].failure_kind is not None):
            raise ValueError("Selection requires a successful final stage")


def _gate_results(gates):
    if (not isinstance(gates, tuple) or len(gates) > RANKING_TOP_K
            or any(not isinstance(gate, QualityGateResult) for gate in gates)
            or len({gate.video_id for gate in gates}) != len(gates)):
        raise ValueError("Invalid immutable quality gate results")


def _attempt_history(attempts, quality_metadata):
    if (not isinstance(attempts, tuple)
            or any(not isinstance(item, SelectionAttempt) for item in attempts)
            or (quality_metadata is not None and not isinstance(quality_metadata, SemanticCallMetadata))):
        raise ValueError("Selection audit history must be immutable and typed")
    counts = {stage: 0 for stage in SelectionStage}
    successful = set()
    for attempt in attempts:
        if (attempt.stage in successful
                or (attempt.stage is SelectionStage.COMPARISON and SelectionStage.QUALITY not in successful)
                or attempt.number != counts[attempt.stage] + 1):
            raise ValueError("Selection history must preserve bounded stage attempt order")
        counts[attempt.stage] = attempt.number
        if attempt.failure_kind is None:
            successful.add(attempt.stage)


@dataclass(frozen=True, slots=True)
class NoSelection:
    target_id: str
    reason: NoSelectionReason
    quality_gate_results: tuple[QualityGateResult, ...]
    attempts: tuple[SelectionAttempt, ...]
    quality_metadata: SemanticCallMetadata | None = None
    status: SelectionStatus = field(default=SelectionStatus.NO_SELECTION, init=False)

    def __post_init__(self) -> None:
        _text(self.target_id)
        _gate_results(self.quality_gate_results)
        _attempt_history(self.attempts, self.quality_metadata)
        if (not isinstance(self.reason, NoSelectionReason)
                or any(gate.passed for gate in self.quality_gate_results)
                or (self.reason is NoSelectionReason.NO_TRANSCRIPTS
                    and (self.quality_gate_results or self.attempts))
                or (self.reason is NoSelectionReason.ALL_REJECTED
                    and (not self.quality_gate_results or not self.attempts
                         or self.attempts[-1].stage is not SelectionStage.QUALITY
                         or self.attempts[-1].failure_kind is not None))):
            raise ValueError("No selection requires absence or a completed rejecting gate")


@dataclass(frozen=True, slots=True)
class SelectionFailed:
    target_id: str
    stage: SelectionStage
    kind: SelectionFailureKind
    attempt_count: int
    quality_gate_results: tuple[QualityGateResult, ...]
    attempts: tuple[SelectionAttempt, ...]
    quality_metadata: SemanticCallMetadata | None = None
    status: SelectionStatus = field(default=SelectionStatus.SELECTION_FAILED, init=False)

    def __post_init__(self) -> None:
        _text(self.target_id)
        _gate_results(self.quality_gate_results)
        _attempt_history(self.attempts, self.quality_metadata)
        if (not isinstance(self.stage, SelectionStage)
                or not isinstance(self.kind, SelectionFailureKind)
                or type(self.attempt_count) is not int or not 1 <= self.attempt_count <= 3
                or (self.stage is SelectionStage.QUALITY and self.quality_gate_results)
                or not self.attempts or self.attempts[-1].stage is not self.stage
                or self.attempts[-1].number != self.attempt_count
                or self.attempts[-1].failure_kind is not self.kind):
            raise ValueError("Technical failure must identify its stage and attempts")


SourceSelectionOutcome: TypeAlias = SelectedSource | NoSelection | SelectionFailed
