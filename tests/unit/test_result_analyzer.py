import pytest

from app.agents.analysis import AGENT_NAME, ResultAnalyzer, fallback_report
from app.db.database import Database
from app.db.repositories import AnalysisRepository, WorkflowRepository
from app.llm.errors import ProviderResponseError, ProviderTimeoutError
from app.models.analysis import AnalysisStatus
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.execution import ExecutionResult, TestOutcome
from app.models.plan import ExecutionPlan, PlanItem, PolicyResult
from app.models.workflow import AgentRunStatus
from tests.unit.test_intent_agent import FakeProvider

WORKFLOW_ID = "WF-1001"

PLAN = ExecutionPlan(
    module="payment",
    scope="smoke",
    browser="chrome",
    region="US",
    environment="staging",
    items=[
        PlanItem(test_id="PAY-001", priority=1, reasons=["selected"]),
        PlanItem(test_id="PAY-003", priority=2, reasons=["selected"]),
    ],
    policy_result=PolicyResult(allowed=True),
)

RESULTS = [
    ExecutionResult(test_id="PAY-001", status=TestOutcome.PASSED, duration_ms=900),
    ExecutionResult(
        test_id="PAY-003",
        status=TestOutcome.FAILED,
        duration_ms=1840,
        failure_reason="3DS redirect timeout",
    ),
]

ALL_PASSED = [
    ExecutionResult(test_id="PAY-001", status=TestOutcome.PASSED, duration_ms=900),
    ExecutionResult(test_id="PAY-003", status=TestOutcome.PASSED, duration_ms=1100),
]

EVIDENCE = [
    RetrievedEvidence(
        source_id="HIST-001",
        type=EvidenceType.HISTORICAL_FAILURE,
        content="PAY-003 failed on Chrome in US on 2026-07-30: 3DS redirect timed out.",
        score=0.9,
        metadata={"test_id": "PAY-003"},
    ),
    RetrievedEvidence(
        source_id="DOC-PAY-003",
        type=EvidenceType.TEST_DOCUMENTATION,
        content="PAY-003 verifies a payment requiring a 3DS redirect.",
        score=0.7,
        metadata={"test_id": "PAY-003"},
    ),
]


def _payload(**overrides) -> dict:
    payload = {
        "summary": "1 of 2 tests failed.",
        "observations": ["PAY-003 failed after 1840ms"],
        "insufficient_evidence": False,
        "failures": [
            {
                "test_id": "PAY-003",
                "observed_facts": ["The execution timed out during the 3DS redirect"],
                "likely_cause": "Consistent with a 3DS redirect timeout",
                "confidence": 0.82,
                "evidence_source_ids": ["HIST-001"],
                "recommendations": ["Review gateway timeout configuration"],
            }
        ],
    }
    payload.update(overrides)
    return payload


def _analyzer(payload=None, error=None, **kwargs) -> ResultAnalyzer:
    return ResultAnalyzer(
        FakeProvider(payload=payload, error=error),
        provider_model="gpt-test",
        **kwargs,
    )


@pytest.fixture
def database(tmp_path) -> Database:
    created = Database(tmp_path / "test-trigger.db")
    created.initialize()
    WorkflowRepository(created).create_workflow(
        workflow_id=WORKFLOW_ID, query="Run payment smoke tests", dry_run=False
    )
    return created


def test_a_grounded_report_is_accepted() -> None:
    report = _analyzer(_payload()).analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE
    )

    assert report.status is AnalysisStatus.AI_GENERATED
    assert report.summary == "1 of 2 tests failed."
    assert report.failures[0].test_id == "PAY-003"
    assert report.failures[0].evidence_source_ids == ["HIST-001"]
    assert report.failures[0].observed_facts
    assert report.prompt_version == "analysis-v1"
    assert report.provider_model == "gpt-test"


