# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Documentation and architecture are complete. Module 1 (Foundation and Data) is mostly built; Modules 2–11 have no code. Suite is green: 27 tests.

Built: `app/models/test_case.py`, `app/models/workflow.py`, `app/catalog.py`, `app/config.py`, `app/db/` (schema, `Database`, `WorkflowRepository`).

Remaining in Module 1:

- **FND-1** — `TestIntent`, `ExecutionPlan`, `PlanItem`, `ExecutionResult`, `AnalysisReport`, `RetrievedEvidence` models
- **FND-4** — repositories for `test_plans`, `executions`, `test_results`, `analysis_reports`, `workflow_events` (tables exist; only `WorkflowRepository` is implemented)
- **FND-5** — `knowledge_base/` history and jurisdiction fixtures (catalog seed is done: 12 tests)

Finish those before starting Module 2 or 3 — everything downstream depends on Module 1's contracts.

The repo uses TDD: tests are often written before the code exists. A failing import in `tests/` is a specification, not breakage. Never delete or skip one to get green.

## Commands

```bash
uv sync --extra dev            # install deps into .venv (Python 3.11 via uv)
uv run pytest                  # full suite
uv run pytest tests/unit/test_catalog.py                      # one file
uv run pytest tests/unit/test_catalog.py::test_catalog_filters_known_payment_smoke_tests_for_chrome_in_us   # one test
uv run pytest -k catalog       # by name
```

`pyproject.toml` sets `pythonpath = ["."]`, so no editable install is needed. No linter or type checker is configured yet.

## Environment

`requires-python = ">=3.10"`; the venv is 3.11. 3.10 is the floor because the code uses PEP 604 annotations (`TestCase | None` in `app/catalog.py`) that fail at import on 3.9.

`python` is not on PATH; use `uv run python` or `python3` (system 3.9 — not the project interpreter).

## Source of truth for design

Read the docs before writing new modules — they define contracts precisely enough that guessing is wrong.

- `docs/module-map.md` — 12 modules, dependency order, 59 MVP stories. **Build in this order.**
- `docs/modules/NN-*.md` — per-module owned interfaces, stories, acceptance criteria, boundaries
- `docs/workflow.md` — LangGraph state machine, node read/write contract, invariants
- `docs/data-model.md` — Pydantic models and the 7 SQLite tables
- `docs/api-contract.md` — endpoints, error shape, status-code mapping
- `docs/architecture.md` — component ownership table, trust boundaries
- `product.md` — full product spec (2100 lines); the docs are the distilled version

## Architecture

A local-only modular monolith that turns a natural-language testing request into a policy-validated, executed, explained workflow:

```
query → Intent Agent → Retrieval Agent → Planner → Policy Service → Execution Agent → Result Analyzer
                                                                    (mock Jenkins)
```

LangGraph owns ordering and routing over a shared `TestWorkflowState`; agents return validated state updates and never call each other directly. Every step writes an audit record to SQLite.

Target layout (from README, mostly not yet created): `app/api`, `app/agents`, `app/orchestration`, `app/services`, `app/models`, `app/db`, `app/llm`, plus `frontend/`, `knowledge_base/`, `scripts/`.

## Non-negotiable design rules

These are the point of the project — violating them defeats it:

1. **The LLM never authorizes anything.** It parses language and explains results. Selection, policy validation, and status transitions are deterministic code.
2. **Executable test IDs come only from `data/test_cases.json`.** An LLM must never produce a test ID that enters a plan.
3. **Retrieval precedes any evidence-dependent LLM call**, and the response cites the returned source IDs.
4. **Policy runs after planning and before execution**, in plain code: test exists, browser supported, region supported, module/scope match, jurisdiction rules satisfied, non-empty plan.
5. **LLM failure must not hide execution results** — fall back to a deterministic summary (`FALLBACK_SUMMARY` → `COMPLETED`).
6. **`dry_run=true` stops at `DRY_RUN_COMPLETE`** after policy validation; it creates no job and no test-result rows.
7. **`OPENAI_API_KEY` is backend-only.** Never in an API response, event payload, DB row, log, image, or frontend build arg.
8. Pydantic validates every boundary payload; timestamps are UTC and application-assigned.

## Conventions in existing code

- Controlled vocabulary lives in `str`-valued enums in `app/models/` (`ModuleName`, `TestScope`, `Browser`, `Region`, `Criticality`, `WorkflowStatus`, `AgentRunStatus`) — reuse them; do not redefine per module. Module 1 owns shared models.
- Status changes go through `WorkflowRepository.update_status`, which enforces `ALLOWED_TRANSITIONS` in `app/models/workflow.py`. Never write a status column directly, and never add a transition that isn't in `docs/workflow.md`.
- `Database.connect()` is a context manager that enables `PRAGMA foreign_keys`, commits on success, rolls back on exception. All persistence goes through it.
- Repositories return Pydantic models, not `sqlite3.Row`. Payload dicts are JSON columns; timestamps are UTC ISO strings on disk, `datetime` in models.
- Loaders are classmethod constructors (`TestCatalog.load`, `.load_default`) and validate invariants eagerly (duplicate IDs raise at construction).
- Keyword-only arguments for multi-parameter filters/writers (`catalog.filter(*, module, scope, browser, region)`).
- Test names are full sentences describing behavior, not `test_filter`.
- `TestCatalog`/`TestCase` trigger a `PytestCollectionWarning` because pytest tries to collect `Test*` classes. Harmless; do not rename the domain classes to silence it.

## Git

Working on `main` with one docs commit. Everything under `app/`, `tests/`, `data/`, `pyproject.toml` is still untracked.
