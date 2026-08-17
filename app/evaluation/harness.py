"""Evaluation harness for intent, retrieval, and grounded analysis.

Deliberately small and manually reviewable. It measures whether the controls
behave as designed — vocabulary is respected, incompatible evidence is filtered
out, relevant documents rank within K, and ungrounded analysis is rejected —
not whether a model is statistically validated.

No live provider is required: intent cases replay recorded provider output, so
results are reproducible and cost nothing.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from app.agents.analysis import ResultAnalyzer
from app.agents.intent import ClarificationRequired, IntentAgent
from app.agents.retrieval import RetrievalAgent
from app.catalog import TestCatalog
from app.llm.provider import LLMProvider
from app.models.analysis import AnalysisStatus
from app.models.evidence import RetrievedEvidence
from app.models.execution import ExecutionResult
from app.models.intent import TestIntent
from app.models.plan import ExecutionPlan, PlanItem, PolicyResult

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "dataset.json"
DEFAULT_K = 5

INTENT_FIELDS = ("module", "scope", "browser", "region")


class CaseResult(BaseModel):
    case_id: str
    passed: bool
    detail: str = ""


class MetricReport(BaseModel):
    name: str
    passed: int
    total: int
    cases: List[CaseResult] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0


class EvaluationReport(BaseModel):
    intent: MetricReport
    retrieval: MetricReport
    analysis: MetricReport

    @property
    def all_passed(self) -> bool:
        return all(
            report.passed == report.total
            for report in (self.intent, self.retrieval, self.analysis)
        )


class ReplayProvider(LLMProvider):
    """Returns a recorded payload, so evaluation never calls a paid provider."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def extract_structured(self, **kwargs) -> Dict[str, Any]:
        return self.payload


def load_dataset(path: Path = DEFAULT_DATASET) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_intent(dataset: Dict[str, Any]) -> MetricReport:
    """Check that each query yields the labelled fields, or asks for clarification."""
    cases: List[CaseResult] = []

    for case in dataset["intent_cases"]:
        expected = case.get("expected")
        payload = _intent_payload(case)
        outcome = IntentAgent(ReplayProvider(payload)).parse_intent(case["query"])

        if expected is None:
            passed = isinstance(outcome, ClarificationRequired)
            detail = "asked for clarification" if passed else "produced an intent anyway"
            if passed and case.get("expected_missing"):
                missing = set(outcome.missing_fields)
                passed = set(case["expected_missing"]) <= missing
                detail = f"missing={sorted(missing)}"
            if passed and case.get("expected_unsupported"):
                unsupported = set(outcome.unsupported_values)
                passed = set(case["expected_unsupported"]) <= unsupported
                detail = f"unsupported={sorted(unsupported)}"
        else:
            passed = isinstance(outcome, TestIntent) and all(
                _value(outcome, field) == expected[field] for field in INTENT_FIELDS
            )
            detail = (
                "matched all fields"
                if passed
                else f"got {_as_fields(outcome)}, expected {expected}"
            )

        cases.append(CaseResult(case_id=case["id"], passed=passed, detail=detail))

    return MetricReport(
        name="intent_field_accuracy",
        passed=sum(case.passed for case in cases),
        total=len(cases),
        cases=cases,
    )


def evaluate_retrieval(
    dataset: Dict[str, Any],
    agent: RetrievalAgent,
    catalog: TestCatalog,
    *,
    k: int = DEFAULT_K,
) -> MetricReport:
    """Measure filter correctness and Hit@K / Recall@K over the labelled sets."""
    cases: List[CaseResult] = []
    hits = 0
    recalls: List[float] = []

    for case in dataset["retrieval_cases"]:
        intent = TestIntent(confidence=1.0, **case["intent"])
        result = agent.retrieve(intent)
        returned = result.source_ids[:k]

        relevant = set(case["relevant_source_ids"])
        found = relevant & set(returned)
        recall = len(found) / len(relevant) if relevant else 0.0
        recalls.append(recall)
        if found:
            hits += 1

        # Filter correctness is the hard requirement: an incompatible test may
        # never appear as evidence, regardless of ranking quality.
        leaked = [
            evidence.metadata.get("test_id")
            for evidence in result.all_evidence
            if evidence.metadata.get("test_id") in set(case["forbidden_test_ids"])
        ]

        cases.append(
            CaseResult(
                case_id=case["id"],
                passed=not leaked,
                detail=(
                    f"recall={recall:.2f} returned={returned}"
                    if not leaked
                    else f"leaked incompatible tests: {leaked}"
                ),
            )
        )

    total = len(cases)
    return MetricReport(
        name="retrieval_filter_correctness",
        passed=sum(case.passed for case in cases),
        total=total,
        cases=cases,
        extra={
            "k": k,
            "hit_at_k": round(hits / total, 3) if total else 0.0,
            "recall_at_k": round(sum(recalls) / total, 3) if total else 0.0,
        },
    )


