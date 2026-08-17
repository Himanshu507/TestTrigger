import json

import pytest

from app.knowledge.documents import KnowledgeDocument, decode_list, list_contains
from app.knowledge.loader import KnowledgeBaseError, load_documents
from app.models.evidence import EvidenceType


def _document(**overrides) -> dict:
    document = {
        "source_id": "HIST-900",
        "type": "historical_failure",
        "content": "PAY-003 failed on Chrome.",
        "metadata": {
            "test_id": "PAY-003",
            "browser": "chrome",
            "region": "US",
            "date": "2026-07-30",
        },
    }
    document.update(overrides)
    return document


def test_committed_knowledge_base_loads_and_validates() -> None:
    documents = load_documents()

    assert len(documents) >= 20
    assert {document.type for document in documents} == {
        EvidenceType.TEST_DOCUMENTATION,
        EvidenceType.HISTORICAL_FAILURE,
        EvidenceType.JURISDICTION_RULE,
    }


def test_document_requires_the_metadata_its_type_declares() -> None:
    with pytest.raises(ValueError, match="missing metadata"):
        KnowledgeDocument.model_validate(
            _document(metadata={"test_id": "PAY-003", "browser": "chrome"})
        )


def test_jurisdiction_rule_requires_applicability() -> None:
    with pytest.raises(ValueError, match="applies_to_modules"):
        KnowledgeDocument.model_validate(
            _document(
                source_id="RULE-900",
                type="jurisdiction_rule",
                metadata={"region": "US-Nevada"},
            )
        )


def test_list_metadata_is_encoded_for_scalar_only_stores() -> None:
    document = KnowledgeDocument.model_validate(
        _document(
            source_id="RULE-900",
            type="jurisdiction_rule",
            metadata={"region": "EU", "applies_to_modules": ["payment", "checkout"]},
        )
    )

    flattened = document.flatten_metadata()

    assert flattened["applies_to_modules"] == "|payment|checkout|"
    assert flattened["source_id"] == "RULE-900"
    assert flattened["type"] == "jurisdiction_rule"


def test_encoded_list_membership_is_exact() -> None:
    encoded = "|payment|checkout|"

    assert list_contains(encoded, "payment") is True
    assert list_contains(encoded, "pay") is False
    assert decode_list(encoded) == ["payment", "checkout"]
    assert decode_list(None) == []


def test_missing_directory_is_reported(tmp_path) -> None:
    with pytest.raises(KnowledgeBaseError, match="not found"):
        load_documents(tmp_path / "absent")


def test_empty_corpus_is_reported(tmp_path) -> None:
    with pytest.raises(KnowledgeBaseError, match="no documents"):
        load_documents(tmp_path)


def test_malformed_json_is_reported(tmp_path) -> None:
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(KnowledgeBaseError, match="not valid JSON"):
        load_documents(tmp_path)


def test_non_array_file_is_reported(tmp_path) -> None:
    (tmp_path / "object.json").write_text('{"source_id": "X"}', encoding="utf-8")

    with pytest.raises(KnowledgeBaseError, match="JSON array"):
        load_documents(tmp_path)


def test_duplicate_source_ids_are_rejected(tmp_path) -> None:
    (tmp_path / "a.json").write_text(json.dumps([_document()]), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps([_document()]), encoding="utf-8")

    with pytest.raises(KnowledgeBaseError, match="duplicate source IDs"):
        load_documents(tmp_path)


def test_loading_is_deterministic(tmp_path) -> None:
    (tmp_path / "a.json").write_text(json.dumps([_document()]), encoding="utf-8")
    (tmp_path / "b.json").write_text(
        json.dumps([_document(source_id="HIST-901")]), encoding="utf-8"
    )

    first = [document.source_id for document in load_documents(tmp_path)]
    second = [document.source_id for document in load_documents(tmp_path)]

    assert first == second == ["HIST-900", "HIST-901"]
