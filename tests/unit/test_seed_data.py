"""Seed-data completeness checks (FND-5).

The knowledge base is evidence for planning and analysis, so a document that
references an unknown test ID would let an agent cite something the catalog
cannot execute.
"""

from typing import List

import pytest

from app.catalog import TestCatalog
from app.knowledge.documents import KnowledgeDocument, decode_list
from app.knowledge.loader import load_documents
from app.models.evidence import EvidenceType


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture(scope="module")
def documents() -> List[KnowledgeDocument]:
    return load_documents()


def _of_type(documents: List[KnowledgeDocument], evidence_type: EvidenceType) -> list:
    return [document for document in documents if document.type is evidence_type]


def test_catalog_holds_between_ten_and_fifteen_tests(catalog: TestCatalog) -> None:
    assert 10 <= len(catalog.all()) <= 15


def test_catalog_covers_every_module_and_scope(catalog: TestCatalog) -> None:
    tests = catalog.all()
    assert {test.module for test in tests} == set(type(tests[0].module))
    assert {test.scope for test in tests} == set(type(tests[0].scope))


@pytest.mark.parametrize(
    "evidence_type",
    [
        EvidenceType.TEST_DOCUMENTATION,
        EvidenceType.HISTORICAL_FAILURE,
        EvidenceType.JURISDICTION_RULE,
    ],
)
def test_every_evidence_type_is_represented(
    documents: List[KnowledgeDocument], evidence_type: EvidenceType
) -> None:
    assert _of_type(documents, evidence_type)


def test_source_ids_are_unique_across_the_knowledge_base(
    documents: List[KnowledgeDocument],
) -> None:
    source_ids = [document.source_id for document in documents]
    assert len(source_ids) == len(set(source_ids))


def test_every_referenced_test_id_exists_in_the_catalog(
    documents: List[KnowledgeDocument], catalog: TestCatalog
) -> None:
    referenced = {
        document.metadata["test_id"]
        for document in documents
        if "test_id" in document.metadata
    }

    assert referenced
    assert all(catalog.get(test_id) is not None for test_id in referenced)


def test_every_catalog_test_has_documentation(
    documents: List[KnowledgeDocument], catalog: TestCatalog
) -> None:
    documented = {
        document.metadata["test_id"]
        for document in _of_type(documents, EvidenceType.TEST_DOCUMENTATION)
    }

    assert documented == {test.id for test in catalog.all()}


def test_historical_failures_use_supported_browsers_and_regions(
    documents: List[KnowledgeDocument], catalog: TestCatalog
) -> None:
    for failure in _of_type(documents, EvidenceType.HISTORICAL_FAILURE):
        test_case = catalog.get(failure.metadata["test_id"])
        assert failure.metadata["browser"] in test_case.browsers
        assert failure.metadata["region"] in test_case.regions


def test_jurisdiction_rules_apply_to_known_modules(
    documents: List[KnowledgeDocument], catalog: TestCatalog
) -> None:
    known_modules = {test.module.value for test in catalog.all()}
    known_regions = {region.value for test in catalog.all() for region in test.regions}

    for rule in _of_type(documents, EvidenceType.JURISDICTION_RULE):
        assert rule.metadata["region"] in known_regions
        modules = rule.metadata["applies_to_modules"]
        assert modules
        assert set(decode_list(rule.flatten_metadata()["applies_to_modules"])) <= known_modules
