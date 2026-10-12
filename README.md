# League Knowledge Platform

The League Knowledge Platform builds curated League of Legends knowledge for a voice-first AI coach. It discovers educational sources, integrates their content into a traceable Markdown Knowledge Wiki, and maintains a local retrieval index derived from that Wiki.

## Status

V1 is in planning and development. The architecture below describes the accepted direction, not a claim that the full pipeline is implemented.

## V1 at a glance

- A versioned local catalog targets all Champions for initial knowledge acquisition. Role-specific guidance and reusable concepts may emerge from the selected sources; V1 does not require a Champion × Role target matrix or systematic general-concept targets.
- Manually initiated, resumable runs repeatedly seek new knowledge. Each logical run attempts the configured targets and integrates at most one newly selected source per target. No Champion is permanently complete.
- For each target, discovery seeks approximately 20 unseen YouTube candidates where available. Deterministic metadata ranking narrows them to the Top 3 for transient transcript comparison; an LLM selects one source, and only that source enters Bronze.
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

Each page enriches its search results with available video metadata. Missing optional fields remain `None`; an upstream failure raises `DiscoveryError` rather than returning a successful page. Filtering previously integrated sources and deciding whether to request another page belong to later orchestration. Ranking and transcript evaluation are also outside this component.

Run offline tests with `python -m unittest discover -s tests -v`. They use injected responses and require neither a YouTube key nor network access.
