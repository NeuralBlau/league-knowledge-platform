# Architecture

## Planned flow

```text
Automated source discovery
  → Candidate ranking
  → Transcript acquisition and evaluation
  → Top-K source selection
  → Bronze
  → Silver
  → Gold
  → Azure AI Search
  → Coach retrieval and reasoning
```

Source selection is automated: discover YouTube candidates, use inexpensive source metadata to rank and filter them, acquire transcripts for shortlisted candidates, and use an LLM to assess relevance and educational quality. Select the best 1–3 sources where appropriate before batch ingestion. The exact ranking and evaluation rules will be tested as the first sources are processed. V1 aims to cover every champion through relevant Champion + Role combinations, which are identified during discovery; it does not require every role for every champion.

| Layer | Responsibility | Output |
| --- | --- | --- |
| Bronze | Preserve selected raw source material and provenance. | Source identifiers, source details, transcript or text, timestamps where available, and ingestion information. |
| Silver | Clean and organize content without replacing the source's meaning. | Logical sections and source-aligned chunks with deterministic source metadata. |
| Gold | Prepare chunks for serving and traceability. | Retrieval-ready text, embeddings, source references, and metadata for search. |

The layers keep raw input, transformations, and serving data independently inspectable. Chunks remain linked to their source so retrieved evidence can be traced back and pipeline changes can be evaluated.

## Retrieval boundary

V1 uses one Azure AI Search index for unstructured expert knowledge from both Champion + Role and General Concept guides. The coach can search the combined corpus and use the returned source text when forming an answer. The initial retrieval prototype will assess keyword, vector, and hybrid approaches and determine whether filters or reranking help.

Ingestion records only metadata that is reliably known from the source or ingestion process. Detailed coaching concepts remain in the text. Query planning, retrieval, and reasoning interpret those concepts at runtime using the player's supplied game context. Dedicated Champion Matchup guides may be added later.

## System context

The Knowledge Platform is one part of League AI Coach. A separate Voice Coach handles player input, session context, retrieval requests, reasoning, and responses. A separate evaluation system assesses retrieval and answer quality. V1 does not read live game state automatically; the player provides relevant context.

The accepted decisions behind this design are recorded in the [ADRs](adr/001-medallion-architecture.md).
