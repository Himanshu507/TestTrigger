"""Graph nodes.

Each node performs one step, records its transition, and returns a state
subset. Nodes never call one another; routing is the graph's job.
"""

from typing import Any, Dict, List

from app.agents.analysis import fallback_report
from app.agents.execution import ExecutionError, ExecutionRefusedError
from app.agents.intent import ClarificationRequired
from app.agents.retrieval import RetrievalError
from app.models.evidence import RetrievedEvidence
from app.models.execution import ExecutionResult, ExecutionStatus
from app.models.intent import TestIntent
from app.models.plan import ExecutionPlan
from app.models.workflow import WorkflowStatus
from app.orchestration.dependencies import WorkflowDependencies
from app.orchestration.state import TestWorkflowState, record_error


def _advance(
    dependencies: WorkflowDependencies,
    state: TestWorkflowState,
    status: WorkflowStatus,
    *,
    step: str,
    metadata: Dict[str, Any] = None,
) -> str:
    """Persist a status change and its timeline event before returning it.

    Status is written before and after every material boundary, so a crash
    leaves an inspectable record rather than a silent gap.
    """
    workflow_id = state["workflow_id"]
    dependencies.workflows.update_status(workflow_id, status)
    dependencies.events.record_event(
        workflow_id=workflow_id,
        step=step,
        status=status.value,
        metadata=metadata or {},
    )
    return status.value


def intent_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Parse the request, or route to clarification with the reason."""
    outcome = dependencies.intent_agent.parse_intent(
        state["user_query"], workflow_id=state["workflow_id"]
    )

    if isinstance(outcome, ClarificationRequired):
        return {
            "clarification": outcome.model_dump(mode="json"),
            "summary": outcome.detail,
            "errors": record_error(state, "intent", outcome.detail),
            "status": _advance(
                dependencies,
                state,
                WorkflowStatus.NEEDS_CLARIFICATION,
                step="intent",
                metadata={"reason": outcome.reason.value},
            ),
        }

    return {
        "intent": outcome.model_dump(mode="json"),
        "status": _advance(
            dependencies,
            state,
            WorkflowStatus.INTENT_PARSED,
            step="intent",
            metadata={"confidence": outcome.confidence},
        ),
    }


def retrieval_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Gather evidence, or fail the workflow rather than plan blind."""
    intent = TestIntent.model_validate(state["intent"])

    try:
        result = dependencies.retrieval_agent.retrieve(
            intent, workflow_id=state["workflow_id"]
        )
    except RetrievalError as error:
        message = str(error)
        return {
            "summary": f"Evidence retrieval failed: {message}",
            "errors": record_error(state, "retrieval", message),
            "status": _advance(
                dependencies,
                state,
                WorkflowStatus.RETRIEVAL_FAILED,
                step="retrieval",
                metadata={"error": message},
            ),
        }

    return {
        "retrieved_context": result.model_dump(mode="json"),
        "status": _advance(
            dependencies,
            state,
            WorkflowStatus.EVIDENCE_RETRIEVED,
            step="retrieval",
            metadata={"source_count": len(result.all_evidence)},
        ),
    }


def planning_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Select catalogued tests and apply deterministic policy."""
    intent = TestIntent.model_validate(state["intent"])
    outcome = dependencies.planning_service.plan_and_validate(
        intent,
        _evidence(state),
        workflow_id=state["workflow_id"],
        reference_date=dependencies.reference_date,
    )

    return {
        "test_plan": outcome.plan.model_dump(mode="json"),
        "policy_result": (
            outcome.plan.policy_result.model_dump(mode="json")
            if outcome.plan.policy_result
            else None
        ),
        "summary": outcome.rejection_summary,
        "status": _advance(
            dependencies,
            state,
            WorkflowStatus.PLAN_CREATED,
            step="planning",
            metadata={
                "test_ids": outcome.plan.test_ids,
                "allowed": outcome.is_executable,
            },
        ),
    }


def rejection_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Terminate a plan that policy blocked, with every violation preserved."""
    plan = ExecutionPlan.model_validate(state["test_plan"])
    violations = plan.policy_result.violations if plan.policy_result else []
    summary = state.get("summary") or "The request was rejected by policy."

    return {
        "summary": summary,
        "errors": record_error(state, "policy", summary),
        "status": _advance(
            dependencies,
            state,
            WorkflowStatus.REJECTED,
            step="policy",
            metadata={"violation_codes": [violation.code for violation in violations]},
        ),
    }


