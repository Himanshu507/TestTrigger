"""Durable access to workflow lifecycle and audit records."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.db.database import Database
from app.db.records import StoredAnalysisReport, StoredPlanItem, WorkflowEvent
from app.models.analysis import AnalysisReport
from app.models.execution import (
    Execution,
    ExecutionResult,
    ExecutionStatus,
    TestOutcome,
)
from app.models.plan import ExecutionPlan
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


class ExecutionNotFoundError(LookupError):
    """Raised when an operation targets an execution that does not exist."""

    def __init__(self, execution_id: int) -> None:
        super().__init__(f"execution {execution_id} does not exist")
        self.execution_id = execution_id


class WorkflowRepository:
    """Reads and writes workflow and agent-run records.

    Holds no business policy: it persists decisions other modules make.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    @property
    def database(self) -> Database:
        """Expose the shared connection factory so sibling repositories can reuse it."""
        return self._database

    def initialize(self) -> None:
        self._database.initialize()

    def create_workflow(
        self,
        *,
        workflow_id: str,
        query: str,
        dry_run: bool,
        idempotency_key: Optional[str] = None,
    ) -> Workflow:
        """Create the lifecycle root in the initial ``RECEIVED`` state."""
        now = _utc_now()
        workflow = Workflow(
            id=workflow_id,
            query=query,
            status=WorkflowStatus.RECEIVED,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows (
                    id, query, status, dry_run, idempotency_key, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow.id,
                    workflow.query,
                    workflow.status.value,
                    int(workflow.dry_run),
                    workflow.idempotency_key,
                    _to_iso(workflow.created_at),
                    _to_iso(workflow.updated_at),
                ),
            )
        return workflow

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[Workflow]:
        """Return a prior workflow for this key so a retry replays, not repeats."""
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflows WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return _to_workflow(row) if row is not None else None

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
        return _to_workflow(row) if row is not None else None

    def count_workflows(self) -> int:
        with self._database.connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]

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


