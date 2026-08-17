"""Load and validate the committed knowledge base from disk."""

import json
from pathlib import Path
from typing import List

from pydantic import ValidationError

from app.knowledge.documents import KnowledgeDocument

DEFAULT_KNOWLEDGE_BASE = Path(__file__).resolve().parents[2] / "knowledge_base"


class KnowledgeBaseError(ValueError):
    """Raised when the corpus on disk is unusable."""


def load_documents(root: Path = DEFAULT_KNOWLEDGE_BASE) -> List[KnowledgeDocument]:
    """Read every JSON document file under ``root`` in a stable order.

    Ordering is deterministic so a re-ingest produces the same corpus, and
    source IDs are checked for uniqueness because the analyzer cites them.
    """
    if not root.is_dir():
        raise KnowledgeBaseError(f"knowledge base directory not found: {root}")

    documents: List[KnowledgeDocument] = []
    for path in sorted(root.rglob("*.json")):
        documents.extend(_load_file(path))

    if not documents:
        raise KnowledgeBaseError(f"knowledge base at {root} contains no documents")

    _reject_duplicate_source_ids(documents)
    return documents


def _load_file(path: Path) -> List[KnowledgeDocument]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise KnowledgeBaseError(f"{path.name} is not valid JSON: {error}") from error

    if not isinstance(payload, list):
        raise KnowledgeBaseError(f"{path.name} must contain a JSON array")

    try:
        return [KnowledgeDocument.model_validate(row) for row in payload]
    except ValidationError as error:
        raise KnowledgeBaseError(f"{path.name} contains an invalid document: {error}") from error


def _reject_duplicate_source_ids(documents: List[KnowledgeDocument]) -> None:
    seen = set()
    duplicates = set()
    for document in documents:
        if document.source_id in seen:
            duplicates.add(document.source_id)
        seen.add(document.source_id)
    if duplicates:
        raise KnowledgeBaseError(
            "duplicate source IDs in knowledge base: " + ", ".join(sorted(duplicates))
        )
