# ADR 001: Medallion architecture

**Status:** Accepted

## Context

Educational sources need cleaning, segmentation, and preparation before they can support retrieval. Keeping each stage inspectable helps trace an answer back to source material and reproduce processing results.

## Decision

Use three data layers:

- **Bronze:** preserve raw source material and provenance.
- **Silver:** clean and structure the content into source-aligned chunks with deterministic source metadata.
- **Gold:** prepare retrieval-ready chunks, embeddings, metadata, and source references for publication to search.

## Consequences

Raw, processed, and serving representations can be inspected independently. Pipeline changes can be evaluated without losing the original source. The additional layers require explicit transformation steps and storage management.
