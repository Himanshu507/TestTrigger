# Module 7 — Result Analysis

**Stories:** 5 MVP stories

**Owns:** collection-ready analysis inputs, evidence-grounded structured reasoning, observed-versus-inferred reporting, deterministic fallback summaries, and analysis report persistence.

**Depends on:** Foundation and Data, Knowledge Base and Retrieval, Mock Execution, Workflow Orchestration.
**Used by:** API and Client Interface.

## Purpose

Turn normalized execution outcomes into a useful report without letting an LLM fabricate root causes. The analyzer augments results; it is never allowed to erase them.

## Structured output

```json
{
  "summary": "1 of 4 tests failed.",
  "failures": [
    {
      "test_id": "PAY-003",
      "observed_facts": ["Current execution timed out during 3DS redirect"],
      "likely_cause": "A 3DS redirect timeout is consistent with the observed failure.",
      "confidence": 0.82,
      "evidence_source_ids": ["history:PAY-003:2026-07-30"],
      "recommendations": ["Review gateway timeout configuration"]
    }
  ]
}
```

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| ANL-1 | Assemble bounded, typed analysis context. | Inputs include results, test documentation, historical evidence, and execution context only. |
| ANL-2 | Create a versioned grounded-analysis prompt and output schema. | The model must distinguish observed facts, inference, uncertainty, evidence IDs, and recommendations. |
| ANL-3 | Validate and reject unsupported analysis claims. | An output without evidence attribution or with an unknown test ID is not accepted as grounded. |
| ANL-4 | Produce deterministic fallback summary. | Provider timeout/format failure still returns pass/fail counts and raw failure reasons. |
| ANL-5 | Persist report, provider metadata, and fallback status. | Workflow inspection shows whether analysis is AI-generated or fallback, without secrets. |

## Grounding policy

- Use only provided current results and retrieved evidence.
- Do not state a root cause as fact when evidence supports only a hypothesis.
- Cite source IDs in structured output; human text may render friendly evidence labels.
- Explicitly say when evidence is insufficient.
- Never recommend an execution or retry that violates deterministic policy.

## Boundaries

The analyzer does not change job status, select additional tests, modify raw results, or approve an execution plan.

## Tests

Cover all-pass reports, one/multiple failure reports, missing historical evidence, malformed model output, timeout fallback, unknown test IDs, and report persistence.