def test_the_prompt_carries_results_evidence_and_context_only() -> None:
    provider = FakeProvider(_payload())

    ResultAnalyzer(provider).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    prompt = provider.calls[0]["user_prompt"]
    assert "PAY-003: failed in 1840ms (3DS redirect timeout)" in prompt
    assert "[HIST-001]" in prompt
    assert "browser: chrome" in prompt
    assert "region: US" in prompt


def test_the_schema_separates_observed_facts_from_inference() -> None:
    provider = FakeProvider(_payload())

    ResultAnalyzer(provider).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    properties = provider.calls[0]["schema"]["properties"]["failures"]["items"][
        "properties"
    ]
    assert "observed_facts" in properties
    assert "likely_cause" in properties
    assert "evidence_source_ids" in properties


def test_an_all_passing_run_produces_a_report_without_failures() -> None:
    report = _analyzer(
        _payload(summary="0 of 2 tests failed.", failures=[])
    ).analyze(plan=PLAN, results=ALL_PASSED, evidence=EVIDENCE)

    assert report.status is AnalysisStatus.AI_GENERATED
    assert report.failures == []


def test_multiple_failures_are_all_reported() -> None:
    results = [
        ExecutionResult(
            test_id="PAY-001",
            status=TestOutcome.FAILED,
            duration_ms=700,
            failure_reason="authorization declined",
        ),
        RESULTS[1],
    ]
    payload = _payload(
        failures=[
            {
                "test_id": "PAY-001",
                "observed_facts": ["Authorization was declined"],
                "likely_cause": "Consistent with a declined card",
                "confidence": 0.5,
                "evidence_source_ids": ["DOC-PAY-003"],
                "recommendations": [],
            },
            _payload()["failures"][0],
        ]
    )

    report = _analyzer(payload).analyze(plan=PLAN, results=results, evidence=EVIDENCE)

    assert [failure.test_id for failure in report.failures] == ["PAY-001", "PAY-003"]


def test_a_claim_about_an_unknown_test_is_rejected() -> None:
    payload = _payload()
    payload["failures"][0]["test_id"] = "ZZZ-999"

    report = _analyzer(payload).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    assert report.status is AnalysisStatus.FALLBACK
    assert "was not part of this execution" in report.fallback_reason


def test_a_claim_about_a_passing_test_is_rejected() -> None:
    payload = _payload()
    payload["failures"][0]["test_id"] = "PAY-001"

    report = _analyzer(payload).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    assert report.status is AnalysisStatus.FALLBACK
    assert "did not fail" in report.fallback_reason


def test_a_citation_of_unavailable_evidence_is_rejected() -> None:
    payload = _payload()
    payload["failures"][0]["evidence_source_ids"] = ["HIST-999"]

    report = _analyzer(payload).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    assert report.status is AnalysisStatus.FALLBACK
    assert "HIST-999" in report.fallback_reason


def test_a_failure_without_attribution_is_rejected() -> None:
    payload = _payload()
    payload["failures"][0]["evidence_source_ids"] = []

    report = _analyzer(payload).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    assert report.status is AnalysisStatus.FALLBACK


def test_an_out_of_range_confidence_is_rejected() -> None:
    payload = _payload()
    payload["failures"][0]["confidence"] = 4.2

    report = _analyzer(payload).analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    assert report.status is AnalysisStatus.FALLBACK


def test_an_empty_summary_is_rejected() -> None:
    report = _analyzer(_payload(summary="")).analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE
    )

    assert report.status is AnalysisStatus.FALLBACK


def test_a_non_object_payload_is_rejected() -> None:
    report = _analyzer(["not", "an", "object"]).analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE
    )

    assert report.status is AnalysisStatus.FALLBACK


@pytest.mark.parametrize(
    "error",
    [ProviderTimeoutError("timed out"), ProviderResponseError("malformed JSON")],
)
def test_a_provider_failure_falls_back_to_facts(error) -> None:
    report = _analyzer(error=error).analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE
    )

    assert report.status is AnalysisStatus.FALLBACK
    assert report.summary == "1 of 2 test(s) failed."
    assert any("3DS redirect timeout" in line for line in report.observations)
    assert report.failures == []


