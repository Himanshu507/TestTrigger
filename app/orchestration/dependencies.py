"""Everything the graph needs, supplied from outside.

The graph decides when a component runs and where its result goes. It never
constructs its own collaborators, which keeps composition in one place and lets
tests substitute fakes for every boundary.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol, Sequence

from app.agents.execution import ExecutionAgent
from app.agents.intent import IntentAgent
from app.agents.retrieval import RetrievalAgent
from app.db.repositories import (
    AnalysisRepository,
    EventRepository,
    WorkflowRepository,
)
from app.models.analysis import AnalysisReport
from app.models.evidence import RetrievedEvidence
from app.models.execution import ExecutionResult
from app.models.plan import ExecutionPlan
from app.services.planning_service import PlanningService


class ResultAnalyzer(Protocol):
    """Produces a grounded report. Implemented by Module 7.

    Until that module lands, the graph falls back to a deterministic summary,
    which is the same path an analysis outage takes.
    """

    def analyze(
        self,
        *,
        plan: ExecutionPlan,
        results: Sequence[ExecutionResult],
        evidence: Sequence[RetrievedEvidence],
        workflow_id: Optional[str] = None,
    ) -> AnalysisReport:
        ...


@dataclass
class WorkflowDependencies:
    """Collaborators and configuration for one graph run."""

    intent_agent: IntentAgent
    retrieval_agent: RetrievalAgent
    planning_service: PlanningService
    execution_agent: ExecutionAgent
    workflows: WorkflowRepository
    events: EventRepository
    analysis: Optional[AnalysisRepository] = None
    analyzer: Optional[ResultAnalyzer] = None
    reference_date: Optional[date] = None
