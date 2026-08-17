"""Execution Agent: hands a policy-validated plan to the external system.

The agent chooses nothing. It refuses any plan policy has not cleared, submits
exactly the planned test IDs, and persists the mapping from workflow to job
before anything else can fail.
"""

import hashlib
from typing import List, Optional

from app.db.repositories import ExecutionRepository, WorkflowRepository
from app.integrations.mock_jenkins import (
    JenkinsUnavailableError,
    JobNotFoundError,
    MockJenkinsService,
    build_job_request,
)
from app.models.execution import Execution, ExecutionStatus, InvalidJobTransitionError
from app.models.plan import ExecutionPlan
from app.models.workflow import AgentRunStatus

AGENT_NAME = "execution"


class ExecutionRefusedError(RuntimeError):
    """Raised when a plan is not cleared for execution.

    This is the last gate before an external side effect, so it fails loudly
    rather than degrading.
    """


class ExecutionError(RuntimeError):
    """Raised when a validated plan could not be executed.

    The execution record survives, so the workflow stays inspectable and the
    plan is not lost.
    """


def build_idempotency_key(workflow_id: str, plan: ExecutionPlan) -> str:
    """Derive a stable key from the workflow and exactly what it would run."""
    parts = [
        workflow_id,
        plan.module.value,
        plan.scope.value,
        plan.browser.value,
        plan.region.value,
        plan.environment or "",
        ",".join(plan.test_ids),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class ExecutionAgent:
    """Submits validated plans and collects normalized results."""

    def __init__(
        self,
        jenkins: MockJenkinsService,
        executions: ExecutionRepository,
        *,
        repository: Optional[WorkflowRepository] = None,
    ) -> None:
        self._jenkins = jenkins
        self._executions = executions
        self._repository = repository

    def execute(
        self,
        plan: ExecutionPlan,
        *,
        workflow_id: str,
        idempotency_key: Optional[str] = None,
    ) -> Execution:
        """Run a validated plan, or return the job an earlier attempt created."""
        if not plan.is_executable:
            raise ExecutionRefusedError(
                "execution requires a plan cleared by policy validation"
            )

        key = idempotency_key or build_idempotency_key(workflow_id, plan)
        existing = self._executions.find_by_idempotency_key(key)
        if existing is not None:
            return self._with_results(existing)

        request = build_job_request(
            test_ids=plan.test_ids,
            browser=plan.browser.value,
            region=plan.region.value,
            environment=plan.environment,
        )

        try:
            job = self._jenkins.submit(request)
        except JenkinsUnavailableError as error:
            self._record(
                workflow_id,
                status=AgentRunStatus.FAILED,
                output={"idempotency_key": key},
                error=str(error),
            )
            raise ExecutionError(f"job submission failed: {error}") from error

        execution = self._executions.create_execution(
            workflow_id=workflow_id,
            external_job_id=job.job_id,
            idempotency_key=key,
        )

        return self._collect(execution, job.job_id, workflow_id)

    def _collect(
        self, execution: Execution, job_id: str, workflow_id: str
    ) -> Execution:
        """Drive the job to a terminal state and persist whatever it produced."""
        try:
            finished = self._jenkins.run_to_completion(job_id)
        except (JenkinsUnavailableError, JobNotFoundError, InvalidJobTransitionError) as error:
            failed = self._executions.update_status(
                execution.id, ExecutionStatus.FAILED
            )
            self._record(
                workflow_id,
                status=AgentRunStatus.FAILED,
                output={"execution_id": execution.id, "external_job_id": job_id},
                error=str(error),
            )
            raise ExecutionError(f"job {job_id} failed: {error}") from error

        results = self._executions.record_results(execution.id, finished.results)
        updated = self._executions.update_status(execution.id, finished.status)

        self._record(
            workflow_id,
            status=(
                AgentRunStatus.FAILED
                if finished.status is ExecutionStatus.FAILED
                else AgentRunStatus.COMPLETED
            ),
            output={
                "execution_id": execution.id,
                "external_job_id": job_id,
                "status": finished.status.value,
                "result_count": len(results),
            },
            error=finished.error,
        )
        return updated.model_copy(update={"results": results})

    def cancel(self, workflow_id: str) -> Execution:
        """Cancel the active job for a workflow, keeping existing state intact."""
        execution = self._executions.find_by_workflow(workflow_id)
        if execution is None:
            raise ExecutionError(f"workflow {workflow_id} has no execution to cancel")
        if execution.status.is_terminal:
            raise InvalidJobTransitionError(execution.status, ExecutionStatus.CANCELLED)

        self._jenkins.cancel(execution.external_job_id)
        cancelled = self._executions.update_status(
            execution.id, ExecutionStatus.CANCELLED
        )
        self._record(
            workflow_id,
            status=AgentRunStatus.COMPLETED,
            output={
                "execution_id": execution.id,
                "external_job_id": execution.external_job_id,
                "status": ExecutionStatus.CANCELLED.value,
            },
        )
        return self._with_results(cancelled)

    def _with_results(self, execution: Execution) -> Execution:
        results: List = self._executions.list_results(execution.id)
        return execution.model_copy(update={"results": results})

    def _record(
        self,
        workflow_id: str,
        *,
        status: AgentRunStatus,
        output: dict,
        error: Optional[str] = None,
    ) -> None:
        if self._repository is None:
            return
        self._repository.record_agent_run(
            workflow_id=workflow_id,
            agent_name=AGENT_NAME,
            status=status,
            input_payload={"workflow_id": workflow_id},
            output_payload=output,
            error=error,
        )
