"""Shared test doubles for provider and vector-store behavior."""

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence

from app.llm.embeddings import EmbeddingProvider
from app.retrieval.store import EmbeddedDocument, VectorMatch, VectorStore, VectorStoreError

VECTOR_SIZE = 16


class HashingEmbedder(EmbeddingProvider):
    """Deterministic embeddings derived from token hashes.

    Real enough for similarity ordering (shared words pull vectors together)
    while staying offline and repeatable.
    """

    def __init__(self, size: int = VECTOR_SIZE) -> None:
        self.size = size
        self.calls: List[List[str]] = []

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> List[float]:
        vector = [0.0] * self.size
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[digest[0] % self.size] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return [1.0] + [0.0] * (self.size - 1)
        return [value / norm for value in vector]


class FailingEmbedder(EmbeddingProvider):
    """Raises the supplied provider error on every call."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise self.error


class FailingVectorStore(VectorStore):
    """Simulates a vector-store outage."""

    def upsert(self, documents: Sequence[EmbeddedDocument]) -> None:
        raise VectorStoreError("upsert failed: store unavailable")

    def query(self, **kwargs) -> List[VectorMatch]:
        raise VectorStoreError("query failed: store unavailable")

    def count(self) -> int:
        raise VectorStoreError("count failed: store unavailable")


class RecordingVectorStore(VectorStore):
    """Captures queries and replays canned matches."""

    def __init__(self, matches: Optional[List[VectorMatch]] = None) -> None:
        self.matches = matches or []
        self.queries: List[Dict[str, Any]] = []
        self.upserted: List[EmbeddedDocument] = []

    def upsert(self, documents: Sequence[EmbeddedDocument]) -> None:
        self.upserted.extend(documents)

    def query(self, *, embedding, top_k, where=None) -> List[VectorMatch]:
        self.queries.append({"top_k": top_k, "where": where})
        wanted = (where or {}).get("$and", [{}])[0].get("type")
        return [
            match for match in self.matches if match.metadata.get("type") == wanted
        ][:top_k]

    def count(self) -> int:
        return len(self.upserted)
