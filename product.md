# Test Trigger

## Product Specification

**Project Type:** Take-Home Assignment / Mini Production-Style AI System

**Primary Goal:** Build a mini version of an AI-powered test orchestration platform inspired by Test Trigger.

**Audience:** Engineering interviewer / reviewer, developers, future maintainers.
**Primary Stack:** Python, FastAPI, LangGraph, ChromaDB, SQLite, OpenAI API for LLM and embeddings, local web chat UI, Docker Compose.

---

# 1. Product Vision

The product converts a user's natural-language testing request into a validated, explainable and executable test workflow.

Example request:

> Run smoke tests for the payment module on Chrome in the US region.

The system should not simply pass this sentence to an LLM and ask it to generate an answer. It should follow a controlled workflow:

```text
Natural Language Request
        |
        v
Intent Understanding
        |
        v
Evidence Retrieval (RAG)
        |
        v
Test Planning + Policy Validation
        |
        v
Execution Planning
        |
        v
Mock Jenkins Execution
        |
        v
Result Collection
        |
        v
AI Failure Analysis
        |
        v
Human-Readable Report
```

The core design principle is:

> **Use LLMs for semantic understanding and reasoning, RAG for evidence, deterministic code for guarantees and business rules, LangGraph for orchestration, and the database for durable state.**

---

# 2. Problem We Are Solving

Traditional test execution requires users to know:

- exact test suite names;
- supported browsers;
- regions/environments;
- test IDs;
- historical failure patterns;
- execution APIs or Jenkins jobs.

The product creates a natural-language interface over those systems.

Instead of:

```text
Select suite = PAYMENT_SMOKE
Browser = Chrome
Region = US
Environment = staging
Click Run
```

a user can say:

```text
Run payment smoke tests on Chrome in the US region.
```

The system translates that request into structured intent, finds the correct tests and supporting evidence, validates policies, triggers execution and explains the results.

---

# 3. Product Goals

## 3.1 Must-Have Goals

1. Accept natural-language test requests.
2. Extract structured intent from those requests.
3. Retrieve relevant test metadata, historical failures and jurisdiction rules.
4. Select or plan an executable test set.
5. Validate the planned execution using deterministic rules.
6. Trigger a mock Jenkins-like execution service.
7. Track execution state and individual test results.
8. Analyze failures using an LLM grounded in retrieved evidence.
9. Persist workflow and agent execution state.
10. Expose the complete workflow through a FastAPI API, local web chat UI, and a simple CLI or example client.
11. Run the frontend and backend together locally with Docker Compose.

## 3.2 Quality Goals

The implementation should be:

- modular;
- testable;
- observable;
- explainable;
- deterministic where possible;
- resilient to LLM or external-service failure;
- easy for a new engineer to run locally.

## 3.3 Non-Goals

The take-home version will not implement:

- real browser automation;
- real Jenkins infrastructure;
- Kubernetes deployment;
- distributed worker infrastructure;
- production-grade authentication/authorization;
- enterprise-scale vector search;
- real customer data;
- public hosting or deployment;
- a complex frontend beyond the focused local chat interface;

Those can be discussed as production extensions rather than implemented in the 72-hour submission.

---

# 4. Core Product Principles

These are non-negotiable engineering rules for the project.

## Rule 1 — Do not make the LLM responsible for deterministic decisions

The LLM may interpret and reason, but code must own things such as:

- whether a browser is supported;
- whether a region is valid;
- whether a test exists;
- whether a test belongs to a requested scope;
- whether an execution is allowed by a known rule;
- whether a retry is permitted by policy.

## Rule 2 — Retrieval must happen before LLM decision-making that depends on external evidence

The Retrieval Agent must fetch relevant evidence before planning or AI analysis that relies on that evidence.

## Rule 3 — Never let the LLM invent test IDs

Tests must come from a known catalog. The system may ask an LLM to reason about relevance, but executable test IDs must be validated against the catalog.

## Rule 4 — Every important decision must be explainable

For each selected test, the system should be able to answer:

> Why was this test selected?

Possible reasons include:

- module match;
- scope match;
- browser compatibility;
- region compatibility;
- business-rule requirement;
- historical failure risk;
- criticality.

## Rule 5 — Persist workflow state

Do not keep the entire workflow only in memory. The system should persist enough state to inspect and audit a run later.

## Rule 6 — Agents must have clear responsibilities

An agent should not silently perform another agent's job.

## Rule 7 — Prefer simple components

Do not add technology just to make the architecture look complex. Every component should have a clear reason to exist.

## Rule 8 — Build a working deterministic core before adding LLM complexity

The system should still be understandable and partially useful when the LLM is unavailable.

---

# 5. Target User Experience

## 5.1 Primary Request

```text
POST /api/v1/workflows
```

Request:

```json
{
  "query": "Run smoke tests for the payment module on Chrome in the US region"
}
```

Response:

```json
{
  "workflow_id": "WF-1001",
  "status": "completed",
  "summary": "Executed 4 payment smoke tests. 3 passed and 1 failed.",
  "execution_id": "JOB-2001"
}
```

