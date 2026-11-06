"""Learned reranker: a trained linear scorer over retrieval evidence (FR-11).

The MVP reranker is a hand-weighted blend of idf coverage, bigram overlap and title
match - features that proxy semantics with lexical statistics. Once the dense side
carries real meaning (M7), that proxy double-counts: `results/embeddings.md` shows
fusion weights move nothing while the blend demotes correct chunks.

This replaces the fixed weights with weights *learned* from labelled pairs, fitted
only on queries whose evidence lives in the training documents and scored only on
queries whose evidence lives in held-out documents. All features are already in
[0, 1] after per-query normalisation, so the weights are readable and no scaler has
to be shipped alongside them.

Fallback is deliberate: no weights file (or `rerank_kind=blend`) keeps the MVP
behaviour, so a clone with no model still runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..config import SETTINGS, Settings
from ..text.tokenize import bigrams, tokenize
from .rerank import Reranker

FEATURES = (
    "cosine",  # dense similarity, the semantic signal (0..1)
    "bm25",  # sparse score, normalised by the best in this candidate list
    "rrf",  # fused rank score, normalised the same way
    "coverage",  # idf-weighted share of query terms present in the chunk
    "bigram",  # phrase overlap
    "title",  # title overlap
    "section",  # heading overlap: answers often live under the queried topic
    "length",  # chunk length / budget, a mild verbosity prior
)


class LearnedReranker:
    """Implements the same `rerank` contract as `Reranker`, with learned weights."""

    name: str

    def __init__(self, model: dict[str, Any], *, idf: dict[str, float], settings: Settings) -> None:
        if tuple(model.get("features", ())) != FEATURES:
            raise ValueError("rerank model feature list does not match this code")
        self._weights = np.asarray(model["weights"], dtype=np.float32)
        self._idf = idf
        self._settings = settings
        self.name = str(model.get("name", "logreg-v1"))
        self._chunk_features: dict[int, tuple] | None = None

    def attach_features(self, features: dict[int, tuple]) -> None:
        """Reuse the index's cached token sets instead of re-tokenising per request.

        The M5 load test found per-request tokenisation dominated p95; a trained ranker
        must not quietly undo that, so it reads the same cache the blend reads.
        """
        self._chunk_features = features

    def rerank(
        self,
        query: str,
        candidates: list[tuple[int, float, str, str, str]],
        *,
        k: int,
        context: dict[str, dict[int, float]] | None = None,
    ) -> list[tuple[int, float]]:
        """Score candidates with the learned weights; ties break by index (FR-12)."""
        if not candidates:
            return []
        matrix = self.feature_matrix(query, candidates, context or {})
        scores = 1.0 / (1.0 + np.exp(-(matrix @ self._weights)))
        ranked = sorted(
            ((idx, float(score)) for idx, score in zip(
                (cand[0] for cand in candidates), scores, strict=True
            )),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[:k]

    def feature_matrix(
        self,
        query: str,
        candidates: list[tuple[int, float, str, str, str]],
        context: dict[str, dict[int, float]],
    ) -> np.ndarray:
        """(n, len(FEATURES)) float32; every column already scaled to [0, 1]."""
        query_tokens = tokenize(query)
        query_set = set(query_tokens)
        query_bigrams = set(bigrams(query_tokens))
        sparse = context.get("sparse", {})
        cosine = context.get("cosine", {})
        max_sparse = max(sparse.values(), default=0.0)
        max_rrf = max((cand[1] for cand in candidates), default=0.0)
        rows = np.zeros((len(candidates), len(FEATURES)), dtype=np.float32)
        for row, (idx, fuse_score, text, title, section) in enumerate(candidates):
            cached = (self._chunk_features or {}).get(idx)
            if cached is not None:
                chunk_tokens, chunk_bigrams, title_tokens, section_tokens = cached
            else:
                chunk_tokens = set(tokenize(text))
                chunk_bigrams = set(bigrams(list(chunk_tokens)))
                title_tokens, section_tokens = set(tokenize(title)), set(tokenize(section))
            rows[row] = (
                max(0.0, cosine.get(idx, 0.0)),
                (sparse.get(idx, 0.0) / max_sparse) if max_sparse > 0.0 else 0.0,
                (fuse_score / max_rrf) if max_rrf > 0.0 else 0.0,
                _coverage(query_set, query_bigrams, chunk_tokens, self._idf),
                _ratio(query_bigrams, chunk_bigrams),
                _ratio(query_set, title_tokens),
                _ratio(query_set, section_tokens),
                min(1.0, len(tokenize(text)) / self._settings.chunk_tokens),
            )
        return rows


def _coverage(
    query_set: set[str],
    query_bigrams: set[str],
    chunk_tokens: set[str],
    idf: dict[str, float],
) -> float:
    """idf-weighted share of the query's terms (and phrases) present in the chunk."""
    total = found = 0.0
    for term in query_set:
        weight = idf.get(term, 1.0)
        total += weight
        found += weight if term in chunk_tokens else 0.0
    return (found / total) if total > 0.0 else 0.0


def _ratio(needles: set[str], haystack: set[str]) -> float:
    """Overlap fraction; 0.0 when there is nothing to match (never a division by zero)."""
    return (len(needles & haystack) / len(needles)) if needles else 0.0


def load_model(path: str | Path) -> dict[str, Any] | None:
    """Read committed weights; None when absent, which keeps the blend fallback."""
    file = Path(path)
    if not file.exists():
        return None
    return json.loads(file.read_text(encoding="utf-8"))


def build_reranker(
    idf: dict[str, float], *, settings: Settings = SETTINGS
) -> Reranker | LearnedReranker:
    """`learned` only when weights exist AND the training report marks them adopted.

    The second condition is the point: a model that lost on held-out documents is kept
    in the repo as evidence, and this check makes it inert instead of one careless
    config edit away from production.
    """
    if settings.rerank_kind != "learned":
        return Reranker(idf, settings=settings)
    model = load_model(settings.rerank_model_path)
    if model is None or not model.get("adopted", False):
        return Reranker(idf, settings=settings)
    return LearnedReranker(model, idf=idf, settings=settings)
