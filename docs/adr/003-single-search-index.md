# ADR 003: One search index for expert knowledge

**Status:** Accepted

## Context

Champion-specific and general guides serve the same runtime retrieval use case. Separate indexes would introduce routing and maintenance work before evaluation shows a need for them.

## Decision

Use one Azure AI Search index for unstructured expert knowledge from Champion + Role guides and General Concept guides. The initial query planner searches the combined corpus.

## Consequences

Both source categories share a retrieval path and can contribute evidence to one answer. Filtering or separate indexes can be reconsidered if retrieval evaluation shows a concrete need.
