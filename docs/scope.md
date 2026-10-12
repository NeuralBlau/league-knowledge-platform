# V1 scope

## Purpose

The Knowledge Platform acquires and compiles curated League of Legends knowledge for a voice-first coach. The coach can retrieve that knowledge and reason over game context supplied by the player. This repository covers knowledge acquisition, curation, and retrieval; the Voice Coach and its evaluation system are separate.

V1 is an incremental, local-first system rather than a fixed source corpus. Its initial acquisition targets are all Champions in a versioned, machine-readable local catalog. There is no Champion × Role target matrix: role-specific guidance and reusable general concepts may emerge from selected sources and be represented in Gold. Systematic acquisition for general-concept targets is future scope.

## Included in V1

- **Repeated acquisition:** Manually initiate a logical run that attempts all configured Champion targets. A run may span physical batches or sessions and resume. It integrates at most one new selected source per target; no target is permanently complete after a source count or run.
- **Two-stage source selection:** Seek approximately 20 unseen YouTube candidates per target where useful results are available. Exclude integrated source IDs and refill search results as needed. Deterministically pre-rank unseen candidates using views/popularity, recency, and duration. Acquire transcripts transiently for the Top 3 and let an LLM select one best source for educational usefulness, relevance, information density, clarity, and noise. Only that source enters Bronze. Record source exhaustion without failing the whole run.
- **Bronze and Silver:** Preserve the admitted source's raw transcript and available provenance in Bronze. Clean reliably identifiable noise, organize logical sections, and retain timestamps and deterministic provenance in Silver without synthesizing League knowledge or imposing a semantic ontology.
- **Knowledge curation:** A Knowledge Curator inspects relevant existing Gold knowledge while processing one selected Silver source at a time. Gold is the canonical, versioned Markdown Knowledge Wiki with an adaptive structure, source provenance, and preserved contradictions. The curator may make no change, enrich, rewrite, create, merge, link, or flag a conflict; it does not autonomously delete knowledge in V1.
- **Local state and retrieval:** Local SQL state tracks integrated sources, run progress and per-target outcomes, raw knowledge-change counts, and index synchronization. A local retrieval/vector index is derived from Gold and updates changed documents incrementally, including removal of stale vectors where applicable. It is a serving layer, not the source of truth.
- **Knowledge-gain evaluation:** Compare raw per-run/per-target counts of new, enriched, rewritten, and merged concepts; links; conflicts; created or updated Wiki pages; and no-change integrations where applicable. V1 does not require a synthetic aggregate score or an automatic stopping threshold.

V1 uses local Bronze, Silver, and Gold files, local operational SQL state, and a local retrieval index. External source/search and LLM APIs are used where needed. Azure infrastructure, including Azure AI Search, is not required for V1; Azure remains a possible future deployment target.

## Outside V1

- Systematic general-concept or dedicated Champion Matchup target acquisition. Such knowledge may still emerge from Champion sources and be represented in Gold.
- Automatic patch tracking or knowledge invalidation after game updates.
- Automatic scheduling, event-driven ingestion, or distributed workers.
- A fixed Champion × Role target matrix, fixed source quota, permanent Champion-completion state, or automatic marginal-gain stop threshold.
- A mandatory fixed Gold ontology, semantic labels on Silver chunks, or autonomous destructive deletion of Gold knowledge.
- Automatic live game-state reading; the player supplies relevant context.
- Persistent cross-game user memory. The separate Voice Coach may maintain current-game session state.

The [architecture](architecture.md) describes the flow and the [ADRs](adr/001-medallion-architecture.md) record the decisions and their history.
