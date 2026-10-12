# ADR 002: Source-aligned chunks

**Status:** Superseded for the Gold/retrieval model; retained for Silver

## Context

The first retrieval system needs useful text passages with clear provenance. Generating canonical knowledge units from every source would add transformation complexity and make source-level debugging harder.

## Decision

The original decision was to clean source content and split it into chunks aligned with the original material, preserving source references and timestamps, rather than generating canonical knowledge units. That source-faithful representation remains a Silver responsibility.

## Consequences

The source processing path remains traceable and inspectable. Gold now uses an agent-curated Markdown Wiki, which may integrate and restructure knowledge while preserving provenance and contradictions. The [Gold decision](008-canonical-gold-wiki.md) supersedes the original restriction on curated knowledge; the [retrieval index](010-incremental-gold-retrieval-index.md) is derived from Gold rather than directly treating Silver chunks as canonical knowledge.
