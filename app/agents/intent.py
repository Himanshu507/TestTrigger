"""Intent Agent: natural language to a validated TestIntent.

The agent extracts meaning only. It never selects tests, scores risk, decides
policy, or triggers execution.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, ValidationError

from app.agents.normalization import (
    normalize_browser,
    normalize_module,
    normalize_region,
    normalize_scope,
)
from app.db.repositories import WorkflowRepository
from app.llm.errors import ProviderError
from app.llm.prompts import (
    INTENT_PROMPT_VERSION,
    INTENT_SCHEMA_NAME,
    INTENT_SYSTEM_PROMPT,
    build_intent_schema,
    build_intent_user_prompt,
)
from app.llm.provider import LLMProvider
from app.models.intent import TestIntent
from app.models.test_case import Browser, ModuleName, Region, TestScope
from app.models.workflow import AgentRunStatus

AGENT_NAME = "intent"
REQUIRED_FIELDS = ("module", "scope", "browser", "region")
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

_VOCABULARIES = {
    "module": ModuleName,
    "scope": TestScope,
    "browser": Browser,
    "region": Region,
}

_NORMALIZERS = {
    "module": normalize_module,
    "scope": normalize_scope,
    "browser": normalize_browser,
    "region": normalize_region,
}


class ClarificationReason(str, Enum):
    """Why a request could not become an executable intent."""

    EMPTY_QUERY = "empty_query"
    MISSING_FIELDS = "missing_fields"
    UNSUPPORTED_VALUE = "unsupported_value"
    LOW_CONFIDENCE = "low_confidence"
    PROVIDER_ERROR = "provider_error"
    INVALID_OUTPUT = "invalid_output"


class ClarificationRequired(BaseModel):
    """A typed non-answer that preserves the query and explains the gap.

    Returning this instead of a guess is what keeps an unparsed request from
    silently becoming an execution.
    """

    query: str
    reason: ClarificationReason
    detail: str = Field(min_length=1)
    missing_fields: List[str] = Field(default_factory=list)
    unsupported_values: Dict[str, str] = Field(default_factory=dict)


IntentOutcome = Union[TestIntent, ClarificationRequired]


class IntentAgent:
    """Converts a query into a `TestIntent` or a typed clarification request."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        repository: Optional[WorkflowRepository] = None,
    ) -> None:
        self._provider = provider
        self._confidence_threshold = confidence_threshold
        self._repository = repository

    def parse_intent(
        self, query: str, *, workflow_id: Optional[str] = None
    ) -> IntentOutcome:
        """Extract intent, or explain why clarification is required."""
        if not query or not query.strip():
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.EMPTY_QUERY,
                detail="the request was empty",
                missing_fields=list(REQUIRED_FIELDS),
            )

        try:
            raw = self._provider.extract_structured(
                system_prompt=INTENT_SYSTEM_PROMPT,
                user_prompt=build_intent_user_prompt(query),
                schema=build_intent_schema(),
                schema_name=INTENT_SCHEMA_NAME,
            )
        except ProviderError as error:
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.PROVIDER_ERROR,
                detail=f"intent extraction failed: {error}",
                missing_fields=list(REQUIRED_FIELDS),
                error=str(error),
            )

        if not isinstance(raw, dict):
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.INVALID_OUTPUT,
                detail="provider output was not an object",
                missing_fields=list(REQUIRED_FIELDS),
            )

        normalized, unsupported = _normalize_fields(raw)
        missing = [name for name in REQUIRED_FIELDS if normalized.get(name) is None]

        try:
            intent = TestIntent(
                **normalized,
                environment=_clean_environment(raw.get("environment")),
                confidence=raw.get("confidence", 0.0),
                missing_fields=missing,
            )
        except ValidationError as error:
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.INVALID_OUTPUT,
                detail=f"provider output failed validation: {error.error_count()} errors",
                missing_fields=list(REQUIRED_FIELDS),
                error=str(error),
            )

        if unsupported:
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.UNSUPPORTED_VALUE,
                detail=
                "the request named values outside the supported vocabulary: "
                + ", ".join(f"{field}={value!r}" for field, value in unsupported.items()),
                missing_fields=missing,
                unsupported_values=unsupported,
            )

        if not intent.is_actionable:
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.MISSING_FIELDS,
                detail="the request did not state a supported "
                + "; ".join(_supported_hint(field) for field in missing),
                missing_fields=missing,
            )

        if intent.confidence < self._confidence_threshold:
            return self._clarify(
                query=query,
                workflow_id=workflow_id,
                reason=ClarificationReason.LOW_CONFIDENCE,
                detail=(
                    f"confidence {intent.confidence} is below the configured "
                    f"threshold {self._confidence_threshold}"
                ),
                missing_fields=missing,
            )

        self._record(
            workflow_id,
            query,
            status=AgentRunStatus.COMPLETED,
            output=intent.model_dump(mode="json"),
        )
        return intent

    def _clarify(
        self,
        *,
        query: str,
        workflow_id: Optional[str],
        reason: ClarificationReason,
        detail: str,
        missing_fields: List[str],
        unsupported_values: Optional[Dict[str, str]] = None,
        error: Optional[str] = None,
    ) -> ClarificationRequired:
        clarification = ClarificationRequired(
            query=query,
            reason=reason,
            detail=detail,
            missing_fields=missing_fields,
            unsupported_values=unsupported_values or {},
        )
        self._record(
            workflow_id,
            query,
            status=(
                AgentRunStatus.FAILED
                if reason is ClarificationReason.PROVIDER_ERROR
                else AgentRunStatus.COMPLETED
            ),
            output=clarification.model_dump(mode="json"),
            error=error,
        )
        return clarification

    def _record(
        self,
        workflow_id: Optional[str],
        query: str,
        *,
        status: AgentRunStatus,
        output: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        """Persist the agent run so a workflow detail response can explain it."""
        if self._repository is None or workflow_id is None:
            return
        self._repository.record_agent_run(
            workflow_id=workflow_id,
            agent_name=AGENT_NAME,
            status=status,
            input_payload={"query": query, "prompt_version": INTENT_PROMPT_VERSION},
            output_payload=output,
            error=error,
        )


def _supported_hint(field: str) -> str:
    """Name a missing field alongside the values that would satisfy it.

    A field can read as missing either because the request omitted it or
    because the value it named is outside the vocabulary, and the schema
    prevented the model from echoing it back. Listing the supported values
    answers both cases without guessing which one occurred.
    """
    vocabulary = _VOCABULARIES.get(field)
    if vocabulary is None:
        return field
    return f"{field} ({', '.join(member.value for member in vocabulary)})"


def _normalize_fields(raw: Dict[str, Any]) -> tuple:
    """Resolve raw values to controlled members, collecting unsupported ones."""
    normalized: Dict[str, Any] = {}
    unsupported: Dict[str, str] = {}

    for field, normalizer in _NORMALIZERS.items():
        value = raw.get(field)
        if value is not None and not isinstance(value, str):
            unsupported[field] = str(value)
            normalized[field] = None
            continue

        resolved = normalizer(value)
        normalized[field] = resolved
        if value is not None and resolved is None and value.strip():
            unsupported[field] = value

    return normalized, unsupported


def _clean_environment(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None
