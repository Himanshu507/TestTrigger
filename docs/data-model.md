# Data Model

## Domain contracts

Pydantic models define the boundary contracts between API, agents, services, persistence, and integrations. These models use controlled values for module, scope, browser, region, criticality, and status.

| Model | Purpose | Key fields |
| --- | --- | --- |
| `TestIntent` | Validated interpretation of a user request | module, scope, browser, region, environment, confidence, missing fields |
| `TestCase` | Source-of-truth executable test metadata | ID, module, scope, browsers, regions, criticality, description |
| `RetrievedEvidence` | Attributable retrieval result | source ID, type, content excerpt, score, metadata |
| `PlanItem` | One selected test and why it was selected | test ID, priority, risk score, reasons |
| `ExecutionPlan` | Validated executable test set | intent context, plan items, policy result |
| `ExecutionResult` | One simulated test outcome | test ID, status, duration, failure reason |
| `AnalysisReport` | Grounded result explanation | summary, observations, inferences, evidence, recommendations |

## Test catalog

The versioned catalog is the only allowed origin of executable test IDs.

```json
{
  "id": "PAY-001",
  "name": "Card Authorization",
  "module": "payment",
  "scope": "smoke",
  "browsers": ["chrome", "firefox"],
  "regions": ["US", "EU"],
  "criticality": "high",
  "description": "Validates card authorization flow"
}
```

Catalog requirements: unique IDs, normalized module/browser values, controlled regions and scopes, and independently loaded data rather than prompt-derived records.

## Evidence records

The knowledge base has four separately identifiable document classes:

| Type | Example | Minimum metadata |
| --- | --- | --- |
| Test documentation | What `PAY-003` validates | test ID, module, scope |
| Historical failure | Chrome 3DS timeout on a date | test ID, browser, region, date |
| Jurisdiction rule | Extra validation for US-Nevada | region/jurisdiction, applicability |
| Catalog-derived context | Compatibility details | test ID, browser, region |

ChromaDB stores embeddings and document metadata. SQLite stores references to selected source IDs in agent-run payloads or workflow events; it need not duplicate vector content.

## SQLite persistence

| Table | Responsibility | Key fields |
| --- | --- | --- |
| `workflows` | Lifecycle root and original request | id, query, status, dry_run, timestamps |
| `agent_runs` | Audit individual agent/service invocations | workflow ID, name, status, input/output payloads, timing, error |
| `test_plans` | Record selected tests and rationale | workflow ID, test ID, priority, risk score, reason |
| `executions` | Map a workflow to an external job | workflow ID, external job ID, idempotency key, status, timing |
| `test_results` | Persist normalized per-test outcomes | execution ID, test ID, status, duration, failure reason |
| `analysis_reports` | Persist factual and AI/fallback conclusion | workflow ID, summary, analysis payload, timestamp |
| `workflow_events` | API-ready timeline of meaningful transitions | workflow ID, step, status, metadata, timestamp |

## Integrity constraints

- `workflow_id` references an existing workflow in every dependent table.
- `external_job_id` and idempotency keys are unique where appropriate.
- `test_plans.test_id` must resolve to a current catalog record when written.
- Status fields use controlled enumerations.
- JSON payloads are validated before persistence and redacted of secrets.
- Timestamps use UTC and are assigned by the application, not an LLM.

## Retention and privacy

The demo uses synthetic test metadata and results. A production design must define retention, encryption, access control, audit access, and tenant boundaries before ingesting customer test artefacts or production incident information.

## Local web and OpenAI configuration

The web chat client holds only presentation state and the local backend origin. It does not persist an OpenAI key or call OpenAI directly. The backend reads `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_EMBEDDING_MODEL` from environment configuration; those values are not database records, event payloads, or API response fields. Docker Compose injects the key into the backend service at runtime rather than storing it in an image.
