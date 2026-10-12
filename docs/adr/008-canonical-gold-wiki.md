# ADR 008: Canonical agent-curated Gold Markdown Wiki

**Status:** Accepted

## Context

Source-aligned Silver sections preserve evidence, but retrieval-ready chunks alone do not maintain an evolving, consolidated understanding of League knowledge. The earlier [source-aligned chunk decision](002-source-aligned-chunks.md) remains useful for Silver.

## Decision

Bronze retains only admitted selected raw sources. Silver cleans and segments them faithfully with timestamps and provenance, without semantic synthesis. Gold is the canonical, versioned, agent-curated Markdown Knowledge Wiki. Its structure adapts rather than following a mandatory fixed ontology. For each selected Silver source, a Knowledge Curator inspects relevant existing Gold knowledge, preserves provenance and contradictions, avoids duplicate concepts, and may apply NO_CHANGE, ENRICH, REWRITE, CREATE, MERGE, LINK, or FLAG_CONFLICT. Autonomous destructive DELETE is excluded from V1.

## Consequences

Gold becomes the source of truth for serving and later retrieval evaluation. Curated knowledge can express roles and reusable strategic concepts without requiring semantic labels on Silver chunks. The [retrieval index](010-incremental-gold-retrieval-index.md) is derived from Gold.
