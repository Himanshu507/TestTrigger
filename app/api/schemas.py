"""Request and response shapes for the public API.

These adapt domain records to the documented contract. They never carry
provider prompts, credentials, or unbounded retrieval content.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CreateWorkflowRequest(BaseModel):
    query: str = Field(min_length=1, description="Natural-language testing request.")
    dry_run: bool = Field(
        default=False, description="Validate and plan without starting a CI job."
    )


class CreateWorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    summary: Optional[str] = None
    execution_id: Optional[str] = None


class IntentView(BaseModel):
    module: Optional[str] = None
    scope: Optional[str] = None
    browser: Optional[str] = None
    region: Optional[str] = None
    environment: Optional[str] = None
    confidence: Optional[float] = None
    missing_fields: List[str] = Field(default_factory=list)


class RetrievalView(BaseModel):
    """Source IDs only. Retrieved content is not republished through the API."""

    sources: List[str] = Field(default_factory=list)


class PlanTestView(BaseModel):
    test_id: str
    priority: int
    risk_score: Optional[float] = None
    reasons: List[str] = Field(default_factory=list)


class PlanView(BaseModel):
    tests: List[PlanTestView] = Field(default_factory=list)


class TestResultView(BaseModel):
    test_id: str
    status: str
    duration_ms: int
    failure_reason: Optional[str] = None


class ExecutionView(BaseModel):
    execution_id: str
    status: str
    results: List[TestResultView] = Field(default_factory=list)


class AnalysisView(BaseModel):
    summary: str
    status: str
    observations: List[str] = Field(default_factory=list)
    failures: List[Dict[str, Any]] = Field(default_factory=list)
    insufficient_evidence: bool = False
    fallback_reason: Optional[str] = None


class EventView(BaseModel):
    event_id: str
    step: str
    status: str
    occurred_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowDetailResponse(BaseModel):
    workflow_id: str
    query: str
    status: str
    dry_run: bool
    created_at: datetime
    updated_at: datetime
    intent: Optional[IntentView] = None
    retrieval: Optional[RetrievalView] = None
    plan: Optional[PlanView] = None
    execution: Optional[ExecutionView] = None
    analysis: Optional[AnalysisView] = None
    timeline: List[EventView] = Field(default_factory=list)


class EventsResponse(BaseModel):
    workflow_id: str
    events: List[EventView] = Field(default_factory=list)


class CancelResponse(BaseModel):
    workflow_id: str
    execution_id: str
    status: str


class DependencyHealth(BaseModel):
    name: str
    ready: bool
    detail: Optional[str] = None


class FeatureStatus(BaseModel):
    """Which optional capabilities are configured.

    Reports whether a feature is on and why it is not, never the configuration
    value behind it.
    """

    name: str
    enabled: bool
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    """Liveness is the response itself; readiness is per dependency."""

    status: str
    dependencies: List[DependencyHealth] = Field(default_factory=list)
    features: List[FeatureStatus] = Field(default_factory=list)