class PlanRepository:
    """Persists which tests were selected and the reasons behind each choice."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def save_plan(self, workflow_id: str, plan: ExecutionPlan) -> List[StoredPlanItem]:
        """Write every plan item so the selection stays explainable after the run."""
        created_at = _utc_now()
        with self._database.connect() as connection:
            for item in plan.items:
                connection.execute(
                    """
                    INSERT INTO test_plans (
                        workflow_id, test_id, priority, risk_score, risk_factors,
                        reasons, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
                        item.test_id,
                        item.priority,
                        item.risk_score,
                        json.dumps([factor.model_dump() for factor in item.risk_factors]),
                        json.dumps(item.reasons),
                        _to_iso(created_at),
                    ),
                )
        return self.list_plan_items(workflow_id)

    def list_plan_items(self, workflow_id: str) -> List[StoredPlanItem]:
        """Return persisted plan items in execution priority order."""
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM test_plans WHERE workflow_id = ? ORDER BY priority, id",
                (workflow_id,),
            ).fetchall()
        return [
            StoredPlanItem(
                id=row["id"],
                workflow_id=row["workflow_id"],
                test_id=row["test_id"],
                priority=row["priority"],
                risk_score=row["risk_score"],
                risk_factors=json.loads(row["risk_factors"]),
                reasons=json.loads(row["reasons"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]


class ExecutionRepository:
    """Maps workflows to external jobs and stores normalized test results."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create_execution(
        self,
        *,
        workflow_id: str,
        external_job_id: str,
        idempotency_key: str,
        status: ExecutionStatus = ExecutionStatus.QUEUED,
    ) -> Execution:
        """Record a submitted job. Unique constraints make a retry conflict visible."""
        started_at = _utc_now()
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO executions (
                    workflow_id, external_job_id, idempotency_key, status, started_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    external_job_id,
                    idempotency_key,
                    ExecutionStatus(status).value,
                    _to_iso(started_at),
                ),
            )
            execution_id = cursor.lastrowid

        return Execution(
            id=execution_id,
            workflow_id=workflow_id,
            external_job_id=external_job_id,
            idempotency_key=idempotency_key,
            status=ExecutionStatus(status),
            started_at=started_at,
        )

    def next_external_job_number(self, prefix: str = "JOB-") -> int:
        """Return one past the highest job number already recorded.

        External job IDs are unique in the executions table, so a restarted
        simulator must continue the sequence rather than restart it.
        """
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT external_job_id FROM executions WHERE external_job_id LIKE ?",
                (f"{prefix}%",),
            ).fetchall()

        highest = 0
        for row in rows:
            suffix = row["external_job_id"][len(prefix) :]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return highest + 1

    def get_execution(self, execution_id: int) -> Optional[Execution]:
        return self._fetch_one("SELECT * FROM executions WHERE id = ?", (execution_id,))

    def find_by_idempotency_key(self, idempotency_key: str) -> Optional[Execution]:
        """Look up a prior submission so a client retry cannot start a second job."""
        return self._fetch_one(
            "SELECT * FROM executions WHERE idempotency_key = ?", (idempotency_key,)
        )

    def find_by_workflow(self, workflow_id: str) -> Optional[Execution]:
        return self._fetch_one(
            "SELECT * FROM executions WHERE workflow_id = ? ORDER BY id DESC LIMIT 1",
            (workflow_id,),
        )

    def update_status(self, execution_id: int, status: ExecutionStatus) -> Execution:
        """Advance job state, stamping completion when the status is terminal."""
        execution = self.get_execution(execution_id)
        if execution is None:
            raise ExecutionNotFoundError(execution_id)

        target = ExecutionStatus(status)
        completed_at = _utc_now() if target.is_terminal else execution.completed_at
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE executions SET status = ?, completed_at = ? WHERE id = ?",
                (
                    target.value,
                    _to_iso(completed_at) if completed_at is not None else None,
                    execution_id,
                ),
            )
        return execution.model_copy(
            update={"status": target, "completed_at": completed_at}
        )

    def record_results(
        self, execution_id: int, results: Iterable[ExecutionResult]
    ) -> List[ExecutionResult]:
        """Persist per-test outcomes. Results survive any later analysis failure."""
        recorded_at = _to_iso(_utc_now())
        stored = list(results)
        with self._database.connect() as connection:
            for result in stored:
                connection.execute(
                    """
                    INSERT INTO test_results (
                        execution_id, test_id, status, duration_ms,
                        failure_reason, recorded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        execution_id,
                        result.test_id,
                        result.status.value,
                        result.duration_ms,
                        result.failure_reason,
                        recorded_at,
                    ),
                )
        return stored

    def list_results(self, execution_id: int) -> List[ExecutionResult]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM test_results WHERE execution_id = ? ORDER BY id",
                (execution_id,),
            ).fetchall()
        return [
            ExecutionResult(
                test_id=row["test_id"],
                status=TestOutcome(row["status"]),
                duration_ms=row["duration_ms"],
                failure_reason=row["failure_reason"],
            )
            for row in rows
        ]

    def _fetch_one(self, sql: str, parameters: tuple) -> Optional[Execution]:
        with self._database.connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
        if row is None:
            return None
        completed_at = row["completed_at"]
        return Execution(
            id=row["id"],
            workflow_id=row["workflow_id"],
            external_job_id=row["external_job_id"],
            idempotency_key=row["idempotency_key"],
            status=ExecutionStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
        )


class AnalysisRepository:
    """Stores the grounded or fallback explanation for a workflow."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def save_report(self, workflow_id: str, report: AnalysisReport) -> StoredAnalysisReport:
        created_at = _utc_now()
        payload = report.model_dump(mode="json")
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_reports (
                    workflow_id, summary, analysis_payload, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (workflow_id, report.summary, json.dumps(payload), _to_iso(created_at)),
            )
            report_id = cursor.lastrowid

        return StoredAnalysisReport(
            id=report_id,
            workflow_id=workflow_id,
            summary=report.summary,
            analysis_payload=payload,
            created_at=created_at,
        )

    def get_report(self, workflow_id: str) -> Optional[StoredAnalysisReport]:
        """Return the most recent report, so an analysis retry supersedes a fallback."""
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM analysis_reports
                WHERE workflow_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (workflow_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredAnalysisReport(
            id=row["id"],
            workflow_id=row["workflow_id"],
            summary=row["summary"],
            analysis_payload=json.loads(row["analysis_payload"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class EventRepository:
    """Records the API-facing timeline of meaningful workflow transitions."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def record_event(
        self,
        *,
        workflow_id: str,
        step: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowEvent:
        occurred_at = _utc_now()
        payload = metadata or {}
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO workflow_events (
                    workflow_id, step, status, metadata, occurred_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (workflow_id, step, status, json.dumps(payload), _to_iso(occurred_at)),
            )
            event_id = cursor.lastrowid

        return WorkflowEvent(
            id=event_id,
            workflow_id=workflow_id,
            step=step,
            status=status,
            metadata=payload,
            occurred_at=occurred_at,
        )

    def list_events(self, workflow_id: str) -> List[WorkflowEvent]:
        """Return events in occurrence order for the timeline endpoint."""
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_events WHERE workflow_id = ? ORDER BY id",
                (workflow_id,),
            ).fetchall()
        return [
            WorkflowEvent(
                id=row["id"],
                workflow_id=row["workflow_id"],
                step=row["step"],
                status=row["status"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
            )
            for row in rows
        ]


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
        idempotency_key=row["idempotency_key"],
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
