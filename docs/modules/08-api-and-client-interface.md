# Module 8 — API and Client Interface

**Stories:** 5 MVP stories

**Owns:** FastAPI routes, request and response adapters, HTTP error mapping, workflow inspection, health/readiness output, and CLI/example-client contracts.

**Depends on:** Foundation and Data, Workflow Orchestration, Result Analysis.
**Used by:** the local web chat interface, human users, reviewers, and future clients.

## Purpose

Expose the orchestrated product through a minimal, stable HTTP interface. Routes adapt transport concerns to domain services; they must not contain workflow business logic.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| API-1 | Implement workflow creation with input validation and idempotency header handling. | Valid requests create/reuse a workflow; malformed requests return the documented error shape. |
| API-2 | Implement detailed workflow inspection. | `GET /workflows/{id}` returns intent, evidence summary, plan, execution, analysis, and timeline where available. |
| API-3 | Implement workflow events and active-job cancellation. | Events are ordered; cancellation is only attempted for a cancellable execution. |
| API-4 | Implement health/readiness and structured HTTP error mapping. | Dependency readiness is observable without exposing secrets or internal stack traces. |
| API-5 | Provide CLI, copyable HTTP, and OpenAPI examples. | A new engineer or the local chat UI can submit each documented demo scenario without writing custom backend code. |

## Route contracts

The canonical route definitions, payloads, status codes, and error envelope live in [API Contract](../api-contract.md). Keep OpenAPI descriptions synchronized with it.

## Interface rules

- Generate IDs in the application/domain layer, not from a client-provided path or LLM.
- Return correlation/workflow IDs for processable requests even if a later dependency fails.
- Avoid exposing raw provider prompts, OpenAI API keys, stack traces, or unrestricted retrieval contents.
- Version all externally used paths under `/api/v1`.
- Default unknown errors to safe generic messages while logging diagnostic context internally.

## Boundaries

Routes authenticate/validate/map; orchestration runs the workflow; repositories persist; services decide. A route does not filter the catalog, create Chroma queries, or write prompts.

## Tests

Use FastAPI test clients for validation, errors, idempotent replay, detail/not-found responses, event ordering, cancellation states, health readiness, and example-payload compatibility.
