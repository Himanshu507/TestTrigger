"""Run the evaluation set and print a reviewable report.

Usage:
    uv run python scripts/evaluate.py
    uv run python scripts/evaluate.py --k 3 --output docs/evaluation-results.md

Uses recorded provider output and a deterministic local embedder, so it needs
no API key and costs nothing to run.
"""

import argparse
import hashlib
import math
import sys
import tempfile
from pathlib import Path
from typing import List, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.retrieval import RetrievalAgent  # noqa: E402
from app.catalog import TestCatalog  # noqa: E402
from app.evaluation.harness import (  # noqa: E402
    DEFAULT_K,
    format_report,
    run_evaluation,
)
from app.knowledge.ingest import ingest  # noqa: E402
from app.llm.embeddings import EmbeddingProvider  # noqa: E402
from app.retrieval.store import ChromaVectorStore  # noqa: E402

VECTOR_SIZE = 16


class DeterministicEmbedder(EmbeddingProvider):
    """Token-hash embeddings: repeatable, offline, and free."""

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> List[float]:
        vector = [0.0] * VECTOR_SIZE
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[digest[0] % VECTOR_SIZE] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return [1.0] + [0.0] * (VECTOR_SIZE - 1)
        return [value / norm for value in vector]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the Test Trigger evaluation set")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--output", type=Path, help="Also write the report to a file")
    args = parser.parse_args(argv)

    catalog = TestCatalog.load_default()
    embedder = DeterministicEmbedder()

    with tempfile.TemporaryDirectory() as directory:
        store = ChromaVectorStore(directory, collection_name="evaluation")
        ingest(store, embedder)
        report = run_evaluation(
            agent=RetrievalAgent(store, embedder, catalog),
            catalog=catalog,
            k=args.k,
        )

    text = format_report(report)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"\nWrote {args.output}")

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
