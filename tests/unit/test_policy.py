import pytest

from app.catalog import TestCatalog
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.intent import TestIntent
from app.models.plan import ExecutionPlan, PlanItem
from app.services.policy import POLICY_VERSION, PolicyService, ViolationCode, rejection_summary


@pytest.fixture(scope="module")
def catalog() -> TestCatalog:
    return TestCatalog.load_default()


@pytest.fixture
def policy(catalog) -> PolicyService:
    return PolicyService(catalog)


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


def _plan(test_ids=("PAY-001",), **overrides) -> ExecutionPlan:
    values = {
        "module": "payment",
        "scope": "smoke",
        "browser": "chrome",
        "region": "US",
        "items": [
            PlanItem(test_id=test_id, priority=index, reasons=["selected"])
            for index, test_id in enumerate(test_ids, start=1)
        ],
    }
    values.update(overrides)
    return ExecutionPlan(**values)


def _rule(source_id: str, region: str, modules, **extra):
    return RetrievedEvidence(
        source_id=source_id,
        type=EvidenceType.JURISDICTION_RULE,
        content="rule text for humans",
        metadata={"region": region, "applies_to_modules": modules, **extra},
    )


def _codes(result) -> set:
    return {violation.code for violation in result.violations}


def test_a_compatible_plan_is_allowed(policy) -> None:
    result = policy.validate(_plan(), _intent())

    assert result.allowed is True
    assert result.violations == []
    assert result.policy_version == POLICY_VERSION


def test_an_empty_plan_is_rejected(policy) -> None:
    result = policy.validate(_plan(test_ids=()), _intent())

    assert result.allowed is False
    assert ViolationCode.NO_TESTS_SELECTED in _codes(result)


def test_an_unknown_test_id_is_rejected(policy) -> None:
    result = policy.validate(_plan(test_ids=("ZZZ-999",)), _intent())

    assert ViolationCode.UNKNOWN_TEST in _codes(result)
    assert result.violations[0].test_id == "ZZZ-999"


def test_a_test_from_another_module_is_rejected(policy) -> None:
    result = policy.validate(_plan(test_ids=("WAL-001",)), _intent())

    assert ViolationCode.MODULE_MISMATCH in _codes(result)


def test_a_test_of_the_wrong_scope_is_rejected(policy) -> None:
    result = policy.validate(_plan(test_ids=("PAY-002",)), _intent())

    assert ViolationCode.SCOPE_MISMATCH in _codes(result)


def test_an_unsupported_browser_is_rejected(policy) -> None:
    plan = _plan(test_ids=("PAY-003",), browser="firefox")

    result = policy.validate(plan, _intent(browser="firefox"))

    assert ViolationCode.UNSUPPORTED_BROWSER in _codes(result)


def test_an_unsupported_region_is_rejected(policy) -> None:
    plan = _plan(test_ids=("PAY-001",), region="UK")

    result = policy.validate(plan, _intent(region="UK"))

    assert ViolationCode.UNSUPPORTED_REGION in _codes(result)


def test_a_plan_that_does_not_match_the_request_is_rejected(policy) -> None:
    result = policy.validate(_plan(browser="firefox"), _intent(browser="chrome"))

    assert ViolationCode.INTENT_MISMATCH in _codes(result)


def test_a_jurisdiction_rule_can_block_a_browser(policy) -> None:
    plan = _plan(test_ids=("PAY-003",), region="US-Nevada", browser="safari")
    rule = _rule(
        "RULE-005", "US-Nevada", ["withdrawal", "payment"], unsupported_browsers=["safari"]
    )

    result = policy.validate(plan, _intent(region="US-Nevada", browser="safari"), [rule])

    jurisdiction = next(
        violation
        for violation in result.violations
        if violation.code == ViolationCode.JURISDICTION_VIOLATION
    )
    assert "RULE-005" in jurisdiction.message
    assert jurisdiction.field == "browser"


def test_a_jurisdiction_rule_for_another_region_does_not_apply(policy) -> None:
    rule = _rule("RULE-005", "US-Nevada", ["payment"], unsupported_browsers=["chrome"])

    result = policy.validate(_plan(), _intent(), [rule])

    assert result.allowed is True


def test_a_jurisdiction_rule_for_another_module_does_not_apply(policy) -> None:
    rule = _rule("RULE-004", "US", ["withdrawal"], unsupported_browsers=["chrome"])

    result = policy.validate(_plan(), _intent(), [rule])

    assert result.allowed is True


def test_jurisdiction_rules_are_read_from_metadata_not_prose(policy) -> None:
    rule = _rule("RULE-009", "US", ["payment"])
    rule.metadata["requirement"] = "chrome is absolutely forbidden here"

    result = policy.validate(_plan(), _intent(), [rule])

    assert result.allowed is True


def test_delimited_rule_metadata_from_the_vector_store_is_understood(policy) -> None:
    rule = RetrievedEvidence(
        source_id="RULE-005",
        type=EvidenceType.JURISDICTION_RULE,
        content="rule text",
        metadata={
            "region": "US-Nevada",
            "applies_to_modules": "|withdrawal|payment|",
            "unsupported_browsers": "|safari|",
        },
    )
    plan = _plan(test_ids=("PAY-003",), region="US-Nevada", browser="safari")

    result = policy.validate(plan, _intent(region="US-Nevada", browser="safari"), [rule])

    assert ViolationCode.JURISDICTION_VIOLATION in _codes(result)


def test_non_jurisdiction_evidence_is_ignored_by_policy(policy) -> None:
    history = RetrievedEvidence(
        source_id="HIST-001",
        type=EvidenceType.HISTORICAL_FAILURE,
        content="PAY-001 failed",
        metadata={"test_id": "PAY-001", "unsupported_browsers": ["chrome"]},
    )

    assert policy.validate(_plan(), _intent(), [history]).allowed is True


def test_every_violation_is_machine_readable(policy) -> None:
    result = policy.validate(_plan(test_ids=("WAL-002",)), _intent())

    assert not result.allowed
    for violation in result.violations:
        assert violation.code.isupper()
        assert violation.message


def test_rejection_summary_lists_the_codes(policy) -> None:
    result = policy.validate(_plan(test_ids=("ZZZ-999",)), _intent())

    summary = rejection_summary(result)

    assert ViolationCode.UNKNOWN_TEST in summary
    assert POLICY_VERSION in summary


def test_an_allowed_result_has_no_rejection_summary(policy) -> None:
    assert rejection_summary(policy.validate(_plan(), _intent())) is None
