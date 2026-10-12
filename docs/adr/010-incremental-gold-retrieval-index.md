# ADR 010: Incremental local retrieval index derived from Gold

**Status:** Accepted

## Context

The [Gold Wiki](008-canonical-gold-wiki.md) is the canonical knowledge store. Serving retrieval directly from its Markdown files needs a derived index that stays synchronized as curation changes documents.

## Decision

Maintain a local retrieval/vector index derived from Gold, not a separate source of truth. Detect Gold documents changed since their last indexed version; re-chunk and re-embed changed documents, upsert their vectors, remove stale vectors where applicable, and update synchronization state. Do not rebuild the complete corpus after every curation run. No particular vector database product is mandated.

## Consequences

The serving layer can be repaired from canonical Gold. [Local operational state](009-local-state-and-knowledge-gain.md) tracks synchronization. The former [Azure AI Search requirement](003-single-search-index.md) is superseded for V1.
