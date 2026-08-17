# Module 1 — Foundation and Data

**Stories:** 6 MVP stories

**Owns:** shared domain contracts, catalog loading, local configuration, SQLite schema, repositories, and seed data.

**Depends on:** none.
**Used by:** every other MVP module.

## Purpose

This module gives the rest of the application trusted data and durable records. It establishes the boundary that free-form LLM output is never itself a source of truth.

## Public interfaces

- Pydantic models: `TestIntent`, `TestCase`, `ExecutionPlan`, `ExecutionResult`, `AnalysisReport`, and workflow status models.
- Catalog repository: read normalized tests by ID and filter candidates by module/scope/browser/region.
- Workflow repositories: create/update workflows, record agent runs, plans, executions, results, reports, and events.
- Settings object: loads safe local configuration from environment and defaults.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| FND-1 | Define controlled domain models and enums. | Invalid scopes, statuses, or malformed payloads fail validation with useful field errors. |
| FND-2 | Load a versioned test catalog. | Duplicate IDs and non-normalized controlled values are rejected during load. |
| FND-3 | Create SQLite schema and migration/bootstrap path. | A clean local database has all documented tables and foreign-key integrity enabled. |
| FND-4 | Implement repositories for workflow, agent-run, plan, execution, result, report, and event records. | Each repository operation can be unit-tested without route or agent imports. |
| FND-5 | Add deterministic seed data. | The catalog contains 10–15 tests plus representative history/rule fixtures for demo scenarios. |
| FND-6 | Add typed settings and environment validation. | Missing optional LLM configuration disables AI calls safely; secrets never appear in logs. |

## Boundaries

This module does not parse natural language, query ChromaDB, decide policy, or submit jobs. It only provides contracts and reliable access to data other modules own.

## Implementation notes

- Keep persistence payloads JSON-compatible and Pydantic-validated.
- Normalize values at ingestion boundaries (`Google Chrome` becomes `chrome` only via approved normalization logic).
- Store timestamps in UTC.
- Make catalog/seed location configurable for tests, but do not make the production catalog prompt-controlled.

## Tests

Unit tests cover enum validation, catalog uniqueness, repository CRUD, foreign-key behavior, settings defaults, and seed-data completeness.
