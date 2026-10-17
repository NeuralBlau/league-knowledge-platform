"""Small synthetic run inputs and external boundaries, with no live fallback."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

from league_knowledge_platform import (
    CandidateQualityAssessment, CandidateVideo, CaptionKind, CaptionSegment, CaptionTrack,
    ComparativeCandidateAssessment, ComparativeSelection, DiscoveryPage, ProviderTranscript,
    QualityAssessmentBatch, SelectionCapabilityError, SelectionFailureKind,
)

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
CHAMPIONS = (
    {"id": "Ahri", "key": "103", "name": "Ahri"},
    {"id": "Aatrox", "key": "266", "name": "Aatrox"},
    {"id": "Anivia", "key": "34", "name": "Anivia"},
)


def write_catalog(path, champions=CHAMPIONS, version="16.20.1"):
    value = {
        "schema_version": 1, "roster_version": version,
        "generated_at": "2026-10-17T12:00:00Z",
        "source": {"provider": "Riot Games Data Dragon", "locale": "en_US",
                   "url": f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"},
        "champions": list(champions),
    }
    Path(path).write_text(json.dumps(value), encoding="utf-8")
    return Path(path)


class Discovery:
    def __init__(self, scripts=None, hook=None):
        self.scripts = {key: list(values) for key, values in (scripts or {}).items()}
        self.calls = []
        self.hook = hook

    def discover_page(self, target, cursor=None):
        self.calls.append((target, cursor))
        if self.hook is not None:
            self.hook(target)
        if target.id in self.scripts:
            result = self.scripts[target.id].pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return DiscoveryPage(target.id, (
            CandidateVideo(target.id, target.id + "Video", "Synthetic guide", "Fixture channel",
                           NOW, 1000, 600),
        ), None, True)


class Captions:
    def __init__(self, unavailable=(), failure=None):
        self.unavailable = unavailable
        self.failure = failure
        self.calls = []

    def list_tracks(self, video_id):
        self.calls.append(video_id)
        if self.failure is not None:
            raise self.failure
        if video_id in self.unavailable:
            return ()
        return (CaptionTrack(video_id, "en", CaptionKind.MANUAL, video_id, "fake", "fixture"),)

    def fetch_track(self, track):
        return ProviderTranscript(track, (
            CaptionSegment(0, "Synthetic complete transcript for " + track.video_id,
                           Decimal("0.125"), Decimal("1.25")),
        ))


class Selection:
    def __init__(self, *, rejected=(), fail_targets=(), retry_failures=0):
        self.rejected = rejected
        self.fail_targets = fail_targets
        self.retry_failures = retry_failures
        self.quality_calls = []
        self.comparison_calls = []

    def assess_quality(self, request):
        self.quality_calls.append(request)
        if request.target_id in self.fail_targets or self.retry_failures > 0:
            self.retry_failures = max(0, self.retry_failures - 1)
            raise SelectionCapabilityError(SelectionFailureKind.TIMEOUT, retryable=True)
        return QualityAssessmentBatch(tuple(CandidateQualityAssessment(
            candidate.video_id, candidate.video_id not in self.rejected, True, True, False,
            "Synthetic absolute assessment.",
        ) for candidate in request.candidates))

    def compare_sources(self, request):
        self.comparison_calls.append(request)
        return ComparativeSelection(request.candidates[0].video_id, tuple(
            ComparativeCandidateAssessment(candidate.video_id, "Relevant", "Educational", "Dense",
                                           "Clear", "Useful scope", "Little noise")
            for candidate in request.candidates
        ), "Synthetic comparison.")


def process_environment():
    environment = dict(os.environ)
    root = Path(__file__).resolve().parents[1]
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "tests")))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment
