# Development workflow

Development is human-supervised: agents prepare plans, implement approved changes, validate their work, and obtain independent AI PR review before handing off a successful result. Humans approve the design and retain final pull-request review and manual merge authority. Implementation self-review and independent AI review are separate gates.

## Requirements and public documentation

Azure DevOps is the private source of truth for feature requirements, Product Backlog Items (PBIs), and acceptance criteria. Repository documentation explains the public scope, architecture, decisions, and development process; it does not duplicate the private backlog.

Read the relevant feature, PBI, and acceptance criteria alongside [V1 scope](scope.md), [architecture](architecture.md), and the [ADRs](adr/). Perform the separate Requirement Quality Review before Technical Planning whenever an implementation PBI is handed to an agent. Resolve missing or inconsistent product requirements with a human in the private planning context; do not infer approval or invent requirements.

Keep detailed plans, private requirements, discussions, and sensitive validation evidence in Azure DevOps or an authorized private task conversation. Updating Azure DevOps requires explicit task authorization. Public branches, files, commits, and PRs must contain only information approved for publication. A PBI reference is suitable for public traceability only if GitHub does not expand it into a private URL; otherwise give the reference to the authorized reviewer privately.

## PBI Definition of Ready

A PBI is ready for Technical Planning when:

- objective is clear
- scope is sufficiently bounded
- acceptance criteria are testable
- relevant constraints are documented
- blocking dependencies are identified
- no unresolved product-level ambiguity requires assumptions

Technical implementation choices are intentionally not prerequisites for readiness unless the PBI explicitly constrains them.

## Workflow

```mermaid
flowchart TD
    A["Implementation PBI handed to agent"] --> B{"Requirement Quality Review"}
    B -- "NOT READY" --> C["List product blockers; stop for human refinement"]
    C --> A
    B -- "READY" --> D{"Full Technical Implementation Plan required?"}
    D -- "Yes" --> E["Versioned plan with Mermaid diagram if non-trivial"]
    E --> F["Iterative technical design discussion"]
    F --> G{"Current plan version approved by a human?"}
    G -- "No" --> E
    G -- "Yes" --> H["Dedicated PBI branch and implementation"]
    D -- "Explicit narrow-change exception" --> X["Record exception and human authorization"]
    X --> H
    H --> I{"Material scope or design change?"}
    I -- "Yes: stop affected work" --> E
    I -- "No" --> J["Applicable validation and complete diff self-review"]
    J --> K["Public pull request"]
    K --> BUD{"Review cycles used < 3?"}
    BUD -- "No; no current-HEAD PASS" --> ESC["Stop automation; escalate findings to human"]
    BUD -- "Yes" --> AV{"Independent reviewer available?"}
    AV -- "No" --> IR["INDEPENDENT REVIEW REQUIRED; stop"]
    AV -- "Yes" --> REV["Fresh independent context; complete PR review; count cycle"]
    REV --> MAT{"Material plan change required?"}
    MAT -- "Yes" --> PLAN["PLAN REVISION REQUIRED; stop affected work"]
    PLAN --> E
    MAT -- "No" --> RESULT{"Review result"}
    RESULT -- "CHANGES_REQUIRED" --> MORE{"Review cycles used < 3?"}
    MORE -- "No" --> ESC
    MORE -- "Yes" --> FIX["Assess findings; fix valid issues within approved plan"]
    FIX --> VALID["Relevant validation; commit and push"]
    VALID --> BUD
    RESULT -- "PASS" --> SHA{"Reviewed SHA equals current PR HEAD?"}
    SHA -- "No: previous PASS invalid" --> BUD
    SHA -- "Yes" --> READY["Ready for Human Review"]
    READY --> L["Human review"]
    L --> M["Manual human merge"]
    L -- "New commit: invalidate PASS" --> BUD
```

For an explicitly allowed narrow-change exception, the full plan is omitted, but Requirement Quality Review and applicable human authorization still precede implementation.

