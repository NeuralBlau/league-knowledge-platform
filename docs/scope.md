# V1 scope

## Purpose

The Knowledge Platform investigates whether upstream agentic knowledge preparation can reduce query-time complexity and latency for previously unseen multi-hop questions while preserving answer quality. This is a hypothesis to evaluate, not a demonstrated result. League of Legends serves as the experimental domain rather than the primary technical purpose: it supplies evolving, semi-structured knowledge with cross-concept dependencies.

This repository currently builds the acquisition and knowledge-preparation side. Implemented acquisition reaches transient English transcripts; LLM best-source selection, Bronze/Silver processing, curation, Gold persistence, and retrieval indexing remain planned. A separate Voice Coach may later retrieve the prepared knowledge and reason over game context supplied by the player; its application and evaluation remain separate from the knowledge-preparation experiment.

V1 is an incremental, local-first system rather than a fixed source corpus. Its initial acquisition targets are all Champions in a versioned, machine-readable local catalog. There is no Champion × Role target matrix: role-specific guidance and reusable general concepts may emerge from selected sources and be represented in Gold. Systematic acquisition for general-concept targets is future scope.

## Included in V1

The following is the accepted V1 target scope, not an inventory of delivered functionality. The [current implementation](../README.md#current-implementation) lists the available components. Resumable runs, Bronze/Silver/Gold processing, broader operational state, indexing, and knowledge-change measurements are not yet implemented; the integrated-source catalog capability alone does not provide those stages.

- **Repeated acquisition:** Manually initiate a logical run that attempts all configured Champion targets. A run may span physical batches or sessions and resume. It integrates at most one new selected source per target; no target is permanently complete after a source count or run.
- **Two-stage source selection:** Seek approximately 20 unseen YouTube candidates per target where useful results are available. Exclude integrated source IDs and refill search results as needed. Apply duration eligibility, then deterministically pre-rank using views/popularity and recency. Acquire transcripts transiently for up to three eligible candidates and let an LLM select one best source for educational usefulness, relevance, information density, clarity, and noise. Only that source enters Bronze. Record source exhaustion without failing the whole run.
- **Bronze and Silver:** Preserve the admitted source's raw transcript and available provenance in Bronze. Clean reliably identifiable noise, organize logical sections, and retain timestamps and deterministic provenance in Silver without synthesizing League knowledge or imposing a semantic ontology.
- **Knowledge curation:** A Knowledge Curator inspects relevant existing Gold knowledge while processing one selected Silver source at a time. Gold is the canonical, versioned Markdown Knowledge Wiki with an adaptive structure, source provenance, and preserved contradictions. The curator may make no change, enrich, rewrite, create, merge, link, or flag a conflict; it does not autonomously delete knowledge in V1.
- **Local state and retrieval:** Local SQL state tracks integrated sources, run progress and per-target outcomes, raw knowledge-change counts, and index synchronization. A local retrieval/vector index is derived from Gold and updates changed documents incrementally, including removal of stale vectors where applicable. It is a serving layer, not the source of truth.
- **Knowledge-gain evaluation:** Compare raw per-run/per-target counts of new, enriched, rewritten, and merged concepts; links; conflicts; created or updated Wiki pages; and no-change integrations where applicable. V1 does not require a synthetic aggregate score or an automatic stopping threshold.

The V1 design uses local Bronze, Silver, and Gold files, local operational SQL state, and a local retrieval index. External source/search and LLM APIs are used where needed. Azure infrastructure, including Azure AI Search, is not required for V1; Azure remains a possible future deployment target.

## Future comparative evaluation

A conventional fixed-size chunking plus retrieval baseline is planned and still needs implementation. It will be compared with agentically prepared, structured knowledge using the same source material and the same previously unseen multi-hop questions. Query-time comparison and full evaluation follow later, considering answer/retrieval quality, query-time efficiency, and preparation effort without assuming either approach wins.

The planned experiment supplements the accepted preparation architecture. Neither the baseline nor evaluation logic is implemented, and no latency reduction has been measured. Existing raw knowledge-gain requirements remain part of the V1 target scope; they are not completed evaluation results.

## Outside V1

- Systematic general-concept or dedicated Champion Matchup target acquisition. Such knowledge may still emerge from Champion sources and be represented in Gold.
- Automatic patch tracking or knowledge invalidation after game updates.
- Automatic scheduling, event-driven ingestion, or distributed workers.
- A fixed Champion × Role target matrix, fixed source quota, permanent Champion-completion state, or automatic marginal-gain stop threshold.
- A mandatory fixed Gold ontology, semantic labels on Silver chunks, or autonomous destructive deletion of Gold knowledge.
- Automatic live game-state reading; the player supplies relevant context.
- Persistent cross-game user memory. The separate Voice Coach may maintain current-game session state.

The [architecture](architecture.md) describes the flow and the [ADRs](adr/001-medallion-architecture.md) record the decisions and their history.
