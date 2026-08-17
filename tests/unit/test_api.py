import pytest
from fastapi.testclient import TestClient

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
from app.orchestration.dependencies import WorkflowDependencies
from app.retrieval.store import ChromaVectorStore
from app.services.planning_service import PlanningService
from tests.fakes import HashingEmbedder
from tests.unit.test_intent_agent import FakeProvider

QUERY = "Run smoke tests for the payment module on Chrome in the US region"
SETTINGS = AppSettings.from_environment({"FRONTEND_ORIGIN": "http://localhost:5173"})


def _intent_payload(**overrides) -> dict:
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


def _client(
    tmp_path,
    *,
    intent_payload=None,
    intent_error=None,
    jenkins=None,
    seed_store: bool = True,
) -> TestClient:
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()
    workflows = WorkflowRepository(database)
    catalog = TestCatalog.load_default()

    store = ChromaVectorStore(str(tmp_path / "chroma"), collection_name="api_test")
    if seed_store:
        ingest(store, HashingEmbedder())

    jenkins = jenkins or MockJenkinsService(seed="demo")
    dependencies = WorkflowDependencies(
        intent_agent=IntentAgent(
            FakeProvider(
                payload=intent_payload if intent_error is None else None,
                error=intent_error,
            ),
            repository=workflows,
        ),
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
    )
    application = create_app(
        SETTINGS, dependencies=dependencies, vector_store=store, jenkins=jenkins
    )
    return TestClient(application, raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path) -> TestClient:
    return _client(tmp_path, intent_payload=_intent_payload())


def test_a_valid_request_creates_and_runs_a_workflow(client) -> None:
    response = client.post("/api/v1/workflows", json={"query": QUERY})

    assert response.status_code == 201
    body = response.json()
    assert body["workflow_id"] == "WF-1001"
    assert body["status"] == "completed"
    assert body["execution_id"].startswith("JOB-")
    assert body["summary"]


def test_a_dry_run_reports_a_plan_without_a_job(client) -> None:
    response = client.post(
        "/api/v1/workflows", json={"query": QUERY, "dry_run": True}
    )

    assert response.status_code == 201
    assert response.json()["status"] == "dry_run_complete"
    assert response.json()["execution_id"] is None


def test_an_empty_query_returns_the_documented_error_shape(client) -> None:
    response = client.post("/api/v1/workflows", json={"query": ""})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "MALFORMED_REQUEST"
    assert error["details"][0]["field"] == "query"


def test_a_missing_query_is_rejected(client) -> None:
    assert client.post("/api/v1/workflows", json={}).status_code == 400


