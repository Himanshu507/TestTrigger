"""Seed-data completeness checks (FND-5).

The knowledge base is evidence for planning and analysis, so a document that
references an unknown test ID would let an agent cite something the catalog
cannot execute.
"""

import json
from pathlib import Path

import pytest

from app.catalog import TestCatalog
from app.models.evidence import EvidenceType, RetrievedEvidence

KNOWLEDGE_BASE = Path(__file__).resolve().parents[2] / "knowledge_base"
DOCUMENT_FILES = {
    "test_documentation.json": EvidenceType.TEST_DOCUMENTATION,
    "historical_failures.json": EvidenceType.HISTORICAL_FAILURE,
    "jurisdiction_rules.json": EvidenceType.JURISDICTION_RULE,
}


def _load(filename: str) -> list:
    return json.loads((KNOWLEDGE_BASE / filename).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture(scope="module")
def documents() -> list:
    return [
        RetrievedEvidence.model_validate(document)
        for filename in DOCUMENT_FILES
        for document in _load(filename)
    ]


def test_catalog_holds_between_ten_and_fifteen_tests(catalog: TestCatalog) -> None:
    assert 10 <= len(catalog.all()) <= 15


def test_catalog_covers_every_module_and_scope(catalog: TestCatalog) -> None:
    tests = catalog.all()
    assert {test.module for test in tests} == set(type(tests[0].module))
    assert {test.scope for test in tests} == set(type(tests[0].scope))


@pytest.mark.parametrize("filename,expected_type", DOCUMENT_FILES.items())
def test_documents_validate_as_evidence(filename: str, expected_type) -> None:
    documents = [RetrievedEvidence.model_validate(row) for row in _load(filename)]

    assert documents
    assert all(document.type is expected_type for document in documents)


def test_source_ids_are_unique_across_the_knowledge_base(documents: list) -> None:
    source_ids = [document.source_id for document in documents]
    assert len(source_ids) == len(set(source_ids))


def test_every_referenced_test_id_exists_in_the_catalog(
    documents: list, catalog: TestCatalog
) -> None:
    referenced = {
        document.metadata["test_id"]
        for document in documents
        if "test_id" in document.metadata
    }

    assert referenced
    assert all(catalog.get(test_id) is not None for test_id in referenced)


def test_every_catalog_test_has_documentation(catalog: TestCatalog) -> None:
    documented = {
        document["metadata"]["test_id"] for document in _load("test_documentation.json")
    }

    assert documented == {test.id for test in catalog.all()}


def test_historical_failures_use_supported_browsers_and_regions(
    catalog: TestCatalog,
) -> None:
    for failure in _load("historical_failures.json"):
        metadata = failure["metadata"]
        test_case = catalog.get(metadata["test_id"])
        assert metadata["browser"] in test_case.browsers
        assert metadata["region"] in test_case.regions
