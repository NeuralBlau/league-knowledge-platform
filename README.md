# League Knowledge Platform

The League Knowledge Platform builds curated League of Legends knowledge for a voice-first AI coach. It discovers educational sources, integrates their content into a traceable Markdown Knowledge Wiki, and maintains a local retrieval index derived from that Wiki.

## Status

V1 is in planning and development. The architecture below describes the accepted direction, not a claim that the full pipeline is implemented.

## V1 at a glance

- A versioned local catalog targets all Champions for initial knowledge acquisition. Role-specific guidance and reusable concepts may emerge from the selected sources; V1 does not require a Champion × Role target matrix or systematic general-concept targets.
- Manually initiated, resumable runs repeatedly seek new knowledge. Each logical run attempts the configured targets and integrates at most one newly selected source per target. No Champion is permanently complete.
- For each target, collection seeks 20 unique unseen YouTube candidates where available and returns at most 20. Deterministic metadata ranking selects up to three eligible candidates, and their available English captions are acquired transiently. LLM comparison and selected-source Bronze admission will follow.
- Silver cleans and segments selected material faithfully. A Knowledge Curator integrates it into Gold, the canonical, versioned Markdown Knowledge Wiki.
- Local SQL stores operational progress and knowledge-change counts. An incremental local retrieval/vector index serves Gold. Azure is a possible future deployment target, not a V1 requirement.

See [V1 scope](docs/scope.md), [architecture](docs/architecture.md), and the [architecture decisions](docs/adr/001-medallion-architecture.md) for details. Dedicated Champion Matchup target acquisition and persistent cross-game user memory are outside initial V1 scope.

This repository is part of the larger League AI Coach project.

## Champion target loading and YouTube discovery

The committed `data/champion_targets.json` catalog is loaded locally with `load_targets()`. Loading validates the complete catalog and raises `TargetLoadError` if it cannot be used. No Riot request is needed at runtime.

Set `YOUTUBE_API_KEY` in the environment before discovery. Keep the key out of repository files and logs. Python 3.10 or newer is required. The discovery API returns one search page per call, including normalized video metadata and a target-bound continuation cursor:

```python
from league_knowledge_platform import YouTubeDiscovery, load_targets

target = load_targets()[0]
discovery = YouTubeDiscovery()
page = discovery.discover_page(target)
# A caller may pass page.next_cursor to discover_page for a later page.
```

Each page enriches its search results with available video metadata. Missing optional fields remain `None`; an upstream failure raises `DiscoveryError` rather than returning a successful page. The separate collector below filters integrated sources and decides whether to request another page. Ranking and transcript evaluation remain outside the discovery and collection components.

## Local source catalog and unseen collection

The source catalog stores only globally integrated YouTube video IDs. A selected source qualifies as integrated after its raw material has been successfully persisted to Bronze. Discovery, collection, ranking, and rejection do not register sources. The later Bronze integration caller must invoke `catalog.register_integrated(video_id)` only after persistence succeeds; repeating that registration is safe and preserves the first registration timestamp. The catalog does not perform or verify Bronze writes itself.

Use SQLite 3.24 or newer with Python's standard-library `sqlite3`. Explicit initialization creates schema version 1; construction and reads never create or migrate a catalog. The database path is caller-controlled; `.state/knowledge_platform.sqlite3` is a suggested local path excluded from Git.

```python
from pathlib import Path
from league_knowledge_platform import (
    YouTubeDiscovery,
    collect_unseen_candidates,
    initialize_source_catalog,
    load_targets,
)

# Explicit setup, separate from read-only collection.
catalog = initialize_source_catalog(Path(".state/knowledge_platform.sqlite3"))
target = load_targets()[0]
result = collect_unseen_candidates(
    target,
    discovery=YouTubeDiscovery(),  # Requires YOUTUBE_API_KEY; performs live discovery.
    catalog_reader=catalog,
)
# result is the input for deterministic ranking, not an ingestion decision.
```

