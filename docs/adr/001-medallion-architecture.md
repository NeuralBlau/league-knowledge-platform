# ADR 001: Medallion architecture

**Status:** Accepted (amended for V1)

## Context

Educational sources need cleaning, segmentation, and preparation before they can support retrieval. Keeping each stage inspectable helps trace an answer back to source material and reproduce processing results.

## Decision

Use three data layers:

- **Bronze:** preserve only admitted, selected raw source material and provenance.
- **Silver:** clean and structure the content faithfully into source-aligned sections with deterministic source metadata.
- **Gold:** maintain the canonical, agent-curated Markdown Knowledge Wiki. A retrieval index is derived from Gold rather than being Gold itself.

## Consequences

Raw, processed, and curated representations can be inspected independently. Pipeline changes can be evaluated without losing the original source. The additional layers require explicit transformation steps and storage management.

## Decision history

The original V1 decision placed retrieval-ready chunks and embeddings in Gold. The later [canonical Gold decision](008-canonical-gold-wiki.md) changed Gold to curated Markdown knowledge and placed serving vectors in a [derived local index](010-incremental-gold-retrieval-index.md). The Bronze/Silver/Gold separation remains accepted.
