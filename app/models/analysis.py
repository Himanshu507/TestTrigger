"""Grounded result explanation contracts."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.plan import TEST_ID_PATTERN


class AnalysisStatus(str, Enum):
    """How a report was produced.

    ``FALLBACK`` marks a deterministic summary written without the LLM, so a
    reader can tell grounded AI analysis from a provider outage.
    """

    AI_GENERATED = "ai_generated"
    FALLBACK = "fallback"


class FailureAnalysis(BaseModel):
    """An inferred cause for one failed test, tied to the evidence behind it."""

    test_id: str = Field(pattern=TEST_ID_PATTERN)
    likely_cause: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_source_ids: List[str] = Field(min_length=1)
    recommendations: List[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    """Result explanation that separates observed facts from inferred causes.

    ``observations`` holds what the execution actually reported.
    ``failures`` holds inference, and each entry must cite evidence. A fallback
    report states facts only: it may not infer causes without an LLM.
    """

    summary: str = Field(min_length=1)
    status: AnalysisStatus
    observations: List[str] = Field(default_factory=list)
    failures: List[FailureAnalysis] = Field(default_factory=list)
    insufficient_evidence: bool = False
    fallback_reason: Optional[str] = None

    @model_validator(mode="after")
    def fallback_reports_must_not_infer_causes(self) -> "AnalysisReport":
        if self.status is AnalysisStatus.FALLBACK and self.failures:
            raise ValueError(
                "a fallback report states observed facts and cannot infer causes"
            )
        if self.status is AnalysisStatus.FALLBACK and not self.fallback_reason:
            raise ValueError("a fallback report must record why analysis was degraded")
        return self
