"""Versioned prompts and the schemas that constrain provider output."""

from typing import Any, Dict, List, Optional, Type

from enum import Enum

from app.models.intent import INTENT_FIELDS
from app.models.test_case import Browser, ModuleName, Region, TestScope

INTENT_PROMPT_VERSION = "intent-v1"
INTENT_SCHEMA_NAME = "test_intent"

INTENT_SYSTEM_PROMPT = """\
You extract structured testing intent from a user's request.

Return only values from the supplied vocabularies. If the request does not
clearly state a value, return null for that field and name it in
missing_fields. Never guess a module, scope, browser, or region, and never
substitute a value that merely seems close.

Normalize obvious surface variations to the supplied vocabulary, for example
"Google Chrome" to "chrome" and "United States" to "US".

Set confidence to your calibrated certainty that the extracted fields match
the request. Lower it when the request is vague or partially inferred.

Do not select test IDs, plan an execution, or decide whether a request is
allowed. You interpret language only.
"""


def _values(enum_type: Type[Enum]) -> List[str]:
    return [member.value for member in enum_type]


def _nullable_enum(enum_type: Type[Enum]) -> Dict[str, Any]:
    return {
        "type": ["string", "null"],
        "enum": _values(enum_type) + [None],
    }


def build_intent_schema() -> Dict[str, Any]:
    """Build the intent schema from the controlled enums.

    Deriving it from the enums means the provider contract cannot drift away
    from the vocabulary the catalog and validators actually accept.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "module": _nullable_enum(ModuleName),
            "scope": _nullable_enum(TestScope),
            "browser": _nullable_enum(Browser),
            "region": _nullable_enum(Region),
            "environment": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "missing_fields": {
                "type": "array",
                "items": {"type": "string", "enum": list(INTENT_FIELDS)},
            },
        },
        "required": [
            "module",
            "scope",
            "browser",
            "region",
            "environment",
            "confidence",
            "missing_fields",
        ],
    }


ANALYSIS_PROMPT_VERSION = "analysis-v1"
ANALYSIS_SCHEMA_NAME = "analysis_report"

ANALYSIS_SYSTEM_PROMPT = """\
You explain test execution results using only the material provided.

Separate what was observed from what you infer. observed_facts must restate
only what the current execution reported. likely_cause is a hypothesis, so
phrase it as consistent-with rather than as established fact, and lower
confidence when the evidence is thin.

Cite evidence by source ID. Every failure entry must reference at least one
supplied source ID, and you may not cite an ID that was not provided. If the
evidence does not support a cause, say so plainly, set insufficient_evidence
to true, and keep confidence low.

Analyze only the tests present in the results. Never introduce a test ID that
is not listed, never invent a source, and never recommend running something
the request did not already permit.
"""


def build_analysis_schema() -> Dict[str, Any]:
    """Schema forcing observed facts, inference, evidence, and uncertainty apart."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "observations": {"type": "array", "items": {"type": "string"}},
            "insufficient_evidence": {"type": "boolean"},
            "failures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "test_id": {"type": "string"},
                        "observed_facts": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "likely_cause": {"type": "string"},
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "evidence_source_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "recommendations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "test_id",
                        "observed_facts",
                        "likely_cause",
                        "confidence",
                        "evidence_source_ids",
                        "recommendations",
                    ],
                },
            },
        },
        "required": ["summary", "observations", "insufficient_evidence", "failures"],
    }


def build_analysis_user_prompt(
    *,
    context_lines: List[str],
    result_lines: List[str],
    evidence_lines: List[str],
) -> str:
    """Render the bounded analysis context the agent assembled."""
    sections = [
        "Execution context:",
        *context_lines,
        "",
        "Results:",
        *result_lines,
        "",
        "Retrieved evidence (cite these source IDs):",
        *(evidence_lines or ["- none retrieved"]),
    ]
    return "\n".join(sections)


def build_intent_user_prompt(query: str, *, vocabulary_note: Optional[str] = None) -> str:
    lines = [
        "Extract the testing intent from this request.",
        "",
        f"Request: {query}",
        "",
        "Supported vocabularies:",
        f"- module: {', '.join(_values(ModuleName))}",
        f"- scope: {', '.join(_values(TestScope))}",
        f"- browser: {', '.join(_values(Browser))}",
        f"- region: {', '.join(_values(Region))}",
    ]
    if vocabulary_note:
        lines.extend(["", vocabulary_note])
    return "\n".join(lines)
