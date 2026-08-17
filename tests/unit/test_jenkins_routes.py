"""HTTP surface of the simulated CI system."""

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import AppSettings
from app.db.database import Database
from app.db.repositories import ExecutionRepository, WorkflowRepository
from app.integrations.mock_jenkins import MockJenkinsService, build_job_request
from app.orchestration.dependencies import WorkflowDependencies
from tests.unit.test_api import _client as _workflow_client  # noqa: F401

SETTINGS = AppSettings.from_environment({})
JOB = {
    "test_ids": ["PAY-001", "PAY-003"],
    "browser": "chrome",
    "region": "US",
    "environment": "staging",
}


@pytest.fixture
def client(tmp_path) -> TestClient:
    """An app whose only wired collaborator is the mock CI service."""
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()
    workflows = WorkflowRepository(database)
    jenkins = MockJenkinsService(seed="routes")

    dependencies = WorkflowDependencies(
        intent_agent=None,
        retrieval_agent=None,
        planning_service=None,
        execution_agent=None,
        workflows=workflows,
        events=None,
    )
    application = create_app(SETTINGS, dependencies=dependencies, jenkins=jenkins)
    return TestClient(application, raise_server_exceptions=False)


def test_a_submitted_job_is_queued_with_a_stable_id(client) -> None:
    response = client.post("/jobs", json=JOB)

    assert response.status_code == 201
    body = response.json()
    assert body["job_id"].startswith("JOB-")
    assert body["status"] == "queued"
    assert body["results"] == []
    assert body["request"]["test_ids"] == ["PAY-001", "PAY-003"]


def test_a_job_can_be_polled(client) -> None:
    job_id = client.post("/jobs", json=JOB).json()["job_id"]

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["job_id"] == job_id


def test_the_documented_lifecycle_runs_to_completion(client) -> None:
    job_id = client.post("/jobs", json=JOB).json()["job_id"]

    assert client.post(f"/jobs/{job_id}/advance").json()["status"] == "running"
    completed = client.post(f"/jobs/{job_id}/advance").json()

    assert completed["status"] == "completed"
    assert [result["test_id"] for result in completed["results"]] == [
        "PAY-001",
        "PAY-003",
    ]


def test_a_terminal_job_cannot_advance_or_cancel(client) -> None:
    job_id = client.post("/jobs", json=JOB).json()["job_id"]
    client.post(f"/jobs/{job_id}/advance")
    client.post(f"/jobs/{job_id}/advance")

    assert client.post(f"/jobs/{job_id}/advance").status_code == 409
    assert client.post(f"/jobs/{job_id}/cancel").status_code == 409


def test_an_active_job_can_be_cancelled(client) -> None:
    job_id = client.post("/jobs", json=JOB).json()["job_id"]

    response = client.post(f"/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_an_unknown_job_returns_the_documented_error_shape(client) -> None:
    response = client.get("/jobs/JOB-9999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_an_invented_test_id_is_rejected(client) -> None:
    response = client.post("/jobs", json={**JOB, "test_ids": ["made-up"]})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_an_empty_job_is_rejected(client) -> None:
    assert client.post("/jobs", json={**JOB, "test_ids": []}).status_code == 400


def test_the_routes_are_documented_separately_from_the_product_api(client) -> None:
    """They simulate an external system, so they stay outside /api/v1."""
    schema = client.get("/openapi.json").json()

    assert "/jobs" in schema["paths"]
    assert "/jobs/{job_id}" in schema["paths"]
    assert "/jobs/{job_id}/cancel" in schema["paths"]
    assert schema["paths"]["/jobs"]["post"]["tags"] == ["mock jenkins"]


def test_the_workflow_and_the_endpoint_observe_the_same_job(tmp_path) -> None:
    """One service instance backs both access paths, so state cannot diverge."""
    client = _workflow_client(
        tmp_path,
        intent_payload={
            "module": "payment",
            "scope": "smoke",
            "browser": "chrome",
            "region": "US",
            "environment": None,
            "confidence": 0.95,
            "missing_fields": [],
        },
    )
    created = client.post(
        "/api/v1/workflows", json={"query": "Run payment smoke tests on Chrome in US"}
    ).json()

    job = client.get(f"/jobs/{created['execution_id']}")

    assert job.status_code == 200
    assert job.json()["status"] == "completed"


def test_a_restarted_simulator_does_not_reissue_a_recorded_job_id(tmp_path) -> None:
    """Job state is in-memory; the executions that reference it are not."""
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()
    WorkflowRepository(database).create_workflow(
        workflow_id="WF-1001", query="q", dry_run=False
    )
    executions = ExecutionRepository(database)
    executions.create_execution(
        workflow_id="WF-1001", external_job_id="JOB-2001", idempotency_key="key-1"
    )

    restarted = MockJenkinsService(
        start_number=executions.next_external_job_number()
    )
    job = restarted.submit(
        build_job_request(test_ids=["PAY-001"], browser="chrome", region="US")
    )

    assert job.job_id == "JOB-2002"


def test_the_job_sequence_starts_at_the_documented_number(tmp_path) -> None:
    database = Database(tmp_path / "test-trigger.db")
    database.initialize()

    assert ExecutionRepository(database).next_external_job_number() == 1
    assert MockJenkinsService(start_number=1)._next_number == 2001
