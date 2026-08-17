"""Workflow entry point: create the record, run the graph, return final state."""

from typing import Optional

from app.db.records import WorkflowEvent
from app.models.workflow import Workflow
from app.orchestration.dependencies import WorkflowDependencies
from app.orchestration.graph import build_graph
from app.orchestration.state import TestWorkflowState, initial_state

WORKFLOW_ID_PREFIX = "WF-"
FIRST_WORKFLOW_NUMBER = 1001


class WorkflowRunner:
    """Runs one workflow from a natural-language query to a terminal state."""

    def __init__(self, dependencies: WorkflowDependencies) -> None:
        self._dependencies = dependencies
        self._graph = build_graph(dependencies)

    def run(
        self,
        query: str,
        *,
        dry_run: bool = False,
        workflow_id: Optional[str] = None,
    ) -> TestWorkflowState:
        """Create the workflow record first, so an ID exists before any agent runs."""
        identifier = workflow_id or self._next_workflow_id()
        self._dependencies.workflows.create_workflow(
            workflow_id=identifier, query=query, dry_run=dry_run
        )
        self._dependencies.events.record_event(
            workflow_id=identifier,
            step="workflow",
            status="received",
            metadata={"dry_run": dry_run},
        )

        return self._graph.invoke(
            initial_state(workflow_id=identifier, user_query=query, dry_run=dry_run)
        )

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._dependencies.workflows.get_workflow(workflow_id)

    def get_timeline(self, workflow_id: str) -> list:
        events: list[WorkflowEvent] = self._dependencies.events.list_events(workflow_id)
        return events

    def _next_workflow_id(self) -> str:
        """Allocate the next ID from persisted state, not an in-memory counter."""
        existing = self._dependencies.workflows.count_workflows()
        return f"{WORKFLOW_ID_PREFIX}{FIRST_WORKFLOW_NUMBER + existing}"