def evaluate_analysis(dataset: Dict[str, Any]) -> MetricReport:
    """Check that grounded reports are accepted and ungrounded ones are refused."""
    cases: List[CaseResult] = []

    for case in dataset["analysis_cases"]:
        results = [ExecutionResult.model_validate(row) for row in case["results"]]
        evidence = [
            RetrievedEvidence(
                source_id=source_id,
                type="historical_failure",
                content=f"evidence {source_id}",
                metadata={},
            )
            for source_id in case["evidence_source_ids"]
        ]

        report = ResultAnalyzer(ReplayProvider(case["model_output"])).analyze(
            plan=_plan_for(results), results=results, evidence=evidence
        )

        grounded = report.status is AnalysisStatus.AI_GENERATED
        passed = grounded == case["expect_grounded"]
        cases.append(
            CaseResult(
                case_id=case["id"],
                passed=passed,
                detail=(
                    f"{case['name']}: {report.status.value}"
                    + (f" ({report.fallback_reason})" if report.fallback_reason else "")
                ),
            )
        )

    return MetricReport(
        name="grounded_analysis_review",
        passed=sum(case.passed for case in cases),
        total=len(cases),
        cases=cases,
    )


def run_evaluation(
    *,
    agent: RetrievalAgent,
    catalog: TestCatalog,
    dataset: Optional[Dict[str, Any]] = None,
    k: int = DEFAULT_K,
) -> EvaluationReport:
    data = dataset or load_dataset()
    return EvaluationReport(
        intent=evaluate_intent(data),
        retrieval=evaluate_retrieval(data, agent, catalog, k=k),
        analysis=evaluate_analysis(data),
    )


def format_report(report: EvaluationReport) -> str:
    """Render a plain-text summary for a reviewer."""
    lines = ["Test Trigger evaluation", "=" * 40]
    for metric in (report.intent, report.retrieval, report.analysis):
        lines.append(
            f"\n{metric.name}: {metric.passed}/{metric.total} "
            f"({metric.score:.0%})"
        )
        for key, value in metric.extra.items():
            lines.append(f"  {key}: {value}")
        for case in metric.cases:
            mark = "PASS" if case.passed else "FAIL"
            lines.append(f"  [{mark}] {case.case_id}: {case.detail}")
    lines.append("\n" + ("All checks passed." if report.all_passed else "FAILURES PRESENT."))
    return "\n".join(lines)


def _intent_payload(case: Dict[str, Any]) -> Dict[str, Any]:
    """Recorded provider output for a labelled query.

    Cases the agent must refuse carry a deliberately imperfect payload — a
    missing field or an unsupported value — which is what the guard should
    catch.
    """
    recorded = case.get("provider_output")
    if recorded is not None:
        return recorded

    expected = case.get("expected") or {}
    payload = {field: expected.get(field) for field in INTENT_FIELDS}
    payload.update({"environment": None, "confidence": 0.95, "missing_fields": []})

    for field in case.get("expected_missing", []):
        payload[field] = None
    if "browser" in case.get("expected_unsupported", []):
        payload["browser"] = "edge"
    return payload


def _plan_for(results: Sequence[ExecutionResult]) -> ExecutionPlan:
    return ExecutionPlan(
        module="payment",
        scope="smoke",
        browser="chrome",
        region="US",
        items=[
            PlanItem(test_id=result.test_id, priority=index, reasons=["evaluated"])
            for index, result in enumerate(results, start=1)
        ],
        policy_result=PolicyResult(allowed=True),
    )


def _value(intent: TestIntent, field: str) -> Optional[str]:
    value = getattr(intent, field)
    return value.value if value is not None else None


def _as_fields(outcome) -> Dict[str, Any]:
    if isinstance(outcome, TestIntent):
        return {field: _value(outcome, field) for field in INTENT_FIELDS}
    return {"clarification": outcome.reason.value}
