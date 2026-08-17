import pytest

from app.models.workflow import WorkflowStatus, can_transition


def test_plan_creation_may_reach_execution_dry_run_or_rejection() -> None:
    assert can_transition(WorkflowStatus.PLAN_CREATED, WorkflowStatus.EXECUTION_QUEUED)
    assert can_transition(WorkflowStatus.PLAN_CREATED, WorkflowStatus.DRY_RUN_COMPLETE)
    assert can_transition(WorkflowStatus.PLAN_CREATED, WorkflowStatus.REJECTED)


def test_execution_cannot_start_before_a_plan_is_validated() -> None:
    assert not can_transition(WorkflowStatus.RECEIVED, WorkflowStatus.EXECUTION_QUEUED)
    assert not can_transition(
        WorkflowStatus.EVIDENCE_RETRIEVED, WorkflowStatus.EXECUTION_QUEUED
    )


def test_failed_analysis_still_reaches_completion_through_fallback() -> None:
    assert can_transition(
        WorkflowStatus.RESULTS_COLLECTED, WorkflowStatus.FALLBACK_SUMMARY
    )
    assert can_transition(WorkflowStatus.FALLBACK_SUMMARY, WorkflowStatus.COMPLETED)


@pytest.mark.parametrize(
    "status",
    [
        WorkflowStatus.NEEDS_CLARIFICATION,
        WorkflowStatus.RETRIEVAL_FAILED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.DRY_RUN_COMPLETE,
        WorkflowStatus.EXECUTION_FAILED,
        WorkflowStatus.COMPLETED,
    ],
)
def test_terminal_statuses_have_no_outgoing_transitions(
    status: WorkflowStatus,
) -> None:
    assert status.is_terminal
    assert not any(can_transition(status, target) for target in WorkflowStatus)