def test_a_missing_provider_falls_back() -> None:
    report = ResultAnalyzer().analyze(plan=PLAN, results=RESULTS)

    assert report.status is AnalysisStatus.FALLBACK
    assert "no analysis provider" in report.fallback_reason


def test_analysis_without_retrieved_evidence_still_reports_facts() -> None:
    payload = _payload(insufficient_evidence=True, failures=[])

    report = _analyzer(payload).analyze(plan=PLAN, results=RESULTS, evidence=[])

    assert report.status is AnalysisStatus.AI_GENERATED
    assert report.insufficient_evidence is True


def test_a_citation_is_impossible_when_no_evidence_was_supplied() -> None:
    report = _analyzer(_payload()).analyze(plan=PLAN, results=RESULTS, evidence=[])

    assert report.status is AnalysisStatus.FALLBACK
    assert "HIST-001" in report.fallback_reason


def test_evidence_is_bounded_before_it_reaches_the_provider() -> None:
    provider = FakeProvider(_payload(failures=[]))
    analyzer = ResultAnalyzer(provider, max_evidence=1)

    analyzer.analyze(plan=PLAN, results=RESULTS, evidence=EVIDENCE)

    prompt = provider.calls[0]["user_prompt"]
    assert "[HIST-001]" in prompt
    assert "[DOC-PAY-003]" not in prompt


def test_the_fallback_summary_counts_passes_and_failures() -> None:
    report = fallback_report(RESULTS, "provider timed out")

    assert report.summary == "1 of 2 test(s) failed."
    assert report.status is AnalysisStatus.FALLBACK
    assert report.fallback_reason == "provider timed out"
    assert len(report.observations) == 2


def test_the_fallback_never_infers_a_cause() -> None:
    assert fallback_report(RESULTS, "reason").failures == []


def test_a_grounded_report_is_persisted_with_provider_metadata(database) -> None:
    analyzer = _analyzer(
        _payload(),
        repository=WorkflowRepository(database),
        reports=AnalysisRepository(database),
    )

    analyzer.analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE, workflow_id=WORKFLOW_ID
    )

    stored = AnalysisRepository(database).get_report(WORKFLOW_ID)
    run = WorkflowRepository(database).list_agent_runs(WORKFLOW_ID)[0]

    assert stored.analysis_payload["status"] == "ai_generated"
    assert stored.analysis_payload["provider_model"] == "gpt-test"
    assert run.agent_name == AGENT_NAME
    assert run.status is AgentRunStatus.COMPLETED


def test_a_rejected_output_is_persisted_as_a_failed_run(database) -> None:
    payload = _payload()
    payload["failures"][0]["test_id"] = "ZZZ-999"
    analyzer = _analyzer(
        payload,
        repository=WorkflowRepository(database),
        reports=AnalysisRepository(database),
    )

    analyzer.analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE, workflow_id=WORKFLOW_ID
    )

    stored = AnalysisRepository(database).get_report(WORKFLOW_ID)
    run = WorkflowRepository(database).list_agent_runs(WORKFLOW_ID)[0]

    assert stored.analysis_payload["status"] == "fallback"
    assert run.status is AgentRunStatus.FAILED


def test_no_secret_reaches_the_persisted_report(database) -> None:
    analyzer = _analyzer(_payload(), reports=AnalysisRepository(database))

    analyzer.analyze(
        plan=PLAN, results=RESULTS, evidence=EVIDENCE, workflow_id=WORKFLOW_ID
    )

    payload = AnalysisRepository(database).get_report(WORKFLOW_ID).analysis_payload
    assert "api_key" not in str(payload).lower()
    assert "sk-" not in str(payload)
