"""Workflow lifecycle domain models."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    """Controlled workflow states from the documented state machine."""

    RECEIVED = "received"
    INTENT_PARSED = "intent_parsed"
    NEEDS_CLARIFICATION = "needs_clarification"
    EVIDENCE_RETRIEVED = "evidence_retrieved"
    RETRIEVAL_FAILED = "retrieval_failed"
    PLAN_CREATED = "plan_created"
    REJECTED = "rejected"
    DRY_RUN_COMPLETE = "dry_run_complete"
    EXECUTION_QUEUED = "execution_queued"
    EXECUTION_RUNNING = "execution_running"
    EXECUTION_FAILED = "execution_failed"
    RESULTS_COLLECTED = "results_collected"
    ANALYZED = "analyzed"
    FALLBACK_SUMMARY = "fallback_summary"
    COMPLETED = "completed"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMINAL_STATUSES = frozenset(
    {
        WorkflowStatus.NEEDS_CLARIFICATION,
        WorkflowStatus.RETRIEVAL_FAILED,
        WorkflowStatus.REJECTED,
        WorkflowStatus.DRY_RUN_COMPLETE,
        WorkflowStatus.EXECUTION_FAILED,
        WorkflowStatus.COMPLETED,
    }
)

# Deterministic transition table. Status changes follow this map, never an LLM
# instruction. See docs/workflow.md for the source state machine.
ALLOWED_TRANSITIONS: Dict[WorkflowStatus, frozenset] = {
    WorkflowStatus.RECEIVED: frozenset(
        {WorkflowStatus.INTENT_PARSED, WorkflowStatus.NEEDS_CLARIFICATION}
    ),
    WorkflowStatus.INTENT_PARSED: frozenset(
        {WorkflowStatus.EVIDENCE_RETRIEVED, WorkflowStatus.RETRIEVAL_FAILED}
    ),
    WorkflowStatus.EVIDENCE_RETRIEVED: frozenset({WorkflowStatus.PLAN_CREATED}),
    WorkflowStatus.PLAN_CREATED: frozenset(
        {
            WorkflowStatus.REJECTED,
            WorkflowStatus.DRY_RUN_COMPLETE,
            WorkflowStatus.EXECUTION_QUEUED,
        }
    ),
    WorkflowStatus.EXECUTION_QUEUED: frozenset(
        {WorkflowStatus.EXECUTION_RUNNING, WorkflowStatus.EXECUTION_FAILED}
    ),
    WorkflowStatus.EXECUTION_RUNNING: frozenset(
        {WorkflowStatus.RESULTS_COLLECTED, WorkflowStatus.EXECUTION_FAILED}
    ),
    WorkflowStatus.RESULTS_COLLECTED: frozenset(
        {WorkflowStatus.ANALYZED, WorkflowStatus.FALLBACK_SUMMARY}
    ),
    WorkflowStatus.ANALYZED: frozenset({WorkflowStatus.COMPLETED}),
    WorkflowStatus.FALLBACK_SUMMARY: frozenset({WorkflowStatus.COMPLETED}),
}


def can_transition(current: WorkflowStatus, target: WorkflowStatus) -> bool:
    """Report whether the state machine permits ``current`` to become ``target``."""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


class InvalidTransitionError(ValueError):
    """Raised when a caller attempts an undocumented status change."""

    def __init__(self, current: WorkflowStatus, target: WorkflowStatus) -> None:
        super().__init__(
            f"workflow cannot move from {current.value} to {target.value}"
        )
        self.current = current
        self.target = target


class AgentRunStatus(str, Enum):
    """Outcome of a single agent or service invocation."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class Workflow(BaseModel):
    """Durable lifecycle root for one natural-language request."""

    id: str = Field(pattern=r"^WF-\d+$")
    query: str = Field(min_length=1)
    status: WorkflowStatus
    dry_run: bool
    created_at: datetime
    updated_at: datetime


class AgentRun(BaseModel):
    """Audit record for one agent or service invocation."""

    id: int
    workflow_id: str
    agent_name: str = Field(min_length=1)
    status: AgentRunStatus
    input_payload: Dict[str, Any]
    output_payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
