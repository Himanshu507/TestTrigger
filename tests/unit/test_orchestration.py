from datetime import date
from typing import List, Optional, Sequence

import pytest

from app.agents.execution import ExecutionAgent
from app.agents.intent import IntentAgent
from app.agents.retrieval import RetrievalAgent, RetrievalError
from app.catalog import TestCatalog
from app.db.database import Database
from app.db.repositories import (
    AnalysisRepository,
    EventRepository,
    ExecutionRepository,
    PlanRepository,
    WorkflowRepository,
)
from app.integrations.mock_jenkins import MockJenkinsService
from app.knowledge.ingest import ingest
from app.models.analysis import AnalysisReport, AnalysisStatus, FailureAnalysis
from app.models.plan import ExecutionPlan
from app.models.workflow import WorkflowStatus
from app.orchestration.dependencies import WorkflowDependencies
from app.orchestration.runner import WorkflowRunner
from app.retrieval.store import ChromaVectorStore
from app.services.planning_service import PlanningService
from tests.fakes import HashingEmbedder
from tests.unit.test_intent_agent import FakeProvider

TODAY = date(2026, 8, 17)
QUERY = "Run smoke tests for payment on Chrome in the US"


def _intent_payload(**overrides) -> dict:
    payload = {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
        "environment": None,
        "confidence": 0.95,
        "missing_fields": [],
    }
    payload.update(overrides)
    return payload


class StubAnalyzer:
    """Returns a canned report, or raises to exercise the fallback route."""

    def __init__(self, report: Optional[AnalysisReport] = None, error: Exception = None):
        self.report = report
        self.error = error
        self.calls = 0

    def analyze(self, *, plan, results, evidence, workflow_id=None) -> AnalysisReport:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.report


class BrokenRetrieval:
    def retrieve(self, intent, *, workflow_id=None):
        raise RetrievalError("evidence retrieval failed: store unavailable")


def _grounded_report() -> AnalysisReport:
    return AnalysisReport(
        summary="1 of 2 tests failed.",
        status=AnalysisStatus.AI_GENERATED,
        observations=["PAY-003 failed"],
        failures=[
            FailureAnalysis(
                test_id="PAY-003",
                likely_cause="3DS redirect timeout",
                confidence=0.8,
                evidence_source_ids=["HIST-001"],
            )
        ],
    )


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture
def database(tmp_path) -> Database:
    created = Database(tmp_path / "test-trigger.db")
    created.initialize()
    return created


@pytest.fixture
def store(tmp_path) -> ChromaVectorStore:
    created = ChromaVectorStore(str(tmp_path / "chroma"), collection_name="orchestration")
    ingest(created, HashingEmbedder())
    return created


def _dependencies(
    database,
    store,
    catalog,
    *,
    intent_payload=None,
    intent_error=None,
    retrieval=None,
    jenkins=None,
    analyzer=None,
) -> WorkflowDependencies:
    workflows = WorkflowRepository(database)
    return WorkflowDependencies(
        intent_agent=IntentAgent(
            FakeProvider(
                payload=intent_payload if intent_error is None else None,
                error=intent_error,
            ),
            repository=workflows,
        ),
        retrieval_agent=retrieval
        or RetrievalAgent(store, HashingEmbedder(), catalog, repository=workflows),
        planning_service=PlanningService(
            catalog, repository=workflows, plan_repository=PlanRepository(database)
        ),
        execution_agent=ExecutionAgent(
            jenkins or MockJenkinsService(seed="demo"),
            ExecutionRepository(database),
            repository=workflows,
        ),
        workflows=workflows,
        events=EventRepository(database),
        analysis=AnalysisRepository(database),
        analyzer=analyzer,
        reference_date=TODAY,
    )


def _runner(database, store, catalog, **kwargs) -> WorkflowRunner:
    return WorkflowRunner(_dependencies(database, store, catalog, **kwargs))


def _steps(database, workflow_id: str) -> List[str]:
    return [event.step for event in EventRepository(database).list_events(workflow_id)]


