from typing import Any, Dict, Optional

import pytest

from app.agents.intent import (
    AGENT_NAME,
    ClarificationReason,
    ClarificationRequired,
    IntentAgent,
)
from app.db.database import Database
from app.db.repositories import WorkflowRepository
from app.llm.errors import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.llm.provider import LLMProvider
from app.models.intent import TestIntent
from app.models.test_case import Browser, ModuleName, Region, TestScope
from app.models.workflow import AgentRunStatus

QUERY = "Run smoke tests for the payment module on Google Chrome in the US region"
WORKFLOW_ID = "WF-1001"


class FakeProvider(LLMProvider):
    """Returns a canned payload or raises a canned provider error."""

    def __init__(
        self, payload: Optional[Any] = None, error: Optional[Exception] = None
    ) -> None:
        self.payload = payload
        self.error = error
        self.calls: list = []

    def extract_structured(self, **kwargs) -> Dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.payload


def _payload(**overrides) -> Dict[str, Any]:
    payload = {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
        "environment": None,
        "confidence": 0.95,
        "missing_fields": [],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def repository(tmp_path) -> WorkflowRepository:
    created = WorkflowRepository(Database(tmp_path / "test-trigger.db"))
    created.initialize()
    created.create_workflow(workflow_id=WORKFLOW_ID, query=QUERY, dry_run=False)
    return created


def test_successful_extraction_produces_an_actionable_intent() -> None:
    agent = IntentAgent(FakeProvider(_payload()))

    intent = agent.parse_intent(QUERY)

    assert isinstance(intent, TestIntent)
    assert intent.module is ModuleName.PAYMENT
    assert intent.scope is TestScope.SMOKE
    assert intent.browser is Browser.CHROME
    assert intent.region is Region.US
    assert intent.is_actionable is True
    assert intent.missing_fields == []


def test_provider_receives_the_schema_and_the_versioned_prompt() -> None:
    provider = FakeProvider(_payload())

    IntentAgent(provider).parse_intent(QUERY)

    call = provider.calls[0]
    assert call["schema"]["properties"]["browser"]["enum"] == [
        "chrome",
        "firefox",
        "safari",
        None,
    ]
    assert "never guess" in call["system_prompt"].lower()
    assert QUERY in call["user_prompt"]


def test_surface_variations_are_normalized_to_catalog_values() -> None:
    agent = IntentAgent(
        FakeProvider(_payload(browser="Google Chrome", region="United States"))
    )

    intent = agent.parse_intent(QUERY)

    assert intent.browser is Browser.CHROME
    assert intent.region is Region.US


def test_unsupported_values_are_never_coerced_to_a_close_match() -> None:
    agent = IntentAgent(FakeProvider(_payload(browser="edge")))

    outcome = agent.parse_intent("Run payment smoke tests on Edge in the US")

    assert isinstance(outcome, ClarificationRequired)
    assert outcome.reason is ClarificationReason.UNSUPPORTED_VALUE
    assert outcome.unsupported_values == {"browser": "edge"}
    assert "browser" in outcome.missing_fields


def test_missing_required_fields_request_clarification_and_keep_the_query() -> None:
    agent = IntentAgent(
        FakeProvider(_payload(browser=None, region=None, missing_fields=["browser"]))
    )

    outcome = agent.parse_intent("Run payment smoke tests")

    assert isinstance(outcome, ClarificationRequired)
    assert outcome.reason is ClarificationReason.MISSING_FIELDS
    assert outcome.missing_fields == ["browser", "region"]
    assert outcome.query == "Run payment smoke tests"


def test_confidence_below_the_configured_threshold_blocks_the_intent() -> None:
    payload = _payload(confidence=0.4)

    assert isinstance(
        IntentAgent(FakeProvider(payload), confidence_threshold=0.8).parse_intent(QUERY),
        ClarificationRequired,
    )
    assert isinstance(
        IntentAgent(FakeProvider(payload), confidence_threshold=0.3).parse_intent(QUERY),
        TestIntent,
    )


def test_low_confidence_clarification_names_the_threshold() -> None:
    agent = IntentAgent(FakeProvider(_payload(confidence=0.2)), confidence_threshold=0.7)

    outcome = agent.parse_intent(QUERY)

    assert outcome.reason is ClarificationReason.LOW_CONFIDENCE
    assert "0.7" in outcome.detail


@pytest.mark.parametrize(
    "error",
    [
        ProviderTimeoutError("provider timed out after 30.0s"),
        ProviderUnavailableError("provider call failed"),
        ProviderResponseError("provider returned malformed JSON"),
    ],
)
def test_provider_failure_becomes_a_typed_outcome_not_a_guess(error) -> None:
    agent = IntentAgent(FakeProvider(error=error))

    outcome = agent.parse_intent(QUERY)

    assert isinstance(outcome, ClarificationRequired)
    assert outcome.reason is ClarificationReason.PROVIDER_ERROR
    assert outcome.query == QUERY
    assert outcome.missing_fields == ["module", "scope", "browser", "region"]


def test_malformed_provider_payload_is_rejected() -> None:
    agent = IntentAgent(FakeProvider(_payload(confidence=7.5)))

    outcome = agent.parse_intent(QUERY)

    assert isinstance(outcome, ClarificationRequired)
    assert outcome.reason is ClarificationReason.INVALID_OUTPUT


def test_non_object_provider_payload_is_rejected() -> None:
    outcome = IntentAgent(FakeProvider(["not", "an", "object"])).parse_intent(QUERY)

    assert isinstance(outcome, ClarificationRequired)
    assert outcome.reason is ClarificationReason.INVALID_OUTPUT


def test_empty_query_never_reaches_the_provider() -> None:
    provider = FakeProvider(_payload())

    outcome = IntentAgent(provider).parse_intent("   ")

    assert isinstance(outcome, ClarificationRequired)
    assert outcome.reason is ClarificationReason.EMPTY_QUERY
    assert provider.calls == []


def test_successful_parse_is_persisted_as_a_completed_agent_run(
    repository: WorkflowRepository,
) -> None:
    agent = IntentAgent(FakeProvider(_payload()), repository=repository)

    agent.parse_intent(QUERY, workflow_id=WORKFLOW_ID)

    runs = repository.list_agent_runs(WORKFLOW_ID)
    assert len(runs) == 1
    assert runs[0].agent_name == AGENT_NAME
    assert runs[0].status is AgentRunStatus.COMPLETED
    assert runs[0].input_payload["query"] == QUERY
    assert runs[0].input_payload["prompt_version"] == "intent-v1"
    assert runs[0].output_payload["module"] == "payment"


def test_provider_failure_is_persisted_as_a_failed_agent_run(
    repository: WorkflowRepository,
) -> None:
    agent = IntentAgent(
        FakeProvider(error=ProviderTimeoutError("timed out")), repository=repository
    )

    agent.parse_intent(QUERY, workflow_id=WORKFLOW_ID)

    run = repository.list_agent_runs(WORKFLOW_ID)[0]
    assert run.status is AgentRunStatus.FAILED
    assert run.error == "timed out"
    assert run.output_payload["reason"] == "provider_error"


def test_clarification_is_persisted_so_the_api_can_explain_it(
    repository: WorkflowRepository,
) -> None:
    agent = IntentAgent(
        FakeProvider(_payload(region=None)), repository=repository
    )

    agent.parse_intent(QUERY, workflow_id=WORKFLOW_ID)

    run = repository.list_agent_runs(WORKFLOW_ID)[0]
    assert run.status is AgentRunStatus.COMPLETED
    assert run.output_payload["reason"] == "missing_fields"
    assert run.output_payload["missing_fields"] == ["region"]


def test_agent_runs_without_a_repository(tmp_path) -> None:
    agent = IntentAgent(FakeProvider(_payload()))

    assert isinstance(agent.parse_intent(QUERY, workflow_id=WORKFLOW_ID), TestIntent)
