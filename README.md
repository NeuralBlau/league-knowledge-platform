# League Knowledge Platform

The League Knowledge Platform is designed to prepare curated League of Legends expert knowledge for a voice-first AI coach. It will select useful sources, process them into traceable text chunks, and make them available for retrieval when the coach answers a player's question.

## Status

V1 is in planning and development. The architecture below describes the accepted direction, not a claim that the full pipeline is implemented.

## V1 at a glance

- Two primary source categories: Champion + Role guides and General Concept guides. V1 targets all champions through their relevant role combinations.
- Automated discovery and selection of candidate sources, followed by batch Bronze, Silver, and Gold processing.
- Source-aligned chunks with minimal metadata derived from the source or ingestion process.
- One Azure AI Search index for unstructured expert knowledge. The coach retrieves relevant text and interprets game concepts at runtime.
- Dedicated Champion Matchup guides are future scope.

See [V1 scope](docs/scope.md) and [architecture](docs/architecture.md) for details. Accepted decisions are recorded in the ADRs for [medallion processing](docs/adr/001-medallion-architecture.md), [source-aligned chunks](docs/adr/002-source-aligned-chunks.md), [one search index](docs/adr/003-single-search-index.md), and [minimal deterministic metadata](docs/adr/004-minimal-deterministic-metadata.md).

This repository is part of the larger League AI Coach project.