def test_an_unparseable_request_returns_422_with_the_workflow_id(tmp_path) -> None:
    client = _client(
        tmp_path, intent_payload=_intent_payload(browser=None, region=None)
    )

    response = client.post("/api/v1/workflows", json={"query": "Run some tests"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "NEEDS_CLARIFICATION"
    assert error["workflow_id"] == "WF-1001"
    assert {detail["field"] for detail in error["details"]} == {"browser", "region"}


def test_a_workflow_remains_retrievable_after_a_4xx(tmp_path) -> None:
    client = _client(tmp_path, intent_payload=_intent_payload(browser=None))
    client.post("/api/v1/workflows", json={"query": "Run some tests"})

    detail = client.get("/api/v1/workflows/WF-1001")

    assert detail.status_code == 200
    assert detail.json()["status"] == "needs_clarification"


def test_a_policy_rejection_returns_422_with_violation_codes(tmp_path) -> None:
    client = _client(
        tmp_path,
        intent_payload=_intent_payload(module="login", region="US-Nevada"),
    )

    response = client.post(
        "/api/v1/workflows", json={"query": "Run login smoke tests in Nevada"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_TESTS_SELECTED"


def test_an_execution_failure_maps_to_503(tmp_path) -> None:
    client = _client(
        tmp_path,
        intent_payload=_intent_payload(),
        jenkins=MockJenkinsService(force_job_failure=True),
    )

    response = client.post("/api/v1/workflows", json={"query": QUERY})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXECUTION_UNAVAILABLE"


def test_a_retrieval_failure_maps_to_424(tmp_path) -> None:
    client = _client(tmp_path, intent_payload=_intent_payload(), seed_store=True)
    client.app.state.runner._dependencies.retrieval_agent = _BrokenRetrieval()

    response = client.post("/api/v1/workflows", json={"query": QUERY})

    assert response.status_code == 424
    assert response.json()["error"]["code"] == "RETRIEVAL_UNAVAILABLE"


class _BrokenRetrieval:
    def retrieve(self, intent, *, workflow_id=None):
        from app.agents.retrieval import RetrievalError

        raise RetrievalError("store unavailable")


def test_a_provider_outage_does_not_leak_internals(tmp_path) -> None:
    client = _client(tmp_path, intent_error=ProviderTimeoutError("timed out"))

    response = client.post("/api/v1/workflows", json={"query": QUERY})

    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "api_key" not in response.text.lower()


def test_a_repeated_idempotency_key_replays_the_original_workflow(client) -> None:
    headers = {"Idempotency-Key": "client-key-1"}

    first = client.post("/api/v1/workflows", json={"query": QUERY}, headers=headers)
    second = client.post("/api/v1/workflows", json={"query": QUERY}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["workflow_id"] == first.json()["workflow_id"]
    assert second.json()["execution_id"] == first.json()["execution_id"]


def test_reusing_a_key_for_a_different_request_is_a_conflict(client) -> None:
    headers = {"Idempotency-Key": "client-key-1"}
    client.post("/api/v1/workflows", json={"query": QUERY}, headers=headers)

    response = client.post(
        "/api/v1/workflows", json={"query": "A different request"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_REQUEST"


def test_workflow_detail_exposes_every_stage(client) -> None:
    created = client.post("/api/v1/workflows", json={"query": QUERY}).json()

    detail = client.get(f"/api/v1/workflows/{created['workflow_id']}").json()

    assert detail["query"] == QUERY
    assert detail["intent"]["module"] == "payment"
    assert detail["retrieval"]["sources"]
    assert [test["test_id"] for test in detail["plan"]["tests"]]
    assert detail["plan"]["tests"][0]["reasons"]
    assert detail["execution"]["execution_id"].startswith("JOB-")
    assert len(detail["execution"]["results"]) == 2
    assert detail["analysis"]["summary"]
    assert detail["timeline"]


def test_workflow_detail_omits_stages_that_did_not_run(tmp_path) -> None:
    client = _client(tmp_path, intent_payload=_intent_payload(browser=None))
    client.post("/api/v1/workflows", json={"query": "Run tests"})

    detail = client.get("/api/v1/workflows/WF-1001").json()

    assert detail["plan"] is None
    assert detail["execution"] is None
    assert detail["analysis"] is None


def test_detail_does_not_republish_retrieved_content(client) -> None:
    created = client.post("/api/v1/workflows", json={"query": QUERY}).json()

    detail = client.get(f"/api/v1/workflows/{created['workflow_id']}").json()

    assert set(detail["retrieval"]) == {"sources"}
    assert all(source.count(" ") == 0 for source in detail["retrieval"]["sources"])


def test_an_unknown_workflow_returns_404(client) -> None:
    response = client.get("/api/v1/workflows/WF-4040")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"


def test_events_are_ordered_and_identified(client) -> None:
    created = client.post("/api/v1/workflows", json={"query": QUERY}).json()

    body = client.get(f"/api/v1/workflows/{created['workflow_id']}/events").json()

    steps = [event["step"] for event in body["events"]]
    assert steps[0] == "workflow"
    assert steps[-1] == "workflow"
    assert "retrieval" in steps
    assert body["events"][0]["event_id"].startswith("EV-")
    assert all(event["occurred_at"] for event in body["events"])


def test_events_for_an_unknown_workflow_return_404(client) -> None:
    assert client.get("/api/v1/workflows/WF-4040/events").status_code == 404


def test_a_finished_job_cannot_be_cancelled(client) -> None:
    created = client.post("/api/v1/workflows", json={"query": QUERY}).json()

    response = client.post(f"/api/v1/workflows/{created['workflow_id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_CANCELLABLE"


def test_cancelling_a_workflow_without_a_job_is_a_conflict(tmp_path) -> None:
    client = _client(tmp_path, intent_payload=_intent_payload())
    client.post("/api/v1/workflows", json={"query": QUERY, "dry_run": True})

    response = client.post("/api/v1/workflows/WF-1001/cancel")

    assert response.status_code == 409


def test_cancelling_an_unknown_workflow_returns_404(client) -> None:
    assert client.post("/api/v1/workflows/WF-4040/cancel").status_code == 404


def test_an_active_job_can_be_cancelled(tmp_path) -> None:
    from app.integrations.mock_jenkins import build_job_request

    client = _client(tmp_path, intent_payload=_intent_payload())
    client.post("/api/v1/workflows", json={"query": QUERY, "dry_run": True})

    jenkins = client.app.state.jenkins
    job = jenkins.submit(
        build_job_request(test_ids=["PAY-001"], browser="chrome", region="US")
    )
    executions = ExecutionRepository(client.app.state.workflows.database)
    executions.create_execution(
        workflow_id="WF-1001", external_job_id=job.job_id, idempotency_key="key-1"
    )

    response = client.post("/api/v1/workflows/WF-1001/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert jenkins.get(job.job_id).status.value == "cancelled"


def test_health_reports_dependency_readiness(client) -> None:
    body = client.get("/health").json()

    assert body["status"] == "ready"
    names = {dependency["name"] for dependency in body["dependencies"]}
    assert {"sqlite", "chromadb", "mock_jenkins"} <= names
    assert all(dependency["ready"] for dependency in body["dependencies"])


def test_health_never_exposes_connection_details(client) -> None:
    """Naming the variable is fine and useful; revealing its value is not."""
    text = client.get("/health").text

    assert "sqlite:///" not in text
    assert "/chroma" not in text
    assert "sk-" not in text
    assert "test-key" not in text


def test_health_reports_feature_status_when_no_key_is_configured(client) -> None:
    features = {
        feature["name"]: feature for feature in client.get("/health").json()["features"]
    }

    assert set(features) == {
        "intent_extraction",
        "semantic_retrieval",
        "ai_result_analysis",
    }
    assert all(feature["enabled"] is False for feature in features.values())
    assert "deterministic summary" in features["ai_result_analysis"]["detail"]


def test_health_reports_features_as_enabled_once_a_key_is_present(tmp_path) -> None:
    from app.api.service import check_features

    configured = AppSettings.from_environment({"OPENAI_API_KEY": "test-key"})

    features = check_features(configured)

    assert all(feature.enabled for feature in features)
    assert all(feature.detail is None for feature in features)


def test_health_reports_degraded_when_a_dependency_fails(client) -> None:
    from tests.fakes import FailingVectorStore

    client.app.state.vector_store = FailingVectorStore()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    chroma = next(
        dependency
        for dependency in response.json()["dependencies"]
        if dependency["name"] == "chromadb"
    )
    assert chroma["ready"] is False
    assert chroma["detail"] == "vector store unavailable"


def test_openapi_documents_the_versioned_routes(client) -> None:
    schema = client.get("/openapi.json").json()

    assert "/api/v1/workflows" in schema["paths"]
    assert "/api/v1/workflows/{workflow_id}" in schema["paths"]
    assert "/api/v1/workflows/{workflow_id}/events" in schema["paths"]
    assert "/api/v1/workflows/{workflow_id}/cancel" in schema["paths"]
    assert "/health" in schema["paths"]


def test_the_documented_example_payload_is_accepted(client) -> None:
    response = client.post(
        "/api/v1/workflows",
        json={
            "query": "Run smoke tests for the payment module on Chrome in the US region",
            "dry_run": False,
        },
    )

    assert response.status_code == 201
    assert set(response.json()) == {
        "workflow_id",
        "status",
        "summary",
        "execution_id",
    }
