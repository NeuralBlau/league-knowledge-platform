# ADR 005: Local-first V1 Knowledge Platform

**Status:** Accepted

## Context

The first Knowledge Platform must validate acquisition, curation, and retrieval without requiring cloud infrastructure. The earlier [single Azure AI Search index](003-single-search-index.md) would make Azure a V1 dependency.

## Decision

Run V1 locally with filesystem Bronze, Silver, and Gold artifacts, local SQL operational state, and a local retrieval/vector index. Use external source/search and LLM APIs where required. Azure infrastructure and Azure AI Search are not required for V1; Azure remains a possible future deployment direction.

## Consequences

Local operation keeps the initial system proportional to its requirements. Any later Azure deployment would require a separate decision and migration plan. This decision does not choose the exact SQL or vector database product.
