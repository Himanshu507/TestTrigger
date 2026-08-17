"""Row-level records returned by repositories that read stored rows back."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StoredPlanItem(BaseModel):
    """One persisted plan row, including why the test was selected."""

    id: int
    workflow_id: str
    test_id: str
    priority: int
    risk_score: Optional[float] = None
    reasons: List[str] = Field(min_length=1)
    created_at: datetime


class StoredAnalysisReport(BaseModel):
    """A persisted report plus the payload the API returns verbatim."""

    id: int
    workflow_id: str
    summary: str
    analysis_payload: Dict[str, Any]
    created_at: datetime


class WorkflowEvent(BaseModel):
    """One entry in the API-facing workflow timeline."""

    id: int
    workflow_id: str
    step: str = Field(min_length=1)
    status: str = Field(min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
