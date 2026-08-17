"""Runs the evaluation set as part of the suite (QLT-5).

Thresholds are asserted rather than merely reported, so a regression in intent
normalization, metadata filtering, or analysis grounding fails the build
instead of quietly degrading a number in a document.
"""

import pytest

from app.agents.retrieval import RetrievalAgent
from app.catalog import TestCatalog
from app.evaluation.harness import (
    evaluate_analysis,
    evaluate_intent,
    evaluate_retrieval,
    format_report,
    load_dataset,
    run_evaluation,
)
from app.knowledge.ingest import ingest
from app.retrieval.store import ChromaVectorStore
from tests.fakes import HashingEmbedder

K = 5


@pytest.fixture(scope="module")
def dataset() -> dict:
    return load_dataset()


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture(scope="module")
def agent(tmp_path_factory, catalog) -> RetrievalAgent:
    directory = tmp_path_factory.mktemp("evaluation")
    store = ChromaVectorStore(str(directory), collection_name="evaluation")
    embedder = HashingEmbedder()
    ingest(store, embedder)
    return RetrievalAgent(store, embedder, catalog)


def test_the_dataset_is_large_enough_to_be_meaningful(dataset) -> None:
    assert len(dataset["intent_cases"]) >= 8
    assert len(dataset["retrieval_cases"]) >= 5
    assert len(dataset["analysis_cases"]) >= 4


def test_intent_extraction_matches_every_labelled_case(dataset) -> None:
    report = evaluate_intent(dataset)

    failures = [case for case in report.cases if not case.passed]
    assert not failures, [f"{case.case_id}: {case.detail}" for case in failures]
    assert report.score == 1.0


def test_metadata_filtering_never_leaks_an_incompatible_test(dataset, agent, catalog) -> None:
    report = evaluate_retrieval(dataset, agent, catalog, k=K)

    failures = [case for case in report.cases if not case.passed]
    assert not failures, [f"{case.case_id}: {case.detail}" for case in failures]


def test_relevant_evidence_is_retrieved_within_k(dataset, agent, catalog) -> None:
    report = evaluate_retrieval(dataset, agent, catalog, k=K)

    assert report.extra["hit_at_k"] >= 0.8, report.extra
    assert report.extra["recall_at_k"] >= 0.7, report.extra


def test_grounded_analysis_is_accepted_and_ungrounded_is_refused(dataset) -> None:
    report = evaluate_analysis(dataset)

    failures = [case for case in report.cases if not case.passed]
    assert not failures, [f"{case.case_id}: {case.detail}" for case in failures]


def test_the_full_report_renders_for_review(dataset, agent, catalog) -> None:
    report = run_evaluation(agent=agent, catalog=catalog, dataset=dataset, k=K)

    text = format_report(report)

    assert report.all_passed
    assert "intent_field_accuracy" in text
    assert "hit_at_k" in text
    assert "recall_at_k" in text
    assert "grounded_analysis_review" in text
