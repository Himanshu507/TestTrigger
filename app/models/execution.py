"""External job and per-test outcome contracts."""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.plan import TEST_ID_PATTERN


class ExecutionStatus(str, Enum):
    """Mock Jenkins job lifecycle."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }


# Legal job lifecycle moves. A terminal job has no outgoing transition, so a
# completed or cancelled job cannot accidentally restart.
ALLOWED_JOB_TRANSITIONS = {
    ExecutionStatus.QUEUED: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }
    ),
    ExecutionStatus.RUNNING: frozenset(
        {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }
    ),
}


def can_transition_job(current: ExecutionStatus, target: ExecutionStatus) -> bool:
    """Report whether the job lifecycle permits this status change."""
    return target in ALLOWED_JOB_TRANSITIONS.get(current, frozenset())


class InvalidJobTransitionError(ValueError):
    """Raised when a caller attempts an illegal job status change."""

    def __init__(self, current: ExecutionStatus, target: ExecutionStatus) -> None:
        super().__init__(f"job cannot move from {current.value} to {target.value}")
        self.current = current
        self.target = target


class TestOutcome(str, Enum):
    """Outcome of a single simulated test."""

    PASSED = "passed"
    FAILED = "failed"


class ExecutionResult(BaseModel):
    """One normalized per-test outcome returned by the execution system."""

    test_id: str = Field(pattern=TEST_ID_PATTERN)
    status: TestOutcome
    duration_ms: int = Field(ge=0)
    failure_reason: Optional[str] = None

    @model_validator(mode="after")
    def failures_must_state_a_reason(self) -> "ExecutionResult":
        if self.status is TestOutcome.FAILED and not self.failure_reason:
            raise ValueError("a failed result must carry a failure reason")
        if self.status is TestOutcome.PASSED and self.failure_reason:
            raise ValueError("a passed result must not carry a failure reason")
        return self


class Execution(BaseModel):
    """Maps a workflow to one external job, guarded by an idempotency key."""

    id: int
    workflow_id: str
    external_job_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    results: List[ExecutionResult] = Field(default_factory=list)