## 5.2 Detailed Workflow Response

The API should also be able to expose:

```text
GET /api/v1/workflows/{workflow_id}
```

Expected response structure:

```json
{
  "workflow_id": "WF-1001",
  "query": "Run smoke tests for the payment module on Chrome in the US region",
  "intent": {},
  "retrieval": {},
  "plan": {},
  "execution": {},
  "analysis": {},
  "timeline": []
}
```

This allows the reviewer to inspect not only the final answer but also how the system reached it.

## 5.3 Local Web Chat Experience

The project includes a small local-only webpage for the interview demonstration. The page is a chat interface, not a full test-management dashboard.

The user enters a natural-language request, such as:

```text
Run smoke tests for the payment module on Chrome in the US region.
```

The chat UI sends that request to the FastAPI backend and renders the workflow response as assistant messages/cards: extracted intent, selected tests, policy status, execution status, failure analysis, and expandable evidence/timeline details. It supports dry-run, clarification, rejection, and service-error states.

The chat UI runs locally only. It does not call OpenAI, ChromaDB, or Jenkins directly, and it must never receive an OpenAI API key.

---

# 6. High-Level Architecture

```text
                         +------------------+
                         |  Local Browser   |
                         | Test Trigger Chat|
                         +--------+---------+
                                  |
                                  v
                         +------------------+
                         |     FastAPI      |
                         +--------+---------+
                                  |
                                  v
                         +------------------+
                         |    LangGraph     |
                         | Workflow Engine  |
                         +--------+---------+
                                  |
             +--------------------+----------------------+
             |                    |                      |
             v                    v                      v
      +-------------+     +--------------+      +---------------+
      | Intent      |     | Retrieval    |      | Execution      |
      | Agent       |     | Agent        |      | Agent          |
      +------+------+     +------+-------+      +-------+--------+
             |                   |                      |
             v                   v                      v
      Structured Intent    ChromaDB + KB        Mock Jenkins API
                                  |
                                  v
                         +------------------+
                         | Test Planner /   |
                         | Policy Service   |
                         +--------+---------+
                                  |
                                  v
                         +------------------+
                         | Result Analyzer  |
                         | LLM + Evidence   |
                         +--------+---------+
                                  |
                                  v
                         +------------------+
                         | SQLite           |
                         | Workflow State   |
                         +------------------+
```

The diagram is logically simplified. The browser chat UI and Python backend run together locally through Docker Compose, while keeping separate frontend and backend boundaries. The implementation may run the backend in a single Python process while preserving module boundaries that a production service architecture would require.

---

# 7. Core Workflow

## Step 1 — Receive Natural Language

Example:

```text
Run smoke tests for the payment module on Chrome in the US region.
```

The API creates a `workflow_id` and records the original request.

## Step 2 — Intent Agent

The Intent Agent converts the request into structured data.

Example:

```json
{
  "module": "payment",
  "scope": "smoke",
  "browser": "chrome",
  "region": "US",
  "environment": null,
  "confidence": 0.96,
  "missing_fields": []
}
```

## Step 3 — Retrieval Agent

The Retrieval Agent uses the normalized intent to retrieve:

1. test metadata;
2. historical failure evidence;
3. region/jurisdiction rules;
4. relevant test documentation.

## Step 4 — Test Planning

The Planner creates a candidate execution plan using:

- known test metadata;
- scope matching;
- browser and region compatibility;
- business rules;
- historical failures;
- test criticality.

## Step 5 — Policy Validation

A deterministic policy layer validates the plan.

Examples:

```text
Unsupported browser -> reject
Unknown test -> reject
Unsupported region -> reject
Required jurisdiction rule not satisfied -> reject
Empty test plan -> reject
```

## Step 6 — Execution Agent

The Execution Agent sends the validated plan to the mock Jenkins service.

## Step 7 — Track Execution

The system tracks:

- queued;
- running;
- completed;
- failed;
- cancelled.

Individual test results are persisted.

## Step 8 — AI Result Analysis

The Analyzer receives:

- current test results;
- test documentation;
- relevant historical failures;
- execution metadata.

The LLM generates a grounded explanation of failures and recommendations.

## Step 9 — Final Response

The system returns:

- what was executed;
- what passed;
- what failed;
- likely causes;
- supporting evidence;
- recommended next steps.

---

# 8. Agent Architecture

The project requires at least three agents. We will implement four logical agents plus deterministic services.

## 8.1 Intent Agent

### Responsibility

Understand the user's natural-language request and convert it into a structured `TestIntent`.

### Input

```text
Run smoke tests for payment on Chrome in US.
```

### Output

```json
{
  "module": "payment",
  "scope": "smoke",
  "browser": "chrome",
  "region": "US",
  "environment": null,
  "confidence": 0.95,
  "missing_fields": []
}
```

### Rules

