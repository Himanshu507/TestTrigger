"""Exercises the real ChromaDB implementation, including persistence."""

import pytest

from app.knowledge.ingest import ingest
from app.knowledge.loader import load_documents
from app.retrieval.store import ChromaVectorStore, EmbeddedDocument, VectorStoreError
from tests.fakes import HashingEmbedder

COLLECTION = "kb_under_test"


def _store(tmp_path, name: str = COLLECTION) -> ChromaVectorStore:
    return ChromaVectorStore(str(tmp_path / "chroma"), collection_name=name)


def _document(source_id: str, content: str, **metadata) -> EmbeddedDocument:
    return EmbeddedDocument(
        source_id=source_id,
        content=content,
        embedding=HashingEmbedder().embed([content])[0],
        metadata={"source_id": source_id, **metadata},
    )


def test_documents_round_trip_with_attribution(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert(
        [
            _document("DOC-1", "payment card authorization", type="test_documentation"),
            _document("HIST-1", "wallet top up failure", type="historical_failure"),
        ]
    )

    matches = store.query(
        embedding=HashingEmbedder().embed(["payment card authorization"])[0], top_k=5
    )

    assert store.count() == 2
    assert matches[0].source_id == "DOC-1"
    assert matches[0].content == "payment card authorization"
    assert matches[0].metadata["type"] == "test_documentation"
    assert 0.0 <= matches[0].score <= 1.0


def test_identical_text_scores_higher_than_unrelated_text(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert(
        [
            _document("DOC-1", "payment card authorization", type="test_documentation"),
            _document("DOC-2", "wallet history rendering", type="test_documentation"),
        ]
    )

    matches = store.query(
        embedding=HashingEmbedder().embed(["payment card authorization"])[0], top_k=2
    )

    assert matches[0].source_id == "DOC-1"
    assert matches[0].score > matches[1].score


def test_metadata_filter_excludes_incompatible_documents(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert(
        [
            _document("DOC-1", "payment smoke", type="test_documentation", test_id="PAY-001"),
            _document("DOC-2", "payment smoke", type="test_documentation", test_id="WAL-001"),
        ]
    )

    matches = store.query(
        embedding=HashingEmbedder().embed(["payment smoke"])[0],
        top_k=5,
        where={"$and": [{"type": "test_documentation"}, {"test_id": {"$in": ["PAY-001"]}}]},
    )

    assert [match.source_id for match in matches] == ["DOC-1"]


def test_upsert_is_idempotent_and_refreshes_content(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert([_document("DOC-1", "original text", type="test_documentation")])
    store.upsert([_document("DOC-1", "updated text", type="test_documentation")])

    matches = store.query(
        embedding=HashingEmbedder().embed(["updated text"])[0], top_k=5
    )

    assert store.count() == 1
    assert matches[0].content == "updated text"


def test_embeddings_survive_a_restart(tmp_path) -> None:
    _store(tmp_path).upsert(
        [_document("DOC-1", "payment card authorization", type="test_documentation")]
    )

    reopened = _store(tmp_path)

    assert reopened.count() == 1


def test_collections_are_isolated_from_each_other(tmp_path) -> None:
    _store(tmp_path, "collection_one").upsert(
        [_document("DOC-1", "payment", type="test_documentation")]
    )

    assert _store(tmp_path, "collection_two").count() == 0


def test_empty_upsert_and_non_positive_top_k_are_no_ops(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert([])

    assert store.count() == 0
    assert store.query(embedding=[0.1] * 16, top_k=0) == []


def test_store_errors_are_wrapped(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(VectorStoreError):
        store.query(embedding=[0.1] * 16, top_k=5, where={"$bogus": "operator"})


def test_ingesting_the_committed_corpus_is_repeatable(tmp_path) -> None:
    store = _store(tmp_path)
    embedder = HashingEmbedder()
    expected = len(load_documents())

    first = ingest(store, embedder)
    second = ingest(store, embedder)

    assert first.document_count == expected
    assert first.collection_size == expected
    assert second.collection_size == expected
    assert first.source_ids == second.source_ids


def test_ingestion_failure_is_surfaced(tmp_path) -> None:
    from tests.fakes import FailingVectorStore

    with pytest.raises(VectorStoreError):
        ingest(FailingVectorStore(), HashingEmbedder())
