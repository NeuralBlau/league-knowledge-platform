# Agent instructions

Use the [development workflow](docs/development-workflow.md). Human supervision takes priority over autonomy.

## Before implementation

- Read the Azure DevOps feature, PBI, and acceptance criteria. Azure DevOps is the private source of truth; request missing requirements privately rather than inventing them.
- Whenever an implementation PBI is handed to the agent, perform a separate Requirement Quality Review before Technical Planning, including for narrow documentation or mechanical changes. Return exactly one outcome: `READY` or `NOT READY`. `READY` requires a clear objective, bounded scope, testable acceptance criteria, documented relevant constraints, identified blocking dependencies, and no unresolved product-level ambiguity. For `NOT READY`, list every missing, ambiguous, contradictory, or non-testable product requirement and why it blocks planning; do not invent requirements, propose product defaults, create an implementation plan, or start implementation. Wait for private PBI refinement. Technical design choices belong to planning unless the PBI constrains them.
- Read [scope](docs/scope.md), [architecture](docs/architecture.md), and relevant [ADRs](docs/adr/). Stay within the approved PBI scope and accepted architecture.
- After `READY`, produce a Technical Implementation Plan unless an explicit narrow-change exception applies. Give every plan an explicit version identifier (`v1`, `v2`, etc.). Cover the applicable objective, scope, acceptance-criteria mapping, architecture, components, data flow, interfaces, data models, dependencies, configuration, failure behavior, affected files, validation, alternatives, risks, compatibility, rollback, and open technical questions. Every non-trivial plan includes at least one useful Mermaid diagram. Keep private plans in Azure DevOps or the authorized private task conversation, not public repository files.
- Discuss and revise the technical design with a human as needed. Stop before implementation until a human explicitly approves the current plan version, or explicitly authorizes an allowed narrow-change exception. A task assignment, silence, or agent review is not design approval. A material scope or design change stops affected work until a newly required or revised, explicitly versioned plan receives human approval.
- A narrow documentation, typo, or similarly mechanical change with no behavior or design impact may skip the full Technical Implementation Plan where explicitly allowed. It never skips the Requirement Quality Review. If the classification or approval boundary is unclear, ask the human reviewer.
- Use a dedicated branch named `pbi-<id>-<short-description>`; never implement a PBI directly on `main`.

## Implementation and validation

- Follow the approved plan, keep changes focused, and update relevant documentation or ADRs when needed.
- Run applicable tests, linting, builds, and other validation actually available in the repository. For documentation, check links, consistency, and the diff. Report missing checks and failures honestly; do not claim unrun checks passed.
- Self-review the complete diff against the PBI, acceptance criteria, scope, architecture, and privacy boundaries before opening a PR. Resolve findings or disclose blockers.

## Delivery and human review

- Use [.github/pull_request_template.md](.github/pull_request_template.md). Publicly summarize objective, scope, relevant acceptance criteria, approach, validation, deviations, and follow-up work. Include a PBI reference only when its rendered form does not expose a private URL; GitHub may automatically expand `AB#<id>` references.
- Publish only approved public information. Do not copy private Azure DevOps descriptions, plans, discussions, credentials, or internal URLs into repository files or PRs. Sanitize criteria; keep sensitive evidence private.
- Default delivery for completed PBI work is to commit, push the dedicated PBI branch, and open a PR for human review. Honor explicit local-only, no-commit, or no-push instructions; do not modify Azure DevOps unless explicitly requested.
- Leave final PR approval and merge to a human. Never self-approve or merge a PR. Revalidate changes requested during review; return material design changes to the design-review gate.
