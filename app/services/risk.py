"""Explainable risk scoring for prioritization.

The score orders a plan; it never authorizes or blocks execution. Every
contributing term is recorded so a reviewer can reconstruct the number by hand.

Weights (documented MVP policy):

    criticality           high 0.50 | medium 0.30 | low 0.10
    failure frequency     up to 0.30, scaled by min(failures, 3) / 3
    failure recency       0.10 within 30 days, 0.05 within 90 days
    matching conditions   0.10 when a past failure shares this browser+region

The sum is clamped to 1.0.
"""

from datetime import date
from typing import Iterable, List, Optional

from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.plan import ExplainableScore, RiskFactor
from app.models.test_case import Browser, Criticality, Region, TestCase

RISK_POLICY_VERSION = "risk-v1"

CRITICALITY_WEIGHTS = {
    Criticality.HIGH: 0.50,
    Criticality.MEDIUM: 0.30,
    Criticality.LOW: 0.10,
}

MAX_COUNTED_FAILURES = 3
FREQUENCY_WEIGHT = 0.30
RECENT_DAYS = 30
RECENT_WEIGHT = 0.10
SEMI_RECENT_DAYS = 90
SEMI_RECENT_WEIGHT = 0.05
MATCHING_CONDITIONS_WEIGHT = 0.10


def risk_score(
    test: TestCase,
    evidence: Iterable[RetrievedEvidence],
    *,
    browser: Optional[Browser] = None,
    region: Optional[Region] = None,
    reference_date: Optional[date] = None,
) -> ExplainableScore:
    """Score one test against its retrieved failure history.

    ``reference_date`` is injected rather than read from the clock so a score
    is reproducible in tests and in an audit.
    """
    today = reference_date or date.today()
    failures = [
        item
        for item in evidence
        if item.type is EvidenceType.HISTORICAL_FAILURE
        and item.metadata.get("test_id") == test.id
    ]

    factors: List[RiskFactor] = [
        RiskFactor(
            name="criticality",
            weight=CRITICALITY_WEIGHTS[test.criticality],
            detail=f"{test.id} is marked {test.criticality.value} criticality",
        )
    ]

    if failures:
        counted = min(len(failures), MAX_COUNTED_FAILURES)
        factors.append(
            RiskFactor(
                name="failure_frequency",
                weight=round(FREQUENCY_WEIGHT * counted / MAX_COUNTED_FAILURES, 4),
                detail=f"{len(failures)} historical failure(s) retrieved for {test.id}",
            )
        )

        recency = _recency_factor(failures, today)
        if recency is not None:
            factors.append(recency)

        matching = _matching_conditions_factor(failures, browser, region)
        if matching is not None:
            factors.append(matching)

    value = min(1.0, round(sum(factor.weight for factor in factors), 4))
    return ExplainableScore(value=value, factors=factors)


def _recency_factor(
    failures: List[RetrievedEvidence], today: date
) -> Optional[RiskFactor]:
    """Weight the most recent failure, ignoring undated or future records."""
    ages = [
        (today - parsed).days
        for parsed in (_parse_date(item.metadata.get("date")) for item in failures)
        if parsed is not None and parsed <= today
    ]
    if not ages:
        return None

    newest = min(ages)
    if newest <= RECENT_DAYS:
        return RiskFactor(
            name="failure_recency",
            weight=RECENT_WEIGHT,
            detail=f"most recent failure was {newest} day(s) ago",
        )
    if newest <= SEMI_RECENT_DAYS:
        return RiskFactor(
            name="failure_recency",
            weight=SEMI_RECENT_WEIGHT,
            detail=f"most recent failure was {newest} day(s) ago",
        )
    return None


def _matching_conditions_factor(
    failures: List[RetrievedEvidence],
    browser: Optional[Browser],
    region: Optional[Region],
) -> Optional[RiskFactor]:
    if browser is None or region is None:
        return None

    matches = [
        item
        for item in failures
        if item.metadata.get("browser") == browser.value
        and item.metadata.get("region") == region.value
    ]
    if not matches:
        return None
    return RiskFactor(
        name="matching_conditions",
        weight=MATCHING_CONDITIONS_WEIGHT,
        detail=(
            f"{len(matches)} past failure(s) on {browser.value} in {region.value}"
        ),
    )


def _parse_date(value: object) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
