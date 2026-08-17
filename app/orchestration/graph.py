"""LangGraph wiring: the happy path and every significant failure route.

Routing lives here and only here, so the terminal outcomes are visible in one
place rather than scattered through agent code.
"""

from functools import partial

from langgraph.graph import END, START, StateGraph

from app.models.workflow import WorkflowStatus
from app.orchestration.dependencies import WorkflowDependencies
from app.orchestration.nodes import (
    analysis_node,
    completion_node,
    dry_run_node,
    execution_node,
    intent_node,
    planning_node,
    rejection_node,
    retrieval_node,
)
from app.orchestration.state import TestWorkflowState

NODE_INTENT = "intent"
NODE_RETRIEVAL = "retrieval"
NODE_PLANNING = "planning"
NODE_REJECTION = "rejection"
NODE_DRY_RUN = "dry_run"
NODE_EXECUTION = "execution"
NODE_ANALYSIS = "analysis"
NODE_COMPLETION = "completion"


def route_after_intent(state: TestWorkflowState) -> str:
    if state["status"] == WorkflowStatus.NEEDS_CLARIFICATION.value:
        return END
    return NODE_RETRIEVAL


def route_after_retrieval(state: TestWorkflowState) -> str:
    if state["status"] == WorkflowStatus.RETRIEVAL_FAILED.value:
        return END
    return NODE_PLANNING


def route_after_planning(state: TestWorkflowState) -> str:
    """Reject, stop at dry run, or execute.

    A dry run takes the identical planning and policy path and diverges only
    here, so what it reports is exactly what would have run.

    Approval-gate seam (documented, not part of the MVP): a future branch adds
    a WAITING_FOR_APPROVAL route between this point and NODE_EXECUTION when
    the plan's risk score crosses a configured threshold. Only an explicit
    approval endpoint may move it on to execution; rejection stays terminal.
    Nothing else in the graph changes, because execution already runs solely on
    a policy-cleared plan.
    """
    policy = state.get("policy_result") or {}
    if not policy.get("allowed"):
        return NODE_REJECTION
    if state.get("dry_run"):
        return NODE_DRY_RUN
    return NODE_EXECUTION


def route_after_execution(state: TestWorkflowState) -> str:
    if state["status"] == WorkflowStatus.EXECUTION_FAILED.value:
        return END
    return NODE_ANALYSIS


def build_graph(dependencies: WorkflowDependencies):
    """Compile the workflow graph against the supplied collaborators."""
    graph = StateGraph(TestWorkflowState)

    for name, node in (
        (NODE_INTENT, intent_node),
        (NODE_RETRIEVAL, retrieval_node),
        (NODE_PLANNING, planning_node),
        (NODE_REJECTION, rejection_node),
        (NODE_DRY_RUN, dry_run_node),
        (NODE_EXECUTION, execution_node),
        (NODE_ANALYSIS, analysis_node),
        (NODE_COMPLETION, completion_node),
    ):
        graph.add_node(name, partial(node, dependencies=dependencies))

    graph.add_edge(START, NODE_INTENT)
    graph.add_conditional_edges(
        NODE_INTENT, route_after_intent, [NODE_RETRIEVAL, END]
    )
    graph.add_conditional_edges(
        NODE_RETRIEVAL, route_after_retrieval, [NODE_PLANNING, END]
    )
    graph.add_conditional_edges(
        NODE_PLANNING,
        route_after_planning,
        [NODE_REJECTION, NODE_DRY_RUN, NODE_EXECUTION],
    )
    graph.add_conditional_edges(
        NODE_EXECUTION, route_after_execution, [NODE_ANALYSIS, END]
    )

    # Rejection and dry run are terminal; analysis always reaches completion,
    # whether it produced a grounded report or a fallback summary.
    graph.add_edge(NODE_REJECTION, END)
    graph.add_edge(NODE_DRY_RUN, END)
    graph.add_edge(NODE_ANALYSIS, NODE_COMPLETION)
    graph.add_edge(NODE_COMPLETION, END)

    return graph.compile()
