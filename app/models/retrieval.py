"""Grouped, bounded retrieval output and its diagnostics."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.models.evidence import RetrievedEvidence


class RetrievalDiagnostics(BaseModel):
    """What was asked of the store and what came back.

    Persisted with the retrieval agent run so a reviewer can see the filters
    and the exact sources that informed a plan or an explanation.
    """

    filters: Dict[str, Any] = Field(default_factory=dict)
    top_k: int
    candidate_test_ids: List[str] = Field(default_factory=list)
    returned_source_ids: List[str] = Field(default_factory=list)
    scores: Dict[str, float] = Field(default_factory=dict)
    dropped_source_ids: List[str] = Field(default_factory=list)
    truncated: bool = False


class RetrievalResult(BaseModel):
    """Evidence grouped by type so callers cannot conflate the categories."""

    test_documentation: List[RetrievedEvidence] = Field(default_factory=list)
    historical_failures: List[RetrievedEvidence] = Field(default_factory=list)
    jurisdiction_rules: List[RetrievedEvidence] = Field(default_factory=list)
    diagnostics: RetrievalDiagnostics

    @property
    def all_evidence(self) -> List[RetrievedEvidence]:
        return [
            *self.test_documentation,
            *self.historical_failures,
            *self.jurisdiction_rules,
        ]

    @property
    def is_empty(self) -> bool:
        return not self.all_evidence

    @property
    def source_ids(self) -> List[str]:
        return [evidence.source_id for evidence in self.all_evidence]
