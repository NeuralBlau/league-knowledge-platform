# ADR 006: Iterative Champion acquisition

**Status:** Accepted

## Context

A fixed Champion × Role matrix or one-time source corpus would not capture knowledge that emerges from selected content or later acquisition runs.

## Decision

Use a versioned, machine-readable local list of all Champions as the initial target catalog. Manually initiated logical runs attempt every configured target and may resume across batches or sessions. Integrate at most one new selected source per target per run. Exclude sources already integrated in later runs; record exhausted targets without failing the whole run. A Champion is never permanently complete. Role-specific and reusable general knowledge can emerge from sources, while systematic general-concept targets remain future scope.

## Consequences

The system needs persistent source identity and run-progress state. Repeated runs allow later comparison of knowledge changes without a fixed source quota or stopping threshold. The [local state decision](009-local-state-and-knowledge-gain.md) records those outcomes.
