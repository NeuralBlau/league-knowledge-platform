# ADR 004: Minimal deterministic metadata

**Status:** Accepted (amended for source and operational metadata)

## Context

Detailed coaching labels inferred during ingestion would add cost, uncertainty, and an ontology to maintain before their retrieval value is demonstrated.

## Decision

Keep Bronze and Silver source and operational metadata deterministic and traceable: source identity, title, creator, URL, publication date, content type, section identity, timestamps, and primary Champion or role where applicable. Silver does not require LLM-generated semantic chunk labels for concepts such as lane dynamics, gankability, wave clear, game phase, or teamfight strategy.

This restriction does not prohibit an LLM from comparing transient transcripts during [source selection](007-two-stage-source-selection.md) or the [Knowledge Curator](008-canonical-gold-wiki.md) from representing semantic knowledge in Gold.

## Consequences

Source metadata remains predictable and auditable without imposing a fixed semantic ontology on Silver. Gold can still express coaching concepts and their relationships as curated knowledge.
