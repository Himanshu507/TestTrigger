"""Assembles API views from persisted records.

Routes adapt transport; this reads the audit trail. Neither contains workflow
business logic — the graph already made every decision recorded here.
"""

from typing import List, Optional

from app.api.schemas import (
    AnalysisView,
    DependencyHealth,
    EventView,
    ExecutionView,
    IntentView,
    PlanTestView,
    PlanView,
    RetrievalView,
    TestResultView,
    WorkflowDetailResponse,
)
from app.db.records import WorkflowEvent
from app.db.repositories import (
    AnalysisRepository,
    EventRepository,
    ExecutionRepository,
    PlanRepository,
    WorkflowRepository,
)

EVENT_ID_PREFIX = "EV-"


class WorkflowInspector:
    """Reads a workflow's durable records and renders the documented views."""

    def __init__(
        self,
        *,
        workflows: WorkflowRepository,
        plans: PlanRepository,
        executions: ExecutionRepository,
        analyses: AnalysisRepository,
        events: EventRepository,
    ) -> None:
        self._workflows = workflows
        self._plans = plans
        self._executions = executions
        self._analyses = analyses
        self._events = events

    def detail(self, workflow_id: str) -> Optional[WorkflowDetailResponse]:
        workflow = self._workflows.get_workflow(workflow_id)
        if workflow is None:
            return None

        return WorkflowDetailResponse(
            workflow_id=workflow.id,
            query=workflow.query,
            status=workflow.status.value,
            dry_run=workflow.dry_run,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            intent=self._intent(workflow_id),
            retrieval=self._retrieval(workflow_id),
            plan=self._plan(workflow_id),
            execution=self._execution(workflow_id),
            analysis=self._analysis(workflow_id),
            timeline=self.timeline(workflow_id),
        )

    def timeline(self, workflow_id: str) -> List[EventView]:
        return [_to_event_view(event) for event in self._events.list_events(workflow_id)]

    def exists(self, workflow_id: str) -> bool:
        return self._workflows.get_workflow(workflow_id) is not None

    def _agent_output(self, workflow_id: str, agent_name: str) -> Optional[dict]:
        """Return the latest output an agent recorded, if it ran at all."""
        runs = [
            run
            for run in self._workflows.list_agent_runs(workflow_id)
            if run.agent_name == agent_name
        ]
        return runs[-1].output_payload if runs else None

    def _intent(self, workflow_id: str) -> Optional[IntentView]:
        payload = self._agent_output(workflow_id, "intent")
        if not payload:
            return None
        return IntentView(
            module=payload.get("module"),
            scope=payload.get("scope"),
            browser=payload.get("browser"),
            region=payload.get("region"),
            environment=payload.get("environment"),
            confidence=payload.get("confidence"),
            missing_fields=payload.get("missing_fields") or [],
        )

    def _retrieval(self, workflow_id: str) -> Optional[RetrievalView]:
        payload = self._agent_output(workflow_id, "retrieval")
        if not payload:
            return None
        return RetrievalView(sources=payload.get("returned_source_ids") or [])

    def _plan(self, workflow_id: str) -> Optional[PlanView]:
        items = self._plans.list_plan_items(workflow_id)
        if not items:
            return None
        return PlanView(
            tests=[
                PlanTestView(
                    test_id=item.test_id,
                    priority=item.priority,
                    risk_score=item.risk_score,
                    reasons=item.reasons,
                )
                for item in items
            ]
        )

    def _execution(self, workflow_id: str) -> Optional[ExecutionView]:
        execution = self._executions.find_by_workflow(workflow_id)
        if execution is None:
            return None
        return ExecutionView(
            execution_id=execution.external_job_id,
            status=execution.status.value,
            results=[
                TestResultView(
                    test_id=result.test_id,
                    status=result.status.value,
                    duration_ms=result.duration_ms,
                    failure_reason=result.failure_reason,
                )
                for result in self._executions.list_results(execution.id)
            ],
        )

    def _analysis(self, workflow_id: str) -> Optional[AnalysisView]:
        report = self._analyses.get_report(workflow_id)
        if report is None:
            return None
        payload = report.analysis_payload
        return AnalysisView(
            summary=payload.get("summary") or report.summary,
            status=payload.get("status", "fallback"),
            observations=payload.get("observations") or [],
            failures=payload.get("failures") or [],
            insufficient_evidence=bool(payload.get("insufficient_evidence")),
            fallback_reason=payload.get("fallback_reason"),
        )


def _to_event_view(event: WorkflowEvent) -> EventView:
    return EventView(
        event_id=f"{EVENT_ID_PREFIX}{event.id:03d}",
        step=event.step,
        status=event.status,
        occurred_at=event.occurred_at,
        metadata=event.metadata,
    )


def check_dependencies(
    *, workflows: WorkflowRepository, store=None, jenkins=None
) -> List[DependencyHealth]:
    """Probe each dependency. Failure detail is a category, never a connection string."""
    checks: List[DependencyHealth] = []

    try:
        workflows.count_workflows()
        checks.append(DependencyHealth(name="sqlite", ready=True))
    except Exception:
        checks.append(
            DependencyHealth(name="sqlite", ready=False, detail="database unavailable")
        )

    if store is not None:
        try:
            store.count()
            checks.append(DependencyHealth(name="chromadb", ready=True))
        except Exception:
            checks.append(
                DependencyHealth(
                    name="chromadb", ready=False, detail="vector store unavailable"
                )
            )

    if jenkins is not None:
        checks.append(DependencyHealth(name="mock_jenkins", ready=True))

    return checks