def _statuses(database, workflow_id: str) -> List[str]:
    return [event.status for event in EventRepository(database).list_events(workflow_id)]


def test_happy_path_completes_with_persisted_state(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(_grounded_report()),
    )

    state = runner.run(QUERY)

    assert state["status"] == WorkflowStatus.COMPLETED.value
    assert state["intent"]["module"] == "payment"
    assert state["test_plan"]["items"]
    assert state["execution_id"].startswith("JOB-")
    assert len(state["execution_results"]) == 2
    assert state["analysis"]["status"] == "ai_generated"
    assert runner.get_workflow(state["workflow_id"]).status is WorkflowStatus.COMPLETED


def test_happy_path_visits_every_stage_in_order(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(_grounded_report()),
    )

    state = runner.run(QUERY)

    assert _steps(database, state["workflow_id"]) == [
        "workflow",
        "intent",
        "retrieval",
        "planning",
        "execution",
        "execution",
        "execution",
        "analysis",
        "workflow",
    ]
    assert _statuses(database, state["workflow_id"])[-4:] == [
        "execution_running",
        "results_collected",
        "analyzed",
        "completed",
    ]


def test_an_unparseable_request_ends_in_clarification(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(browser=None, region=None),
    )

    state = runner.run("Run some tests")

    assert state["status"] == WorkflowStatus.NEEDS_CLARIFICATION.value
    assert state["clarification"]["missing_fields"] == ["browser", "region"]
    assert state["summary"]
    assert state["test_plan"] is None
    assert ExecutionRepository(database).find_by_workflow(state["workflow_id"]) is None


def test_a_provider_outage_ends_in_clarification_not_a_guess(
    database, store, catalog
) -> None:
    from app.llm.errors import ProviderTimeoutError

    runner = _runner(
        database, store, catalog, intent_error=ProviderTimeoutError("timed out")
    )

    state = runner.run(QUERY)

    assert state["status"] == WorkflowStatus.NEEDS_CLARIFICATION.value
    assert state["clarification"]["reason"] == "provider_error"


def test_a_retrieval_failure_is_terminal_and_explained(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        retrieval=BrokenRetrieval(),
    )

    state = runner.run(QUERY)

    assert state["status"] == WorkflowStatus.RETRIEVAL_FAILED.value
    assert "store unavailable" in state["summary"]
    assert state["errors"][0]["step"] == "retrieval"
    assert state["test_plan"] is None


def test_a_policy_rejection_never_reaches_execution(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(module="login", region="US-Nevada"),
    )

    state = runner.run("Run login smoke tests on Chrome in Nevada")

    assert state["status"] == WorkflowStatus.REJECTED.value
    assert "NO_TESTS_SELECTED" in state["summary"]
    assert ExecutionRepository(database).find_by_workflow(state["workflow_id"]) is None


def test_a_rejection_records_its_violation_codes(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(module="login", region="US-Nevada"),
    )

    state = runner.run("Run login smoke tests in Nevada")

    policy_event = next(
        event
        for event in EventRepository(database).list_events(state["workflow_id"])
        if event.step == "policy"
    )
    assert "NO_TESTS_SELECTED" in policy_event.metadata["violation_codes"]


def test_a_dry_run_stops_before_execution(database, store, catalog) -> None:
    runner = _runner(database, store, catalog, intent_payload=_intent_payload())

    state = runner.run(QUERY, dry_run=True)

    assert state["status"] == WorkflowStatus.DRY_RUN_COMPLETE.value
    assert state["test_plan"]["items"]
    assert state["execution_id"] is None
    assert state["execution_results"] == []
    assert ExecutionRepository(database).find_by_workflow(state["workflow_id"]) is None


def test_a_dry_run_plans_exactly_what_a_real_run_would(database, store, catalog) -> None:
    dry = _runner(
        database, store, catalog, intent_payload=_intent_payload()
    ).run(QUERY, dry_run=True)
    real = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(_grounded_report()),
    ).run(QUERY)

    assert dry["test_plan"]["items"] == real["test_plan"]["items"]


