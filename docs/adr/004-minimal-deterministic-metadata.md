# ADR 004: Minimal deterministic metadata

**Status:** Accepted

## Context

Detailed coaching labels inferred during ingestion would add cost, uncertainty, and an ontology to maintain before their retrieval value is demonstrated.

## Decision

Store only metadata known from the source or ingestion process: source identity, title, creator, URL, publication date, content type, chunk identity, timestamps, and primary champion or role where applicable. Do not add LLM-generated semantic labels for concepts such as lane dynamics, gankability, wave clear, game phase, or teamfight strategy in V1.

Search uses source text; the coach interprets its meaning at runtime through retrieval and reasoning. Evaluate hybrid retrieval before considering richer semantic metadata.

## Consequences

Metadata is predictable and easy to audit. Some concept-specific filtering is unavailable initially; retrieval evaluation will show whether that limitation matters.
