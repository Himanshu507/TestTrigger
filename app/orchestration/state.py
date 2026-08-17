"""Typed shared workflow state.

Nodes read and return subsets of this state. It is the orchestration snapshot;
the SQLite records remain the audit trail, and the state is reconstructible
from them.
"""

from typing import Any, Dict, List, Optional, TypedDict

from app.models.workflow import WorkflowStatus


class TestWorkflowState(TypedDict, total=False):
    """State passed between graph nodes."""

    workflow_id: str
    user_query: str
    dry_run: bool
    status: str
    intent: Optional[Dict[str, Any]]
    clarification: Optional[Dict[str, Any]]
    retrieved_context: Optional[Dict[str, Any]]
    test_plan: Optional[Dict[str, Any]]
    policy_result: Optional[Dict[str, Any]]
    execution_id: Optional[str]
    execution_status: Optional[str]
    execution_results: List[Dict[str, Any]]
    analysis: Optional[Dict[str, Any]]
    summary: Optional[str]
    errors: List[Dict[str, Any]]


def initial_state(
    *, workflow_id: str, user_query: str, dry_run: bool
) -> TestWorkflowState:
    """Build the state a workflow starts from."""
    return TestWorkflowState(
        workflow_id=workflow_id,
        user_query=user_query,
        dry_run=dry_run,
        status=WorkflowStatus.RECEIVED.value,
        intent=None,
        clarification=None,
        retrieved_context=None,
        test_plan=None,
        policy_result=None,
        execution_id=None,
        execution_status=None,
        execution_results=[],
        analysis=None,
        summary=None,
        errors=[],
    )


def record_error(state: TestWorkflowState, step: str, message: str) -> List[Dict[str, Any]]:
    """Append an error without dropping the ones already recorded."""
    return [*state.get("errors", []), {"step": step, "message": message}]
