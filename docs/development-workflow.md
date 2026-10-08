# Development workflow

Development is human-supervised: agents prepare plans, implement approved changes, validate their work, and explain the result. Humans approve the design and retain final pull-request review and merge authority.

## Requirements and public documentation

Azure DevOps is the private source of truth for feature requirements, Product Backlog Items (PBIs), and acceptance criteria. Repository documentation explains the public scope, architecture, decisions, and development process; it does not duplicate the private backlog.

Read the relevant feature, PBI, and acceptance criteria alongside [V1 scope](scope.md), [architecture](architecture.md), and the [ADRs](adr/). If requirements are missing, inaccessible, or inconsistent, resolve them with a human in the private planning context before implementing affected work. Do not infer approval or invent acceptance criteria.

Keep detailed plans, private requirements, discussions, and sensitive validation evidence in Azure DevOps or an authorized private task conversation. Updating Azure DevOps requires explicit task authorization. Public branches, files, commits, and PRs must contain only information approved for publication. An `AB#<id>` reference can provide traceability without copying private work-item content or internal URLs.

## PBI Definition of Ready

A PBI is ready for agent planning when:

- objective is clear
- scope is sufficiently bounded
- acceptance criteria exist
- known constraints are documented
- blocking dependencies are identified

Technical implementation details are intentionally not required.

Resolve missing readiness information with a human in the private planning context before agent planning.

## 1. Prepare an implementation plan

Every non-trivial PBI requires an agent-generated implementation plan before production code is modified. Behavior changes, integrations, dependencies, architecture decisions, data migrations, and work spanning multiple components are non-trivial. Narrow documentation, typo, or mechanical changes with no behavior or design impact may skip the full plan; ambiguous cases require human classification.

The plan should cover:

- Objective, scope, non-goals, and relevant acceptance criteria.
- Proposed approach, affected components and files, dependencies, and meaningful alternatives or tradeoffs.
- Applicable tests and validation, including how each criterion will be checked.
- Risks, compatibility or data effects, and rollback considerations where relevant.
- Assumptions, open questions, and any proposed deviations from existing architecture.

Keep the plan in the private planning context. Inspecting the repository and gathering requirements can proceed during planning; implementation of production code cannot.

## 2. Obtain human design approval

A human reviews the plan, resolves blocking questions, and explicitly approves the implementation approach. Record approval and the reviewed plan version in the private task context so the implementing agent can verify it. An initial assignment, permission to inspect the repository, silence, or another agent's review does not satisfy this gate.

If approval is missing, the agent stops before modifying production code and presents the plan for review. If implementation reveals a material change to scope or design, pause affected work, revise the plan, and obtain renewed human approval. This design review is separate from final PR review.

## 3. Implement on a dedicated PBI branch

Create a dedicated branch from an up-to-date `main` using `pbi-<id>-<short-description>`, with a short, public-safe description. Keep each branch focused on its PBI and preserve unrelated local work. Do not implement directly on `main`.

Follow the approved plan and [repository agent instructions](../AGENTS.md). Keep changes small enough to review, stay within the accepted V1 scope and ADRs, and update relevant documentation when behavior or design changes. Record deviations and follow-up work in the private task context; material deviations return to design review.

## 4. Validate and self-review

Before opening a PR, the agent runs applicable automated tests, linting, builds, and other checks available for the changed components. Validate relevant acceptance criteria and inspect the full diff for correctness, regressions, scope, architecture consistency, and accidental disclosure of private information or secrets.

Report the commands run, their results, and any failures, unavailable tooling, or checks not performed. Resolve findings before handing off, or clearly identify unresolved blockers. Never describe a planned or unrun check as passing.

The repository currently contains documentation and no configured application test runner or CI workflow. Documentation changes require checking relative links, consistency with the scope and ADRs, and diff whitespace. As implementation and tooling are added, document and run the applicable automated checks. This process establishes review expectations; it does not itself install CI or configure branch protection.

## 5. Prepare the public pull request

The default delivery for completed PBI work is to commit the validated changes, push the dedicated PBI branch, and open a PR using the [PR template](../.github/pull_request_template.md). Give the human reviewer the PR link and leave final review and merge to them. Honor explicit local-only, no-commit, or no-push instructions: provide the local diff and validation results and stop at that delivery boundary.

The public PR description should stand on its own and include:

- Objective, scope, and explicit exclusions where useful.
- A PBI reference such as `AB#<id>` and a public-safe summary of relevant acceptance criteria.
- Implementation approach and confirmation of the applicable human design approval.
- Validation performed, results, and any limitations or blockers.
- Deviations from the approved plan and identified follow-up work, or an explicit statement that there are none.

Summarize criteria rather than copying private Azure DevOps text. If a criterion cannot be disclosed publicly, state that its validation evidence is available to the authorized human reviewer in the private planning context. Do not imply that public summaries replace the authoritative criteria. Avoid internal URLs, detailed private plans, discussion transcripts, and credentials.

## 6. Human PR review and merge

A human performs the final PR review, checks the result against the authoritative acceptance criteria and validation evidence, and decides whether to merge. Agent self-review and passing automated checks support this decision; they do not replace it. Agents must not approve their own PRs or merge them.

Address review feedback and rerun checks affected by subsequent changes. Return material scope or design changes to the earlier approval gate. Humans retain control over merge and work-item completion; agents update Azure DevOps only when explicitly authorized.
