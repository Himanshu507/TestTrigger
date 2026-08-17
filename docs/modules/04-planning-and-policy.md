# Module 4 — Planning and Policy

**Stories:** 6 MVP stories

**Owns:** candidate selection, compatibility checks, policy enforcement, explainable ordering, risk scoring, and dry-run policy output.

**Depends on:** Foundation and Data, Knowledge Base and Retrieval, Intent Understanding.
**Used by:** Execution, Workflow Orchestration, API.

## Purpose

Convert validated intent and retrieved evidence into an explainable plan containing only catalogued tests, then decide deterministically whether it may execute.

## Public interfaces

- `plan(intent, evidence) -> CandidateExecutionPlan`
- `validate(plan, intent) -> PolicyResult`
- `risk_score(test, evidence) -> ExplainableScore`

`CandidateExecutionPlan` is not executable until `PolicyResult.allowed` is true.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| PLN-1 | Select candidates from the catalog using exact module and scope constraints. | The planner cannot return an ID absent from the catalog. |
| PLN-2 | Enforce browser and region compatibility during selection. | Incompatible tests are excluded with a recorded reason. |
| PLN-3 | Implement deterministic policy checks. | Unknown IDs, empty plans, invalid scope, browser/region conflicts, and jurisdiction violations reject execution. |
| PLN-4 | Add explainable ordering and risk score. | Each selected test records ordered priority, factors, score, and human-readable selection reasons. |
| PLN-5 | Produce structured violations and rejected-plan summaries. | API and workflow can show every policy failure without parsing prose. |
| PLN-6 | Support dry-run plan validation. | A successful dry run returns plan/evidence/policy output and creates no execution request. |

## Planning inputs

- Validated `TestIntent`.
- Catalog records and controlled compatibility values.
- Bounded retrieval evidence: history, test documentation, and jurisdiction context.
- Versioned deterministic policy rules.

## Risk-score policy

The MVP score is a documented weighted combination of criticality, recent/frequent historical failures, and browser/region-specific history. It is a prioritization aid, not a policy bypass. Store both the calculated value and contributing factors.

## Boundaries

The planner never sends a CI job. The policy service never relies on free-form LLM output. An analyzer can explain why a test failed but cannot retroactively make an invalid plan valid.

## Tests

Cover known and unknown tests, compatibility matrices, no-match requests, jurisdiction rules, stable priority ordering, score explanation, and dry-run no-execution behavior.
