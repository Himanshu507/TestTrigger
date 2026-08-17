"""Result Analyzer: grounded explanation with a deterministic floor.

The analyzer augments results; it never erases them. Any output it cannot
verify against the supplied results and evidence is discarded in favour of a
deterministic summary, so an ungrounded claim can never reach a user.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from app.db.repositories import AnalysisRepository, WorkflowRepository
from app.llm.errors import ProviderError
from app.llm.prompts import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SCHEMA_NAME,
    ANALYSIS_SYSTEM_PROMPT,
    build_analysis_schema,
    build_analysis_user_prompt,
)
from app.llm.provider import LLMProvider
from app.models.analysis import AnalysisReport, AnalysisStatus, FailureAnalysis
from app.models.evidence import RetrievedEvidence
from app.models.execution import ExecutionResult, TestOutcome
from app.models.plan import ExecutionPlan
from app.models.workflow import AgentRunStatus

AGENT_NAME = "analysis"
DEFAULT_MAX_EVIDENCE = 12
DEFAULT_MAX_EVIDENCE_CHARS = 4000


class ResultAnalyzer:
    """Produces a grounded report, or a deterministic fallback."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        *,
        provider_model: Optional[str] = None,
        max_evidence: int = DEFAULT_MAX_EVIDENCE,
        max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
        repository: Optional[WorkflowRepository] = None,
        reports: Optional[AnalysisRepository] = None,
    ) -> None:
        self._provider = provider
        self._provider_model = provider_model
        self._max_evidence = max_evidence
        self._max_evidence_chars = max_evidence_chars
        self._repository = repository
        self._reports = reports

    def analyze(
        self,
        *,
        plan: ExecutionPlan,
        results: Sequence[ExecutionResult],
        evidence: Sequence[RetrievedEvidence] = (),
        workflow_id: Optional[str] = None,
    ) -> AnalysisReport:
        """Explain the results, degrading to facts rather than guessing."""
        bounded = self._bound_evidence(evidence)

        if self._provider is None:
            return self._finish(
                fallback_report(results, "no analysis provider is configured"),
                workflow_id,
                status=AgentRunStatus.COMPLETED,
            )

        try:
            raw = self._provider.extract_structured(
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                user_prompt=self._build_prompt(plan, results, bounded),
                schema=build_analysis_schema(),
                schema_name=ANALYSIS_SCHEMA_NAME,
            )
        except ProviderError as error:
            return self._finish(
                fallback_report(results, f"analysis provider failed: {error}"),
                workflow_id,
                status=AgentRunStatus.FAILED,
                error=str(error),
            )

        report, rejection = self._to_report(raw, results, bounded)
        if report is None:
            return self._finish(
                fallback_report(results, f"analysis output rejected: {rejection}"),
                workflow_id,
                status=AgentRunStatus.FAILED,
                error=rejection,
            )
        return self._finish(report, workflow_id, status=AgentRunStatus.COMPLETED)

    def _bound_evidence(
        self, evidence: Sequence[RetrievedEvidence]
    ) -> List[RetrievedEvidence]:
        """Keep the strongest evidence within the configured context budget."""
        ranked = sorted(evidence, key=lambda item: item.score or 0.0, reverse=True)
        kept: List[RetrievedEvidence] = []
        used = 0
        for item in ranked[: self._max_evidence]:
            if used + len(item.content) > self._max_evidence_chars and kept:
                break
            used += len(item.content)
            kept.append(item)
        return kept

    def _build_prompt(
        self,
        plan: ExecutionPlan,
        results: Sequence[ExecutionResult],
        evidence: Sequence[RetrievedEvidence],
    ) -> str:
        return build_analysis_user_prompt(
            context_lines=[
                f"- module: {plan.module.value}",
                f"- scope: {plan.scope.value}",
                f"- browser: {plan.browser.value}",
                f"- region: {plan.region.value}",
                f"- environment: {plan.environment or 'not specified'}",
            ],
            result_lines=[
                f"- {result.test_id}: {result.status.value} in {result.duration_ms}ms"
                + (f" ({result.failure_reason})" if result.failure_reason else "")
                for result in results
            ],
            evidence_lines=[
                f"- [{item.source_id}] ({item.type.value}) {item.content}"
                for item in evidence
            ],
        )

    def _to_report(
        self,
        raw: Dict[str, Any],
        results: Sequence[ExecutionResult],
        evidence: Sequence[RetrievedEvidence],
    ) -> Tuple[Optional[AnalysisReport], Optional[str]]:
        """Validate the model's claims against what actually ran.

        Grounding is checked here rather than trusted from the prompt: the
        schema constrains shape, but only this can confirm attribution.
        """
        if not isinstance(raw, dict):
            return None, "provider output was not an object"

        failed_ids = {
            result.test_id for result in results if result.status is TestOutcome.FAILED
        }
        known_ids = {result.test_id for result in results}
        known_sources = {item.source_id for item in evidence}

        failures: List[FailureAnalysis] = []
        for row in raw.get("failures") or []:
            try:
                failure = FailureAnalysis.model_validate(row)
            except ValidationError as error:
                return None, f"failure entry failed validation: {error.error_count()} errors"

            if failure.test_id not in known_ids:
                return None, f"{failure.test_id} was not part of this execution"
            if failure.test_id not in failed_ids:
                return None, f"{failure.test_id} did not fail in this execution"

            unknown = [
                source_id
                for source_id in failure.evidence_source_ids
                if source_id not in known_sources
            ]
            if unknown:
                return None, f"cited unavailable evidence: {', '.join(sorted(unknown))}"

            failures.append(failure)

        try:
            report = AnalysisReport(
                summary=raw.get("summary") or "",
                status=AnalysisStatus.AI_GENERATED,
                observations=list(raw.get("observations") or []),
                failures=failures,
                insufficient_evidence=bool(raw.get("insufficient_evidence")),
                prompt_version=ANALYSIS_PROMPT_VERSION,
                provider_model=self._provider_model,
            )
        except ValidationError as error:
            return None, f"report failed validation: {error.error_count()} errors"

        return report, None

    def _finish(
        self,
        report: AnalysisReport,
        workflow_id: Optional[str],
        *,
        status: AgentRunStatus,
        error: Optional[str] = None,
    ) -> AnalysisReport:
        """Persist the report and the agent run, then hand the report back."""
        if workflow_id is None:
            return report

        if self._reports is not None:
            self._reports.save_report(workflow_id, report)

        if self._repository is not None:
            self._repository.record_agent_run(
                workflow_id=workflow_id,
                agent_name=AGENT_NAME,
                status=status,
                input_payload={"prompt_version": ANALYSIS_PROMPT_VERSION},
                output_payload=report.model_dump(mode="json"),
                error=error,
            )
        return report


def fallback_report(
    results: Sequence[ExecutionResult], reason: str
) -> AnalysisReport:
    """Deterministic summary: pass/fail counts and raw failure reasons.

    Available whenever grounded analysis is not, so an LLM outage degrades the
    explanation without hiding what happened.
    """
    failed = [result for result in results if result.status is TestOutcome.FAILED]
    summary = f"{len(failed)} of {len(results)} test(s) failed."

    observations = [
        f"{result.test_id} {result.status.value} in {result.duration_ms}ms"
        + (f": {result.failure_reason}" if result.failure_reason else "")
        for result in results
    ]

    return AnalysisReport(
        summary=summary,
        status=AnalysisStatus.FALLBACK,
        observations=observations,
        insufficient_evidence=bool(failed),
        fallback_reason=reason,
    )
