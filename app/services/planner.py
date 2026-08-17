"""Test planner: catalogued candidates, ordered and explained.

The planner reads the catalog and retrieved evidence. It cannot produce an ID
the catalog does not contain, and it never submits a job or decides policy.
"""

from datetime import date
from typing import List, Optional, Sequence

from app.catalog import TestCatalog
from app.models.evidence import RetrievedEvidence
from app.models.intent import TestIntent
from app.models.plan import ExcludedTest, ExecutionPlan, PlanItem
from app.models.test_case import TestCase
from app.services.risk import risk_score

PLANNER_VERSION = "planner-v1"


class PlanningError(ValueError):
    """Raised when planning is attempted on an intent that cannot support it."""


class TestPlanner:
    """Selects and orders catalogued tests for a validated intent."""

    def __init__(self, catalog: TestCatalog) -> None:
        self._catalog = catalog

    def plan(
        self,
        intent: TestIntent,
        evidence: Sequence[RetrievedEvidence] = (),
        *,
        reference_date: Optional[date] = None,
    ) -> ExecutionPlan:
        """Build a candidate plan. It is not executable until policy clears it."""
        if not intent.is_actionable:
            raise PlanningError(
                "planning requires a complete intent; missing: "
                + ", ".join(intent.missing_fields)
            )

        selected: List[TestCase] = []
        exclusions: List[ExcludedTest] = []

        for test in self._catalog.all():
            reason = _exclusion_reason(test, intent)
            if reason is None:
                selected.append(test)
            elif test.module is intent.module:
                # Only record near misses; unrelated modules are noise.
                exclusions.append(ExcludedTest(test_id=test.id, reason=reason))

        scored = [
            (
                test,
                risk_score(
                    test,
                    evidence,
                    browser=intent.browser,
                    region=intent.region,
                    reference_date=reference_date,
                ),
            )
            for test in selected
        ]
        # Highest risk first, then test ID so ordering is stable across runs.
        scored.sort(key=lambda pair: (-pair[1].value, pair[0].id))

        items = [
            PlanItem(
                test_id=test.id,
                priority=index,
                risk_score=score.value,
                risk_factors=score.factors,
                reasons=_selection_reasons(test, intent, score),
            )
            for index, (test, score) in enumerate(scored, start=1)
        ]

        return ExecutionPlan(
            module=intent.module,
            scope=intent.scope,
            browser=intent.browser,
            region=intent.region,
            environment=intent.environment,
            items=items,
            exclusions=exclusions,
        )


def _exclusion_reason(test: TestCase, intent: TestIntent) -> Optional[str]:
    """Return why a catalog test is not eligible, or None when it is."""
    if test.module is not intent.module:
        return f"belongs to the {test.module.value} module"
    if test.scope is not intent.scope:
        return f"is a {test.scope.value} test, not {intent.scope.value}"
    if intent.browser not in test.browsers:
        return f"does not support {intent.browser.value}"
    if intent.region not in test.regions:
        return f"is not available in {intent.region.value}"
    return None


def _selection_reasons(test: TestCase, intent: TestIntent, score) -> List[str]:
    """Explain the selection in human-readable terms, per Rule 4."""
    reasons = [
        f"Matches the {intent.module.value} module and {intent.scope.value} scope",
        f"Supported on {intent.browser.value}",
        f"Available in {intent.region.value}",
        f"Marked {test.criticality.value} criticality",
    ]
    reasons.extend(
        factor.detail
        for factor in score.factors
        if factor.name in {"failure_frequency", "failure_recency", "matching_conditions"}
    )
    return reasons