## 0. Perform the separate Requirement Quality Review

This review is mandatory for every implementation PBI handed to an agent, including a narrow documentation or mechanical change that may later skip the full Technical Implementation Plan. Return exactly one outcome:

- **READY:** the objective and scope are clear, acceptance criteria are testable, relevant constraints and blocking dependencies are identified, and no unresolved product-level ambiguity requires an assumption.
- **NOT READY:** list every missing, ambiguous, contradictory, or non-testable product requirement and explain why it blocks Technical Planning. Do not propose product defaults, resolve the requirement on the human's behalf, create an implementation plan, or implement. Stop until the PBI is refined.

Module structure, interfaces, libraries, dependency injection, asynchronous implementation, internal abstractions, and file organization are technical design choices for planning unless the PBI explicitly constrains them. They are not missing product requirements.

## 1. Prepare an implementation plan

After `READY`, every non-trivial implementation PBI requires an agent-generated Technical Implementation Plan before implementation. Behavior changes, integrations, dependencies, architecture decisions, data migrations, and work spanning multiple components are non-trivial. Narrow documentation, typo, or mechanical changes with no behavior or design impact may skip the full plan only where explicitly allowed; they never skip the Requirement Quality Review. Ambiguous cases require human classification.

Identify each plan version explicitly as `v1`, `v2`, and so on. Include at least one useful Mermaid diagram in every non-trivial plan; add sequence, state, component, or data-flow diagrams when they improve the design discussion. The human and agent may iterate through multiple versions before approval.

The plan should cover, where applicable:

- Objective, scope, non-goals, and a mapping from acceptance criteria to the proposed design and validation.
- Proposed architecture; component responsibilities; data flow; interfaces and contracts; data models; external dependencies; configuration; and error handling or failure behavior where applicable.
- Affected modules and files, alternatives and tradeoffs, and applicable tests and validation.
- Risks, compatibility or data effects, rollback considerations, open technical questions, and proposed deviations from accepted architecture where relevant.

Keep the plan and its versions in the private planning context. Inspecting the repository and gathering requirements can proceed during planning; implementation waits for the applicable human design approval.

## 2. Obtain human design approval

A human reviews the current plan version, discusses and resolves technical questions with the agent, and explicitly approves that specific version. Record the version identifier and its approval in the private task context so the implementing agent can verify them. An initial assignment, permission to inspect the repository, silence, or another agent's review does not satisfy this gate.

If approval is missing, the agent stops before implementation and presents the current version for review. If implementation reveals a material change to scope or design, stop affected work, create a revised plan version (`v2`, `v3`, etc.), and obtain renewed explicit human approval of that version before continuing. Approval of an earlier version does not carry over. This design review is separate from final PR review.

For an explicitly allowed narrow-change exception, record why the full plan is unnecessary and obtain explicit human authorization for the described change. If the change becomes material, stop affected work and create a versioned plan for human approval.

## 3. Implement on a dedicated PBI branch

Create a dedicated branch from an up-to-date `main` using `pbi-<id>-<short-description>`, with a short, public-safe description. Keep each branch focused on its PBI and preserve unrelated local work. Do not implement directly on `main`.

Follow the approved plan and [repository agent instructions](../AGENTS.md). Keep changes small enough to review, stay within the accepted V1 scope and ADRs, and update relevant documentation when behavior or design changes. Record deviations and follow-up work in the private task context; material deviations return to design review.

## 4. Validate and self-review

Before opening a PR, the agent runs applicable automated tests, linting, builds, and other checks available for the changed components. Validate relevant acceptance criteria and inspect the full diff for correctness, regressions, scope, architecture consistency, and accidental disclosure of private information or secrets.

Report the commands run, their results, and any failures, unavailable tooling, or checks not performed. Resolve findings before handing off, or clearly identify unresolved blockers. Never describe a planned or unrun check as passing.

