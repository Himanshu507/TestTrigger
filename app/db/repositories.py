"""Durable access to workflow lifecycle and audit records."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.database import Database
from app.models.workflow import (
    AgentRun,
    AgentRunStatus,
    InvalidTransitionError,
    Workflow,
    WorkflowStatus,
    can_transition,
)

_CLOSED_AGENT_RUN_STATUSES = frozenset({AgentRunStatus.COMPLETED, AgentRunStatus.FAILED})


class WorkflowNotFoundError(LookupError):
    """Raised when an operation targets a workflow that does not exist."""

    def __init__(self, workflow_id: str) -> None:
        super().__init__(f"workflow {workflow_id} does not exist")
        self.workflow_id = workflow_id


class WorkflowRepository:
    """Reads and writes workflow and agent-run records.

    Holds no business policy: it persists decisions other modules make.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def initialize(self) -> None:
        self._database.initialize()

    def create_workflow(self, *, workflow_id: str, query: str, dry_run: bool) -> Workflow:
        """Create the lifecycle root in the initial ``RECEIVED`` state."""
        now = _utc_now()
        workflow = Workflow(
            id=workflow_id,
            query=query,
            status=WorkflowStatus.RECEIVED,
            dry_run=dry_run,
            created_at=now,
            updated_at=now,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows (id, query, status, dry_run, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow.id,
                    workflow.query,
                    workflow.status.value,
                    int(workflow.dry_run),
                    _to_iso(workflow.created_at),
                    _to_iso(workflow.updated_at),
                ),
            )
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
        return _to_workflow(row) if row is not None else None

    def update_status(self, workflow_id: str, status: WorkflowStatus) -> Workflow:
        """Apply a status change permitted by the documented transition table."""
        workflow = self.get_workflow(workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if not can_transition(workflow.status, status):
            raise InvalidTransitionError(workflow.status, status)

        updated_at = _utc_now()
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, _to_iso(updated_at), workflow_id),
            )
        return workflow.model_copy(update={"status": status, "updated_at": updated_at})

    def record_agent_run(
        self,
        *,
        workflow_id: str,
        agent_name: str,
        status: AgentRunStatus,
        input_payload: Dict[str, Any],
        output_payload: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
    ) -> AgentRun:
        """Persist one agent or service invocation for later inspection."""
        run_status = AgentRunStatus(status)
        now = _utc_now()
        started = started_at or now
        completed = now if run_status in _CLOSED_AGENT_RUN_STATUSES else None

        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_runs (
                    workflow_id, agent_name, status, input_payload,
                    output_payload, error, started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    agent_name,
                    run_status.value,
                    json.dumps(input_payload),
                    json.dumps(output_payload) if output_payload is not None else None,
                    error,
                    _to_iso(started),
                    _to_iso(completed) if completed is not None else None,
                ),
            )
            run_id = cursor.lastrowid

        return AgentRun(
            id=run_id,
            workflow_id=workflow_id,
            agent_name=agent_name,
            status=run_status,
            input_payload=input_payload,
            output_payload=output_payload,
            error=error,
            started_at=started,
            completed_at=completed,
        )

    def list_agent_runs(self, workflow_id: str) -> List[AgentRun]:
        """Return the audit trail for a workflow in insertion order."""
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs WHERE workflow_id = ? ORDER BY id",
                (workflow_id,),
            ).fetchall()
        return [_to_agent_run(row) for row in rows]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _to_workflow(row: sqlite3.Row) -> Workflow:
    return Workflow(
        id=row["id"],
        query=row["query"],
        status=WorkflowStatus(row["status"]),
        dry_run=bool(row["dry_run"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _to_agent_run(row: sqlite3.Row) -> AgentRun:
    completed_at = row["completed_at"]
    return AgentRun(
        id=row["id"],
        workflow_id=row["workflow_id"],
        agent_name=row["agent_name"],
        status=AgentRunStatus(row["status"]),
        input_payload=json.loads(row["input_payload"]),
        output_payload=(
            json.loads(row["output_payload"]) if row["output_payload"] is not None else None
        ),
        error=row["error"],
        started_at=datetime.fromisoformat(row["started_at"]),
        completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
    )
