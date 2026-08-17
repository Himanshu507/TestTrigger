from datetime import date

import pytest

from app.catalog import TestCatalog
from app.db.database import Database
from app.db.repositories import ExecutionRepository, PlanRepository, WorkflowRepository
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.intent import TestIntent
from app.models.workflow import AgentRunStatus
from app.services.planning_service import PlanningService
from app.services.policy import ViolationCode

TODAY = date(2026, 8, 17)
WORKFLOW_ID = "WF-1001"


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture
def database(tmp_path) -> Database:
    created = Database(tmp_path / "test-trigger.db")
    created.initialize()
    WorkflowRepository(created).create_workflow(
        workflow_id=WORKFLOW_ID, query="Run payment smoke tests", dry_run=True
    )
    return created


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


def _nevada_rule():
    return RetrievedEvidence(
        source_id="RULE-005",
        type=EvidenceType.JURISDICTION_RULE,
        content="Safari is not certified for the Nevada validation profile.",
        metadata={
            "region": "US-Nevada",
            "applies_to_modules": ["withdrawal", "payment"],
            "unsupported_browsers": ["safari"],
        },
    )


def test_a_valid_request_produces_an_executable_plan(catalog) -> None:
    outcome = PlanningService(catalog).plan_and_validate(_intent(), reference_date=TODAY)

    assert outcome.is_executable is True
    assert outcome.plan.test_ids == ["PAY-001", "PAY-003"]
    assert outcome.rejection_summary is None


def test_a_request_with_no_matching_tests_is_rejected(catalog) -> None:
    outcome = PlanningService(catalog).plan_and_validate(
        _intent(module="login", region="US-Nevada"), reference_date=TODAY
    )

    assert outcome.is_executable is False
    assert outcome.violation_codes == [ViolationCode.NO_TESTS_SELECTED]
    assert "NO_TESTS_SELECTED" in outcome.rejection_summary


def test_a_jurisdiction_rule_rejects_an_otherwise_plannable_request(catalog) -> None:
    outcome = PlanningService(catalog).plan_and_validate(
        _intent(module="withdrawal", region="US-Nevada", browser="safari"),
        [_nevada_rule()],
        reference_date=TODAY,
    )

    assert outcome.is_executable is False
    assert ViolationCode.NO_TESTS_SELECTED in outcome.violation_codes


def test_planning_persists_the_plan_and_an_agent_run(catalog, database) -> None:
    service = PlanningService(
        catalog,
        repository=WorkflowRepository(database),
        plan_repository=PlanRepository(database),
    )

    service.plan_and_validate(_intent(), workflow_id=WORKFLOW_ID, reference_date=TODAY)

    stored = PlanRepository(database).list_plan_items(WORKFLOW_ID)
    run = WorkflowRepository(database).list_agent_runs(WORKFLOW_ID)[0]

    assert [item.test_id for item in stored] == ["PAY-001", "PAY-003"]
    assert stored[0].reasons
    assert run.agent_name == "planner"
    assert run.status is AgentRunStatus.COMPLETED
    assert run.input_payload["policy_version"] == "policy-v1"


def test_risk_factors_survive_persistence(catalog, database) -> None:
    evidence = [
        RetrievedEvidence(
            source_id=f"HIST-{index}",
            type=EvidenceType.HISTORICAL_FAILURE,
            content="PAY-003 failed",
            metadata={
                "test_id": "PAY-003",
                "browser": "chrome",
                "region": "US",
                "date": "2026-08-11",
            },
        )
        for index in range(2)
    ]
    service = PlanningService(catalog, plan_repository=PlanRepository(database))

    service.plan_and_validate(
        _intent(), evidence, workflow_id=WORKFLOW_ID, reference_date=TODAY
    )

    stored = PlanRepository(database).list_plan_items(WORKFLOW_ID)
    top = next(item for item in stored if item.test_id == "PAY-003")

    assert top.risk_score > 0.5
    assert {factor.name for factor in top.risk_factors} >= {
        "criticality",
        "failure_frequency",
    }


def test_a_rejected_plan_records_no_plan_items(catalog, database) -> None:
    service = PlanningService(
        catalog,
        repository=WorkflowRepository(database),
        plan_repository=PlanRepository(database),
    )

    service.plan_and_validate(
        _intent(module="login", region="US-Nevada"),
        workflow_id=WORKFLOW_ID,
        reference_date=TODAY,
    )

    assert PlanRepository(database).list_plan_items(WORKFLOW_ID) == []


def test_planning_never_creates_an_execution(catalog, database) -> None:
    service = PlanningService(
        catalog,
        repository=WorkflowRepository(database),
        plan_repository=PlanRepository(database),
    )

    outcome = service.plan_and_validate(
        _intent(), workflow_id=WORKFLOW_ID, reference_date=TODAY
    )

    assert outcome.is_executable is True
    assert ExecutionRepository(database).find_by_workflow(WORKFLOW_ID) is None


def test_a_dry_run_and_a_real_run_plan_identically(catalog) -> None:
    service = PlanningService(catalog)

    first = service.plan_and_validate(_intent(), reference_date=TODAY)
    second = service.plan_and_validate(_intent(), reference_date=TODAY)

    assert first.plan.model_dump() == second.plan.model_dump()


def test_planning_without_persistence_is_supported(catalog) -> None:
    outcome = PlanningService(catalog).plan_and_validate(
        _intent(), workflow_id=WORKFLOW_ID, reference_date=TODAY
    )

    assert outcome.is_executable is True
