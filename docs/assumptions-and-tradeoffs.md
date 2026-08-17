# Assumptions and Trade-offs

## Explicit MVP assumptions

- The test catalog contains 10–15 synthetic tests across payment, wallet, checkout, login, and withdrawal.
- Supported browser values are Chrome, Firefox, and Safari; supported regions include US, US-Nevada, EU, and UK.
- A local mock Jenkins implementation has deterministic or seeded outcomes so tests and demos are repeatable.
- OpenAI API access powers the initial LLM and embedding paths; the API key is configured only in the local backend environment. The application remains useful when result analysis is unavailable.
- The web UI is a small, local-only chat interface and is not hosted for this interview project.
- Workflow execution may be synchronous for the small local demo, although records and states model an asynchronous system.
- The project stores no real customer data, execution credentials, or production test secrets.

## Important trade-offs

| Decision | Benefit for MVP | Cost / future decision |
| --- | --- | --- |
| Modular monolith | Fast to build and easy to inspect | Need service extraction boundaries at scale. |
| SQLite | Zero operational setup and transparent local state | Replace with PostgreSQL for concurrency, backups, and HA. |
| ChromaDB local persistence | Practical RAG demonstration | Upgrade when corpus size, tenancy, or availability requirements grow. |
| Mock Jenkins | Reliable, controllable test demo | Must define real CI provider auth, callbacks, and retry semantics. |
| Deterministic rules | Explainable and safe plan validation | Policy authoring and versioning will need governance. |
| Synchronous demo path | Simple API walkthrough | Production work needs queues, workers, polling/webhooks, and timeouts. |
| Local chat UI | Gives the demo a human-friendly product surface | It is deliberately not a full collaboration dashboard or hosted application. |
| Docker Compose | Reproducible full-stack local startup | It is not an orchestration or production deployment strategy. |
| OpenAI API and embeddings | One consistent capability for intent, analysis, and semantic retrieval | Requires careful key handling, cost limits, and an offline fallback strategy. |

## Deferred work

- Authentication, authorization, tenant isolation, and rate limiting.
- Public frontend hosting, CI/CD deployment, and production container orchestration.
- Distributed job workers and an event bus.
- Real browser grids and CI integrations.
- Full prompt registry, model routing, quota management, and cost controls.
- Human approval gate, failure-aware retry, and code-analysis agent.
- Formal retrieval and analysis benchmark dashboards.

## Non-negotiable choices

These trade-offs do not weaken the product principles: executable IDs stay catalog-driven; policies stay deterministic; evidence-dependent LLM behavior is retrieved and bounded; state is durable; and LLM failure never hides raw execution results.