- Must use structured output/schema validation.
- Must normalize obvious variations (`Google Chrome` -> `chrome`).
- Must never invent unsupported values.
- Must flag missing information where a required field cannot be safely inferred.
- Must not select test IDs.
- Must not trigger execution.

### Failure Handling

If parsing fails:

```text
workflow.status = NEEDS_CLARIFICATION
```

The system should preserve the original query and parsing error.

---

# 9. Retrieval Agent

## Responsibility

Retrieve evidence needed for test planning and later AI reasoning.

## Evidence Types

### A. Test Metadata

Example:

```json
{
  "test_id": "PAY-001",
  "module": "payment",
  "scope": "smoke",
  "browsers": ["chrome", "firefox"],
  "regions": ["US", "EU"],
  "criticality": "high"
}
```

### B. Historical Failures

Example:

```json
{
  "test_id": "PAY-003",
  "date": "2026-07-30",
  "browser": "chrome",
  "region": "US",
  "failure": "3DS redirect timeout"
}
```

### C. Jurisdiction Rules

Example:

```text
US-Nevada
Maximum wager limit: $X
Additional validation required for affected flows.
```

### D. Test Documentation

Human-readable information describing what individual tests validate.

## Retrieval Strategy

The preferred strategy is hybrid retrieval:

```text
Intent
  |
  v
Metadata filters
  |
  v
Candidate subset
  |
  v
Semantic vector search
  |
  v
Top-K relevant evidence
```

The goal is to combine exact structured constraints with semantic similarity.

## Rules

- Retrieve before evidence-dependent LLM decisions.
- Preserve source/document IDs for explainability.
- Return relevance scores where available.
- Do not return unbounded context.
- Keep different evidence types separately identifiable.
- Never silently drop retrieval failures.

---

# 10. Test Planner

The planner converts intent + retrieved evidence into a structured execution plan.

## Responsibility

Answer:

> Which known tests should execute, in what priority/order, and why?

## Inputs

- `TestIntent`;
- test catalog;
- retrieval results;
- policy rules.

## Output

```json
{
  "module": "payment",
  "scope": "smoke",
  "browser": "chrome",
  "region": "US",
  "tests": [
    {
      "test_id": "PAY-003",
      "priority": 1,
      "risk_score": 0.87,
      "reasons": [
        "Matches requested module and scope",
        "Supported on Chrome",
        "Historical Chrome failure pattern"
      ]
    }
  ]
}
```

## Planning Rule

The planner must only choose tests that exist in the test catalog.

## Optional Risk Score

A simple risk score may be calculated from:

```text
risk_score = weighted combination of:
- historical failure frequency;
- recent failure recency;
- test criticality;
- browser/region-specific failure patterns.
```

The score must be explainable. It does not need to be a machine-learned model in the take-home version.

---

# 11. Policy Service

The Policy Service is intentionally deterministic.

## Responsibility

Validate whether an execution plan is allowed.

## Example Rules

```text
1. Test must exist.
2. Browser must be supported.
3. Region must be supported.
4. Test must match module and requested scope.
5. Jurisdiction restrictions must be satisfied.
6. A zero-test plan is invalid.
```

## Principle

> Business or safety rules should not depend on free-form LLM output.

The LLM can explain a policy, but the policy engine should enforce it.

---

# 12. Execution Agent

## Responsibility

Convert the validated plan into an execution request for the mock Jenkins service.

## Input

```json
{
  "tests": ["PAY-001", "PAY-003"],
  "browser": "chrome",
  "region": "US",
  "environment": "staging"
}
```

## Output

```json
{
  "execution_id": "JOB-2001",
  "status": "QUEUED"
}
```

## Rules

- Must only execute validated plans.
- Must not invent test IDs.
- Must persist the execution request.
- Must support an idempotency key to avoid accidental duplicate execution.
- Must map workflow ID to execution ID.

---

# 13. Mock Jenkins Service

The mock Jenkins service is a local FastAPI service or internal module that behaves like an external job execution system.

## Endpoints

```text
POST /jobs
GET /jobs/{job_id}
POST /jobs/{job_id}/cancel
```

## Lifecycle

```text
QUEUED
  |
  v
RUNNING
  |
  +----> FAILED
  |
  v
COMPLETED
```

## Simulated Results

Each test returns:

```json
{
  "test_id": "PAY-003",
  "status": "FAILED",
  "duration_ms": 1840,
  "failure_reason": "3DS redirect timeout"
}
```

The simulation should use deterministic or seeded behavior where possible so tests and demonstrations are repeatable.

---

# 14. Result Analyzer Agent

## Responsibility

Turn raw execution results into a human-readable, evidence-grounded report.

## Inputs

- failed tests;
- passed tests;
- failure messages;
- test documentation;
- historical failures;
- environment/browser/region context.

## Output

```json
{
  "summary": "1 of 4 tests failed.",
  "failures": [
    {
      "test_id": "PAY-003",
      "likely_cause": "3DS redirect timeout",
      "confidence": 0.82,
      "evidence": [
        "Current execution timed out during 3DS redirect",
        "Three similar Chrome failures occurred historically"
      ],
      "recommendations": [
        "Review gateway timeout configuration",
        "Verify 3DS callback handling"
      ]
    }
  ]
}
```

