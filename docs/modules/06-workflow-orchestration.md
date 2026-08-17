# Module 6 — Workflow Orchestration

**Stories:** 6 MVP stories

**Owns:** LangGraph shared state, node sequencing, conditional edges, workflow statuses, retry rules, approval extension seam, and agent-step persistence coordination.

**Depends on:** Foundation and Data, Intent, Retrieval, Planning and Policy, Mock Execution.
**Used by:** API and Client Interface, Result Analysis.

## Purpose

Coordinate a long-running, stateful workflow without turning an individual agent into an implicit controller. The graph makes the happy path and all significant failure routes visible and testable.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| ORC-1 | Define typed shared state and allowed workflow statuses. | Every node accepts and returns a validated subset of the shared state. |
| ORC-2 | Build the happy-path graph. | Intent → retrieval → plan → policy → execution → results → analysis completes with persisted state. |
| ORC-3 | Add clarification, retrieval-failure, policy-rejection, and execution-failure routes. | Each route ends in a defined terminal status with a user-readable reason. |
| ORC-4 | Add retry and idempotency-aware integration handling. | Retrying a transient submission uses the original idempotency key and never duplicates a job. |
| ORC-5 | Persist agent transitions and reconstruct an API-ready timeline. | Every meaningful node start/completion/failure appears in workflow inspection. |
| ORC-6 | Define dry-run and future approval-gate conditional edges. | Dry run stops before execution; approval is a documented, isolated future branch. |

## Graph rules

- Nodes return data, errors, and a route signal; they do not make hidden cross-module calls.
- State progression is monotonic: a terminal outcome cannot become a running workflow through a routine retry.
- Persist workflow status before and after material external boundaries.
- LLM analysis failure routes to fallback summary, not execution failure.

## Status vocabulary

`RECEIVED`, `NEEDS_CLARIFICATION`, `INTENT_PARSED`, `EVIDENCE_RETRIEVED`, `PLAN_CREATED`, `REJECTED`, `DRY_RUN_COMPLETE`, `EXECUTION_QUEUED`, `EXECUTION_RUNNING`, `RESULTS_COLLECTED`, `FALLBACK_SUMMARY`, `COMPLETED`, `RETRIEVAL_FAILED`, `EXECUTION_FAILED`, and optional `WAITING_FOR_APPROVAL`.

See the full transition diagram in [Workflow Lifecycle](../workflow.md).

## Boundaries

The graph determines **when** a component runs and **where** its result goes. It does not reimplement catalog filtering, policy rules, vector queries, CI behavior, or prompt logic.

## Tests

Use fakes for every dependency to verify the happy path, all conditional terminal paths, event ordering, no execution on dry run/rejection, and fallback analysis handling.
