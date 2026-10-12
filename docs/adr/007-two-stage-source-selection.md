# ADR 007: Two-stage automated source selection

**Status:** Accepted

## Context

Comparing full transcripts for every discovery result is costly, while source metadata alone cannot establish educational quality.

## Decision

For each Champion target, seek approximately 20 unseen YouTube candidates where useful results are available. Filter integrated video IDs and refill search results as needed. Deterministically pre-rank unseen candidates using views/popularity, recency, and duration. Acquire transcripts transiently for the Top 3; use an LLM to compare educational usefulness, relevance, information density, clarity, and noise and select one best source. Only the winner enters Bronze. Non-selected transcripts need no permanent storage.

## Consequences

The source catalog distinguishes integrated sources from transient candidates. Candidate exhaustion becomes a recorded per-target outcome. The exact ranking formula and transcript provider are technical design decisions.
