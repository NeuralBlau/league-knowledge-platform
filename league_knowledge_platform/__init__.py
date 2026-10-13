"""Local League knowledge acquisition components."""

from .models import (
    CandidateVideo, ChampionTarget, DiscoveryCursor, DiscoveryPage,
    RankedCandidate, RankedCandidateSet, UnseenCandidateSet,
)
from .ranking import DEFAULT_RANKING_CONFIG, RankingConfig, rank_candidates
from .source_catalog import SourceCatalogError, SQLiteSourceCatalog, initialize_source_catalog
from .targets import TargetLoadError, load_targets
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

__all__ = [
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
