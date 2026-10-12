# ADR 009: Local operational state and raw knowledge-gain metrics

**Status:** Accepted

## Context

Resumable acquisition and incremental indexing need durable progress and source identities. Repeated runs also need comparable evidence of what knowledge changed.

## Decision

Use a local SQL database conceptually equivalent to SQLite to track integrated sources, logical runs and progress, per-target outcomes, and Gold index synchronization state. Persist raw per-run/per-target counts for new, enriched, rewritten, and merged concepts; links; conflicts; created or updated Wiki pages; and no-change integrations where applicable. Inspect these across runs to assess marginal knowledge gain. Do not define a synthetic aggregate score, scheduler, or automatic stopping threshold in V1.

## Consequences

Runs can resume and source selection can exclude integrated IDs. Raw counts retain their meaning for later analysis. Exact SQL schema and data-access implementation remain technical design choices; transient rejected candidates need no permanent V1 history.
