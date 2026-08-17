# API Examples

Copyable requests for every documented scenario. The contract itself lives in
[api-contract.md](api-contract.md); this page is the runnable version of it.

## Run with Docker (one command)

```bash
cp .env.example .env      # set OPENAI_API_KEY
docker compose up --build
```

| Address | What |
| --- | --- |
| http://localhost:5173 | Chat UI (frontend container) |
| http://localhost:8000 | API (backend container) |
| http://localhost:8000/docs | Interactive OpenAPI |

Both services bind to `127.0.0.1` only. The backend initializes SQLite and
ingests the knowledge base on first start, then skips ingestion on later
starts. Demo state lives on the `test-trigger-data` volume and survives a
restart.

Reset everything, including the volume:

```bash
docker compose down -v
```

## Run from source instead

```bash
uv sync --extra dev
uv run python scripts/ingest_knowledge_base.py     # needs OPENAI_API_KEY
uv run uvicorn app.api.main:build --factory --reload
```

Interactive OpenAPI documentation is served at `http://localhost:8000/docs`, and
the raw schema at `http://localhost:8000/openapi.json`.

Without `OPENAI_API_KEY` the service still starts. Intent parsing then reports a
provider error and analysis uses the deterministic fallback, so the deterministic
core stays inspectable.

## Scenarios

### 1. A request that executes

```bash
curl -s -X POST http://localhost:8000/api/v1/workflows \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-1' \
  -d '{"query": "Run smoke tests for the payment module on Chrome in the US region"}'
```

```json
{
  "workflow_id": "WF-1001",
  "status": "completed",
  "summary": "1 of 2 test(s) failed.",
  "execution_id": "JOB-2001"
}
```

CLI equivalent:

```bash
uv run python scripts/client.py run "Run smoke tests for the payment module on Chrome in the US region"
```

### 2. A dry run

Plans and validates without creating a job.

```bash
curl -s -X POST http://localhost:8000/api/v1/workflows \
  -H 'Content-Type: application/json' \
  -d '{"query": "Run payment smoke tests on Chrome in US", "dry_run": true}'
```

Returns `"status": "dry_run_complete"` and a null `execution_id`.

### 3. An incomplete request → 422

```bash
curl -s -X POST http://localhost:8000/api/v1/workflows \
  -H 'Content-Type: application/json' \
  -d '{"query": "Run some tests"}'
```

```json
{
  "error": {
    "code": "NEEDS_CLARIFICATION",
    "message": "the request did not state: browser, region",
    "workflow_id": "WF-1002",
    "details": [{"field": "browser", "value": null}, {"field": "region", "value": null}]
  }
}
```

The workflow ID is returned even though the request failed, so the run stays
retrievable with `GET /api/v1/workflows/WF-1002`.

### 4. A request policy rejects → 422

```bash
curl -s -X POST http://localhost:8000/api/v1/workflows \
  -H 'Content-Type: application/json' \
  -d '{"query": "Run withdrawal smoke tests on Safari in US-Nevada"}'
```

Returns a violation code such as `JURISDICTION_VIOLATION` or
`NO_TESTS_SELECTED`, with one `details` entry per violation.

### 5. Inspect a workflow

```bash
curl -s http://localhost:8000/api/v1/workflows/WF-1001
```

Returns intent, retrieval source IDs, the plan with selection reasons,
execution results, the analysis report, and the timeline. Retrieved document
text is never republished — only the source IDs that were cited.

### 6. Read the timeline

```bash
curl -s http://localhost:8000/api/v1/workflows/WF-1001/events
```

### 7. Cancel an active job

```bash
curl -s -X POST http://localhost:8000/api/v1/workflows/WF-1001/cancel
```

A job that already finished returns `409 NOT_CANCELLABLE`.

### 8. Health and readiness

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "ready",
  "dependencies": [
    {"name": "sqlite", "ready": true, "detail": null},
    {"name": "chromadb", "ready": true, "detail": null},
    {"name": "mock_jenkins", "ready": true, "detail": null}
  ]
}
```

Returns `503` with `"status": "degraded"` when a dependency is unreachable.
Failure detail is a category, never a connection string.

## Idempotency

Send `Idempotency-Key` to make a retry safe:

- same key, same request → `200` replaying the original workflow
- same key, different request → `409 DUPLICATE_REQUEST`
- no key → every call starts a new workflow

## Error codes

| HTTP | Code | Meaning |
| --- | --- | --- |
| 400 | `MALFORMED_REQUEST` | Input failed validation. |
| 404 | `WORKFLOW_NOT_FOUND` | No such workflow. |
| 409 | `DUPLICATE_REQUEST`, `NOT_CANCELLABLE` | Idempotency conflict, or the job is not cancellable. |
| 422 | `NEEDS_CLARIFICATION`, policy violation codes | Well-formed, but no executable plan can be produced. |
| 424 | `RETRIEVAL_UNAVAILABLE` | Evidence could not be retrieved. |
| 503 | `EXECUTION_UNAVAILABLE` | The execution system failed. |
| 500 | `INTERNAL_ERROR` | Unexpected failure; the message stays generic by design. |