## Analysis Rules

- Do not invent root causes.
- Use retrieved evidence wherever possible.
- Clearly separate observed facts from inferred causes.
- If evidence is insufficient, state that explicitly.
- Return structured JSON before generating a human-readable summary.

---

# 15. Code Analysis Agent (Bonus)

The bonus agent reviews a submitted Python test file.

## Input

```text
path/to/test_payment.py
```

## Checks

Deterministic checks should include:

- hard-coded `sleep()` usage;
- missing assertions;
- poor function naming;
- duplicated setup logic;
- missing error handling where relevant;
- excessive method length;
- hard-coded environment values;
- poor fixture usage;
- unsafe or brittle selectors where applicable;
- logging quality.

The LLM may then summarize the findings using a senior-review style.

## Important Rule

Static analysis finds facts. The LLM explains those facts. The LLM should not be the sole source of code-quality findings.

---

# 16. RAG Knowledge Base

## Directory Layout

```text
knowledge_base/
├── test_docs/
├── historical_failures/
├── jurisdiction_rules/
└── README.md
```

## Minimum Dataset

The demo should contain:

- 10–15 mock tests;
- several historical failure records;
- multiple regional rules;
- test documentation for representative modules.

## Recommended Modules

```text
payment
wallet
checkout
login
withdrawal
```

## Recommended Browsers

```text
chrome
firefox
safari
```

## Recommended Regions

```text
US
US-Nevada
EU
UK
```

The data should be small but intentionally rich enough to demonstrate retrieval and decision-making.

---

## 16.1 Embeddings

The initial implementation uses the OpenAI API to create embeddings for knowledge-base documents. Embedding creation runs in the backend ingestion process and query embedding runs in the backend retrieval service. The local web UI only calls the FastAPI workflow API; it never receives an OpenAI API key or makes direct embedding requests.

# 17. Test Catalog Rules

The catalog is the source of truth for executable tests.

Each test should have at minimum:

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

## Catalog Rules

- IDs must be unique.
- Module names must be normalized.
- Browser names must be normalized.
- Region names must use controlled values.
- Test scope must come from a known enumeration.
- The catalog must be loaded independently from prompts.

---

# 18. SQLite Persistence Model

SQLite is the persistence layer for the take-home implementation.

## `workflows`

```text
id
query
status
created_at
updated_at
```

## `agent_runs`

```text
id
workflow_id
agent_name
status
input_payload
output_payload
started_at
completed_at
error
```

## `test_plans`

```text
id
workflow_id
test_id
priority
risk_score
selection_reason
```

## `executions`

```text
id
workflow_id
external_job_id
status
started_at
completed_at
```

## `test_results`

```text
id
execution_id
test_id
status
duration_ms
failure_reason
```

## `analysis_reports`

```text
id
workflow_id
summary
analysis_payload
created_at
```

The schema may be simplified, but these concepts should exist.

---

# 19. LangGraph Design

LangGraph is used because the system is a stateful multi-step workflow rather than a simple chain.

## Shared State

Conceptually:

```python
class TestWorkflowState(TypedDict):
    workflow_id: str
    user_query: str
    intent: dict
    retrieved_context: dict
    test_plan: dict
    execution_id: str
    execution_status: str
    execution_results: list
    analysis: dict
    errors: list
```

## Graph

```text
START
  |
  v
Intent Agent
  |
  v
Retrieval Agent
  |
  v
Planner
  |
  v
Policy Validation
  |
  +------ invalid ------> END (rejected)
  |
 valid
  |
  v
Execution Agent
  |
  v
Result Collection
  |
  v
Result Analyzer
  |
  v
END
```

## Conditional Paths

At minimum, support:

```text
Intent parsing failure -> NEEDS_CLARIFICATION
Retrieval failure -> RETRY / ERROR
Policy failure -> REJECTED
Execution failure -> EXECUTION_FAILED
LLM analysis failure -> FALLBACK_SUMMARY
```

---

# 20. LLM Usage Strategy

The LLM should be abstracted behind a provider interface.

Example concept:

```text
LLMProvider
├── OpenAIProvider
├── OllamaProvider
└── GroqProvider
```

Only one provider needs to be enabled for the take-home implementation.

For the initial local build, OpenAI is the configured provider for structured intent extraction, grounded result analysis, and embeddings. The provider interface remains so an alternative can be added later without changing workflow or policy code.

## 20.1 OpenAI API Key Handling

Use `OPENAI_API_KEY` only in backend environment configuration. When Docker Compose starts the application, it injects the key into the backend container at runtime from a local `.env` file or shell environment.

Rules:

- Never commit a real key; `.env` must be ignored and `.env.example` contains names only.
- Never include the key in frontend build arguments, browser storage, JavaScript bundles, logs, API responses, or container image layers.
- The backend owns all OpenAI model and embedding calls.
- Report a safe configuration/error state if the key is missing; do not expose the secret in diagnostics.

