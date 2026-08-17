import pytest
from pydantic import ValidationError

from app.models.analysis import AnalysisReport, AnalysisStatus, FailureAnalysis
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.execution import ExecutionResult, ExecutionStatus, TestOutcome
from app.models.intent import TestIntent
from app.models.plan import ExecutionPlan, PlanItem, PolicyResult, PolicyViolation


def test_intent_rejects_values_outside_the_controlled_vocabulary() -> None:
    with pytest.raises(ValidationError):
        TestIntent(module="banking", confidence=0.9)

    with pytest.raises(ValidationError):
        TestIntent(browser="edge", confidence=0.9)


def test_intent_reports_what_it_could_not_infer() -> None:
    intent = TestIntent(
        module="payment", scope="smoke", confidence=0.6, missing_fields=["browser", "region"]
    )

    assert intent.is_actionable is False
    assert intent.browser is None


def test_intent_cannot_claim_a_populated_field_is_missing() -> None:
    with pytest.raises(ValidationError, match="reported missing"):
        TestIntent(module="payment", confidence=0.9, missing_fields=["module"])


def test_fully_specified_intent_is_actionable() -> None:
    intent = TestIntent(
        module="payment", scope="smoke", browser="chrome", region="US", confidence=0.95
    )

    assert intent.is_actionable is True


def test_evidence_requires_an_attributable_source() -> None:
    with pytest.raises(ValidationError):
        RetrievedEvidence(source_id="", type=EvidenceType.HISTORICAL_FAILURE, content="x")


def test_plan_item_must_explain_its_selection() -> None:
    with pytest.raises(ValidationError):
        PlanItem(test_id="PAY-003", priority=1, reasons=[])

    with pytest.raises(ValidationError, match="blank"):
        PlanItem(test_id="PAY-003", priority=1, reasons=["  "])


def test_plan_item_rejects_a_test_id_outside_the_catalog_format() -> None:
    with pytest.raises(ValidationError):
        PlanItem(test_id="made-up-test", priority=1, reasons=["invented"])


def test_failing_policy_result_must_carry_violations() -> None:
    with pytest.raises(ValidationError, match="explain why"):
        PolicyResult(allowed=False)

    with pytest.raises(ValidationError, match="cannot list violations"):
        PolicyResult(
            allowed=True,
            violations=[PolicyViolation(code="UNSUPPORTED_BROWSER", message="no")],
        )


def _plan(**overrides) -> ExecutionPlan:
    defaults = dict(
        module="payment",
        scope="smoke",
        browser="chrome",
        region="US",
        items=[PlanItem(test_id="PAY-001", priority=1, reasons=["module match"])],
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


def test_plan_is_not_executable_until_policy_passes() -> None:
    assert _plan().is_executable is False
    assert _plan(policy_result=PolicyResult(allowed=True)).is_executable is True
    assert (
        _plan(
            policy_result=PolicyResult(
                allowed=False,
                violations=[PolicyViolation(code="NO_TESTS", message="empty")],
            )
        ).is_executable
        is False
    )


def test_empty_plan_cannot_pass_policy_validation() -> None:
    with pytest.raises(ValidationError, match="zero-test plan"):
        _plan(items=[], policy_result=PolicyResult(allowed=True))


def test_plan_cannot_schedule_the_same_test_twice() -> None:
    with pytest.raises(ValidationError, match="same test twice"):
        _plan(
            items=[
                PlanItem(test_id="PAY-001", priority=1, reasons=["module match"]),
                PlanItem(test_id="PAY-001", priority=2, reasons=["duplicate"]),
            ]
        )


def test_plan_returns_test_ids_in_priority_order() -> None:
    plan = _plan(
        items=[
            PlanItem(test_id="PAY-003", priority=2, reasons=["historical risk"]),
            PlanItem(test_id="PAY-001", priority=1, reasons=["criticality"]),
        ]
    )

    assert plan.test_ids == ["PAY-001", "PAY-003"]


def test_failed_result_must_state_a_reason() -> None:
    with pytest.raises(ValidationError, match="failure reason"):
        ExecutionResult(test_id="PAY-003", status=TestOutcome.FAILED, duration_ms=1840)

    with pytest.raises(ValidationError, match="must not carry"):
        ExecutionResult(
            test_id="PAY-001",
            status=TestOutcome.PASSED,
            duration_ms=900,
            failure_reason="unexpected",
        )


def test_only_finished_jobs_are_terminal() -> None:
    assert ExecutionStatus.COMPLETED.is_terminal
    assert ExecutionStatus.CANCELLED.is_terminal
    assert not ExecutionStatus.RUNNING.is_terminal


def test_failure_analysis_must_cite_evidence() -> None:
    with pytest.raises(ValidationError):
        FailureAnalysis(
            test_id="PAY-003",
            likely_cause="3DS redirect timeout",
            confidence=0.82,
            evidence_source_ids=[],
        )


def test_fallback_report_states_facts_without_inferring_causes() -> None:
    report = AnalysisReport(
        summary="1 of 4 tests failed.",
        status=AnalysisStatus.FALLBACK,
        observations=["PAY-003 failed after 1840ms"],
        fallback_reason="analysis provider timed out",
    )

    assert report.failures == []

    with pytest.raises(ValidationError, match="cannot infer causes"):
        AnalysisReport(
            summary="1 of 4 tests failed.",
            status=AnalysisStatus.FALLBACK,
            fallback_reason="provider timed out",
            failures=[
                FailureAnalysis(
                    test_id="PAY-003",
                    likely_cause="guessed",
                    confidence=0.5,
                    evidence_source_ids=["HIST-001"],
                )
            ],
        )


def test_fallback_report_must_record_why_it_degraded() -> None:
    with pytest.raises(ValidationError, match="why analysis was degraded"):
        AnalysisReport(summary="1 of 4 failed.", status=AnalysisStatus.FALLBACK)
