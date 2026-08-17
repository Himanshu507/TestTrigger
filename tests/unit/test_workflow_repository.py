import pytest

from app.db.database import Database
from app.db.repositories import WorkflowNotFoundError, WorkflowRepository
from app.models.workflow import InvalidTransitionError, WorkflowStatus


@pytest.fixture
def repository(tmp_path) -> WorkflowRepository:
    created = WorkflowRepository(Database(tmp_path / "test-trigger.db"))
    created.initialize()
    return created


def test_workflow_repository_persists_workflow_and_agent_run(tmp_path) -> None:
    repository = WorkflowRepository(Database(tmp_path / "test-trigger.db"))
    repository.initialize()

    created = repository.create_workflow(
        workflow_id="WF-1001",
        query="Run payment smoke tests on Chrome in US",
        dry_run=True,
    )
    repository.record_agent_run(
        workflow_id=created.id,
        agent_name="intent",
        status="completed",
        input_payload={"query": created.query},
        output_payload={"module": "payment"},
    )

    workflow = repository.get_workflow("WF-1001")
    agent_runs = repository.list_agent_runs("WF-1001")

    assert workflow is not None
    assert workflow.status is WorkflowStatus.RECEIVED
    assert workflow.dry_run is True
    assert agent_runs[0].agent_name == "intent"
    assert agent_runs[0].output_payload == {"module": "payment"}


def test_unknown_workflow_reads_as_none(repository: WorkflowRepository) -> None:
    assert repository.get_workflow("WF-4040") is None
    assert repository.list_agent_runs("WF-4040") == []


def test_status_update_follows_the_documented_transition_table(
    repository: WorkflowRepository,
) -> None:
    repository.create_workflow(workflow_id="WF-1001", query="q", dry_run=False)

    updated = repository.update_status("WF-1001", WorkflowStatus.INTENT_PARSED)

    assert updated.status is WorkflowStatus.INTENT_PARSED
    assert repository.get_workflow("WF-1001").status is WorkflowStatus.INTENT_PARSED
    assert updated.updated_at >= updated.created_at


def test_execution_cannot_be_queued_without_a_validated_plan(
    repository: WorkflowRepository,
) -> None:
    repository.create_workflow(workflow_id="WF-1001", query="q", dry_run=False)

    with pytest.raises(InvalidTransitionError):
        repository.update_status("WF-1001", WorkflowStatus.EXECUTION_QUEUED)

    assert repository.get_workflow("WF-1001").status is WorkflowStatus.RECEIVED


def test_status_update_on_a_missing_workflow_is_rejected(
    repository: WorkflowRepository,
) -> None:
    with pytest.raises(WorkflowNotFoundError):
        repository.update_status("WF-4040", WorkflowStatus.INTENT_PARSED)


def test_agent_runs_are_returned_in_invocation_order(
    repository: WorkflowRepository,
) -> None:
    repository.create_workflow(workflow_id="WF-1001", query="q", dry_run=False)

    repository.record_agent_run(
        workflow_id="WF-1001",
        agent_name="intent",
        status="completed",
        input_payload={"query": "q"},
        output_payload={"module": "payment"},
    )
    started = repository.record_agent_run(
        workflow_id="WF-1001",
        agent_name="retrieval",
        status="started",
        input_payload={"module": "payment"},
    )
    repository.record_agent_run(
        workflow_id="WF-1001",
        agent_name="planner",
        status="failed",
        input_payload={},
        error="no candidate tests",
    )

    runs = repository.list_agent_runs("WF-1001")

    assert [run.agent_name for run in runs] == ["intent", "retrieval", "planner"]
    assert started.completed_at is None
    assert runs[1].completed_at is None
    assert runs[2].error == "no candidate tests"
    assert runs[2].output_payload is None
