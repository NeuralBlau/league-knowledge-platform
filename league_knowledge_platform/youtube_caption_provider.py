"""Public SDK adapter with a narrowly scoped raw-timing guard at the HTTP boundary."""

from dataclasses import dataclass
from decimal import Decimal
from html import unescape
from importlib.metadata import version
import math

from .defaults import (
    TRANSCRIPT_CONNECT_TIMEOUT_SECONDS, TRANSCRIPT_MAX_RETRIES, TRANSCRIPT_READ_TIMEOUT_SECONDS,
)
from .models import _require_video_id
from .transcript_models import (
    CaptionKind, CaptionSegment, CaptionTrack, ProviderTranscript, TranscriptUnavailableReason,
)
from .transcripts import CaptionProviderError, CaptionUnavailable, TranscriptFailureKind


@dataclass(frozen=True, slots=True)
class TranscriptConfig:
    connect_timeout_seconds: float = TRANSCRIPT_CONNECT_TIMEOUT_SECONDS
    read_timeout_seconds: float = TRANSCRIPT_READ_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        try:
            valid = all(type(value) in (int, float) and math.isfinite(value) and value > 0
                        for value in (self.connect_timeout_seconds, self.read_timeout_seconds))
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("Transcript HTTP timeouts must be finite and positive")


DEFAULT_TRANSCRIPT_CONFIG = TranscriptConfig()


def _guard_caption_timing(content: bytes) -> tuple[CaptionSegment, ...]:
    """Inspect one SDK-fetched XML response; no URL construction or caption fetching.

    Require explicit source timing before the SDK can default missing duration to
    zero. Retain exact decimals and source positions for the public fetch result.
    Unsupported/nested representations fail instead of silently losing content.
    """
    from defusedxml import ElementTree

    try:
        root = ElementTree.fromstring(content)
        if root.tag != "transcript" or any(node.tag != "text" or len(node) for node in root):
            raise CaptionProviderError(TranscriptFailureKind.MALFORMED_RESPONSE)
        if not any(node.text and unescape(node.text).strip() for node in root):
            raise CaptionUnavailable(TranscriptUnavailableReason.EMPTY)
        segments = []
        for index, node in enumerate(root):
            if node.text is None:
                continue  # The public SDK also omits nodes with no text.
            segments.append(CaptionSegment(
                index, unescape(node.text), Decimal(node.attrib["start"]), Decimal(node.attrib["dur"]),
            ))
        return tuple(segments)
    except (CaptionProviderError, CaptionUnavailable):
        raise
    except Exception:
        raise CaptionProviderError(TranscriptFailureKind.PARSING) from None