## LLM Use Cases

### Use LLM for

- natural-language intent extraction;
- evidence-based failure reasoning;
- human-readable explanation;
- optional code-review summarization.

### Do not use LLM for

- test ID validation;
- metadata filtering;
- hard business rules;
- workflow persistence;
- execution authorization;
- deterministic status transitions.

---

# 21. Prompt Engineering Rules

All prompts should live in version-controlled prompt files/modules instead of being buried in Python logic.

Each prompt should define:

- task;
- available context;
- strict output schema;
- prohibited assumptions;
- fallback behavior.

## Grounding Rule

For result analysis:

```text
Use only the provided execution results and retrieved evidence.
Do not invent root causes.
Mark uncertainty explicitly.
```

---

# 22. API Design

Recommended initial API surface:

```text
POST /api/v1/workflows
GET  /api/v1/workflows/{workflow_id}
GET  /api/v1/workflows/{workflow_id}/events
POST /api/v1/code-review
GET  /health
```

Optional:

```text
POST /api/v1/workflows/{workflow_id}/cancel
POST /api/v1/workflows/{workflow_id}/approve
```

---

# 23. Error Handling

The system should explicitly handle:

- malformed user input;
- unsupported browser;
- unsupported region;
- missing module;
- empty retrieval results;
- vector database failure;
- LLM timeout;
- invalid LLM structured output;
- mock Jenkins failure;
- duplicate execution requests.

Error responses should be structured and should include a workflow or request identifier where possible.

Example:

```json
{
  "error": {
    "code": "UNSUPPORTED_BROWSER",
    "message": "Safari is not supported for PAY-003 in this environment.",
    "workflow_id": "WF-1001"
  }
}
```

---

# 24. Observability

For the take-home version, implement lightweight logging.

Every workflow should have:

```text
workflow_id
agent_name
step_name
start_time
end_time
status
error
```

Also capture retrieval information such as:

```text
query
filters
top_k
source_ids
scores
```

For LLM calls capture:

```text
model
latency
success/failure
```

Do not store secrets or sensitive raw credentials.

---

# 25. Idempotency and Safety

A natural-language user request can be accidentally submitted twice.

The execution layer should accept an idempotency key or derive one from the workflow request.

Rule:

> The same workflow must not accidentally trigger two identical executions because of an API retry.

This is particularly important when discussing production scaling.

---

# 26. Dry Run Mode

Add an optional dry-run parameter:

```json
{
  "query": "Run payment smoke tests on Chrome in US",
  "dry_run": true
}
```

The system should perform:

```text
Intent
Retrieval
Planning
Policy Validation
```

but stop before execution.

This provides a safe debugging and demonstration mode.

---

# 27. Human-in-the-Loop Extension

For a high-risk plan, the system can pause before execution.

Example:

```text
risk_score >= 0.80
        |
        v
WAITING_FOR_APPROVAL
        |
   +----+----+
   |         |
approve    reject
   |         |
execute     END
```

This is optional in the implementation but should be mentioned in the scalability architecture.

---

# 28. Evaluation Strategy

The system should have a small evaluation dataset to demonstrate AI quality.

## Intent Evaluation

Measure:

- module extraction accuracy;
- scope extraction accuracy;
- browser extraction accuracy;
- region extraction accuracy.

## Retrieval Evaluation

At minimum document:

- Recall@K or Hit@K;
- qualitative retrieval examples;
- metadata filter correctness.

## Planning Evaluation

Measure whether selected tests match expected catalog filters.

## Analysis Evaluation

Use a small manually reviewed set to evaluate:

- factual correctness;
- evidence grounding;
- hallucination rate;
- recommendation quality.

The goal is not to create an academic benchmark. The goal is to show that the AI portion was evaluated rather than assumed to work.

---

# 29. Testing Strategy

Tests should exist at multiple levels.

## Unit Tests

Test:

- intent parsing adapter;
- metadata filtering;
- policy rules;
- risk scoring;
- repository methods;
- result normalization.

## Integration Tests

Test:

```text
API -> LangGraph -> Retrieval -> Planner
```

and:

```text
Execution Agent -> Mock Jenkins -> Persistence
```

## End-to-End Test

One complete happy path:

```text
user query
-> intent
-> retrieval
-> plan
-> policy
-> execution
-> results
-> analysis
```

## Negative Tests

Include:

- unsupported browser;
- unknown module;
- no matching tests;
- no retrieval evidence;
- simulated Jenkins failure;
- LLM timeout or malformed response.

---

# 30. Recommended Repository Structure

