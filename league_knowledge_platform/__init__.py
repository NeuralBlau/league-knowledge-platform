"""Local League knowledge acquisition components."""

from .models import (
    CandidateVideo, ChampionCatalog, ChampionTarget, DiscoveryCursor, DiscoveryPage,
    RankedCandidate, RankedCandidateSet, UnseenCandidateSet,
)
from .ranking import DEFAULT_RANKING_CONFIG, RankingConfig, rank_candidates
from .source_catalog import SourceCatalogError, SQLiteSourceCatalog, initialize_source_catalog
from .targets import TargetLoadError, load_catalog, load_targets
from .transcript_models import (
    CaptionKind, CaptionSegment, CaptionTrack, ProviderTranscript, TranscriptOutcome,
    TranscriptSegment, TranscriptStatus, TranscriptUnavailableReason, TransientTranscript,
    TransientTranscriptSet,
)
from .transcripts import (
    CaptionProvider, CaptionProviderError, CaptionUnavailable, TranscriptAcquisitionError,
    TranscriptFailureKind, acquire_transcripts,
)
from .youtube_caption_provider import (
    DEFAULT_TRANSCRIPT_CONFIG, TranscriptConfig, YouTubeCaptionProvider,
)
from .unseen import (
    CollectionFailureKind,
    IntegratedSourceReader,
    PageDiscovery,
    UnseenCollectionError,
    collect_unseen_candidates,
)
from .youtube import DiscoveryError, DiscoveryFailureKind, YouTubeDiscovery
from .selection_models import (
    CandidateQualityAssessment, ComparativeCandidateAssessment, ComparativeSelection,
    ComparativeSelectionRequest, NoSelection, NoSelectionReason, QualityAssessmentBatch,
    QualityAssessmentRequest, QualityGateResult, QualityReasonCode, SelectedSource,
    SelectionAttempt, SelectionFailed, SelectionFailureKind, SelectionMethod, SelectionStage,
    SelectionStatus, SemanticCallMetadata, SemanticCandidate, SourceSelectionOutcome,
)
from .source_selection import (
    DEFAULT_SELECTION_CONFIG, SelectionCapabilityError, SelectionConfig,
    SourceSelectionCapability, select_source,
)
from .deepseek_selection import DeepSeekSelectionAdapter, DeepSeekSelectionConfig
from .run_models import (
    AcquisitionRun, RunConfigurationError, RunNotFoundError, RunStage, RunStateError,
    RunStatus, RunSummary, RunTarget, RunTargetStatus, TargetFailure, TargetFailureKind,
)
from .run_lock import RunBusyError
from .run_repository import SQLiteRunRepository, initialize_run_repository
from .acquisition_runs import AcquisitionRunService

__all__ = [
    "AcquisitionRun", "AcquisitionRunService", "ChampionCatalog", "RunBusyError",
    "RunConfigurationError", "RunNotFoundError", "RunStage", "RunStateError", "RunStatus",
    "RunSummary", "RunTarget", "RunTargetStatus", "TargetFailure", "TargetFailureKind",
    "SQLiteRunRepository", "initialize_run_repository", "load_catalog",
    "CandidateQualityAssessment", "ComparativeCandidateAssessment", "ComparativeSelection",
    "ComparativeSelectionRequest", "DEFAULT_SELECTION_CONFIG", "DeepSeekSelectionAdapter",
    "DeepSeekSelectionConfig", "NoSelection", "NoSelectionReason", "QualityAssessmentBatch",
    "QualityAssessmentRequest", "QualityGateResult", "QualityReasonCode", "SelectedSource",
    "SelectionAttempt", "SelectionCapabilityError", "SelectionConfig", "SelectionFailed",
    "SelectionFailureKind", "SelectionMethod", "SelectionStage", "SelectionStatus",
    "SemanticCallMetadata", "SemanticCandidate", "SourceSelectionCapability",
    "SourceSelectionOutcome", "select_source",
    "CaptionKind",
    "CaptionProvider",
    "CaptionProviderError",
    "CaptionSegment",
    "CaptionTrack",
    "CaptionUnavailable",
    "CandidateVideo",
    "ChampionTarget",
    "CollectionFailureKind",
    "DiscoveryCursor",
    "DiscoveryError",
    "DiscoveryFailureKind",
    "DiscoveryPage",
    "DEFAULT_RANKING_CONFIG",
    "DEFAULT_TRANSCRIPT_CONFIG",
    "IntegratedSourceReader",
    "PageDiscovery",
    "ProviderTranscript",
    "RankedCandidate",
    "RankedCandidateSet",
    "RankingConfig",
    "SourceCatalogError",
    "SQLiteSourceCatalog",
    "TargetLoadError",
    "TranscriptAcquisitionError",
    "TranscriptConfig",
    "TranscriptFailureKind",
    "TranscriptOutcome",
    "TranscriptSegment",
    "TranscriptStatus",
    "TranscriptUnavailableReason",
    "TransientTranscript",
    "TransientTranscriptSet",
    "YouTubeCaptionProvider",
    "YouTubeDiscovery",
    "UnseenCandidateSet",
    "UnseenCollectionError",
    "collect_unseen_candidates",
    "acquire_transcripts",
    "initialize_source_catalog",
    "load_targets",
    "rank_candidates",
]
