"""Planning entry point shared by dry runs and real runs.

A dry run and a real run follow the identical planning and validation path, so
what a dry run reports is exactly what would have executed. The difference is
only what the caller does afterwards: this module never submits a job.
"""

from datetime import date
from typing import List, Optional, Sequence

from pydantic import BaseModel

from app.catalog import TestCatalog
from app.db.repositories import PlanRepository, WorkflowRepository
from app.models.evidence import RetrievedEvidence
from app.models.intent import TestIntent
from app.models.plan import ExecutionPlan
from app.models.workflow import AgentRunStatus
from app.services.planner import PLANNER_VERSION, TestPlanner
from app.services.policy import POLICY_VERSION, PolicyService, rejection_summary

SERVICE_NAME = "planner"


class PlanningOutcome(BaseModel):
    """The validated plan plus the summary a caller needs to report it."""

    plan: ExecutionPlan
    rejection_summary: Optional[str] = None

    @property
    def is_executable(self) -> bool:
        return self.plan.is_executable

    @property
    def violation_codes(self) -> List[str]:
        if self.plan.policy_result is None:
            return []
        return [violation.code for violation in self.plan.policy_result.violations]


class PlanningService:
    """Builds a candidate plan and applies deterministic policy to it."""

    def __init__(
        self,
        catalog: TestCatalog,
        *,
        repository: Optional[WorkflowRepository] = None,
        plan_repository: Optional[PlanRepository] = None,
    ) -> None:
        self._planner = TestPlanner(catalog)
        self._policy = PolicyService(catalog)
        self._repository = repository
        self._plan_repository = plan_repository

    def plan_and_validate(
        self,
        intent: TestIntent,
        evidence: Sequence[RetrievedEvidence] = (),
        *,
        workflow_id: Optional[str] = None,
        reference_date: Optional[date] = None,
    ) -> PlanningOutcome:
        """Plan, validate, and persist. Never starts an execution."""
        candidate = self._planner.plan(intent, evidence, reference_date=reference_date)
        result = self._policy.validate(candidate, intent, evidence)
        plan = candidate.model_copy(update={"policy_result": result})

        outcome = PlanningOutcome(plan=plan, rejection_summary=rejection_summary(result))
        self._persist(workflow_id, intent, outcome)
        return outcome

    def _persist(
        self,
        workflow_id: Optional[str],
        intent: TestIntent,
        outcome: PlanningOutcome,
    ) -> None:
        if workflow_id is None:
            return

        if self._plan_repository is not None and outcome.plan.items:
            self._plan_repository.save_plan(workflow_id, outcome.plan)

        if self._repository is None:
            return
        self._repository.record_agent_run(
            workflow_id=workflow_id,
            agent_name=SERVICE_NAME,
            status=AgentRunStatus.COMPLETED,
            input_payload={
                "intent": intent.model_dump(mode="json"),
                "planner_version": PLANNER_VERSION,
                "policy_version": POLICY_VERSION,
            },
            output_payload=outcome.plan.model_dump(mode="json"),
        )
