# Module 12 — Optional Code Analysis Agent

**Stories:** 4 optional stories

**Owns:** deterministic Python test-file checks, finding normalization, evidence-based AI review summary, and code-review API output.

**Depends on:** Foundation and Data, Result Analysis, API and Client Interface.
**Does not block:** the 50-story core workflow.

## Purpose

Review a submitted Python test file in a senior-engineer style while ensuring facts originate from deterministic static checks, not LLM intuition.

## Stories

| ID | Story | Acceptance criterion |
| --- | --- | --- |
| CAD-1 | Parse input safely and run deterministic test-quality checks. | Findings identify location and rule for `sleep()`, missing assertions, naming, duplication, hard-coded environment values, and fixture issues where detectable. |
| CAD-2 | Normalize findings into a stable schema. | Each finding has rule ID, severity, file/line span, observed evidence, and remediation hint. |
| CAD-3 | Add optional LLM review synthesis. | The model summarizes supplied findings only and labels suggestions separately from detected facts. |
| CAD-4 | Expose the code-review endpoint with safe error handling. | Unsupported files, parse failures, and unavailable LLMs return structured, useful output without executing user code. |

## Safety and scope

- Read files; do not execute submitted Python.
- Bound file size and supported paths to configured workspace scope.
- Static rules establish facts; the LLM only groups, prioritizes, and explains them.
- Return line-aware findings so a client can display actionable feedback.

## Why optional

It broadens the product story but does not advance the primary promise—natural-language intent through evidence-backed test execution. It should begin only after the core workflow is reliable and demonstrated.