class YouTubeCaptionProvider:
    """Own a lazily created SDK/session; inject a requests adapter for offline tests.

    SDK use is restricted to public list(), Transcript metadata and fetch(). The
    response hook is active only during fetch(), not a second YouTube client.
    """

    def __init__(self, *, config: TranscriptConfig = DEFAULT_TRANSCRIPT_CONFIG, http_adapter=None):
        if not isinstance(config, TranscriptConfig):
            raise ValueError("Caption provider requires TranscriptConfig")
        self.config = config
        self._http_adapter = http_adapter
        self._session = None
        self._api = None
        self._sdk = None
        self._requests = None
        self._handles = {}
        self._generation = 0
        self._fetching = False
        self._guarded = None
        self._last_status = None
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
        self._handles.clear()
        self._guarded = None
        self._api = None
        self._session = None
        self._closed = True

    def _ensure_client(self) -> None:
        if self._closed:
            raise CaptionProviderError(TranscriptFailureKind.CONFIGURATION)
        if self._api is not None:
            return
        try:
            import requests
            import youtube_transcript_api as sdk
            if version("youtube-transcript-api") != "1.2.4":
                raise CaptionProviderError(TranscriptFailureKind.CONFIGURATION)
        except CaptionProviderError:
            raise
        except ImportError:
            raise CaptionProviderError(TranscriptFailureKind.CONFIGURATION) from None
        config = self.config

        class TimedSession(requests.Session):
            def request(self, method, url, **kwargs):
                kwargs["timeout"] = (config.connect_timeout_seconds, config.read_timeout_seconds)
                return super().request(method, url, **kwargs)

        session = TimedSession()
        session.trust_env = False  # Public captions: no implicit netrc/account authentication.
        adapter = (self._http_adapter if self._http_adapter is not None
                   else requests.adapters.HTTPAdapter(max_retries=TRANSCRIPT_MAX_RETRIES))
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.hooks["response"].append(self._observe_response)
        self._session = session
        self._requests = requests
        self._sdk = sdk
        self._api = sdk.YouTubeTranscriptApi(http_client=session)

    def _observe_response(self, response, **_):
        self._last_status = response.status_code
        if self._fetching and 200 <= response.status_code < 300:
            if response.status_code != 200:
                raise CaptionProviderError(TranscriptFailureKind.MALFORMED_RESPONSE)
            self._guarded = _guard_caption_timing(response.content)
        return response

    def _raise_mapped(self, error: Exception) -> None:
        if isinstance(error, (CaptionProviderError, CaptionUnavailable)):
            raise error from None
        sdk, requests = self._sdk, self._requests
        if isinstance(error, sdk.TranscriptsDisabled):
            raise CaptionUnavailable(TranscriptUnavailableReason.CAPTIONS_DISABLED) from None
        if isinstance(error, sdk.NoTranscriptFound):
            raise CaptionUnavailable(TranscriptUnavailableReason.NO_ENGLISH) from None
        if isinstance(error, requests.exceptions.Timeout):
            kind = TranscriptFailureKind.TIMEOUT
        elif isinstance(error, (sdk.RequestBlocked, sdk.IpBlocked)):
            kind = (TranscriptFailureKind.RATE_LIMIT if self._last_status == 429
                    else TranscriptFailureKind.BLOCKED)
        elif self._last_status == 401 or isinstance(error, sdk.CookieError):
            kind = TranscriptFailureKind.AUTHENTICATION
        elif self._last_status == 403 or isinstance(error, (sdk.AgeRestricted, sdk.PoTokenRequired)):
            kind = TranscriptFailureKind.AUTHORIZATION
        elif isinstance(error, requests.exceptions.ConnectionError):
            kind = TranscriptFailureKind.NETWORK
        elif isinstance(error, (requests.exceptions.ChunkedEncodingError,
                                requests.exceptions.ContentDecodingError)):
            kind = TranscriptFailureKind.MALFORMED_RESPONSE
        elif isinstance(error, sdk.InvalidVideoId):
            kind = TranscriptFailureKind.CONTRACT
        elif isinstance(error, (sdk.YouTubeDataUnparsable, ValueError, KeyError, TypeError, AttributeError)):
            kind = TranscriptFailureKind.PARSING
        else:
            kind = TranscriptFailureKind.SERVICE
        raise CaptionProviderError(kind) from None

    def list_tracks(self, video_id: str) -> tuple[CaptionTrack, ...]:
        _require_video_id(video_id)
        self._ensure_client()
        self._handles.clear()
        self._generation += 1
        self._last_status = None
        try:
            tracks = []
            for index, original in enumerate(self._api.list(video_id)):
                if original.video_id != video_id or type(original.is_generated) is not bool:
                    raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
                track = CaptionTrack(
                    video_id, original.language_code,
                    CaptionKind.AUTO_GENERATED if original.is_generated else CaptionKind.MANUAL,
                    f"{self._generation}:{index}", "youtube-transcript-api", "1.2.4",
                )
                self._handles[track.provider_key] = (track, original)
                tracks.append(track)
            return tuple(tracks)
        except Exception as error:
            self._handles.clear()
            self._raise_mapped(error)

    def fetch_track(self, track: CaptionTrack) -> ProviderTranscript:
        self._ensure_client()
        stored = self._handles.get(track.provider_key) if isinstance(track, CaptionTrack) else None
        if stored is None or stored[0] != track:
            raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
        self._guarded = None
        self._last_status = None
        self._fetching = True
        try:
            fetched = stored[1].fetch(preserve_formatting=True)
            source = self._guarded
            if (source is None or fetched.video_id != track.video_id
                    or fetched.language_code != track.language_code
                    or type(fetched.is_generated) is not bool
                    or fetched.is_generated != (track.kind is CaptionKind.AUTO_GENERATED)
                    or len(fetched) != len(source)):
                raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
            # Guard completeness against unexpected SDK text transformations. The
            # SDK remains the fetch/parser implementation; source timing is exact.
            for snippet, segment in zip(fetched, source):
                if (snippet.text != segment.source_text
                        or snippet.start != float(segment.start_seconds)
                        or snippet.duration != float(segment.duration_seconds)
                        or not math.isfinite(snippet.start) or not math.isfinite(snippet.duration)):
                    raise CaptionProviderError(TranscriptFailureKind.CONTRACT)
            return ProviderTranscript(track, source)
        except Exception as error:
            self._raise_mapped(error)
        finally:
            self._fetching = False
            self._guarded = None
