# Documentation Index

This documentation describes the planned modular-monolith implementation of Test Trigger. It is the source of truth for the initial build sequence and module boundaries.

## Start here

| Document | Use it to understand |
| --- | --- |
| [Module map](module-map.md) | Module names, ownership, dependencies, and the 59-story MVP breakdown. |
| [Architecture](architecture.md) | System boundaries, data flow, component choices, failure handling, and scaling path. |
| [Workflow lifecycle](workflow.md) | LangGraph states, transitions, terminal states, and dry-run behavior. |
| [API contract](api-contract.md) | The target HTTP endpoints, payloads, status codes, and errors. |
| [Data model](data-model.md) | Core Pydantic concepts, test catalog, evidence records, and SQLite tables. |
| [Assumptions and trade-offs](assumptions-and-tradeoffs.md) | Intentional MVP simplifications and decisions to revisit before production. |

## Module guides

1. [Foundation and data](modules/01-foundation-and-data.md)
2. [Knowledge base and retrieval](modules/02-knowledge-base-and-retrieval.md)
3. [Intent understanding](modules/03-intent-understanding.md)
4. [Planning and policy](modules/04-planning-and-policy.md)
5. [Mock execution](modules/05-mock-execution.md)
6. [Workflow orchestration](modules/06-workflow-orchestration.md)
7. [Result analysis](modules/07-result-analysis.md)
8. [API and client interface](modules/08-api-and-client-interface.md)
9. [Local web chat interface](modules/09-local-web-chat-interface.md)
10. [Local container runtime](modules/10-local-container-runtime.md)
11. [Quality and operations](modules/11-quality-and-operations.md)
12. [Optional code analysis](modules/12-optional-code-analysis.md)

## Conventions

- **MVP story** means a small, independently verifiable unit of implementation work.
- **Deterministic** means code and controlled data produce the decision; an LLM may explain it but does not authorize it.
- **Evidence** means a catalog record, retrieved knowledge-base source, policy rule, historical failure, or execution result with an identifier.
- IDs in examples (`WF-1001`, `JOB-2001`, `PAY-003`) are illustrative only.

The first eleven modules form the MVP and total **59 stories**. The twelfth module is optional and adds **4 stories**. The web UI and Docker runtime are local-only features; the OpenAI API key remains backend-only.
