# Module 3 — Intent Understanding

**Stories:** 5 MVP stories

**Owns:** natural-language extraction, provider-backed structured output, normalization, missing-field detection, and intent-agent audit records.

**Depends on:** Foundation and Data.
**Used by:** Retrieval, Planning and Policy, Workflow Orchestration.

## Purpose

Turn a natural-language request into a trusted `TestIntent` contract without selecting tests or triggering execution.

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

## Public interfaces

- `parse_intent(query) -> TestIntent | ClarificationRequired`
- An OpenAI-backed provider interface with structured-output capability, timeout, provider error mapping, and a future provider seam.
- A normalization/validation adapter that checks vocabulary against controlled catalog values.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| INT-1 | Define a strict `TestIntent` output schema and prompt contract. | Provider output missing required semantic fields cannot reach the planner. |
| INT-2 | Implement configurable LLM structured extraction. | A selected provider yields a parsed schema or a typed provider/format error. |
| INT-3 | Normalize approved synonyms. | Examples such as `Google Chrome` resolve to `chrome` without accepting unknown browsers. |
| INT-4 | Detect ambiguous or missing required intent. | The workflow reaches `NEEDS_CLARIFICATION` with specific missing fields and preserves the query. |
| INT-5 | Persist intent-agent inputs, outputs, timing, and errors. | A workflow detail response explains whether parsing succeeded, failed, or needs input. |

## Rules

- The agent may infer only clearly supported values; it must not invent a module, browser, region, or test ID.
- Structured output is validated twice: provider schema parsing, then controlled-vocabulary validation.
- A low confidence score alone is not authorization to execute; the graph applies an explicit configurable threshold or asks for clarification.
- LLM failure produces a typed workflow outcome, never a hidden fallback guess.
- The provider reads `OPENAI_API_KEY` in the backend process only; the local chat UI never calls it directly.

## Boundaries

This agent owns meaning extraction, not retrieval relevance, policy, risk scoring, plan selection, or mock CI interaction.

## Tests

Use provider fakes for successful extraction, synonyms, unknown values, absent module/scope, timeout, malformed JSON, and audit persistence.
