# Module 11 — Quality and Operations

**Stories:** 6 MVP stories

**Owns:** structured logs, trace/correlation conventions, test suites, AI/retrieval evaluation samples, local reproducibility, and safe configuration guidance.

**Depends on:** all other MVP modules.
**Used by:** developers, reviewers, and future operators.

## Purpose

Make the system credible, inspectable, and easy to run. Quality work is not a final afterthought: it verifies that deterministic controls and AI-dependent behavior both behave as designed.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| QLT-1 | Add structured workflow and agent logging. | Each material step logs workflow ID, component, status, timing, and safe error context. |
| QLT-2 | Build unit tests for models, catalog, policy, scoring, repositories, and normalizers. | Core deterministic logic has fast isolated coverage. |
| QLT-3 | Build integration tests for retrieval/planning and execution/persistence. | Real local dependencies or controlled test doubles verify boundary contracts. |
| QLT-4 | Add one end-to-end happy path and negative paths. | The project proves success, unsupported browser, empty plan, CI failure, and LLM fallback. |
| QLT-5 | Add a small intent/retrieval/analysis evaluation set. | Results document intent accuracy, filter correctness, Hit@K/Recall@K, and grounded-analysis review. |
| QLT-6 | Provide reproducible local developer workflow and secret hygiene checks. | Fresh setup, seed/ingest, test, and demo instructions run without committed credentials. |

## Operational telemetry

Log or persist these fields where applicable:

- `workflow_id`, `agent_name`, `step_name`, status, start/end time, and error code.
- Retrieval query abstraction, metadata filters, top-K, source IDs, and scores.
- LLM model identifier, prompt version, latency, and success/failure—never API keys or sensitive raw credentials.
- Mock execution ID, idempotency key hash, status transitions, and result counts.

## Evaluation scope

The demo evaluation is intentionally small and manually reviewable. It should show whether intent fields parse correctly, metadata filtering blocks incompatible evidence, relevant documentation is retrieved within `K`, and analysis separates facts from assumptions. It is evidence of engineering judgment, not a claim of statistically complete model validation.

## Boundaries

This module adds observability and verification around owned behaviour. It does not change production policy, reinterpret analysis, or make tests dependent on a live paid LLM.

## Exit criteria

The project can be cloned, configured from `.env.example`, seeded, ingested, run locally with Docker Compose, tested, and demonstrated with the scenarios documented in the root README. Test failures identify the module and workflow stage involved.
