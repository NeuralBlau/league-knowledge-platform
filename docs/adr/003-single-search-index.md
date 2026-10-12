# ADR 003: One search index for expert knowledge

**Status:** Superseded for V1

## Context

Champion-specific and general guides serve the same runtime retrieval use case. Separate indexes would introduce routing and maintenance work before evaluation shows a need for them.

## Decision

The original V1 decision was to use one Azure AI Search index for unstructured expert knowledge from Champion + Role guides and General Concept guides. The initial query planner would search the combined corpus.

## Consequences

The original design offered a shared retrieval path and avoided premature routing complexity. It is no longer a V1 requirement: initial acquisition targets Champions, Gold is a curated Wiki, and a [local index derived from Gold](010-incremental-gold-retrieval-index.md) serves retrieval. [Local-first V1](005-local-first-v1.md) does not require Azure AI Search. Azure remains a possible later deployment target.
