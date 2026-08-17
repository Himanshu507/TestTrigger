import pytest

from app.agents.retrieval import AGENT_NAME, RetrievalAgent, RetrievalError
from app.catalog import TestCatalog
from app.db.database import Database
from app.db.repositories import WorkflowRepository
from app.knowledge.ingest import ingest
from app.llm.errors import ProviderTimeoutError
from app.models.evidence import EvidenceType
from app.models.intent import TestIntent
from app.models.workflow import AgentRunStatus
from app.retrieval.store import ChromaVectorStore
from tests.fakes import FailingEmbedder, FailingVectorStore, HashingEmbedder

WORKFLOW_ID = "WF-1001"
QUERY = "Run payment smoke tests on Chrome in US"


def _intent(**overrides) -> TestIntent:
    values = {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
        "confidence": 0.95,
    }
    values.update(overrides)
    return TestIntent(**values)


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture
def store(tmp_path) -> ChromaVectorStore:
    created = ChromaVectorStore(str(tmp_path / "chroma"), collection_name="retrieval_test")
    ingest(created, HashingEmbedder())
    return created


@pytest.fixture
def repository(tmp_path) -> WorkflowRepository:
    created = WorkflowRepository(Database(tmp_path / "test-trigger.db"))
    created.initialize()
    created.create_workflow(workflow_id=WORKFLOW_ID, query=QUERY, dry_run=False)
    return created


def _agent(store, catalog, **overrides) -> RetrievalAgent:
    return RetrievalAgent(store, HashingEmbedder(), catalog, **overrides)


def test_evidence_is_grouped_by_type(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(_intent())

    assert result.test_documentation
    assert all(
        evidence.type is EvidenceType.TEST_DOCUMENTATION
        for evidence in result.test_documentation
    )
    assert all(
        evidence.type is EvidenceType.HISTORICAL_FAILURE
        for evidence in result.historical_failures
    )
    assert all(
        evidence.type is EvidenceType.JURISDICTION_RULE
        for evidence in result.jurisdiction_rules
    )


def test_only_catalog_compatible_tests_appear_as_evidence(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(_intent())

    compatible = {
        test.id
        for test in catalog.filter(module="payment", scope="smoke", browser="chrome", region="US")
    }
    referenced = {
        evidence.metadata["test_id"]
        for evidence in result.test_documentation + result.historical_failures
    }

    assert referenced
    assert referenced <= compatible


def test_a_chrome_us_query_never_returns_a_safari_only_candidate(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(
        _intent(module="wallet", scope="regression", browser="safari", region="UK")
    )

    referenced = {
        evidence.metadata["test_id"]
        for evidence in result.test_documentation + result.historical_failures
    }

    assert referenced <= {"WAL-002"}


def test_jurisdiction_rules_are_filtered_by_region_and_module(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(
        _intent(module="withdrawal", scope="smoke", region="US-Nevada")
    )

    assert result.jurisdiction_rules
    for evidence in result.jurisdiction_rules:
        assert evidence.metadata["region"] == "US-Nevada"
        assert "withdrawal" in evidence.metadata["applies_to_modules"]


def test_rules_for_another_region_are_excluded(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(_intent())

    assert all(
        evidence.metadata["region"] == "US" for evidence in result.jurisdiction_rules
    )


def test_every_returned_document_carries_a_source_id_and_score(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(_intent())

    for evidence in result.all_evidence:
        assert evidence.source_id
        assert 0.0 <= evidence.score <= 1.0
    assert result.diagnostics.returned_source_ids == result.source_ids
    assert set(result.diagnostics.scores) == set(result.source_ids)


def test_results_are_bounded_by_the_context_budget(store, catalog) -> None:
    unbounded = _agent(store, catalog).retrieve(_intent())
    bounded = _agent(store, catalog, max_context_chars=200).retrieve(_intent())

    total = sum(len(evidence.content) for evidence in bounded.all_evidence)

    assert len(bounded.all_evidence) < len(unbounded.all_evidence)
    assert total <= 200 or len(bounded.all_evidence) == 1
    assert bounded.diagnostics.truncated is True
    assert bounded.diagnostics.dropped_source_ids


def test_top_k_bounds_each_evidence_group(store, catalog) -> None:
    result = _agent(store, catalog, top_k=1).retrieve(_intent())

    assert len(result.test_documentation) <= 1
    assert len(result.historical_failures) <= 1
    assert result.diagnostics.top_k == 1


def test_diagnostics_record_the_deterministic_filters(store, catalog) -> None:
    result = _agent(store, catalog).retrieve(_intent())

    assert result.diagnostics.filters == {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
    }
    assert "PAY-001" in result.diagnostics.candidate_test_ids


def test_an_empty_store_returns_no_evidence_without_failing(tmp_path, catalog) -> None:
    empty = ChromaVectorStore(str(tmp_path / "chroma"), collection_name="empty_test")

    result = _agent(empty, catalog).retrieve(_intent())

    assert result.is_empty
    assert result.diagnostics.returned_source_ids == []


def test_an_intent_with_no_catalog_candidates_returns_no_test_evidence(
    store, catalog
) -> None:
    result = _agent(store, catalog).retrieve(
        _intent(module="login", scope="smoke", region="US-Nevada")
    )

    assert result.test_documentation == []
    assert result.historical_failures == []
    assert result.diagnostics.candidate_test_ids == []


def test_incomplete_intent_is_refused(store, catalog) -> None:
    with pytest.raises(RetrievalError, match="complete intent"):
        _agent(store, catalog).retrieve(
            TestIntent(module="payment", confidence=0.9, missing_fields=["browser"])
        )


def test_vector_store_failure_is_surfaced_not_replaced_with_emptiness(catalog) -> None:
    agent = RetrievalAgent(FailingVectorStore(), HashingEmbedder(), catalog)

    with pytest.raises(RetrievalError, match="store unavailable"):
        agent.retrieve(_intent())


def test_embedding_failure_is_surfaced(store, catalog) -> None:
    agent = RetrievalAgent(
        store, FailingEmbedder(ProviderTimeoutError("embeddings timed out")), catalog
    )

    with pytest.raises(RetrievalError, match="timed out"):
        agent.retrieve(_intent())


def test_successful_retrieval_is_audited(store, catalog, repository) -> None:
    agent = _agent(store, catalog, repository=repository)

    result = agent.retrieve(_intent(), workflow_id=WORKFLOW_ID)

    run = repository.list_agent_runs(WORKFLOW_ID)[0]
    assert run.agent_name == AGENT_NAME
    assert run.status is AgentRunStatus.COMPLETED
    assert run.input_payload["filters"]["browser"] == "chrome"
    assert run.output_payload["returned_source_ids"] == result.source_ids


def test_retrieval_failure_is_audited_before_raising(catalog, repository) -> None:
    agent = RetrievalAgent(
        FailingVectorStore(), HashingEmbedder(), catalog, repository=repository
    )

    with pytest.raises(RetrievalError):
        agent.retrieve(_intent(), workflow_id=WORKFLOW_ID)

    run = repository.list_agent_runs(WORKFLOW_ID)[0]
    assert run.status is AgentRunStatus.FAILED
    assert "store unavailable" in run.error
