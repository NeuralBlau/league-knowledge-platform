"""Local League knowledge acquisition components."""

from .models import CandidateVideo, ChampionTarget, DiscoveryCursor, DiscoveryPage
from .targets import TargetLoadError, load_targets
from .youtube import DiscoveryError, DiscoveryFailureKind, YouTubeDiscovery

__all__ = [
    "CandidateVideo",
    "ChampionTarget",
    "DiscoveryCursor",
    "DiscoveryError",
    "DiscoveryFailureKind",
    "DiscoveryPage",
    "TargetLoadError",
    "YouTubeDiscovery",
    "load_targets",
]
