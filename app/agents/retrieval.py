"""Retrieval Agent: bounded, attributable evidence for planning and analysis.

Deterministic metadata filters run first; semantic search then ranks only the
compatible subset. The agent returns evidence and diagnostics — it never
selects executable tests, decides policy, or claims a root cause.
"""

from typing import Any, Dict, List, Optional, Sequence

from app.catalog import TestCatalog
from app.db.repositories import WorkflowRepository
from app.knowledge.documents import list_contains
from app.llm.embeddings import EmbeddingProvider
from app.llm.errors import ProviderError
from app.models.evidence import EvidenceType, RetrievedEvidence
from app.models.intent import TestIntent
from app.models.retrieval import RetrievalDiagnostics, RetrievalResult
from app.models.workflow import AgentRunStatus
from app.retrieval.store import VectorStore, VectorStoreError

AGENT_NAME = "retrieval"
DEFAULT_TOP_K = 5
DEFAULT_MAX_CONTEXT_CHARS = 6000

_GROUP_FIELDS = {
    EvidenceType.TEST_DOCUMENTATION: "test_documentation",
    EvidenceType.HISTORICAL_FAILURE: "historical_failures",
    EvidenceType.JURISDICTION_RULE: "jurisdiction_rules",
}


class RetrievalError(RuntimeError):
    """Raised when evidence could not be retrieved.

    Callers must treat this as a failure, not as "no evidence exists".
    """