def test_an_execution_failure_is_terminal_and_keeps_the_plan(
    database, store, catalog
) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        jenkins=MockJenkinsService(force_job_failure=True),
    )

    state = runner.run(QUERY)

    assert state["status"] == WorkflowStatus.EXECUTION_FAILED.value
    assert state["test_plan"]["items"]
    assert state["analysis"] is None
    assert ExecutionRepository(database).find_by_workflow(state["workflow_id"]) is not None


def test_an_analysis_failure_falls_back_and_still_completes(
    database, store, catalog
) -> None:
    analyzer = StubAnalyzer(error=RuntimeError("provider exploded"))
    runner = _runner(
        database, store, catalog, intent_payload=_intent_payload(), analyzer=analyzer
    )

    state = runner.run(QUERY)

    assert state["status"] == WorkflowStatus.COMPLETED.value
    assert state["analysis"]["status"] == "fallback"
    assert "provider exploded" in state["analysis"]["fallback_reason"]
    assert len(state["execution_results"]) == 2
    assert analyzer.calls == 1


def test_results_survive_an_analysis_failure(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(error=RuntimeError("boom")),
    )

    state = runner.run(QUERY)
    execution = ExecutionRepository(database).find_by_workflow(state["workflow_id"])

    assert len(ExecutionRepository(database).list_results(execution.id)) == 2
    assert state["analysis"]["observations"]


def test_a_missing_analyzer_uses_the_fallback_path(database, store, catalog) -> None:
    runner = _runner(database, store, catalog, intent_payload=_intent_payload())

    state = runner.run(QUERY)

    assert state["status"] == WorkflowStatus.COMPLETED.value
    assert state["analysis"]["status"] == "fallback"
    assert "no analysis provider" in state["analysis"]["fallback_reason"]


def test_the_report_is_persisted(database, store, catalog) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(_grounded_report()),
    )

    state = runner.run(QUERY)
    stored = AnalysisRepository(database).get_report(state["workflow_id"])

    assert stored.summary == "1 of 2 tests failed."


def test_a_retry_reuses_the_original_job(database, store, catalog) -> None:
    dependencies = _dependencies(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(_grounded_report()),
    )
    runner = WorkflowRunner(dependencies)

    first = runner.run(QUERY, workflow_id="WF-1001")
    executions = ExecutionRepository(database)
    execution = executions.find_by_workflow("WF-1001")
    retried = dependencies.execution_agent.execute(
        ExecutionPlan.model_validate(first["test_plan"]), workflow_id="WF-1001"
    )

    assert retried.external_job_id == execution.external_job_id
    assert len(executions.list_results(execution.id)) == 2


def test_workflow_ids_are_allocated_from_persisted_state(
    database, store, catalog
) -> None:
    runner = _runner(
        database,
        store,
        catalog,
        intent_payload=_intent_payload(),
        analyzer=StubAnalyzer(_grounded_report()),
    )

    first = runner.run(QUERY)
    second = runner.run(QUERY)

    assert first["workflow_id"] == "WF-1001"
    assert second["workflow_id"] == "WF-1002"


def test_the_timeline_is_available_for_inspection(database, store, catalog) -> None:
    runner = _runner(database, store, catalog, intent_payload=_intent_payload())

    state = runner.run(QUERY, dry_run=True)
    timeline = runner.get_timeline(state["workflow_id"])

    assert [event.step for event in timeline][0] == "workflow"
    assert timeline[-1].status == WorkflowStatus.DRY_RUN_COMPLETE.value
    assert all(event.occurred_at for event in timeline)


def test_a_terminal_workflow_status_is_not_reopened(database, store, catalog) -> None:
    runner = _runner(database, store, catalog, intent_payload=_intent_payload())

    state = runner.run(QUERY, dry_run=True)
    workflow = runner.get_workflow(state["workflow_id"])

    assert workflow.status is WorkflowStatus.DRY_RUN_COMPLETE
    assert workflow.status.is_terminal
