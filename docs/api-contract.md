# API Contract

This is the target public HTTP contract for the initial FastAPI implementation. The local Test Trigger chat UI consumes this API; CLI and direct HTTP clients remain supported. All responses use JSON and include a workflow or request identifier where relevant.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/workflows` | Start a workflow or a dry run. |
| `GET` | `/api/v1/workflows/{workflow_id}` | Inspect the complete workflow snapshot. |
| `GET` | `/api/v1/workflows/{workflow_id}/events` | Read an ordered timeline of workflow and agent events. |
| `POST` | `/api/v1/workflows/{workflow_id}/cancel` | Request cancellation of an active external job. |
| `POST` | `/api/v1/workflows/{workflow_id}/approve` | Optional future approval-gate action. |
| `POST` | `/api/v1/code-review` | Optional code-analysis extension. |
| `GET` | `/health` | Report service and dependency readiness. |

## Create workflow

```http
POST /api/v1/workflows
Idempotency-Key: client-generated-key
Content-Type: application/json
```

```json
{
  "query": "Run smoke tests for the payment module on Chrome in the US region",
  "dry_run": false
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `query` | Yes | Non-empty natural-language testing request. |
| `dry_run` | No | Defaults to `false`; when true, no CI job starts. |
| `Idempotency-Key` header | Recommended | A stable client-generated value for safe request retries. |

The initial MVP may execute synchronously for a small mock job, but the workflow record is created immediately and must always be retrievable. A production version should acknowledge quickly and execute asynchronously.

The browser client submits only workflow input. It never supplies or receives `OPENAI_API_KEY`; model and embedding calls stay inside the backend.

```json
{
  "workflow_id": "WF-1001",
  "status": "completed",
  "summary": "Executed 4 payment smoke tests. 3 passed and 1 failed.",
  "execution_id": "JOB-2001"
}
```

## Get workflow detail

```http
GET /api/v1/workflows/WF-1001
```

```json
{
  "workflow_id": "WF-1001",
  "query": "Run smoke tests for the payment module on Chrome in the US region",
  "status": "completed",
  "intent": {
    "module": "payment",
    "scope": "smoke",
    "browser": "chrome",
    "region": "US",
    "environment": null,
    "confidence": 0.96,
    "missing_fields": []
  },
  "retrieval": {
    "sources": ["test-doc:PAY-003", "history:PAY-003:2026-07-30"]
  },
  "plan": {
    "tests": [{"test_id": "PAY-003", "priority": 1, "reasons": ["Matches module and scope"]}]
  },
  "execution": {"execution_id": "JOB-2001", "status": "COMPLETED"},
  "analysis": {"summary": "1 of 4 tests failed."},
  "timeline": []
}
```

The response must expose inspectable decisions without exposing secrets, provider credentials, or unbounded prompt context.

## Event timeline

Each event provides a time-ordered, lightweight activity record:

```json
{
  "workflow_id": "WF-1001",
  "events": [
    {
      "event_id": "EV-001",
      "step": "retrieval",
      "status": "completed",
      "occurred_at": "2026-08-17T10:15:20Z",
      "metadata": {"source_count": 4}
    }
  ]
}
```

## Error model

All expected domain errors use one shape:

```json
{
  "error": {
    "code": "UNSUPPORTED_BROWSER",
    "message": "Safari is not supported for PAY-003 in this environment.",
    "workflow_id": "WF-1001",
    "details": [{"field": "browser", "value": "safari"}]
  }
}
```

| HTTP status | Example code | Meaning |
| --- | --- | --- |
| `400` | `MALFORMED_REQUEST` | Request cannot be parsed or violates basic input validation. |
| `404` | `WORKFLOW_NOT_FOUND` | The requested workflow does not exist. |
| `409` | `DUPLICATE_REQUEST` | Idempotency conflict or incompatible active transition. |
| `422` | `NEEDS_CLARIFICATION`, `UNSUPPORTED_BROWSER` | The request is well-formed but cannot safely produce an executable plan. |
| `424` / `503` | `RETRIEVAL_UNAVAILABLE`, `EXECUTION_UNAVAILABLE` | A required dependency cannot complete the request. |
| `500` | `INTERNAL_ERROR` | Unexpected failure; the workflow ID remains available when created. |

## Health endpoint

`GET /health` distinguishes liveness from dependency readiness. It should return dependency states for SQLite, ChromaDB, and mock Jenkins, but must never leak connection strings or credentials.

## Compatibility policy

Routes are versioned under `/api/v1`. New optional response fields are backward-compatible; breaking request or response changes require a new API version.
