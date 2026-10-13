"""One-page YouTube candidate discovery with an injectable HTTP boundary."""

from __future__ import annotations

import json
import os
import re
import socket
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .defaults import DISCOVERY_PAGE_SIZE, DISCOVERY_TIMEOUT_SECONDS
from .models import CandidateVideo, ChampionTarget, DiscoveryCursor, DiscoveryPage

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_DURATION = re.compile(
    r"P(?:(?P<weeks>[0-9]+)W)?(?:(?P<days>[0-9]+)D)?"
    r"(?:T(?:(?P<hours>[0-9]+)H)?(?:(?P<minutes>[0-9]+)M)?"
    r"(?:(?P<seconds>[0-9]+)S)?)?\Z"
)


class DiscoveryFailureKind(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    QUOTA = "quota"
    NETWORK = "network"
    SERVICE = "service"
    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"


class DiscoveryError(RuntimeError):
    """A requested discovery page could not be completed."""

    def __init__(self, kind: DiscoveryFailureKind, message: str):
        self.kind = kind
        super().__init__(message)


class HttpStatusFailure(Exception):
    """Sanitized HTTP failure from the transport boundary."""

    def __init__(self, status: int, reason: str | None = None):
        self.status = status
        self.reason = reason
        super().__init__(f"YouTube HTTP {status}")


class JsonTransport(Protocol):
    def get_json(self, endpoint: str, params: Mapping[str, str], timeout: float) -> object:
        """Fetch one JSON response or raise a transport failure."""


class UrllibJsonTransport:
    """Standard-library transport. Never expose request URLs containing the API key."""

    def get_json(self, endpoint: str, params: Mapping[str, str], timeout: float) -> object:
        request = Request(f"{endpoint}?{urlencode(params)}")
        try:
            with urlopen(request, timeout=timeout) as response:
                try:
                    return json.load(response)
                except (ValueError, UnicodeError):
                    raise DiscoveryError(
                        DiscoveryFailureKind.MALFORMED_RESPONSE,
                        "YouTube returned invalid JSON",
                    ) from None
        except HTTPError as error:
            reason = None
            try:
                payload = json.loads(error.read(8192))
                details = payload.get("error", {}).get("errors", [])
                if isinstance(details, list) and details and isinstance(details[0], dict):
                    value = details[0].get("reason")
                    reason = value if isinstance(value, str) else None
            except (ValueError, UnicodeError, AttributeError, TypeError):
                pass
            raise HttpStatusFailure(error.code, reason) from None
        except (TimeoutError, socket.timeout):
            raise DiscoveryError(DiscoveryFailureKind.TIMEOUT, "YouTube request timed out") from None
        except URLError as error:
            kind = (DiscoveryFailureKind.TIMEOUT if isinstance(error.reason, TimeoutError)
                    else DiscoveryFailureKind.NETWORK)
            raise DiscoveryError(kind, "YouTube request failed") from None
        except OSError:
            raise DiscoveryError(DiscoveryFailureKind.NETWORK, "YouTube request failed") from None


def _malformed(message: str) -> DiscoveryError:
    return DiscoveryError(DiscoveryFailureKind.MALFORMED_RESPONSE, message)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _malformed(f"YouTube {field} has an invalid type")
    return value.strip() or None


def _published_at(value: object) -> datetime | None:
    text = _optional_text(value, "publication time")
    if text is None:
        return None
    try:
        published = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _malformed("YouTube publication time is invalid") from None
    if published.utcoffset() is None:
        raise _malformed("YouTube publication time has no timezone")
    return published.astimezone(timezone.utc)


def _view_count(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise _malformed("YouTube view count is invalid")


def _duration_seconds(value: object) -> int | None:
    text = _optional_text(value, "duration")
    if text is None:
        return None
    match = _DURATION.fullmatch(text)
    if match is None or not any(group is not None for group in match.groupdict().values()):
        raise _malformed("YouTube duration is invalid")
    units = {name: int(number or 0) for name, number in match.groupdict().items()}
    return (units["weeks"] * 604800 + units["days"] * 86400
            + units["hours"] * 3600 + units["minutes"] * 60 + units["seconds"])


def _usable_video_id(value: object) -> bool:
    return isinstance(value, str) and _VIDEO_ID.fullmatch(value) is not None


def _object_or_empty(value: object, field: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _malformed(f"YouTube {field} is malformed")
    return value


def _http_error(error: HttpStatusFailure) -> DiscoveryError:
    reason = (error.reason or "").lower()
    if error.status == 401 or "keyinvalid" in reason or "api_key_invalid" in reason:
        kind = DiscoveryFailureKind.AUTHENTICATION
    elif (error.status == 429 or "quota" in reason or "ratelimit" in reason
          or "dailylimit" in reason):
        kind = DiscoveryFailureKind.QUOTA
    elif error.status == 403:
        kind = DiscoveryFailureKind.AUTHORIZATION
    else:
        kind = DiscoveryFailureKind.SERVICE
    return DiscoveryError(kind, f"YouTube request failed with HTTP {error.status}")


class YouTubeDiscovery:
    """Retrieve and normalize exactly one YouTube search page per call."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: JsonTransport | None = None,
        page_size: int = DISCOVERY_PAGE_SIZE,
        timeout_seconds: float = DISCOVERY_TIMEOUT_SECONDS,
    ):
        key = api_key if api_key is not None else os.environ.get("YOUTUBE_API_KEY")
        if not isinstance(key, str) or not key.strip():
            raise DiscoveryError(DiscoveryFailureKind.CONFIGURATION, "YOUTUBE_API_KEY is required")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise ValueError("page_size must be between 1 and 50")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = key
        self._transport = transport if transport is not None else UrllibJsonTransport()
        self._page_size = page_size
        self._timeout = timeout_seconds

    def _get_json(self, endpoint: str, params: dict[str, str]) -> object:
        try:
            return self._transport.get_json(endpoint, params, self._timeout)
        except HttpStatusFailure as error:
            raise _http_error(error) from None
        except DiscoveryError:
            raise
        except (TimeoutError, socket.timeout):
            raise DiscoveryError(DiscoveryFailureKind.TIMEOUT, "YouTube request timed out") from None
        except URLError:
            raise DiscoveryError(DiscoveryFailureKind.NETWORK, "YouTube request failed") from None
        except OSError:
            raise DiscoveryError(DiscoveryFailureKind.NETWORK, "YouTube request failed") from None

    def discover_page(
        self, target: ChampionTarget, cursor: DiscoveryCursor | None = None
    ) -> DiscoveryPage:
        if not target.id or not target.name.strip():
            raise ValueError("Discovery target requires a Champion ID and name")
        if cursor is not None:
            if cursor.target_id != target.id:
                raise ValueError("Discovery cursor belongs to another Champion target")
            if not cursor.page_token:
                raise ValueError("Discovery cursor has no page token")

        search_params = {
            "part": "snippet",
            "type": "video",
            "q": f"League of Legends {target.name} guide",
            "order": "relevance",
            "maxResults": str(self._page_size),
            "key": self._api_key,
        }
        if cursor is not None:
            search_params["pageToken"] = cursor.page_token
        search = self._get_json(_SEARCH_URL, search_params)
        if not isinstance(search, dict) or not isinstance(search.get("items"), list):
            raise _malformed("YouTube search response has no valid items list")
        next_token = search.get("nextPageToken")
        if next_token is not None and (not isinstance(next_token, str) or not next_token):
            raise _malformed("YouTube search continuation is invalid")
        if cursor is not None and next_token == cursor.page_token:
            raise _malformed("YouTube search continuation did not advance")

        search_items: list[tuple[str, dict]] = []
        seen_ids: set[str] = set()
        for item in search["items"]:
            if not isinstance(item, dict):
                raise _malformed("YouTube search item is malformed")
            identity = item.get("id")
            if not isinstance(identity, dict) or identity.get("kind") not in (None, "youtube#video"):
                continue
            video_id = identity.get("videoId")
            if not _usable_video_id(video_id) or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            snippet = _object_or_empty(item.get("snippet"), "search snippet")
            search_items.append((video_id, snippet))

        details_by_id: dict[str, dict] = {}
        if search_items:
            details = self._get_json(_VIDEOS_URL, {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(video_id for video_id, _ in search_items),
                "key": self._api_key,
            })
            if not isinstance(details, dict) or not isinstance(details.get("items"), list):
                raise _malformed("YouTube video details response has no valid items list")
            for item in details["items"]:
                if not isinstance(item, dict) or not _usable_video_id(item.get("id")):
                    raise _malformed("YouTube video details contain an invalid identity")
                video_id = item["id"]
                if video_id in details_by_id:
                    raise _malformed("YouTube video details repeat an identity")
                if video_id in seen_ids:
                    details_by_id[video_id] = item

        candidates: list[CandidateVideo] = []
        for video_id, search_snippet in search_items:
            details = details_by_id.get(video_id, {})
            snippet = _object_or_empty(details.get("snippet"), "video snippet")
            statistics = _object_or_empty(details.get("statistics"), "statistics")
            content = _object_or_empty(details.get("contentDetails"), "content details")
            title = _optional_text(snippet.get("title"), "title")
            channel = _optional_text(snippet.get("channelTitle"), "channel title")
            published = _published_at(snippet.get("publishedAt"))
            candidates.append(CandidateVideo(
                target_id=target.id,
                video_id=video_id,
                title=title if title is not None else _optional_text(search_snippet.get("title"), "title"),
                channel_title=(channel if channel is not None
                               else _optional_text(search_snippet.get("channelTitle"), "channel title")),
                published_at_utc=(published if published is not None
                                  else _published_at(search_snippet.get("publishedAt"))),
                view_count=_view_count(statistics.get("viewCount")),
                duration_seconds=_duration_seconds(content.get("duration")),
            ))

        next_cursor = (DiscoveryCursor(target_id=target.id, page_token=next_token)
                       if next_token is not None else None)
        return DiscoveryPage(
            target_id=target.id,
            candidates=tuple(candidates),
            next_cursor=next_cursor,
            exhausted=next_cursor is None,
        )
