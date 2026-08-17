from datetime import date

import pytest

from app.catalog import TestCatalog
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.test_case import Browser, Region
from app.services.risk import risk_score

TODAY = date(2026, 8, 17)


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


def _failure(test_id: str, *, day: str, browser: str = "chrome", region: str = "US"):
    return RetrievedEvidence(
        source_id=f"HIST-{test_id}-{day}",
        type=EvidenceType.HISTORICAL_FAILURE,
        content=f"{test_id} failed on {browser} in {region}",
        metadata={"test_id": test_id, "browser": browser, "region": region, "date": day},
    )


def test_score_without_history_reflects_criticality_only(catalog) -> None:
    score = risk_score(catalog.get("PAY-003"), [], reference_date=TODAY)

    assert score.value == 0.5
    assert [factor.name for factor in score.factors] == ["criticality"]


def test_low_criticality_scores_below_high(catalog) -> None:
    high = risk_score(catalog.get("WDR-002"), [], reference_date=TODAY)
    low = risk_score(catalog.get("WDR-003"), [], reference_date=TODAY)

    assert high.value > low.value


def test_frequent_recent_matching_failures_raise_the_score(catalog) -> None:
    evidence = [
        _failure("PAY-003", day="2026-08-11"),
        _failure("PAY-003", day="2026-08-04"),
        _failure("PAY-003", day="2026-07-30"),
    ]

    score = risk_score(
        catalog.get("PAY-003"),
        evidence,
        browser=Browser.CHROME,
        region=Region.US,
        reference_date=TODAY,
    )

    assert score.value == pytest.approx(0.5 + 0.30 + 0.10 + 0.10)
    assert {factor.name for factor in score.factors} == {
        "criticality",
        "failure_frequency",
        "failure_recency",
        "matching_conditions",
    }


def test_every_factor_is_explained_and_sums_to_the_score(catalog) -> None:
    score = risk_score(
        catalog.get("PAY-003"),
        [_failure("PAY-003", day="2026-08-11")],
        browser=Browser.CHROME,
        region=Region.US,
        reference_date=TODAY,
    )

    assert score.value == pytest.approx(sum(f.weight for f in score.factors))
    assert all(factor.detail for factor in score.factors)


def test_frequency_weight_is_capped(catalog) -> None:
    three = [_failure("PAY-003", day="2026-08-11") for _ in range(3)]
    six = [_failure("PAY-003", day="2026-08-11") for _ in range(6)]

    assert risk_score(
        catalog.get("PAY-003"), three, reference_date=TODAY
    ).value == risk_score(catalog.get("PAY-003"), six, reference_date=TODAY).value


def test_old_failures_contribute_frequency_but_not_recency(catalog) -> None:
    score = risk_score(
        catalog.get("PAY-003"),
        [_failure("PAY-003", day="2025-01-01")],
        reference_date=TODAY,
    )

    names = {factor.name for factor in score.factors}
    assert "failure_frequency" in names
    assert "failure_recency" not in names


def test_semi_recent_failures_get_the_smaller_recency_weight(catalog) -> None:
    score = risk_score(
        catalog.get("PAY-003"),
        [_failure("PAY-003", day="2026-06-20")],
        reference_date=TODAY,
    )

    recency = next(f for f in score.factors if f.name == "failure_recency")
    assert recency.weight == 0.05


def test_failures_under_other_conditions_do_not_count_as_matching(catalog) -> None:
    score = risk_score(
        catalog.get("PAY-003"),
        [_failure("PAY-003", day="2026-08-11", browser="chrome", region="US-Nevada")],
        browser=Browser.CHROME,
        region=Region.US,
        reference_date=TODAY,
    )

    assert "matching_conditions" not in {factor.name for factor in score.factors}


def test_history_for_another_test_is_ignored(catalog) -> None:
    score = risk_score(
        catalog.get("PAY-001"),
        [_failure("PAY-003", day="2026-08-11")],
        reference_date=TODAY,
    )

    assert [factor.name for factor in score.factors] == ["criticality"]


def test_undated_and_future_failures_do_not_produce_recency(catalog) -> None:
    undated = _failure("PAY-003", day="2026-08-11")
    undated.metadata["date"] = "not-a-date"
    future = _failure("PAY-003", day="2027-01-01")

    score = risk_score(catalog.get("PAY-003"), [undated, future], reference_date=TODAY)

    assert "failure_recency" not in {factor.name for factor in score.factors}


def test_score_never_exceeds_one(catalog) -> None:
    evidence = [_failure("WDR-001", day="2026-08-16") for _ in range(20)]

    score = risk_score(
        catalog.get("WDR-001"),
        evidence,
        browser=Browser.CHROME,
        region=Region.US,
        reference_date=TODAY,
    )

    assert score.value <= 1.0