The repository contains Python acquisition components and offline unit/integration tests, run with `python -m unittest discover -s tests -v`. Install `requirements-transcripts.txt` to include the offline SDK adapter tests; without those optional dependencies, those tests explicitly skip. No CI workflow is currently configured. Documentation changes require checking Markdown/Mermaid rendering where applicable, relative links, consistency with the scope and ADRs, implemented/planned status, and diff whitespace. This process establishes review expectations; it does not itself install CI or configure branch protection.

## 5. Prepare the public pull request

The default delivery is to commit the validated changes, push the dedicated PBI branch, and open a PR using the [PR template](../.github/pull_request_template.md). PR creation initiates independent AI review; it does not complete the implementation workflow. Report the PR as pending independent review until the gate below passes. Honor explicit local-only, no-commit, or no-push instructions: provide the local diff and validation results and stop at that delivery boundary without claiming independent PR review passed.

The public PR description should stand on its own and include:

- Objective, scope, and explicit exclusions where useful.
- A publication-safe PBI reference, if one can be shown without exposing an internal URL, and a public-safe summary of relevant acceptance criteria.
- Implementation approach, confirmation that the separate Requirement Quality Review returned `READY`, and the approved plan version or explicit narrow-change exception. Note renewed approval for a materially revised version where applicable.
- Validation performed, results, and any limitations or blockers.
- Deviations from the approved plan and identified follow-up work, or an explicit statement that there are none.

Summarize criteria rather than copying private Azure DevOps text. If a criterion cannot be disclosed publicly, state that its validation evidence is available to the authorized human reviewer in the private planning context. Do not imply that public summaries replace the authoritative criteria. Avoid internal URLs, detailed private plans, discussion transcripts, and credentials.

## 6. Independent AI PR review

The implementation agent obtains a fresh Codex reviewer/subagent or independently triggered Codex review context after opening the PR. Every cycle uses a new context without inherited implementation conversation, defensive arguments, or implementation self-review conclusions. Native delegation is sufficient; this workflow does not install CI, GitHub Actions, an external orchestrator, or an API integration. These are repository instructions, not an enforced GitHub merge check.

### Reviewer inputs and responsibilities

Supply a neutral review packet, and require the reviewer to read:

- The latest authoritative PBI description and all acceptance criteria, with its revision identified.
- The explicitly human-approved Technical Implementation Plan version and approval evidence. Where the existing narrow-change exception was expressly authorized, include that authorization instead; AI review creates no new exception.
- Repository rules including `AGENTS.md`, relevant scope/architecture decisions, and any applicable local instructions.
- The PR identity, base, exact current HEAD commit SHA, complete PR diff, and relevant existing implementation and tests. Review the whole PR, not only the newest commit or previous findings.

Keep private requirements, plans, and detailed evidence in the authorized private task context. Do not include credentials in the packet or publish private artifacts. Missing authoritative inputs prevent a valid PASS; report the limitation rather than inventing requirements. The PR description and implementation validation claims are not substitutes for independent inspection.

The reviewer checks acceptance-criteria and approved-plan compliance, correctness, architecture boundaries, unintended scope changes, regression risk, test coverage, relevant security and secret handling, repository conventions, maintainability, and obvious defects. It may inspect files/diffs and run useful checks/tests. It must not edit implementation or repository files, commit, push, approve or merge the PR, change product requirements, or approve material architecture deviations. The reviewer role ends with its report; it does not perform remediation or initiate a nested review loop. The implementation agent avoids concurrent edits during review so the checked-out files match the reviewed commit.

### Review result

Require this structured result, with the full reviewed HEAD SHA:

```text
AI PR REVIEW
reviewed_commit: <PR HEAD SHA>
status: PASS | CHANGES_REQUIRED

findings:
- severity: BLOCKER | MAJOR | MINOR
  requirement_or_plan: <affected reference, where applicable>
  location: <file and relevant location>
  issue: <problem>
  evidence: <supporting observation or check>
  required_change: <actionable correction>
```