Each collection reads one immutable integrated-ID snapshot before requesting its first page. It excludes integrated IDs, deduplicates across all fetched pages, retains the first candidate's metadata and discovery order, and stops at 20 unique unseen candidates. Overflow is discarded in discovery order. Empty, duplicate-only, or fully integrated pages still trigger refill when a continuation cursor exists. No heuristic page limit or quality threshold is applied.

`UnseenCandidateSet` contains `target_id`, an immutable `candidates` tuple, and `exhausted`; `target_reached` indicates exactly 20 candidates. Normal search exhaustion returns any smaller available set, including an empty set, successfully. Exhaustion means the last successful page had no continuation; it can also be true when the target of 20 is reached.

A discovery failure, including on a later refill page, raises `UnseenCollectionError` rather than returning a successful partial pool. Its `kind`, optional `discovery_failure_kind`, and exception cause distinguish discovery, catalog, and contract failures. Collection does not retry discovery automatically, initialize missing databases, register candidates, or write any persistent state. Missing/corrupt catalogs and unsupported schema versions fail explicitly.

The snapshot is fixed for one collection; it is not a reservation against concurrent source integration. Registration uses short atomic SQL transactions and an idempotent video-ID primary key. Coordinating parallel integrations and recovering between Bronze writes and catalog registration belong to later orchestration. Ranking, transcripts, source selection, Bronze/Silver/Gold processing, run state, and scheduling are not implemented by this collector.

Run offline tests with `python -m unittest discover -s tests -v`. They use injected responses and require neither a YouTube key nor network access.

## Deterministic candidate ranking

`rank_candidates()` consumes a completed `UnseenCandidateSet` and returns an immutable `RankedCandidateSet`. Known durations below 3 minutes or above 30 minutes are excluded before ranking; both boundaries are eligible. Unknown duration remains eligible. Duration has no score contribution: a 10-minute and a 25-minute video with otherwise identical ranking metadata receive identical scores.

```python
from datetime import datetime, timezone
from league_knowledge_platform import rank_candidates

# Use one explicit reference time for reproducible evaluation of this collection.
reference_time = datetime(2026, 10, 13, tzinfo=timezone.utc)
shortlist = rank_candidates(result, reference_time=reference_time)
for entry in shortlist.candidates:
    original_video = entry.candidate
    print(original_video.video_id, entry.score)
```

For eligible candidates, popularity is `ln(1 + views) / ln(1 + maximum eligible views)`. All known counts being zero yields zero popularity. Recency is `2 ** (-age_days / 365)`, where age is calculated against the supplied timezone-aware reference time and capped at zero for a future publication date. Reference times are normalized to UTC; a reference time without a timezone is rejected.

The score is 70% popularity plus 30% recency, rounded to 12 decimal places. Missing views or publication dates remain absent and contribute zero; the other signal's weight is not increased. Equal final scores preserve the original collection/discovery order. This is a metadata funnel, not a judgment of educational or semantic quality.

The output contains exactly `min(3, eligible_count)` entries, including none when every video is excluded. Each entry retains the original `CandidateVideo` object, discovery index, both normalized signals, their contributions, and final score. The set records the UTC reference time, immutable scoring configuration, input and eligible counts, and `input_exhausted` from collection. An empty shortlist does not imply search exhaustion or cause discovery/refill. The ranker makes no network, filesystem, or database calls, and does not register sources or persist candidates. Transcript acquisition is the separate stage below; semantic source selection remains future work.

Non-secret tunable defaults are centrally discoverable in `league_knowledge_platform/defaults.py`: duration bounds, Top-K, scoring weights, recency half-life, score precision, the existing unseen limit, and discovery page size/timeout. `RankingConfig` consumes the scoring defaults and can be supplied explicitly for reproducible evaluation; it requires positive weights summing to one with popularity stronger than recency. Eligibility limits and Top-K come from the central service defaults. Existing discovery settings retain their established values and override behavior. Secrets such as `YOUTUBE_API_KEY` remain environment/runtime configuration and never belong in the defaults module.

## Transient English caption acquisition

Install the optional provider dependencies in your Python environment:

```shell
python -m pip install -r requirements-transcripts.txt
```

