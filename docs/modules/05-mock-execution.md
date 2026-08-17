# Module 5 — Mock Execution

**Stories:** 5 MVP stories

**Owns:** mock Jenkins job API, lifecycle, deterministic result simulation, idempotent submission, result normalization, and cancellation.

**Depends on:** Foundation and Data, Planning and Policy.
**Used by:** Workflow Orchestration, Result Analysis, API.

## Purpose

Demonstrate integration with a CI-like external system without real browser automation or Jenkins infrastructure. The module accepts only policy-validated plans.

## Target interface

```text
POST /jobs
GET  /jobs/{job_id}
POST /jobs/{job_id}/cancel
```

Lifecycle: `QUEUED → RUNNING → COMPLETED`, with `FAILED` and `CANCELLED` terminal outcomes.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| EXE-1 | Implement job submission and job-status contract. | A validated request returns a stable `JOB-*` ID and queued status. |
| EXE-2 | Model legal lifecycle transitions. | Invalid status jumps are rejected and terminal jobs cannot restart accidentally. |
| EXE-3 | Generate seeded/deterministic per-test outcomes. | Repeating the same seed and request yields reproducible pass/fail and duration data. |
| EXE-4 | Add idempotent execution mapping and persistence. | A duplicate submission key returns the original job rather than creating another job. |
| EXE-5 | Normalize results and support cancellation/error paths. | Per-test results persist with a defined cancelled/failed job outcome. |

## Rules

- The execution adapter validates the policy-approved plan before sending it.
- Store workflow ID, external job ID, request hash/idempotency key, timestamps, and integration errors.
- No mock result may add or remove an unrequested test ID.
- Polling or callback collection must tolerate an external failure without deleting existing workflow state.

## Boundaries

This module does not select tests, determine policy, prompt an LLM, or make a workflow-terminal decision beyond the job status it owns.

## Tests

Cover valid lifecycle, invalid transitions, deterministic simulation, duplicate submissions, cancellation, a forced CI failure, and result persistence.
