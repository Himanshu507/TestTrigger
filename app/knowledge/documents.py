"""Knowledge-base document contract and metadata rules."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field, model_validator

from app.models.evidence import EvidenceType

REQUIRED_METADATA: Dict[EvidenceType, tuple] = {
    EvidenceType.TEST_DOCUMENTATION: ("test_id", "module", "scope"),
    EvidenceType.HISTORICAL_FAILURE: ("test_id", "browser", "region", "date"),
    EvidenceType.JURISDICTION_RULE: ("region", "applies_to_modules"),
    EvidenceType.CATALOG_CONTEXT: ("test_id",),
}

# Chroma metadata values must be scalars, so list-valued applicability is
# stored as a delimited string and filtered in Python after the vector query.
LIST_DELIMITER = "|"


class KnowledgeDocument(BaseModel):
    """One ingestible document with the metadata its type requires."""

    source_id: str = Field(min_length=1)
    type: EvidenceType
    content: str = Field(min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def metadata_must_satisfy_the_type_contract(self) -> "KnowledgeDocument":
        missing = [
            key for key in REQUIRED_METADATA[self.type] if key not in self.metadata
        ]
        if missing:
            raise ValueError(
                f"{self.source_id} ({self.type.value}) is missing metadata: "
                + ", ".join(missing)
            )
        return self

    def flatten_metadata(self) -> Dict[str, Any]:
        """Return vector-store-safe metadata.

        Scalars pass through; lists become delimited strings so they survive a
        store that only accepts scalar metadata values.
        """
        flattened: Dict[str, Any] = {
            "source_id": self.source_id,
            "type": self.type.value,
        }
        for key, value in self.metadata.items():
            if isinstance(value, (list, tuple)):
                flattened[key] = encode_list(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                flattened[key] = value
            else:
                flattened[key] = str(value)
        return flattened


def encode_list(values) -> str:
    """Encode a list as a delimited string that supports exact membership tests."""
    return LIST_DELIMITER + LIST_DELIMITER.join(str(value) for value in values) + LIST_DELIMITER


def decode_list(value: Any) -> List[str]:
    if not isinstance(value, str):
        return []
    return [part for part in value.split(LIST_DELIMITER) if part]


def list_contains(value: Any, candidate: str) -> bool:
    """Report whether an encoded list contains an exact value."""
    return candidate in decode_list(value)
