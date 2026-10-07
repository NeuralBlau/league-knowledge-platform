# V1 scope

## Purpose

The Knowledge Platform prepares curated League of Legends educational content for a voice-first coach. The coach combines retrieved expert knowledge with game context supplied by the player to answer situational questions. This repository covers the knowledge ingestion and retrieval side of that larger system.

V1 aims to establish a searchable, traceable knowledge base and a retrieval prototype. Its first content categories are:

1. **Champion + Role guides:** champion guidance in the context of a specific role. V1 aims to cover every champion through relevant Champion + Role combinations; it does not require every possible role for every champion. Relevant combinations are identified during source discovery.
2. **General Concept guides:** guidance on concepts such as pathing, objectives, tempo, lane priority, and teamfighting.

Covering every champion calls for a substantial selected corpus. Roughly 200 or more videos is a reasonable initial order of magnitude, not a fixed source quota.

## Included in V1

- Automated source selection: discover YouTube candidates, apply inexpensive metadata-based ranking and filtering, acquire transcripts for shortlisted candidates, evaluate relevance and educational quality with an LLM, and select the best 1–3 sources where appropriate. The selection criteria and thresholds remain implementation details to validate.
- Batch ingestion of selected source content through Bronze, Silver, and Gold layers.
- Cleaning and segmentation into chunks that remain aligned with their original source, including timestamps and source references where available.
- Minimal metadata known from the source or ingestion process, such as source identity, title, creator, URL, publication date, content type, and applicable champion or role.
- Embeddings and publishing of retrieval-ready chunks to a single Azure AI Search index for unstructured expert knowledge.
- A retrieval prototype that can search the combined corpus with text and vector signals and evaluate the quality of retrieved evidence. The exact search and ranking configuration will be validated in the prototype.

The coach's runtime uses retrieval and reasoning over source text to interpret concepts in context. The ingestion pipeline does not assign detailed semantic labels for concepts such as gankability, wave clear, or power spikes.

## Outside V1

- Dedicated Champion Matchup guides, which are a future source category.
- Automatic awareness of game patches; V1 uses a fixed knowledge snapshot.
- Automatic reading of live game state; the player supplies relevant context.
- Systematic champion matchup coverage.
- LLM-generated canonical knowledge units or a detailed semantic ontology at ingestion time.
- Event-driven ingestion or distributed infrastructure beyond what the initial batch pipeline needs.

The separate Voice Coach and evaluation systems will consume and assess the knowledge platform as the larger project develops. Their implementation details are outside this repository's V1 scope.
