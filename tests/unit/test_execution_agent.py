import pytest

from app.agents.execution import (
    AGENT_NAME,
    ExecutionAgent,
    ExecutionError,
    ExecutionRefusedError,
    build_idempotency_key,
)
from app.db.database import Database
from app.db.repositories import ExecutionRepository, WorkflowRepository
from app.integrations.mock_jenkins import MockJenkinsService, build_job_request
from app.models.execution import ExecutionStatus, InvalidJobTransitionError
from app.models.plan import ExecutionPlan, PlanItem, PolicyResult, PolicyViolation
from app.models.workflow import AgentRunStatus

WORKFLOW_ID = "WF-1001"


@pytest.fixture
def database(tmp_path) -> Database:
    created = Database(tmp_path / "test-trigger.db")
    created.initialize()
    WorkflowRepository(created).create_workflow(
        workflow_id=WORKFLOW_ID, query="Run payment smoke tests", dry_run=False
    )
    return created


def _plan(*, allowed: bool = True, test_ids=("PAY-001", "PAY-003"), **overrides):
    values = {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
        "environment": "staging",
        "items": [
            PlanItem(test_id=test_id, priority=index, reasons=["selected"])
            for index, test_id in enumerate(test_ids, start=1)
        ],
        "policy_result": (
            PolicyResult(allowed=True)
            if allowed
            else PolicyResult(
                allowed=False,
                violations=[PolicyViolation(code="NO_TESTS_SELECTED", message="empty")],
            )
        ),
    }
    values.update(overrides)
    return ExecutionPlan(**values)


def _agent(database, jenkins=None) -> ExecutionAgent:
    return ExecutionAgent(
        jenkins or MockJenkinsService(seed="demo"),
        ExecutionRepository(database),
        repository=WorkflowRepository(database),
    )


def test_a_validated_plan_runs_to_completion(database) -> None:
    execution = _agent(database).execute(_plan(), workflow_id=WORKFLOW_ID)

    assert execution.status is ExecutionStatus.COMPLETED
    assert execution.external_job_id.startswith("JOB-")
    assert [result.test_id for result in execution.results] == ["PAY-001", "PAY-003"]


def test_an_unvalidated_plan_is_refused(database) -> None:
    agent = _agent(database)

    with pytest.raises(ExecutionRefusedError):
        agent.execute(
            _plan().model_copy(update={"policy_result": None}), workflow_id=WORKFLOW_ID
        )

    assert ExecutionRepository(database).find_by_workflow(WORKFLOW_ID) is None


def test_a_rejected_plan_is_refused(database) -> None:
    with pytest.raises(ExecutionRefusedError):
        _agent(database).execute(
            _plan(allowed=False, test_ids=()), workflow_id=WORKFLOW_ID
        )


def test_results_are_persisted_and_reloadable(database) -> None:
    execution = _agent(database).execute(_plan(), workflow_id=WORKFLOW_ID)

    stored = ExecutionRepository(database).list_results(execution.id)

    assert [result.test_id for result in stored] == ["PAY-001", "PAY-003"]
    assert all(result.duration_ms > 0 for result in stored)


def test_a_duplicate_submission_returns_the_original_job(database) -> None:
    agent = _agent(database)
    plan = _plan()

    first = agent.execute(plan, workflow_id=WORKFLOW_ID)
    second = agent.execute(plan, workflow_id=WORKFLOW_ID)

    assert second.id == first.id
    assert second.external_job_id == first.external_job_id
    assert [r.test_id for r in second.results] == [r.test_id for r in first.results]


def test_a_retry_does_not_duplicate_results(database) -> None:
    agent = _agent(database)
    plan = _plan()

    agent.execute(plan, workflow_id=WORKFLOW_ID)
    execution = agent.execute(plan, workflow_id=WORKFLOW_ID)

    assert len(ExecutionRepository(database).list_results(execution.id)) == 2


