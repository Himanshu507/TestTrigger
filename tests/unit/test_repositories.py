import sqlite3

import pytest

from app.db.database import Database
from app.db.repositories import (
    AnalysisRepository,
    EventRepository,
    ExecutionNotFoundError,
    ExecutionRepository,
    PlanRepository,
    WorkflowRepository,
)
from app.models.analysis import AnalysisReport, AnalysisStatus, FailureAnalysis
from app.models.execution import ExecutionResult, ExecutionStatus, TestOutcome
from app.models.plan import ExecutionPlan, PlanItem, PolicyResult

WORKFLOW_ID = "WF-1001"


@pytest.fixture
def database(tmp_path) -> Database:
    created = Database(tmp_path / "test-trigger.db")
    created.initialize()
    WorkflowRepository(created).create_workflow(
        workflow_id=WORKFLOW_ID, query="Run payment smoke tests", dry_run=False
    )
    return created


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        module="payment",
        scope="smoke",
        browser="chrome",
        region="US",
        items=[
            PlanItem(
                test_id="PAY-003",
                priority=2,
                risk_score=0.87,
                reasons=["Matches module and scope", "Historical Chrome failure pattern"],
            ),
            PlanItem(test_id="PAY-001", priority=1, reasons=["Matches module and scope"]),
        ],
        policy_result=PolicyResult(allowed=True),
    )


def test_plan_repository_preserves_every_selection_reason(database: Database) -> None:
    repository = PlanRepository(database)

    stored = repository.save_plan(WORKFLOW_ID, _plan())

    assert [item.test_id for item in stored] == ["PAY-001", "PAY-003"]
    assert stored[1].reasons == [
        "Matches module and scope",
        "Historical Chrome failure pattern",
    ]
    assert stored[1].risk_score == 0.87
    assert stored[0].risk_score is None


def test_plan_repository_rejects_a_duplicate_test_for_one_workflow(
    database: Database,
) -> None:
    repository = PlanRepository(database)
    repository.save_plan(WORKFLOW_ID, _plan())

    with pytest.raises(sqlite3.IntegrityError):
        repository.save_plan(WORKFLOW_ID, _plan())


def test_execution_repository_finds_a_prior_submission_by_idempotency_key(
    database: Database,
) -> None:
    repository = ExecutionRepository(database)

    created = repository.create_execution(
        workflow_id=WORKFLOW_ID, external_job_id="JOB-2001", idempotency_key="key-1"
    )

    assert created.status is ExecutionStatus.QUEUED
    assert repository.find_by_idempotency_key("key-1").id == created.id
    assert repository.find_by_idempotency_key("unused") is None


def test_reusing_an_idempotency_key_cannot_start_a_second_job(
    database: Database,
) -> None:
    repository = ExecutionRepository(database)
    repository.create_execution(
        workflow_id=WORKFLOW_ID, external_job_id="JOB-2001", idempotency_key="key-1"
    )

    with pytest.raises(sqlite3.IntegrityError):
        repository.create_execution(
            workflow_id=WORKFLOW_ID, external_job_id="JOB-2002", idempotency_key="key-1"
        )


def test_terminal_execution_status_stamps_a_completion_time(database: Database) -> None:
    repository = ExecutionRepository(database)
    created = repository.create_execution(
        workflow_id=WORKFLOW_ID, external_job_id="JOB-2001", idempotency_key="key-1"
    )

    running = repository.update_status(created.id, ExecutionStatus.RUNNING)
    assert running.completed_at is None

    completed = repository.update_status(created.id, ExecutionStatus.COMPLETED)
    assert completed.completed_at is not None
    assert repository.get_execution(created.id).status is ExecutionStatus.COMPLETED


def test_updating_a_missing_execution_is_rejected(database: Database) -> None:
    with pytest.raises(ExecutionNotFoundError):
        ExecutionRepository(database).update_status(404, ExecutionStatus.RUNNING)


def test_execution_results_round_trip(database: Database) -> None:
    repository = ExecutionRepository(database)
    created = repository.create_execution(
        workflow_id=WORKFLOW_ID, external_job_id="JOB-2001", idempotency_key="key-1"
    )

    repository.record_results(
        created.id,
        [
            ExecutionResult(test_id="PAY-001", status=TestOutcome.PASSED, duration_ms=900),
            ExecutionResult(
                test_id="PAY-003",
                status=TestOutcome.FAILED,
                duration_ms=1840,
                failure_reason="3DS redirect timeout",
            ),
        ],
    )

    results = repository.list_results(created.id)

    assert [result.test_id for result in results] == ["PAY-001", "PAY-003"]
    assert results[1].failure_reason == "3DS redirect timeout"
    assert results[0].failure_reason is None


def test_results_cannot_reference_a_missing_execution(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        ExecutionRepository(database).record_results(
            404,
            [ExecutionResult(test_id="PAY-001", status=TestOutcome.PASSED, duration_ms=1)],
        )


def test_analysis_repository_returns_the_latest_report(database: Database) -> None:
    repository = AnalysisRepository(database)
    repository.save_report(
        WORKFLOW_ID,
        AnalysisReport(
            summary="Deterministic summary.",
            status=AnalysisStatus.FALLBACK,
            observations=["PAY-003 failed"],
            fallback_reason="provider timed out",
        ),
    )
    repository.save_report(
        WORKFLOW_ID,
        AnalysisReport(
            summary="1 of 2 tests failed.",
            status=AnalysisStatus.AI_GENERATED,
            failures=[
                FailureAnalysis(
                    test_id="PAY-003",
                    likely_cause="3DS redirect timeout",
                    confidence=0.82,
                    evidence_source_ids=["HIST-001"],
                    recommendations=["Review gateway timeout configuration"],
                )
            ],
        ),
    )

    stored = repository.get_report(WORKFLOW_ID)

    assert stored.summary == "1 of 2 tests failed."
    assert stored.analysis_payload["status"] == "ai_generated"
    assert stored.analysis_payload["failures"][0]["evidence_source_ids"] == ["HIST-001"]


def test_missing_analysis_report_reads_as_none(database: Database) -> None:
    assert AnalysisRepository(database).get_report(WORKFLOW_ID) is None


def test_event_repository_returns_an_ordered_timeline(database: Database) -> None:
    repository = EventRepository(database)

    repository.record_event(workflow_id=WORKFLOW_ID, step="intent", status="completed")
    repository.record_event(
        workflow_id=WORKFLOW_ID,
        step="retrieval",
        status="completed",
        metadata={"source_count": 4},
    )

    events = repository.list_events(WORKFLOW_ID)

    assert [event.step for event in events] == ["intent", "retrieval"]
    assert events[0].metadata == {}
    assert events[1].metadata == {"source_count": 4}


def test_events_cannot_reference_a_missing_workflow(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        EventRepository(database).record_event(
            workflow_id="WF-4040", step="intent", status="completed"
        )
