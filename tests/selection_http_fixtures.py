"""Synthetic selection artifacts and an HTTP boundary with no live fallback."""

from datetime import datetime, timezone
from decimal import Decimal
import json

from league_knowledge_platform import (
    CandidateVideo, CaptionKind, CaptionSegment, CaptionTrack, ChampionTarget,
    ProviderTranscript, UnseenCandidateSet, acquire_transcripts, rank_candidates,
)

try:
    import requests
except ImportError:
    requests = None

TARGET = ChampionTarget("Ahri", "103", "Ahri")
REFERENCE = datetime(2026, 10, 15, tzinfo=timezone.utc)


class FakeCaptions:
    def __init__(self, texts=None, unavailable=()):
        self.texts = texts or {}
        self.unavailable = unavailable
        self.calls = []

    def list_tracks(self, video_id):
        self.calls.append(video_id)
        if video_id in self.unavailable:
            return ()
        return (CaptionTrack(video_id, "en", CaptionKind.MANUAL, video_id, "fake", "fixture"),)

    def fetch_track(self, track):
        return ProviderTranscript(track, (
            CaptionSegment(0, self.texts.get(track.video_id, "Useful target mechanics " + track.video_id),
                           Decimal("0.125"), Decimal("1.25")),
        ))


def transcript_set(*ids, texts=None, unavailable=()):
    # Deliberately reverse lexical ID order through distinct popularity metadata.
    videos = tuple(CandidateVideo("Ahri", video_id, "rank-title", "rank-channel",
                                 REFERENCE, 100000 * (index + 1), 600)
                   for index, video_id in enumerate(ids))
    ranked = rank_candidates(UnseenCandidateSet("Ahri", videos, True), reference_time=REFERENCE)
    return acquire_transcripts(ranked, provider=FakeCaptions(texts, unavailable))


def quality_item(video_id, *, passes=True, **overrides):
    item = {"video_id": video_id, "target_relevant": passes, "educational_substance": True,
            "transcript_usable": True, "noise_dominates": False,
            "rationale": "Synthetic independent quality explanation.", "reason_codes": []}
    item.update(overrides)
    return item


def comparison_item(video_id):
    return {"video_id": video_id, "target_relevance": "Target focused.",
            "educational_usefulness": "Explains decisions.", "information_density": "Useful detail.",
            "clarity": "Clear explanation.", "breadth_depth": "Connects mechanics to decisions.",
            "noise": "Little noise."}


def quality_document(*ids, rejected=()):
    return {"assessments": [quality_item(video_id, passes=video_id not in rejected) for video_id in ids]}


def comparison_document(*ids, winner=None):
    return {"selected_video_id": winner or ids[-1],
            "assessments": [comparison_item(video_id) for video_id in ids],
            "selection_reason": "Synthetic strongest durable-knowledge explanation."}


def envelope(document, *, finish="stop", **overrides):
    value = {"model": "fixture-model", "choices": [{"finish_reason": finish,
             "message": {"role": "assistant", "content": json.dumps(document)}}]}
    value.update(overrides)
    return value


class SelectionHTTPAdapter(requests.adapters.HTTPAdapter if requests else object):
    def __init__(self, script):
        super().__init__(max_retries=0)
        self.script = list(script)
        self.calls = []
        self.closed = False

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        if not self.script:
            raise AssertionError("Unexpected request; live network is disabled")
        if request.method != "POST" or request.url != "https://api.deepseek.com/chat/completions":
            raise AssertionError("Unexpected selection HTTP endpoint")
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        status, content = entry
        if isinstance(content, dict):
            content = json.dumps(content).encode("utf-8")
        if isinstance(content, str):
            content = content.encode("utf-8")
        response = requests.Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = content
        response._content_consumed = True
        return response

    def close(self):
        self.closed = True
        super().close()
