# Agent instructions

Use the [development workflow](docs/development-workflow.md). Human supervision takes priority over autonomy.

## Before implementation

- Read the Azure DevOps feature, PBI, and acceptance criteria. Azure DevOps is the private source of truth; request missing requirements privately rather than inventing them.
- Before agent planning, verify the PBI Definition of Ready: clear objective, sufficiently bounded scope, existing acceptance criteria, documented known constraints, and identified blocking dependencies. Technical implementation details are intentionally not required. Resolve missing readiness information privately with a human before planning.
- Read [scope](docs/scope.md), [architecture](docs/architecture.md), and relevant [ADRs](docs/adr/). Stay within the approved PBI scope and accepted architecture.
- For every non-trivial PBI, produce an implementation plan covering objective, scope, acceptance criteria, approach, affected files, validation, risks, and open questions. Keep private planning in Azure DevOps or the authorized private task conversation, not public repository files.
- Stop before modifying production code until a human explicitly approves the plan. A task assignment, silence, or agent review is not design approval. Material changes to scope or design require renewed human approval.
- Only narrow documentation, typo, or similarly mechanical changes with no behavior or design impact can skip the full plan. If the classification is unclear, ask the human reviewer.
- Use a dedicated branch named `pbi-<id>-<short-description>`; never implement a PBI directly on `main`.

## Implementation and validation

- Follow the approved plan, keep changes focused, and update relevant documentation or ADRs when needed.
- Run applicable tests, linting, builds, and other validation actually available in the repository. For documentation, check links, consistency, and the diff. Report missing checks and failures honestly; do not claim unrun checks passed.
- Self-review the complete diff against the PBI, acceptance criteria, scope, architecture, and privacy boundaries before opening a PR. Resolve findings or disclose blockers.

## Delivery and human review

- Use [.github/pull_request_template.md](.github/pull_request_template.md). Publicly summarize objective, scope, relevant acceptance criteria, approach, validation, deviations, and follow-up work; include `AB#<id>` where useful.
- Publish only approved public information. Do not copy private Azure DevOps descriptions, plans, discussions, credentials, or internal URLs into repository files or PRs. Sanitize criteria; keep sensitive evidence private.
- Respect the task's delivery boundary. Commit, push, or open a PR only when authorized; do not modify Azure DevOps unless explicitly requested.
- Leave final PR approval and merge to a human. Never self-approve or merge a PR. Revalidate changes requested during review; return material design changes to the design-review gate.
