<!-- Use only information approved for public GitHub. Keep private plans, work-item
text, sensitive evidence, internal URLs, and credentials in the private task context. -->

## Objective and scope

<!-- Explain the problem, resulting behavior, included changes, and exclusions. -->

<!-- GitHub may expand AB# references into private Azure DevOps URLs. Include a PBI
reference only if its rendered form is publication-safe; otherwise provide it
privately to the authorized reviewer. -->

PBI reference: <!-- public-safe reference, or "available privately" -->

## Relevant acceptance criteria

<!-- Summarize public-safe criteria and map each to validation evidence. Do not copy
private Azure DevOps text. For confidential criteria, state that evidence is available
to the authorized human reviewer in the private planning context. -->

| Public-safe criterion | Validation evidence and result |
| --- | --- |
| <!-- Criterion or private-evidence note --> | <!-- Check and outcome --> |

## Requirement review and design approval

<!-- Confirm the separate Requirement Quality Review returned READY before Technical
Planning, even if a narrow mechanical change skipped the full plan. Explain the
public-safe approach and key tradeoffs. For a required plan, identify its explicit
version (v1, v2, etc.) and confirm that a human approved that version before
implementation. Identify any materially revised version and renewed approval.
If a full plan was explicitly unnecessary, explain the narrow-change exception.
Do not paste the private review or implementation plan. -->

- [ ] Requirement Quality Review returned `READY` before Technical Planning.
- Approved Technical Implementation Plan version, or explicit narrow-change exception: <!-- vN / exception -->
- Material plan revisions and renewed approval, if applicable: <!-- vN or None -->

## Validation and self-review

<!-- List actual commands or checks and outcomes, including applicable automated
tests. Report failures, unavailable checks, and remaining blockers explicitly. -->

- [ ] Applicable validation completed; results and limitations documented.
- [ ] Full diff self-reviewed against scope, acceptance criteria, and architecture.
- [ ] Public content checked for private planning details and secrets.

## Deviations

<!-- State deviations from the approved plan and their human approval where needed,
or explicitly state None. Material changes require renewed design approval. -->

## Follow-up work

<!-- List remaining work and public-safe references, or explicitly state None. -->

## Independent AI PR review

<!-- PR creation and implementation self-review do not satisfy this gate. Keep the
full reviewer report in the authorized private task context; summarize only public-safe
status here. Update this section without adding a repository commit for review status.
A new commit invalidates previous PASS, including changes during human review.
Use a fresh independent context and the complete current PR for each cycle.
Stop automatic review/remediation after at most three cycles; never reset on commits.
Unavailable independent review: INDEPENDENT REVIEW REQUIRED. Material changes:
PLAN REVISION REQUIRED and renewed human approval. Neither is a passed gate. -->

- Reviewed PR HEAD SHA: <!-- full SHA, or Pending -->
- Review status: <!-- Pending / PASS / CHANGES_REQUIRED / Stale / INDEPENDENT REVIEW REQUIRED / PLAN REVISION REQUIRED / Escalated -->
- Review cycles used: <!-- 0–3; maximum 3 per PR -->
- Unresolved findings: <!-- public-safe summary, including MINOR findings; or None -->
- Ready for Human Review: <!-- Yes only with independent PASS for current HEAD; otherwise No -->

## Human review and merge

- [ ] Final review by a human completed, including private acceptance criteria where applicable.

<!-- Leave the final review checkbox unchecked for the human reviewer. Independent
AI PASS must precede human-review handoff and never replaces human review or manual
human merge. Agent self-review and passing checks do not authorize approval or merge. -->
