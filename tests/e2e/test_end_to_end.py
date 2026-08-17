"""End-to-end paths through the HTTP API.

Everything below the API is real: the catalog, ChromaDB, SQLite, the policy
service, and the mock CI system. Only the LLM boundary is replaced, so these
prove the whole product without a live paid provider.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents.analysis import ResultAnalyzer
from app.agents.execution import ExecutionAgent
from app.agents.intent import IntentAgent
from app.agents.retrieval import RetrievalAgent
from app.api.main import create_app
from app.catalog import TestCatalog
from app.config import AppSettings
from app.db.database import Database
from app.db.repositories import (
    AnalysisRepository,
    EventRepository,
    ExecutionRepository,
    PlanRepository,
    WorkflowRepository,
)
from app.integrations.mock_jenkins import MockJenkinsService
from app.knowledge.ingest import ingest
from app.llm.errors import ProviderTimeoutError
from app.llm.provider import LLMProvider
from app.orchestration.dependencies import WorkflowDependencies
from app.retrieval.store import ChromaVectorStore
from app.services.planning_service import PlanningService
from tests.fakes import HashingEmbedder

SETTINGS = AppSettings.from_environment({})


class ScriptedProvider(LLMProvider):
    """Replays intent then analysis payloads, or raises a recorded error."""

    def __init__(self, *payloads, error: Exception = None) -> None:
        self.payloads = list(payloads)
        self.error = error
        self.calls = 0

    def extract_structured(self, *, schema_name: str, **kwargs) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if not self.payloads:
            raise AssertionError(f"no scripted payload left for {schema_name}")
        return self.payloads.pop(0)


def _intent(**overrides) -> dict:
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


def _analysis(**overrides) -> dict:
    payload = {
        "summary": "Execution finished.",
        "observations": ["all planned tests reported"],
        "insufficient_evidence": False,
        "failures": [],
    }
    payload.update(overrides)
    return payload


def _client(tmp_path, provider, *, jenkins=None) -> TestClient:
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()
    workflows = WorkflowRepository(database)
    catalog = TestCatalog.load_default()

    store = ChromaVectorStore(str(tmp_path / "chroma"), collection_name="e2e")
    ingest(store, HashingEmbedder())

    jenkins = jenkins or MockJenkinsService(seed="e2e")
    dependencies = WorkflowDependencies(
        intent_agent=IntentAgent(provider, repository=workflows),
        retrieval_agent=RetrievalAgent(
            store, HashingEmbedder(), catalog, repository=workflows
        ),
        planning_service=PlanningService(
            catalog, repository=workflows, plan_repository=PlanRepository(database)
        ),
        execution_agent=ExecutionAgent(
            jenkins, ExecutionRepository(database), repository=workflows
        ),
        workflows=workflows,
        events=EventRepository(database),
        analysis=AnalysisRepository(database),
        analyzer=ResultAnalyzer(
            provider, provider_model="gpt-test", repository=workflows
        ),
    )
    application = create_app(
        SETTINGS, dependencies=dependencies, vector_store=store, jenkins=jenkins
    )
    return TestClient(application, raise_server_exceptions=False)


def _submit(client, query: str, **body):
    return client.post("/api/v1/workflows", json={"query": query, **body})


def test_the_happy_path_runs_and_explains_itself(tmp_path) -> None:
    client = _client(tmp_path, ScriptedProvider(_intent(), _analysis()))

    created = _submit(
        client, "Run smoke tests for the payment module on Chrome in the US region"
    )

    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "completed"

    detail = client.get(f"/api/v1/workflows/{body['workflow_id']}").json()
    assert detail["intent"]["module"] == "payment"
    assert detail["retrieval"]["sources"]
    assert [test["test_id"] for test in detail["plan"]["tests"]] == ["PAY-003", "PAY-001"]
    assert len(detail["execution"]["results"]) == 2
    assert detail["analysis"]["status"] == "ai_generated"

    steps = [event["step"] for event in detail["timeline"]]
    assert steps[0] == "workflow"
    assert "retrieval" in steps and "planning" in steps and "analysis" in steps


def test_an_unsupported_browser_never_reaches_execution(tmp_path) -> None:
    """Safari is not supported for the Nevada payment smoke test."""
    client = _client(
        tmp_path, ScriptedProvider(_intent(browser="safari", region="US-Nevada"))
    )

    response = _submit(client, "Run payment smoke tests on Safari in Nevada")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] in {"NO_TESTS_SELECTED", "JURISDICTION_VIOLATION"}

    detail = client.get(f"/api/v1/workflows/{error['workflow_id']}").json()
    assert detail["status"] == "rejected"
    assert detail["execution"] is None


def test_an_empty_plan_is_rejected_with_a_reason(tmp_path) -> None:
    client = _client(
        tmp_path, ScriptedProvider(_intent(module="login", region="US-Nevada"))
    )

    response = _submit(client, "Run login smoke tests on Chrome in Nevada")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_TESTS_SELECTED"


def test_a_ci_failure_keeps_the_plan_and_reports_503(tmp_path) -> None:
    client = _client(
        tmp_path,
        ScriptedProvider(_intent(), _analysis()),
        jenkins=MockJenkinsService(force_job_failure=True),
    )

    response = _submit(client, "Run payment smoke tests on Chrome in US")

    assert response.status_code == 503
    workflow_id = response.json()["error"]["workflow_id"]

    detail = client.get(f"/api/v1/workflows/{workflow_id}").json()
    assert detail["status"] == "execution_failed"
    assert detail["plan"]["tests"], "a validated plan must survive a CI failure"
    assert detail["analysis"] is None


def test_an_llm_outage_still_completes_with_observed_facts(tmp_path) -> None:
    """Intent parses, then the provider dies before analysis."""

    class FailingAfterIntent(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0

        def extract_structured(self, **kwargs) -> dict:
            self.calls += 1
            if self.calls == 1:
                return _intent()
            raise ProviderTimeoutError("analysis timed out")

    client = _client(tmp_path, FailingAfterIntent())

    response = _submit(client, "Run payment smoke tests on Chrome in US")

    assert response.status_code == 201
    detail = client.get(f"/api/v1/workflows/{response.json()['workflow_id']}").json()

    assert detail["status"] == "completed"
    assert detail["analysis"]["status"] == "fallback"
    assert "analysis timed out" in detail["analysis"]["fallback_reason"]
    assert len(detail["execution"]["results"]) == 2, "results must survive the outage"
    assert detail["analysis"]["observations"]


def test_an_unparseable_request_asks_for_clarification(tmp_path) -> None:
    client = _client(
        tmp_path, ScriptedProvider(_intent(browser=None, region=None))
    )

    response = _submit(client, "Run some tests")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "NEEDS_CLARIFICATION"
    assert {detail["field"] for detail in error["details"]} == {"browser", "region"}


def test_a_dry_run_plans_without_executing(tmp_path) -> None:
    client = _client(tmp_path, ScriptedProvider(_intent()))

    response = _submit(client, "Run payment smoke tests on Chrome in US", dry_run=True)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "dry_run_complete"
    assert body["execution_id"] is None

    detail = client.get(f"/api/v1/workflows/{body['workflow_id']}").json()
    assert detail["plan"]["tests"]
    assert detail["execution"] is None


def test_an_ungrounded_explanation_is_refused_end_to_end(tmp_path) -> None:
    client = _client(
        tmp_path,
        ScriptedProvider(
            _intent(),
            _analysis(
                failures=[
                    {
                        "test_id": "WAL-002",
                        "observed_facts": ["invented"],
                        "likely_cause": "invented",
                        "confidence": 0.99,
                        "evidence_source_ids": ["HIST-001"],
                        "recommendations": [],
                    }
                ]
            ),
        ),
    )

    response = _submit(client, "Run payment smoke tests on Chrome in US")
    detail = client.get(f"/api/v1/workflows/{response.json()['workflow_id']}").json()

    assert detail["status"] == "completed"
    assert detail["analysis"]["status"] == "fallback"
    assert detail["analysis"]["failures"] == []


def test_a_retry_with_the_same_key_does_not_run_twice(tmp_path) -> None:
    client = _client(tmp_path, ScriptedProvider(_intent(), _analysis()))
    headers = {"Idempotency-Key": "e2e-key"}
    query = "Run payment smoke tests on Chrome in US"

    first = client.post("/api/v1/workflows", json={"query": query}, headers=headers)
    second = client.post("/api/v1/workflows", json={"query": query}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["execution_id"] == first.json()["execution_id"]


@pytest.mark.parametrize(
    "query,expected_status",
    [
        ("Run payment smoke tests on Chrome in US", 201),
        ("", 400),
    ],
)
def test_input_validation_boundaries(tmp_path, query, expected_status) -> None:
    client = _client(tmp_path, ScriptedProvider(_intent(), _analysis()))

    assert _submit(client, query).status_code == expected_status
