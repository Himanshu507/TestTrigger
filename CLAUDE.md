# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Documentation and architecture are complete. **Modules 1 and 3 are done (11 of 59 stories).** Suite is green: 125 tests.

- **Module 1 — Foundation:** domain models in `app/models/`, `TestCatalog`, `AppSettings`, the 7-table SQLite schema, five repositories in `app/db/repositories.py`. Seed data is `data/test_cases.json` (12 tests) plus `knowledge_base/`.
- **Module 3 — Intent:** `app/llm/` (provider interface, `OpenAIProvider`, versioned prompts) and `app/agents/` (`IntentAgent`, normalization).

Next is Module 2 (Knowledge Base and Retrieval), which unblocks Module 4 (Planning and Policy). See `docs/module-map.md` for the dependency order.

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
- Agents depend on the `LLMProvider` ABC, never on the `openai` SDK — tests use a fake provider. Provider failures are the typed errors in `app/llm/errors.py`; an agent turns them into an explicit outcome (e.g. `ClarificationRequired`) and never a guessed value.
- Provider schemas are built from the enums (`build_intent_schema`), so the prompt contract cannot drift from the vocabulary validators accept. Output is validated twice: schema, then `app/agents/normalization.py`, which returns `None` for unknown values rather than snapping to a near match.
- Repositories return Pydantic models, not `sqlite3.Row`. Payload dicts are JSON columns; timestamps are UTC ISO strings on disk, `datetime` in models.
- Loaders are classmethod constructors (`TestCatalog.load`, `.load_default`) and validate invariants eagerly (duplicate IDs raise at construction).
- Keyword-only arguments for multi-parameter filters/writers (`catalog.filter(*, module, scope, browser, region)`).
- Test names are full sentences describing behavior, not `test_filter`.
- Models enforce their own invariants with `@model_validator`, so an illegal object cannot exist: a failed `ExecutionResult` must state a reason, a `PlanItem` must give reasons, a passing `PolicyResult` cannot list violations, a fallback `AnalysisReport` cannot infer causes. Add invariants there rather than re-checking in callers.
- `python_classes = []` in `pyproject.toml` disables pytest class collection, because the domain owns `TestCase`, `TestIntent`, `TestCatalog`, and `TestOutcome`. Write tests as plain functions; do not rename domain classes.

## Git

Working on `main` with one docs commit. Everything under `app/`, `tests/`, `data/`, `pyproject.toml` is still untracked.
