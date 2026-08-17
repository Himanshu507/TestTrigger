"""Repeatable knowledge-base ingestion.

Ingestion is idempotent: documents are upserted under their stable source ID,
so re-running refreshes content instead of duplicating records.
"""

from pathlib import Path
from typing import List, Optional, Sequence

from pydantic import BaseModel

from app.knowledge.documents import KnowledgeDocument
from app.knowledge.loader import DEFAULT_KNOWLEDGE_BASE, load_documents
from app.llm.embeddings import EmbeddingProvider
from app.retrieval.store import EmbeddedDocument, VectorStore

DEFAULT_BATCH_SIZE = 64


class IngestionReport(BaseModel):
    """What a single ingestion run wrote."""

    document_count: int
    source_ids: List[str]
    collection_size: int


def ingest(
    store: VectorStore,
    embedder: EmbeddingProvider,
    *,
    root: Path = DEFAULT_KNOWLEDGE_BASE,
    documents: Optional[Sequence[KnowledgeDocument]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> IngestionReport:
    """Embed and upsert the corpus, returning a summary of the run."""
    corpus = list(documents) if documents is not None else load_documents(root)

    for start in range(0, len(corpus), batch_size):
        batch = corpus[start : start + batch_size]
        vectors = embedder.embed([document.content for document in batch])
        store.upsert(
            [
                EmbeddedDocument(
                    source_id=document.source_id,
                    content=document.content,
                    embedding=vector,
                    metadata=document.flatten_metadata(),
                )
                for document, vector in zip(batch, vectors)
            ]
        )

    return IngestionReport(
        document_count=len(corpus),
        source_ids=[document.source_id for document in corpus],
        collection_size=store.count(),
    )
