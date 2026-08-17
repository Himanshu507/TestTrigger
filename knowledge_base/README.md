# Knowledge Base

Synthetic evidence for planning and result analysis. Retrieval reads this
corpus; it is never the source of executable test IDs — that remains
`data/test_cases.json`.

## Layout

```text
knowledge_base/
  test_docs/            # what each catalogued test validates
  historical_failures/  # past failures with browser, region, and date
  jurisdiction_rules/   # regional constraints and their applicability
```

Each directory holds one or more `.json` files containing an array of
documents. Ingestion globs every `.json` under this tree, so adding a file is
enough to extend the corpus.

## Document schema

```json
{
  "source_id": "HIST-001",
  "type": "historical_failure",
  "content": "PAY-003 failed on Chrome in US on 2026-07-30: ...",
  "metadata": {"test_id": "PAY-003", "browser": "chrome", "region": "US"}
}
```

| Field | Rule |
| --- | --- |
| `source_id` | Unique across the whole corpus. Cited by the analyzer, so it must be stable. |
| `type` | One of `test_documentation`, `historical_failure`, `jurisdiction_rule`, `catalog_context`. |
| `content` | The text that is embedded and shown as evidence. |
| `metadata` | Type-specific filter keys. See below. |

## Required metadata by type

| Type | Required | Optional |
| --- | --- | --- |
| `test_documentation` | `test_id`, `module`, `scope` | — |
| `historical_failure` | `test_id`, `browser`, `region`, `date` | `failure` |
| `jurisdiction_rule` | `region`, `applies_to_modules` | `requirement` |

Every `test_id` must resolve to a catalog record, and a historical failure must
use a browser and region that the referenced test actually supports. Both rules
are enforced by `tests/unit/test_seed_data.py`, because evidence citing a test
the catalog cannot run would let an agent explain a result that never happened.

## Ingestion

```bash
uv run python scripts/ingest_knowledge_base.py
```

The script is idempotent: documents are upserted under their `source_id`, so
re-running it refreshes content without duplicating records.
