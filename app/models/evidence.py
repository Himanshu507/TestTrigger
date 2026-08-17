"""Attributable retrieval results."""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    """The four separately identifiable knowledge-base document classes."""

    TEST_DOCUMENTATION = "test_documentation"
    HISTORICAL_FAILURE = "historical_failure"
    JURISDICTION_RULE = "jurisdiction_rule"
    CATALOG_CONTEXT = "catalog_context"


class RetrievedEvidence(BaseModel):
    """One retrieved document with the identifier needed to cite it.

    ``source_id`` is mandatory: evidence that cannot be attributed cannot
    ground an explanation.
    """

    source_id: str = Field(min_length=1)
    type: EvidenceType
    content: str = Field(min_length=1)
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
