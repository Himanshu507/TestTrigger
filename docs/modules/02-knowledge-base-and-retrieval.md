# Module 2 — Knowledge Base and Retrieval

**Stories:** 6 MVP stories

**Owns:** knowledge-base taxonomy, ingestion, metadata filtering, vector retrieval, evidence grouping, and retrieval diagnostics.

**Depends on:** Foundation and Data.
**Used by:** Planner, Result Analyzer, Workflow Orchestration.

## Purpose

Retrieve relevant evidence before a planner or analyzer makes a decision that depends on information outside the user request. Retrieval combines deterministic metadata filters with semantic similarity; it is not an unbounded prompt search.

## Evidence layout

```text
knowledge_base/
  test_docs/
  historical_failures/
  jurisdiction_rules/
  README.md
```

Every document carries a stable source ID and type-specific metadata. Test metadata remains in the catalog; retrieval augments it with documentation, history, and policy context.

## Public interfaces

- `ingest()` loads documents, chunks them when needed, validates metadata, and persists Chroma collections.
- `retrieve(intent, top_k)` returns bounded `RetrievedEvidence` grouped as test docs, history, jurisdiction rules, and retrieval diagnostics.
- Retrieval logs filters, top-K, source IDs, scores, and errors against `workflow_id`.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| RET-1 | Define KB file layout and metadata schemas. | Every sample document has a unique source ID, document type, and applicable module/region/test metadata. |
| RET-2 | Build a repeatable ingestion script. | A clean local vector store can be populated from the committed synthetic KB without manual edits. |
| RET-3 | Configure persistent ChromaDB collections. | Restarting the app retains embeddings and supports test-isolated collections. |
| RET-4 | Apply deterministic metadata filters before semantic search. | A query for Chrome/US never returns an incompatible candidate as plan evidence. |
| RET-5 | Group and bound returned evidence. | Callers receive separate, source-attributed evidence categories and a configured maximum context size. |
| RET-6 | Add diagnostics and failure propagation. | Queries record filters/source IDs/scores; vector-store errors are surfaced rather than silently replaced. |

## Retrieval sequence

1. Validate and normalize `TestIntent`.
2. Filter the catalog and knowledge metadata by controlled constraints.
3. Query only the compatible subset for semantic relevance.
4. Return the top relevant evidence records by type with source IDs and scores.
5. Persist an auditable retrieval summary.

## Boundaries

Retrieval never chooses executable tests, authorizes policy, or generates a root-cause claim. It returns evidence and diagnostics only.

## Tests

Test metadata filter correctness, ingestion idempotency, document attribution, bounded results, retrieval with empty data, and a simulated Chroma failure.