def dry_run_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Stop after validation. No job is created and no results are written."""
    plan = ExecutionPlan.model_validate(state["test_plan"])
    summary = (
        f"Dry run: {len(plan.items)} test(s) would run on "
        f"{plan.browser.value} in {plan.region.value}."
    )

    return {
        "summary": summary,
        "status": _advance(
            dependencies,
            state,
            WorkflowStatus.DRY_RUN_COMPLETE,
            step="dry_run",
            metadata={"test_ids": plan.test_ids},
        ),
    }


def execution_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Submit the validated plan and collect normalized results."""
    plan = ExecutionPlan.model_validate(state["test_plan"])
    workflow_id = state["workflow_id"]

    queued = _advance(
        dependencies,
        state,
        WorkflowStatus.EXECUTION_QUEUED,
        step="execution",
        metadata={"test_ids": plan.test_ids},
    )
    running_state = {**state, "status": queued}
    _advance(
        dependencies,
        running_state,
        WorkflowStatus.EXECUTION_RUNNING,
        step="execution",
        metadata={},
    )
    running_state = {**running_state, "status": WorkflowStatus.EXECUTION_RUNNING.value}

    try:
        execution = dependencies.execution_agent.execute(plan, workflow_id=workflow_id)
    except (ExecutionError, ExecutionRefusedError) as error:
        message = str(error)
        return {
            "summary": f"Execution failed: {message}",
            "errors": record_error(state, "execution", message),
            "status": _advance(
                dependencies,
                running_state,
                WorkflowStatus.EXECUTION_FAILED,
                step="execution",
                metadata={"error": message},
            ),
        }

    results = [result.model_dump(mode="json") for result in execution.results]

    if execution.status is not ExecutionStatus.COMPLETED:
        message = f"job {execution.external_job_id} ended as {execution.status.value}"
        return {
            "execution_id": execution.external_job_id,
            "execution_status": execution.status.value,
            "execution_results": results,
            "summary": f"Execution failed: {message}",
            "errors": record_error(state, "execution", message),
            "status": _advance(
                dependencies,
                running_state,
                WorkflowStatus.EXECUTION_FAILED,
                step="execution",
                metadata={"external_job_id": execution.external_job_id},
            ),
        }

    return {
        "execution_id": execution.external_job_id,
        "execution_status": execution.status.value,
        "execution_results": results,
        "status": _advance(
            dependencies,
            running_state,
            WorkflowStatus.RESULTS_COLLECTED,
            step="execution",
            metadata={
                "external_job_id": execution.external_job_id,
                "result_count": len(results),
            },
        ),
    }


def analysis_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Explain the results, falling back to a deterministic summary.

    An analysis failure never hides execution results: it downgrades the report
    and still reaches COMPLETED.
    """
    results = [ExecutionResult.model_validate(row) for row in state["execution_results"]]
    plan = ExecutionPlan.model_validate(state["test_plan"])

    report = None
    fallback_reason = None

    if dependencies.analyzer is None:
        fallback_reason = "no analysis provider is configured"
    else:
        try:
            report = dependencies.analyzer.analyze(
                plan=plan,
                results=results,
                evidence=_evidence(state),
                workflow_id=state["workflow_id"],
            )
        except Exception as error:  # any analyzer failure degrades, never blocks
            fallback_reason = f"analysis failed: {error}"

    if report is None:
        report = fallback_report(results, fallback_reason)
        status = WorkflowStatus.FALLBACK_SUMMARY
    else:
        status = WorkflowStatus.ANALYZED

    if dependencies.analysis is not None:
        dependencies.analysis.save_report(state["workflow_id"], report)

    return {
        "analysis": report.model_dump(mode="json"),
        "summary": report.summary,
        "status": _advance(
            dependencies,
            state,
            status,
            step="analysis",
            metadata={"analysis_status": report.status.value},
        ),
    }


def completion_node(
    state: TestWorkflowState, dependencies: WorkflowDependencies
) -> Dict[str, Any]:
    """Close a workflow that produced results."""
    return {
        "status": _advance(
            dependencies,
            state,
            WorkflowStatus.COMPLETED,
            step="workflow",
            metadata={"execution_id": state.get("execution_id")},
        )
    }


def _evidence(state: TestWorkflowState) -> List[RetrievedEvidence]:
    context = state.get("retrieved_context") or {}
    return [
        RetrievedEvidence.model_validate(row)
        for key in ("test_documentation", "historical_failures", "jurisdiction_rules")
        for row in context.get(key, [])
    ]


