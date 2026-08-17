from datetime import date

import pytest

from app.catalog import TestCatalog
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.intent import TestIntent
from app.services.planner import PlanningError, TestPlanner

TODAY = date(2026, 8, 17)


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture
def planner(catalog) -> TestPlanner:
    return TestPlanner(catalog)


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


def _failure(test_id: str, day: str, browser: str = "chrome", region: str = "US"):
    return RetrievedEvidence(
        source_id=f"HIST-{test_id}-{day}",
        type=EvidenceType.HISTORICAL_FAILURE,
        content=f"{test_id} failed",
        metadata={"test_id": test_id, "browser": browser, "region": region, "date": day},
    )


def test_plan_contains_only_catalogued_tests(planner, catalog) -> None:
    plan = planner.plan(_intent(), reference_date=TODAY)

    assert plan.items
    assert all(catalog.get(item.test_id) is not None for item in plan.items)


def test_selection_matches_module_scope_browser_and_region(planner) -> None:
    plan = planner.plan(_intent(), reference_date=TODAY)

    assert sorted(item.test_id for item in plan.items) == ["PAY-001", "PAY-003"]


def test_incompatible_tests_are_excluded_with_a_reason(planner) -> None:
    plan = planner.plan(_intent(browser="safari"), reference_date=TODAY)

    excluded = {exclusion.test_id: exclusion.reason for exclusion in plan.exclusions}
    assert "PAY-003" in excluded
    assert "does not support safari" in excluded["PAY-003"]


def test_wrong_scope_is_excluded_with_a_reason(planner) -> None:
    plan = planner.plan(_intent(), reference_date=TODAY)

    excluded = {exclusion.test_id: exclusion.reason for exclusion in plan.exclusions}
    assert "regression test, not smoke" in excluded["PAY-002"]


def test_region_exclusion_is_recorded(planner) -> None:
    plan = planner.plan(_intent(region="UK"), reference_date=TODAY)

    excluded = {exclusion.test_id: exclusion.reason for exclusion in plan.exclusions}
    assert "not available in UK" in excluded["PAY-001"]


def test_unrelated_modules_are_not_listed_as_exclusions(planner) -> None:
    plan = planner.plan(_intent(), reference_date=TODAY)

    assert all(exclusion.test_id.startswith("PAY-") for exclusion in plan.exclusions)


def test_a_request_with_no_matches_produces_an_empty_plan(planner) -> None:
    plan = planner.plan(
        _intent(module="login", scope="smoke", region="US-Nevada"), reference_date=TODAY
    )

    assert plan.items == []
    assert plan.is_executable is False


def test_higher_risk_tests_are_ordered_first(planner) -> None:
    evidence = [
        _failure("PAY-001", "2026-08-15"),
        _failure("PAY-001", "2026-08-10"),
        _failure("PAY-001", "2026-08-05"),
    ]

    plan = planner.plan(_intent(), evidence, reference_date=TODAY)

    assert plan.test_ids == ["PAY-001", "PAY-003"]
    assert plan.items[0].priority == 1
    assert plan.items[0].risk_score > plan.items[1].risk_score


def test_ordering_is_stable_when_scores_tie(planner) -> None:
    first = planner.plan(_intent(), reference_date=TODAY)
    second = planner.plan(_intent(), reference_date=TODAY)

    assert first.test_ids == second.test_ids == ["PAY-001", "PAY-003"]
    assert [item.priority for item in first.items] == [1, 2]


def test_every_item_records_score_factors_and_readable_reasons(planner) -> None:
    plan = planner.plan(_intent(), [_failure("PAY-003", "2026-08-11")], reference_date=TODAY)

    item = next(item for item in plan.items if item.test_id == "PAY-003")
    assert item.risk_score > 0
    assert {factor.name for factor in item.risk_factors} >= {"criticality"}
    assert any("payment module and smoke scope" in reason for reason in item.reasons)
    assert any("historical failure" in reason for reason in item.reasons)


def test_a_candidate_plan_is_not_executable_before_policy_runs(planner) -> None:
    plan = planner.plan(_intent(), reference_date=TODAY)

    assert plan.policy_result is None
    assert plan.is_executable is False


def test_planning_requires_a_complete_intent(planner) -> None:
    with pytest.raises(PlanningError, match="complete intent"):
        planner.plan(
            TestIntent(module="payment", confidence=0.9, missing_fields=["browser"])
        )


def test_plan_carries_the_requested_context(planner) -> None:
    plan = planner.plan(_intent(environment="staging"), reference_date=TODAY)

    assert plan.module.value == "payment"
    assert plan.browser.value == "chrome"
    assert plan.region.value == "US"
    assert plan.environment == "staging"
