"""Deterministic policy validation.

Every rule here is plain code over trusted data. The LLM may later explain a
rejection, but it can neither produce nor overturn one. A plan is not
executable until this service returns an allowed result.
"""

from typing import Iterable, List, Optional, Sequence

from app.catalog import TestCatalog
from app.knowledge.documents import decode_list
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.intent import TestIntent
from app.models.plan import ExecutionPlan, PolicyResult, PolicyViolation

POLICY_VERSION = "policy-v1"

UNSUPPORTED_BROWSERS_KEY = "unsupported_browsers"


class ViolationCode:
    """Stable codes so clients can branch without parsing prose."""

    NO_TESTS_SELECTED = "NO_TESTS_SELECTED"
    UNKNOWN_TEST = "UNKNOWN_TEST"
    MODULE_MISMATCH = "MODULE_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    UNSUPPORTED_BROWSER = "UNSUPPORTED_BROWSER"
    UNSUPPORTED_REGION = "UNSUPPORTED_REGION"
    INTENT_MISMATCH = "INTENT_MISMATCH"
    JURISDICTION_VIOLATION = "JURISDICTION_VIOLATION"


class PolicyService:
    """Validates a candidate plan against the catalog and jurisdiction rules."""

    def __init__(self, catalog: TestCatalog) -> None:
        self._catalog = catalog

    def validate(
        self,
        plan: ExecutionPlan,
        intent: TestIntent,
        evidence: Sequence[RetrievedEvidence] = (),
    ) -> PolicyResult:
        """Return an allowed result, or every violation that blocks execution."""
        violations: List[PolicyViolation] = []

        violations.extend(_check_plan_matches_intent(plan, intent))
        violations.extend(self._check_tests(plan))
        violations.extend(_check_jurisdiction(plan, evidence))

        if not plan.items:
            violations.append(
                PolicyViolation(
                    code=ViolationCode.NO_TESTS_SELECTED,
                    message=(
                        f"No catalogued {plan.scope.value} test for the "
                        f"{plan.module.value} module runs on {plan.browser.value} "
                        f"in {plan.region.value}."
                    ),
                )
            )

        if violations:
            return PolicyResult(
                allowed=False, violations=violations, policy_version=POLICY_VERSION
            )
        return PolicyResult(allowed=True, policy_version=POLICY_VERSION)

    def _check_tests(self, plan: ExecutionPlan) -> List[PolicyViolation]:
        """Every planned test must exist and be runnable under the plan context."""
        violations: List[PolicyViolation] = []

        for item in plan.items:
            test = self._catalog.get(item.test_id)
            if test is None:
                violations.append(
                    PolicyViolation(
                        code=ViolationCode.UNKNOWN_TEST,
                        message=f"{item.test_id} is not in the test catalog.",
                        test_id=item.test_id,
                    )
                )
                continue

            if test.module is not plan.module:
                violations.append(
                    PolicyViolation(
                        code=ViolationCode.MODULE_MISMATCH,
                        message=(
                            f"{test.id} belongs to the {test.module.value} module, "
                            f"not {plan.module.value}."
                        ),
                        test_id=test.id,
                        field="module",
                    )
                )
            if test.scope is not plan.scope:
                violations.append(
                    PolicyViolation(
                        code=ViolationCode.SCOPE_MISMATCH,
                        message=(
                            f"{test.id} is a {test.scope.value} test, "
                            f"not {plan.scope.value}."
                        ),
                        test_id=test.id,
                        field="scope",
                    )
                )
            if plan.browser not in test.browsers:
                violations.append(
                    PolicyViolation(
                        code=ViolationCode.UNSUPPORTED_BROWSER,
                        message=(
                            f"{plan.browser.value} is not supported for {test.id}."
                        ),
                        test_id=test.id,
                        field="browser",
                    )
                )
            if plan.region not in test.regions:
                violations.append(
                    PolicyViolation(
                        code=ViolationCode.UNSUPPORTED_REGION,
                        message=f"{test.id} is not available in {plan.region.value}.",
                        test_id=test.id,
                        field="region",
                    )
                )

        return violations


def _check_plan_matches_intent(
    plan: ExecutionPlan, intent: TestIntent
) -> List[PolicyViolation]:
    """A plan must execute what the user asked for, not a substituted context."""
    violations = []
    for field in ("module", "scope", "browser", "region"):
        planned = getattr(plan, field)
        requested = getattr(intent, field)
        if planned is not requested:
            violations.append(
                PolicyViolation(
                    code=ViolationCode.INTENT_MISMATCH,
                    message=(
                        f"The plan targets {field}={planned.value} but the request "
                        f"asked for {requested.value}."
                    ),
                    field=field,
                )
            )
    return violations


def _check_jurisdiction(
    plan: ExecutionPlan, evidence: Iterable[RetrievedEvidence]
) -> List[PolicyViolation]:
    """Enforce jurisdiction rules from structured metadata only.

    Rule text is for humans; the decision reads declared constraint fields, so
    policy never depends on parsing prose.
    """
    violations = []
    for rule in evidence:
        if rule.type is not EvidenceType.JURISDICTION_RULE:
            continue
        if rule.metadata.get("region") != plan.region.value:
            continue
        if plan.module.value not in _applicable_modules(rule):
            continue

        unsupported = _decode(rule.metadata.get(UNSUPPORTED_BROWSERS_KEY))
        if plan.browser.value in unsupported:
            violations.append(
                PolicyViolation(
                    code=ViolationCode.JURISDICTION_VIOLATION,
                    message=(
                        f"{rule.source_id}: {plan.browser.value} is not permitted "
                        f"for {plan.module.value} in {plan.region.value}."
                    ),
                    field="browser",
                )
            )
    return violations


def _applicable_modules(rule: RetrievedEvidence) -> List[str]:
    return _decode(rule.metadata.get("applies_to_modules"))


def _decode(value: object) -> List[str]:
    """Accept either a real list or the delimited form the vector store returns."""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return decode_list(value)


def rejection_summary(result: PolicyResult) -> Optional[str]:
    """One-line summary of why a plan was rejected, for timelines and the UI."""
    if result.allowed:
        return None
    codes = sorted({violation.code for violation in result.violations})
    return (
        f"Rejected by {result.policy_version or POLICY_VERSION} with "
        f"{len(result.violations)} violation(s): {', '.join(codes)}"
    )