```text
test-trigger/
│
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── routes_workflow.py
│   │   ├── routes_execution.py
│   │   └── routes_code_review.py
│   │
│   ├── agents/
│   │   ├── intent_agent.py
│   │   ├── retrieval_agent.py
│   │   ├── execution_agent.py
│   │   ├── analysis_agent.py
│   │   └── code_analysis_agent.py
│   │
│   ├── orchestration/
│   │   ├── graph.py
│   │   └── state.py
│   │
│   ├── services/
│   │   ├── retrieval_service.py
│   │   ├── planner.py
│   │   ├── policy_service.py
│   │   ├── execution_service.py
│   │   └── analysis_service.py
│   │
│   ├── models/
│   │   ├── intent.py
│   │   ├── test_case.py
│   │   ├── plan.py
│   │   ├── execution.py
│   │   └── workflow.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repositories.py
│   │
│   └── llm/
│       ├── provider.py
│       └── prompts.py
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── api/
│   │   └── app/
│   ├── Dockerfile
│   └── package.json
│
├── knowledge_base/
│   ├── test_docs/
│   ├── historical_failures/
│   └── jurisdiction_rules/
│
├── data/
│   └── test_cases.json
│
├── scripts/
│   └── ingest.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── docs/
│   └── architecture.md
│
├── README.md
├── product.md
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
├── .env.example
└── pyproject.toml
```

The final structure can be simplified if necessary, but boundaries should remain clear.

---

# 31. Build Order

The project must be built incrementally. Do not begin by creating all agents.

## Phase 1 — Domain and Data Foundation

Build first:

1. test catalog;
2. Pydantic/domain models;
3. SQLite schema;
4. seed data.

### Why

Every downstream component needs a stable representation of tests, workflows and executions.

---

## Phase 2 — Knowledge Base and Retrieval

Build:

1. knowledge-base documents;
2. ingestion script;
3. embeddings;
4. ChromaDB persistence;
5. retrieval service;
6. metadata filtering.

### Why

The retrieval layer is core to the assignment. Validate retrieval quality before adding agents around it.

---

## Phase 3 — Mock Execution Service

Build:

1. mock Jenkins API;
2. job lifecycle;
3. deterministic/seated result simulation;
4. execution persistence.

### Why

The Execution Agent should integrate with a working service rather than hide execution logic inside the agent.

---

## Phase 4 — Intent Agent

Build:

1. structured prompt;
2. output schema;
3. normalization;
4. validation;
5. negative-path handling.

### Why

Intent becomes the contract between the user request and the rest of the workflow.

---

## Phase 5 — Retrieval Agent

Build:

1. intent-aware query construction;
2. metadata filters;
3. vector search;
4. evidence grouping;
5. retrieval logging.

### Why

This demonstrates the required RAG flow and gives the planner reliable evidence.

---

## Phase 6 — Planner and Policy Layer

Build:

1. candidate test selection;
2. compatibility validation;
3. jurisdiction checks;
4. risk scoring;
5. execution plan generation.

### Why

This is where the system turns evidence into an actual executable workflow. Keep important rules deterministic.

---

## Phase 7 — LangGraph Integration

Build:

1. shared workflow state;
2. graph nodes;
3. conditional edges;
4. error transitions;
5. persistence of agent steps.

### Why

Integrate the graph after individual components are stable. This dramatically reduces debugging complexity.

---

## Phase 8 — AI Result Analysis

Build:

1. grounded analysis prompt;
2. structured output;
3. confidence/evidence fields;
4. fallback summary when LLM is unavailable.

### Why

The analyzer is additive. The workflow should already execute successfully without it.

---

## Phase 9 — API and Client Contract

Build:

1. workflow endpoint;
2. workflow status endpoint;
3. event/timeline endpoint;
4. CLI or curl examples;
5. CORS configuration for the local chat UI.

### Why

The API should expose a clean product interface over the already-working domain services before a browser client consumes it.

---

## Phase 10 — Local Web Chat UI

Build:

1. local chat page shell;
2. query input, send action, and dry-run control;
3. workflow status and assistant-message rendering;
4. expandable intent, plan, evidence, and timeline details;
5. error and clarification states.

### Why

The UI is the focused product surface for the interview demonstration. It must remain a thin client of FastAPI and must never expose the OpenAI API key.

---

## Phase 11 — Local Docker Runtime

Build:

1. backend Dockerfile;
2. frontend Dockerfile;
3. Docker Compose frontend/backend service wiring;
4. persistent SQLite and ChromaDB volumes;
5. runtime environment and health-check configuration.

### Why

One local Docker Compose command should start the full demo reproducibly for an interviewer. This is a local runtime, not a hosting or production-deployment solution.

---

## Phase 12 — Testing and Evaluation

Add:

1. unit tests;
2. integration tests;
3. one end-to-end workflow test;
4. AI evaluation samples;
5. retrieval evaluation examples.

### Why

The evaluator explicitly cares about code quality and RAG quality.

---

## Phase 13 — Documentation and Polish

Finalize:

1. README;
2. architecture document;
3. sample request/response;
4. sequence diagram;
5. local setup instructions;
6. assumptions and trade-offs;
7. production scaling section.
8. local chat UI and Docker run instructions;
9. environment-variable and OpenAI API-key handling guidance.

### Why

The final review should be easy for someone unfamiliar with the project.

---

# 32. Production Scalability Strategy