class RetrievalAgent:
    """Retrieves evidence for an intent within deterministic constraints."""

    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        catalog: TestCatalog,
        *,
        top_k: int = DEFAULT_TOP_K,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        repository: Optional[WorkflowRepository] = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._catalog = catalog
        self._top_k = top_k
        self._max_context_chars = max_context_chars
        self._repository = repository

    def retrieve(
        self, intent: TestIntent, *, workflow_id: Optional[str] = None
    ) -> RetrievalResult:
        """Return grouped evidence for an actionable intent."""
        if not intent.is_actionable:
            raise RetrievalError(
                "retrieval requires a complete intent; missing: "
                + ", ".join(intent.missing_fields)
            )

        candidate_test_ids = [
            test.id
            for test in self._catalog.filter(
                module=intent.module,
                scope=intent.scope,
                browser=intent.browser,
                region=intent.region,
            )
        ]
        query_text = _build_query_text(intent)

        try:
            embedding = self._embed(query_text)
            groups = self._query_groups(embedding, intent, candidate_test_ids)
        except (VectorStoreError, ProviderError) as error:
            self._record(
                workflow_id,
                status=AgentRunStatus.FAILED,
                input_payload=_input_payload(intent, query_text, candidate_test_ids),
                output_payload={"error": str(error)},
                error=str(error),
            )
            raise RetrievalError(f"evidence retrieval failed: {error}") from error

        result = _bound(
            groups,
            diagnostics=RetrievalDiagnostics(
                filters=_filters(intent),
                top_k=self._top_k,
                candidate_test_ids=candidate_test_ids,
            ),
            max_context_chars=self._max_context_chars,
        )

        self._record(
            workflow_id,
            status=AgentRunStatus.COMPLETED,
            input_payload=_input_payload(intent, query_text, candidate_test_ids),
            output_payload=result.diagnostics.model_dump(mode="json"),
        )
        return result

    def _embed(self, query_text: str) -> List[float]:
        vectors = self._embedder.embed([query_text])
        if not vectors:
            raise VectorStoreError("embedding provider returned no vector")
        return vectors[0]

    def _query_groups(
        self,
        embedding: Sequence[float],
        intent: TestIntent,
        candidate_test_ids: List[str],
    ) -> Dict[EvidenceType, List[RetrievedEvidence]]:
        """Run one filtered query per evidence type, keeping types separable."""
        groups: Dict[EvidenceType, List[RetrievedEvidence]] = {}

        for evidence_type in _GROUP_FIELDS:
            where = _where_clause(evidence_type, intent, candidate_test_ids)
            if where is None:
                groups[evidence_type] = []
                continue

            matches = self._store.query(
                embedding=embedding, top_k=self._top_k, where=where
            )
            if evidence_type is EvidenceType.JURISDICTION_RULE:
                matches = [
                    match
                    for match in matches
                    if list_contains(
                        match.metadata.get("applies_to_modules"), intent.module.value
                    )
                ]

            groups[evidence_type] = [
                RetrievedEvidence(
                    source_id=match.source_id,
                    type=evidence_type,
                    content=match.content,
                    score=match.score,
                    metadata=match.metadata,
                )
                for match in matches
            ]
        return groups

    def _record(
        self,
        workflow_id: Optional[str],
        *,
        status: AgentRunStatus,
        input_payload: Dict[str, Any],
        output_payload: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        if self._repository is None or workflow_id is None:
            return
        self._repository.record_agent_run(
            workflow_id=workflow_id,
            agent_name=AGENT_NAME,
            status=status,
            input_payload=input_payload,
            output_payload=output_payload,
            error=error,
        )


def _filters(intent: TestIntent) -> Dict[str, Any]:
    return {
        "module": intent.module.value,
        "scope": intent.scope.value,
        "browser": intent.browser.value,
        "region": intent.region.value,
    }


def _input_payload(
    intent: TestIntent, query_text: str, candidate_test_ids: List[str]
) -> Dict[str, Any]:
    return {
        "filters": _filters(intent),
        "query_text": query_text,
        "candidate_test_ids": candidate_test_ids,
    }


def _build_query_text(intent: TestIntent) -> str:
    return (
        f"{intent.scope.value} tests for the {intent.module.value} module "
        f"on {intent.browser.value} in {intent.region.value}"
    )


def _where_clause(
    evidence_type: EvidenceType, intent: TestIntent, candidate_test_ids: List[str]
) -> Optional[Dict[str, Any]]:
    """Build the deterministic filter applied before semantic ranking.

    Test docs and failure history are restricted to catalog entries that are
    actually runnable under this intent, so an incompatible test can never
    reach the planner as evidence. Returning None means "no candidates", which
    skips the query entirely.
    """
    if evidence_type is EvidenceType.JURISDICTION_RULE:
        return {
            "$and": [
                {"type": evidence_type.value},
                {"region": intent.region.value},
            ]
        }

    if not candidate_test_ids:
        return None
    return {
        "$and": [
            {"type": evidence_type.value},
            {"test_id": {"$in": candidate_test_ids}},
        ]
    }


def _bound(
    groups: Dict[EvidenceType, List[RetrievedEvidence]],
    *,
    diagnostics: RetrievalDiagnostics,
    max_context_chars: int,
) -> RetrievalResult:
    """Drop the weakest evidence until the context budget is respected.

    Bounding is applied across all types by score, so a large group cannot
    crowd out a more relevant document of another type.
    """
    ranked = sorted(
        ((evidence_type, evidence) for evidence_type, items in groups.items() for evidence in items),
        key=lambda pair: pair[1].score or 0.0,
        reverse=True,
    )

    kept: Dict[EvidenceType, List[RetrievedEvidence]] = {key: [] for key in groups}
    used = 0
    for evidence_type, evidence in ranked:
        cost = len(evidence.content)
        if used + cost > max_context_chars and used > 0:
            diagnostics.dropped_source_ids.append(evidence.source_id)
            continue
        used += cost
        kept[evidence_type].append(evidence)

    diagnostics.truncated = bool(diagnostics.dropped_source_ids)
    for items in kept.values():
        items.sort(key=lambda evidence: evidence.score or 0.0, reverse=True)

    result = RetrievalResult(
        test_documentation=kept.get(EvidenceType.TEST_DOCUMENTATION, []),
        historical_failures=kept.get(EvidenceType.HISTORICAL_FAILURE, []),
        jurisdiction_rules=kept.get(EvidenceType.JURISDICTION_RULE, []),
        diagnostics=diagnostics,
    )
    diagnostics.returned_source_ids = result.source_ids
    diagnostics.scores = {
        evidence.source_id: evidence.score or 0.0 for evidence in result.all_evidence
    }
    return result