Use `findings: []` when there are no findings. PASS requires no unresolved BLOCKER or MAJOR findings. Disclose remaining MINOR findings even when the result is PASS. A missing, incomplete, or unbound report cannot establish the gate. The implementation agent cannot turn its own self-review or a disputed major finding into independent PASS.

The full reviewer report is the authoritative review artifact in the private task context. Keep a compact publication-safe summary in the PR's AI-review section: reviewed HEAD, status, cycles used, unresolved findings, and readiness for human review. Update the PR description without creating a repository commit merely to record review status. Do not copy private requirement or plan content into that summary.

## 7. Remediation, limits, and blocked review

On `CHANGES_REQUIRED`, first check for material changes and the remaining cycle budget. If three cycles have already been used, stop automatic remediation and escalate as described below. Otherwise, the implementation agent:

1. Examines each finding against the authoritative requirements and approved plan.
2. Fixes valid findings within approved scope and adds or updates tests where appropriate. Records evidence for any disputed finding; does not silently dismiss unresolved BLOCKER or MAJOR findings.
3. Reruns relevant validation and self-reviews the changes, then commits and pushes fixes to the same PR.
4. Obtains a fresh independent reviewer for the new HEAD. That reviewer reads the complete current PR against the authoritative inputs, not merely the previous findings or corrective diff.

Track at most **three independent AI review cycles per PR** in the private task context. Increment the count when a fresh review is dispatched; a dispatched review whose result becomes stale or unusable still consumes a cycle. Commits, remediation, or a revised plan do not reset the count. Before dispatch, check that the count is below three. If no valid PASS for current HEAD exists after the third cycle, stop automatic remediation and review, report current HEAD and remaining findings/limitations, and escalate to a human. Escalation is not `Ready for Human Review` under a passed gate and does not authorize merge. Never create an unbounded agent-to-agent loop.

If a finding requires a material product-behavior, architecture, scope, or approved-plan change, stop affected work with `PLAN REVISION REQUIRED`. Explain the finding and why the current plan cannot satisfy it; propose the next explicitly versioned plan (`v2`, then `v3`, etc.). Obtain explicit human approval before implementation resumes. Independent AI review cannot bypass Requirement Quality Review, plan-version identification, human design approval, or renewed material-change approval.

If spawning/delegation or an independent Codex context is unavailable, report `INDEPENDENT REVIEW REQUIRED`, the PR, exact current HEAD, and the limitation. Preserve validation and self-review evidence and stop before claiming successful workflow completion. A separately initiated independent review may later satisfy the gate subject to the same inputs, HEAD binding, and remaining cycle budget. Missing required reviewer inputs or an unusable report likewise require an explicit blocked-review handoff, not fabricated PASS.

## 8. Current-HEAD gate and handoff

Record the full PR HEAD before review and re-read it before successful human-review handoff. `reviewed_commit` must equal current PR HEAD. A PASS for commit A does not apply after commit B is pushed, including documentation-only fixes or changes requested during human review. Mark the old summary stale and require a fresh complete review of B within the remaining budget; if the budget is exhausted, stop and escalate. Verify the workspace represents the reviewed commit; dirty or changing files cannot establish current-HEAD PASS.

Only a valid independent PASS for the exact current HEAD establishes **Ready for Human Review**. Stop implementation activity and give the human the PR, HEAD, review-cycle count, result, remaining MINOR findings, validation limitations, and follow-up work. AI PASS is not final PR approval or merge permission.

## 9. Human PR review and merge

A human performs the final PR review, checks the result against the authoritative acceptance criteria and validation evidence, and decides whether to merge. Agent self-review and passing automated checks support this decision; they do not replace it. Agents must not approve their own PRs or merge them.

Address review feedback and rerun checks affected by subsequent changes. Any new commit invalidates previous AI PASS and returns to the current-HEAD gate within the same three-cycle budget. Return material scope or design changes to the earlier approval gate. Humans retain control over merge and work-item completion; agents update Azure DevOps only when explicitly authorized.
