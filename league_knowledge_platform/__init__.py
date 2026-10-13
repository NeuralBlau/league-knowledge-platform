"""Local League knowledge acquisition components."""

from .models import CandidateVideo, ChampionTarget, DiscoveryCursor, DiscoveryPage, UnseenCandidateSet
from .source_catalog import SourceCatalogError, SQLiteSourceCatalog, initialize_source_catalog
from .targets import TargetLoadError, load_targets
from .unseen import (
    CollectionFailureKind,
    IntegratedSourceReader,
    PageDiscovery,
    UnseenCollectionError,
    collect_unseen_candidates,
)
from .youtube import DiscoveryError, DiscoveryFailureKind, YouTubeDiscovery

__all__ = [
    "CandidateVideo",
    "ChampionTarget",
    "CollectionFailureKind",
    "DiscoveryCursor",
    "DiscoveryError",
    "DiscoveryFailureKind",
    "DiscoveryPage",
    "IntegratedSourceReader",
    "PageDiscovery",
    "SourceCatalogError",
    "SQLiteSourceCatalog",
    "TargetLoadError",
    "YouTubeDiscovery",
    "UnseenCandidateSet",
    "UnseenCollectionError",
    "collect_unseen_candidates",
    "initialize_source_catalog",
    "load_targets",
]