The take-home should be a modular monolith, but its interfaces should support future decomposition.

## Current Architecture

```text
Local Browser
  |
Local Chat UI
  |
FastAPI
  |
LangGraph
  |
Services
  |
ChromaDB + SQLite
  |
Mock Jenkins
```

## Future Architecture

```text
Hosted Web Client
    |
API Gateway
    |
Workflow Orchestrator
    |
    +----------------------+-------------------+
    |                      |                   |
Intent Service      Retrieval Service   Policy Service
    |                      |                   |
    |                 Vector DB               |
    +----------------------+-------------------+
                           |
                    Execution Service
                           |
                     Queue / Event Bus
                           |
                  Test Execution Workers
                           |
                     Result Processor
                           |
                      AI Analyzer
```

## Production Evolution

### API Layer

Scale FastAPI horizontally behind a load balancer.

### Web Client

Keep the local chat UI as a separate frontend boundary. If the product is later hosted, serve it through a managed static host/CDN and use a secure API gateway for backend access. The initial Docker Compose setup is intentionally local only.

### Orchestration

Persist workflow state so a workflow can resume after process restarts.

### Queue

Use Kafka, RabbitMQ, SQS or similar for long-running execution jobs.

### Database

Move from SQLite to PostgreSQL.

### Cache

Use Redis for ephemeral state, locks and frequently accessed metadata.

### Vector Store

Use a managed or scalable vector database if retrieval volume requires it.

### Execution

Replace mock Jenkins with actual CI providers, browser grids or internal execution services.

### Observability

Add OpenTelemetry, metrics, traces and structured logs.

### Security

Add authentication, authorization, secrets management and tenant isolation. Keep OpenAI API keys server-side with managed secret storage; never move model or embedding calls into the browser client.

### LLM Gateway

Centralize model/provider routing, quotas, prompt versions, retries and cost tracking.

---

# 33. Scalability Rules

1. Keep APIs stateless.
2. Keep workflow state durable.
3. Treat test execution as asynchronous.
4. Use idempotency for external execution requests.
5. Separate control plane from execution workers.
6. Keep LLM provider access behind an interface.
7. Version prompts and retrieval configuration.
8. Keep vector data independent from application process memory.
9. Capture trace IDs across agent steps.
10. Do not make an LLM call where a deterministic rule is sufficient.

---

# 34. Reliability and Resilience

The system should be designed so one dependency failure does not destroy all useful information.

## LLM Failure

Fallback to:

```text
Deterministic execution summary
```

## Vector DB Failure

Fail safely and mark the workflow as retrieval failure unless a predefined deterministic fallback is acceptable.

## Jenkins Failure

Persist the failure and allow workflow inspection/retry.

## Duplicate Requests

Use idempotency handling.

## Partial Workflow Failure

Persist completed steps and failed steps. Never lose the workflow state because a later step failed.

## Local Runtime Failure

If the local chat UI is unavailable, the FastAPI API and CLI/example client remain usable. If `OPENAI_API_KEY` is missing or the provider is unavailable, return a safe configuration or fallback-analysis status without exposing a secret or losing deterministic workflow information.

---

# 35. Creativity / Differentiation Features

The following are optional but recommended because they improve the product story without dramatically increasing complexity.

## 35.1 Risk-Based Test Prioritization

Prioritize tests using historical failures and criticality.

## 35.2 Explainable Test Selection

Show why each test was selected.

## 35.3 Dry Run

Plan and validate without execution.

## 35.4 Human Approval Gate

Pause high-risk executions.

## 35.5 Failure-Aware Retry

Retry transient failures but do not blindly rerun known functional failures.

## 35.6 Code Analysis Agent

Review a Python test file against senior-engineer coding standards.

The first priority is a polished core workflow. Optional features must never destabilize the MVP.

---

# 36. Demo Scenarios

The README and final demonstration should include at least these scenarios.

## Scenario A — Happy Path

```text
Run payment smoke tests on Chrome in US.
```

Expected:

- intent extracted;
- relevant tests retrieved;
- plan created;
- execution triggered;
- results generated;
- AI summary returned.

## Scenario B — Historical Risk

```text
Run payment smoke tests on Chrome in US-Nevada.
```

Expected:

- jurisdiction evidence retrieved;
- historical failures affect prioritization;
- plan includes explainable reasoning.

## Scenario C — Invalid Request

```text
Run payment smoke tests on Edge in US.
```

Expected:

- unsupported browser detected;
- execution blocked.

## Scenario D — Empty Retrieval

Request a combination with no matching tests.

Expected:

- no arbitrary test IDs;
- workflow stops safely;
- useful error message.

## Scenario E — Execution Failure

Simulate Jenkins failure.

Expected:

- workflow status becomes execution-failed;
- state is persisted;
- API exposes the failure.

## Scenario F — LLM Failure

Simulate LLM timeout.

Expected:

- execution results remain available;
- fallback deterministic summary is returned.

---

# 37. README Requirements

The final README must include:

1. product overview;
2. architecture diagram;
3. technology choices;
4. project structure;
5. setup instructions;
6. environment variables;
7. ingestion instructions;
8. how to start FastAPI;
9. example API request;
10. example output;
11. example CLI usage;
12. testing instructions;
13. known limitations;
14. production scaling approach;
15. local web chat UI overview;
16. Docker Compose startup and reset instructions;
17. OpenAI API-key and embedding configuration guidance.

The README should be written so a new engineer can clone the repo and understand the system without a verbal explanation.

---

# 38. Architecture Document Requirements

The separate architecture document should be concise but technically strong.

It should contain:

## 1. Problem

What the platform solves.

## 2. Architecture

A system diagram showing:

```text
Local Browser -> Test Trigger Chat UI -> FastAPI -> LangGraph -> Agents/Services -> Retrieval/Execution -> Analysis
```

## 3. Data Flow

Show the complete request lifecycle.

## 4. Component Decisions

Explain why we selected:

- FastAPI;
- local web chat UI;
- Docker Compose local runtime;
- LangGraph;
- ChromaDB;
- SQLite;
- OpenAI API for LLM and embeddings.

## 5. Reliability

Explain failure handling.

## 6. Scalability

Explain how the modular monolith becomes distributed.

## 7. Trade-offs

Explicitly state what was simplified for the take-home.

---

# 39. Definition of Done

The project is considered complete when all of the following are true.

## Core Functionality

- [ ] Natural-language request is accepted.
- [ ] Intent is extracted into a validated schema.
- [ ] Retrieval happens using ChromaDB.
- [ ] Metadata filtering is implemented.
- [ ] Test catalog contains 10–15 usable mock tests.
- [ ] Historical failure data is retrievable.
- [ ] Region/jurisdiction rules are retrievable.
- [ ] Test plan is generated from known tests.
- [ ] Deterministic policy validation is implemented.
- [ ] Mock Jenkins execution works.
- [ ] Execution and test results are persisted.
- [ ] LLM produces grounded result analysis.
- [ ] LangGraph connects the workflow.
- [ ] Local chat UI submits requests and renders workflow outcomes.
- [ ] Docker Compose starts the frontend and backend together locally.
- [ ] OpenAI embeddings are created only by the backend.

## Engineering Quality

- [ ] Code is modular.
- [ ] Errors are structured.
- [ ] Unit tests cover core logic.
- [ ] At least one end-to-end workflow test exists.
- [ ] Logging/tracing information is present.
- [ ] Environment configuration is separated from code.
- [ ] No secrets are committed.
- [ ] OpenAI API keys are backend-only and absent from browser bundles and container images.

## Documentation

- [ ] README is complete.
- [ ] Architecture document is complete.
- [ ] Sample request/response is documented.
- [ ] Production scaling is explained.
- [ ] Trade-offs are explicitly documented.
- [ ] Local UI and Docker runbook are documented.

## Optional

- [ ] Code Analysis Agent.
- [ ] Dry-run mode.
- [ ] Risk-based prioritization.
- [ ] Human approval workflow.
- [ ] Failure-aware retry strategy.

---

# 40. Final Product Positioning

The final product should be presented as:

> **Test Trigger is an AI-assisted test orchestration platform with a local chat interface. It converts natural-language testing intent into an evidence-backed, policy-validated and executable test workflow, then analyzes the resulting failures using grounded AI.**

The most important engineering story is the separation of responsibilities:

```text
Intent Agent
    -> Understand the request

Retrieval Agent
    -> Gather evidence

Planner / Policy Service
    -> Decide what is valid and executable

Execution Agent
    -> Trigger the run

Result Analyzer
    -> Explain what happened using evidence

LangGraph
    -> Orchestrate the stateful workflow

SQLite
    -> Persist state and audit trail

ChromaDB
    -> Retrieve semantic evidence

OpenAI API (backend only)
    -> Perform language understanding, evidence-based reasoning, and embeddings

Local Chat UI
    -> Present the workflow and its explanation to the user

Docker Compose
    -> Run the frontend and backend together locally
```

The project should feel like a small, well-engineered product rather than a collection of AI demos.

---

# 41. Implementation Philosophy

The project should follow this sequence of thinking for every feature:

```text
1. What problem does this feature solve?
2. Does this require an LLM?
3. What data does it need?
4. What should be deterministic?
5. What state must be persisted?
6. What happens when the dependency fails?
7. How would this scale?
8. How will we test it?
```

If a proposed feature cannot answer those questions clearly, it should not be added to the core workflow.

---

# 42. Golden Rule for the Project

> **Build the smallest system that demonstrates strong AI engineering judgment, not the largest system that can fit into 72 hours.**

The evaluator should be able to see, within a few minutes of running the project:

1. a natural-language request;
2. structured intent;
3. retrieved evidence;
4. an explainable test plan;
5. policy validation;
6. an execution job;
7. real-looking test results;
8. grounded AI analysis;
9. persisted workflow history.

That single end-to-end path is the primary product demonstration.