def test_the_idempotency_key_reflects_what_would_run() -> None:
    plan = _plan()

    assert build_idempotency_key(WORKFLOW_ID, plan) == build_idempotency_key(
        WORKFLOW_ID, plan
    )
    assert build_idempotency_key(WORKFLOW_ID, plan) != build_idempotency_key(
        WORKFLOW_ID, _plan(test_ids=("PAY-001",))
    )
    assert build_idempotency_key(WORKFLOW_ID, plan) != build_idempotency_key(
        "WF-1002", plan
    )


def test_an_explicit_key_overrides_the_derived_one(database) -> None:
    agent = _agent(database)

    first = agent.execute(_plan(), workflow_id=WORKFLOW_ID, idempotency_key="key-1")
    second = agent.execute(
        _plan(test_ids=("PAY-001",)), workflow_id=WORKFLOW_ID, idempotency_key="key-1"
    )

    assert second.id == first.id


def test_only_planned_test_ids_reach_the_external_system(database) -> None:
    execution = _agent(database).execute(
        _plan(test_ids=("PAY-003",)), workflow_id=WORKFLOW_ID
    )

    assert [result.test_id for result in execution.results] == ["PAY-003"]


def test_a_submission_failure_keeps_the_workflow_inspectable(database) -> None:
    agent = _agent(database, MockJenkinsService(unavailable=True))

    with pytest.raises(ExecutionError, match="submission failed"):
        agent.execute(_plan(), workflow_id=WORKFLOW_ID)

    run = WorkflowRepository(database).list_agent_runs(WORKFLOW_ID)[0]
    assert run.status is AgentRunStatus.FAILED
    assert ExecutionRepository(database).find_by_workflow(WORKFLOW_ID) is None


def test_a_ci_failure_preserves_the_execution_record(database) -> None:
    agent = _agent(database, MockJenkinsService(force_job_failure=True))

    execution = agent.execute(_plan(), workflow_id=WORKFLOW_ID)

    assert execution.status is ExecutionStatus.FAILED
    assert execution.completed_at is not None
    assert ExecutionRepository(database).find_by_workflow(WORKFLOW_ID) is not None


def test_a_ci_failure_is_recorded_as_a_failed_agent_run(database) -> None:
    agent = _agent(database, MockJenkinsService(force_job_failure=True))

    agent.execute(_plan(), workflow_id=WORKFLOW_ID)

    run = WorkflowRepository(database).list_agent_runs(WORKFLOW_ID)[0]
    assert run.status is AgentRunStatus.FAILED
    assert "simulated CI infrastructure failure" in run.error


def test_a_successful_run_is_audited(database) -> None:
    agent = _agent(database)

    execution = agent.execute(_plan(), workflow_id=WORKFLOW_ID)

    run = WorkflowRepository(database).list_agent_runs(WORKFLOW_ID)[0]
    assert run.agent_name == AGENT_NAME
    assert run.status is AgentRunStatus.COMPLETED
    assert run.output_payload["external_job_id"] == execution.external_job_id
    assert run.output_payload["result_count"] == 2


def test_an_active_execution_can_be_cancelled(database) -> None:
    jenkins = MockJenkinsService(seed="demo")
    agent = _agent(database, jenkins)
    job = jenkins.submit(
        build_job_request(test_ids=_plan().test_ids, browser="chrome", region="US")
    )
    ExecutionRepository(database).create_execution(
        workflow_id=WORKFLOW_ID, external_job_id=job.job_id, idempotency_key="key-1"
    )

    cancelled = agent.cancel(WORKFLOW_ID)

    assert cancelled.status is ExecutionStatus.CANCELLED
    assert jenkins.get(job.job_id).status is ExecutionStatus.CANCELLED


def test_a_completed_execution_cannot_be_cancelled(database) -> None:
    agent = _agent(database)
    agent.execute(_plan(), workflow_id=WORKFLOW_ID)

    with pytest.raises(InvalidJobTransitionError):
        agent.cancel(WORKFLOW_ID)


def test_cancelling_a_workflow_without_an_execution_is_reported(database) -> None:
    with pytest.raises(ExecutionError, match="no execution to cancel"):
        _agent(database).cancel(WORKFLOW_ID)
