"""Populate the local ChromaDB collection from the committed knowledge base.

Usage:
    uv run python scripts/ingest_knowledge_base.py

Requires OPENAI_API_KEY, because embeddings come from the configured provider
rather than a model the vector store downloads on its own.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import AppSettings  # noqa: E402
from app.knowledge.ingest import ingest  # noqa: E402
from app.llm.embeddings import OpenAIEmbeddingProvider  # noqa: E402
from app.llm.errors import ProviderNotConfiguredError  # noqa: E402
from app.retrieval.store import ChromaVectorStore  # noqa: E402


def main() -> int:
    settings = AppSettings.from_environment()

    try:
        embedder = OpenAIEmbeddingProvider(
            settings, timeout_seconds=settings.llm_timeout_seconds
        )
    except ProviderNotConfiguredError as error:
        print(f"Cannot ingest: {error}", file=sys.stderr)
        return 1

    store = ChromaVectorStore(settings.chroma_persist_directory)
    report = ingest(store, embedder)

    print(f"Ingested {report.document_count} documents.")
    print(f"Collection now holds {report.collection_size} records.")
    print(f"Persisted to {settings.chroma_persist_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