`acquire_transcripts()` consumes the completed `RankedCandidateSet` without changing ranking, identity, metadata, or relative order. It uses our replaceable `CaptionProvider` protocol. `YouTubeCaptionProvider` wraps the pinned `youtube-transcript-api==1.2.4` public SDK and retrieves existing public caption tracks without a YouTube Data API key. It does not translate captions, download audio, or run speech recognition.

```python
from league_knowledge_platform import YouTubeCaptionProvider, acquire_transcripts

# This explicitly performs live caption requests for the supplied shortlist.
# Offline tests inject a fake provider or synthetic HTTP adapter instead.
with YouTubeCaptionProvider() as provider:
    transcripts = acquire_transcripts(shortlist, provider=provider)

for outcome in transcripts.outcomes:
    print(outcome.ranked_candidate.candidate.video_id, outcome.status.value)
# transcripts.transcripts contains only successful transient acquisitions.
```

Manual English captions are preferred over auto-generated English captions across all accepted English locales. Within each caption type the stable preference is `en`, `en-US`, `en-GB`, then other English variants. Matching is case-insensitive and accepts `_` as a locale separator; original language metadata is retained. A valid but empty manual track may fall back to another existing English track. A technical manual-track failure aborts acquisition rather than being hidden by an automatic-track fallback.

Each acquired transcript references the original `RankedCandidate` and retains ordered segments with source position, decoded source text, whitespace-normalized text, and exact `Decimal` start/duration seconds. Empty segments may be removed; substantive content, repeated captions, overlapping times, and explicit zero duration are preserved. Text is not summarized, semantically cleaned, or truncated for model context. The derived `text` property joins normalized segments without replacing their timing/provenance representation.

The SDK adapter uses public `list()` and track `fetch()` interfaces. A narrowly scoped response hook checks source timing before the SDK can replace a missing duration with zero. It cross-checks the public fetch result against the source response; unsupported caption structures or unexpected text/timing transformations fail explicitly. It does not construct caption URLs, parse YouTube pages, or call private SDK parser functions.

For 0–3 input candidates, `TransientTranscriptSet` retains the original shortlist and an explicit `acquired` or `unavailable` outcome for every candidate. No tracks, disabled captions, no acceptable English track, and valid empty caption content are normal unavailability. Acquisition continues, and successful transcripts retain their original relative order: A acquired, B unavailable, C acquired returns A then C. An empty shortlist makes no provider call; all normally unavailable candidates produce a successful empty transcript tuple with their outcomes.

Timeout, network, rate-limit/blocking, applicable authentication/authorization, service, parsing, malformed/incomplete response, and provider-contract errors raise `TranscriptAcquisitionError`. Its `kind`, `video_id`, `shortlist_position`, and `phase` identify the failure without transcript content or provider URLs. Processing stops, and earlier transcripts are never returned as a successful partial set. General SDK retrieval errors are not classified as normal absence.

Caption responses and transcripts remain in memory. There are no transcript files, persistent caches, Bronze writes, or source-catalog mutations. The caller owns the successful result until downstream source comparison is complete; the provider context closes its HTTP session and clears its track handles. Only a later selected winner may enter Bronze through a separate integration stage. Transcript acquisition does not select a winner, invoke an LLM, rediscover sources, refill, or change ranking.

`TranscriptConfig` consumes centralized non-secret defaults: 5-second HTTP connect timeout and 15-second read timeout. Requests are sequential, with no automatic retry of technical failures. These HTTP timeouts do not promise a fixed overall operation duration. Secrets remain environment/runtime configuration, never defaults. The SDK relies on YouTube web interfaces that can change or block requests; offline validation verifies behavior and integration contracts, not live availability.

Run the full offline suite after installing the optional dependencies:

```shell
python -m unittest discover -s tests -v
```

The real SDK tests use synthetic responses through the public HTTP adapter boundary and never fall back to live YouTube. Without the optional dependencies, SDK adapter tests explicitly skip; the existing components and fake-provider acquisition tests remain available. Synthetic fixture text is test data, not persisted acquired candidate content.
