# ADR 002: Source-aligned chunks

**Status:** Accepted

## Context

The first retrieval system needs useful text passages with clear provenance. Generating canonical knowledge units from every source would add transformation complexity and make source-level debugging harder.

## Decision

Clean source content and split it into chunks that remain aligned with the original material. Preserve source references and timestamps where available. Do not turn source content into LLM-generated canonical knowledge units in V1.

## Consequences

The pipeline remains easier to trace, reproduce, and inspect. Source passages may contain some redundancy, which retrieval evaluation can measure before adding more aggressive transformations.
