"""Read-only, one-Champion unseen collection over the existing discovery API."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from .models import (
    UNSEEN_CANDIDATE_LIMIT,
    CandidateVideo,
    ChampionTarget,
    DiscoveryCursor,
    DiscoveryPage,
    UnseenCandidateSet,
    _require_video_id,
)
from .source_catalog import SourceCatalogError
from .youtube import DiscoveryError, DiscoveryFailureKind


class IntegratedSourceReader(Protocol):
    def load_integrated_ids(self) -> frozenset[str]:
        """Read an immutable snapshot or raise SourceCatalogError."""


class PageDiscovery(Protocol):
    def discover_page(
        self, target: ChampionTarget, cursor: DiscoveryCursor | None = None
    ) -> DiscoveryPage:
        """Return one page or raise DiscoveryError."""


class CollectionFailureKind(str, Enum):
    CATALOG = "catalog"
    DISCOVERY = "discovery"
    CONTRACT = "contract"


class UnseenCollectionError(RuntimeError):
    """A collection failed; accumulated candidates are never a success payload."""

    def __init__(
        self,
        kind: CollectionFailureKind,
        message: str,
        *,
        discovery_failure_kind: DiscoveryFailureKind | None = None,
    ):
        self.kind = kind
        self.discovery_failure_kind = discovery_failure_kind
        super().__init__(message)


def collect_unseen_candidates(
    target: ChampionTarget,
    *,
    discovery: PageDiscovery,
    catalog_reader: IntegratedSourceReader,
) -> UnseenCandidateSet:
    """Collect at most 20 unique unseen videos; no catalog writes or partial success.

    The integrated-ID snapshot is fixed for this operation. Callers requiring
    coordination with concurrent integrations must supply that coordination.
    """
    if not isinstance(target, ChampionTarget):
        raise ValueError("Collection requires a Champion target")
    try:
        integrated_ids = catalog_reader.load_integrated_ids()
    except SourceCatalogError as error:
        raise UnseenCollectionError(
            CollectionFailureKind.CATALOG, "Cannot read the integrated-source catalog"
        ) from error
    if not isinstance(integrated_ids, frozenset):
        raise UnseenCollectionError(
            CollectionFailureKind.CONTRACT, "Catalog reader did not supply an immutable snapshot"
        )
    try:
        for video_id in integrated_ids:
            _require_video_id(video_id)
    except ValueError as error:
        raise UnseenCollectionError(
            CollectionFailureKind.CONTRACT, "Catalog snapshot contains an invalid source identity"
        ) from error

    accumulated: dict[str, CandidateVideo] = {}
    used_cursors: set[DiscoveryCursor] = set()
    cursor: DiscoveryCursor | None = None
    while True:
        if cursor is not None:
            if cursor in used_cursors:
                raise UnseenCollectionError(
                    CollectionFailureKind.CONTRACT, "Discovery continuation formed a cycle"
                )
            used_cursors.add(cursor)
        try:
            page = discovery.discover_page(target, cursor)
        except DiscoveryError as error:
            raise UnseenCollectionError(
                CollectionFailureKind.DISCOVERY,
                "Unseen candidate collection failed during discovery",
                discovery_failure_kind=error.kind,
            ) from error
        if not isinstance(page, DiscoveryPage) or page.target_id != target.id:
            raise UnseenCollectionError(
                CollectionFailureKind.CONTRACT, "Discovery page belongs to another target or is invalid"
            )
        for candidate in page.candidates:
            if not isinstance(candidate, CandidateVideo) or candidate.target_id != target.id:
                raise UnseenCollectionError(
                    CollectionFailureKind.CONTRACT, "Discovery candidate belongs to another target"
                )
            try:
                _require_video_id(candidate.video_id)
            except ValueError as error:
                raise UnseenCollectionError(
                    CollectionFailureKind.CONTRACT, "Discovery candidate has an invalid video identity"
                ) from error
            if candidate.video_id in integrated_ids or candidate.video_id in accumulated:
                continue
            accumulated[candidate.video_id] = candidate
            if len(accumulated) == UNSEEN_CANDIDATE_LIMIT:
                break
        if len(accumulated) == UNSEEN_CANDIDATE_LIMIT or page.exhausted:
            return UnseenCandidateSet(target.id, tuple(accumulated.values()), page.exhausted)
        cursor = page.next_cursor
