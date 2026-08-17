"""Vector-store interface and the persistent ChromaDB implementation."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

DEFAULT_COLLECTION = "test_trigger_knowledge"
# Cosine distance runs 0 (identical) to 2 (opposite); map it onto a 0-1 score.
MAX_COSINE_DISTANCE = 2.0


class VectorStoreError(RuntimeError):
    """Raised when the vector store cannot serve a request.

    Retrieval surfaces this rather than returning an empty result, so a store
    outage can never look like an absence of evidence.
    """


class EmbeddedDocument(BaseModel):
    """A document plus its vector, ready to persist."""

    source_id: str
    content: str
    embedding: List[float] = Field(min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VectorMatch(BaseModel):
    """One semantic search hit with its attribution and score."""

    source_id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float = Field(ge=0.0, le=1.0)


class VectorStore(ABC):
    """Persists embedded documents and answers filtered similarity queries."""

    @abstractmethod
    def upsert(self, documents: Sequence[EmbeddedDocument]) -> None:
        """Insert or replace documents, keyed by source ID."""

    @abstractmethod
    def query(
        self,
        *,
        embedding: Sequence[float],
        top_k: int,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[VectorMatch]:
        """Return the closest matches within the deterministic filter."""

    @abstractmethod
    def count(self) -> int:
        """Return how many documents are stored."""


class ChromaVectorStore(VectorStore):
    """Persistent ChromaDB collection using externally supplied embeddings.

    Embeddings are always passed in, so the store never silently downloads or
    applies an embedding model of its own.
    """

    def __init__(
        self,
        persist_directory: str,
        *,
        collection_name: str = DEFAULT_COLLECTION,
        client: Optional[Any] = None,
    ) -> None:
        import chromadb

        self._client = client or chromadb.PersistentClient(path=persist_directory)
        try:
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                embedding_function=None,
                configuration={"hnsw": {"space": "cosine"}},
            )
        except Exception as error:  # chromadb raises vendor-specific errors
            raise VectorStoreError(f"could not open collection: {error}") from error

    def upsert(self, documents: Sequence[EmbeddedDocument]) -> None:
        batch = list(documents)
        if not batch:
            return
        try:
            self._collection.upsert(
                ids=[document.source_id for document in batch],
                embeddings=[document.embedding for document in batch],
                documents=[document.content for document in batch],
                metadatas=[document.metadata for document in batch],
            )
        except Exception as error:
            raise VectorStoreError(f"upsert failed: {error}") from error

    def query(
        self,
        *,
        embedding: Sequence[float],
        top_k: int,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[VectorMatch]:
        if top_k <= 0:
            return []
        try:
            response = self._collection.query(
                query_embeddings=[list(embedding)],
                n_results=top_k,
                where=where or None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as error:
            raise VectorStoreError(f"query failed: {error}") from error

        return _to_matches(response)

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception as error:
            raise VectorStoreError(f"count failed: {error}") from error


def _to_matches(response: Dict[str, Any]) -> List[VectorMatch]:
    ids = _first(response.get("ids"))
    documents = _first(response.get("documents"))
    metadatas = _first(response.get("metadatas"))
    distances = _first(response.get("distances"))

    matches = []
    for index, source_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else {}
        matches.append(
            VectorMatch(
                source_id=source_id,
                content=documents[index] if index < len(documents) else "",
                metadata=dict(metadata or {}),
                score=_to_score(distances[index] if index < len(distances) else None),
            )
        )
    return matches


def _first(value: Any) -> List[Any]:
    if not value:
        return []
    return list(value[0]) if value[0] is not None else []


def _to_score(distance: Optional[float]) -> float:
    """Convert cosine distance to a 0-1 relevance score."""
    if distance is None:
        return 0.0
    score = 1.0 - (float(distance) / MAX_COSINE_DISTANCE)
    return max(0.0, min(1.0, score))
