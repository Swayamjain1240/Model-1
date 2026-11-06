"""HybridIndex: one tenant's in-memory view over the store, exposing the Retriever seam.

(ATL-SwDD-001 s.6-s.7.) The view is built lazily per tenant and invalidated
coarsely (whole tenant) on ingest - fine-grained invalidation is a stage-2
optimisation with a measurable target, not an M2 habit.
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS, Settings
from ..interfaces import InputError, Passage
from ..store import Store, StoredChunk
from ..text.tokenize import bigrams, tokenize
from .embedder import build_embedder
from .fuse import rrf
from .learned import build_reranker
from .sparse import BM25Index

MODES = ("sparse", "dense", "hybrid")


class HybridIndex:
    """search(query, *, tenant_id, k, mode) -> ranked passages (FR-07); tenant_id required."""

    def __init__(self, store: Store, *, settings: Settings = SETTINGS) -> None:
        self._store = store
        self._settings = settings
        self._views: dict[str, _TenantView] = {}

    def invalidate(self, tenant_id: str) -> None:
        """Drop one tenant's view; the next search rebuilds it from the store."""
        self._views.pop(tenant_id, None)

    def search(self, query: str, *, tenant_id: str, k: int, mode: str = "hybrid") -> list[Passage]:
        """Contract: k >= 1, len(result) <= k, one tenant, score-descending order (FR-08, FR-09).

        A tenant with an empty view returns [] rather than raising: "no documents"
        is a legitimate state the M3 refusal gate decides about.
        """
        if not tenant_id:
            raise InputError("empty tenant_id")
        if k < 1:
            raise InputError("k must be at least 1")
        if mode not in MODES:
            raise InputError(f"mode must be one of {MODES}, not {mode!r}")
        query = query.strip()
        if not query:
            raise InputError("empty query")
        view = self._view(tenant_id)
        if view is None:
            return []
        return view.search(query, k=k, mode=mode)

    def diagnostics(
        self, query: str, *, tenant_id: str, mode: str = "hybrid"
    ) -> tuple[Passage, dict] | None:
        """Top passage plus its cosine / coverage / confidence split (ATL-TDD-001 s.7).

        Used by the eval harness for the refusal decision; returns None when the
        tenant view is empty, which the harness counts as a refusal at every theta.
        """
        passages = self.search(query, tenant_id=tenant_id, k=1, mode=mode)
        if not passages:
            return None
        view = self._view(tenant_id)
        return passages[0], view.diagnose(query, passages[0])

    def candidate_set(
        self, query: str, *, tenant_id: str
    ) -> tuple[list[tuple[int, float, str, str, str]], dict[str, dict[int, float]]]:
        """Public access to the reranker's inputs, for training and diagnosis (M8)."""
        view = self._view(tenant_id)
        return view.candidate_set(query) if view is not None else ([], {})

    def view(self, tenant_id: str) -> _TenantView | None:
        """Read-only view access: the trainer needs chunk labels, not SQL."""
        return self._view(tenant_id)

    def _view(self, tenant_id: str) -> _TenantView | None:
        view = self._views.get(tenant_id)
        if view is None:
            chunks = self._store.list_chunks(tenant_id=tenant_id)
            if not chunks:
                return None
            view = _TenantView(chunks, settings=self._settings)
            self._views[tenant_id] = view
        return view


class _TenantView:
    """BM25 index, vector matrix and reranker, built once per tenant view."""

    def __init__(self, chunks: list[StoredChunk], *, settings: Settings) -> None:
        self._settings = settings
        texts = [chunk.text for chunk in chunks]
        self._chunks = list(chunks)
        self._index_of = {chunk.chunk_id: idx for idx, chunk in enumerate(self._chunks)}
        self._sparse = BM25Index(texts, settings=settings)
        self._embedder = build_embedder(settings.embedder_kind, self._sparse.idf, settings=settings)
        self._matrix = self._embedder.embed(texts)
        self._reranker = build_reranker(self._sparse.idf, settings=settings)
        # M5 perf: chunk features are immutable per view, so cache them once and the
        # reranker stops re-tokenising candidate text on every search (load-test finding)
        features: dict[int, tuple] = {}
        for idx, chunk in enumerate(self._chunks):
            ordered = tokenize(chunk.text)
            tokens = set(ordered)
            features[idx] = (
                tokens,
                # bigrams of a *set* depend on iteration order, which is hash-salted per
                # process: that made rankings differ between identical runs (found by the
                # M10 reproducibility check). Pairs come from the ordered tokens.
                set(bigrams(ordered)),
                set(tokenize(chunk.title)),
                set(tokenize(chunk.section)),
            )
        self._reranker.attach_features(features)

    def search(self, query: str, *, k: int, mode: str) -> list[Passage]:
        s = self._settings
        if mode == "sparse":
            return self._passages(self._sparse.search(tokenize(query), k=k)[:k])
        if mode == "dense":
            return self._passages(self._dense_search(query, k=k)[:k])
        candidates, context = self.candidate_set(query)
        reranked = self._reranker.rerank(
            query, candidates, k=min(k, s.rerank_candidates), context=context
        )
        return self._passages(reranked)

    def candidate_set(
        self, query: str
    ) -> tuple[list[tuple[int, float, str, str, str]], dict[str, dict[int, float]]]:
        """Exactly what the reranker sees: fused candidates plus their score context.

        Shared with the M8 trainer on purpose - training on a different feature
        pipeline than serving is how a learned ranker silently stops working.
        """
        s = self._settings
        sparse_pool = self._sparse.search(tokenize(query), k=s.sparse_candidates)
        dense_pool = self._dense_search(query, k=s.dense_candidates)
        lists = [[idx for idx, _ in sparse_pool], [idx for idx, _ in dense_pool]]
        fused = rrf(lists, k=s.rrf_k, weights=(s.rrf_weight_sparse, s.rrf_weight_dense))
        fused_top = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
        candidates: list[tuple[int, float, str, str, str]] = []
        for idx, score in fused_top[: s.fused_candidates]:
            chunk = self._chunks[idx]
            candidates.append((idx, score, chunk.text, chunk.title, chunk.section))
        return candidates, {"sparse": dict(sparse_pool), "cosine": dict(dense_pool)}

    @property
    def idf(self) -> dict[str, float]:
        """Corpus idf of this view; the trainer needs it to build the same features."""
        return self._sparse.idf

    def doc_of(self, idx: int) -> str:
        """Document id of a candidate index, for labelling training pairs (M8)."""
        return self._chunks[idx].doc_id

    def diagnose(self, query: str, passage: Passage) -> dict[str, float]:
        """Confidence components of one retrieved passage, formulas from ATL-TDD-001 s.7."""
        position = self._index_of[passage.chunk_id]
        query_vector = self._embedder.embed([query])[0]
        cosine = float(np.dot(self._matrix[position], query_vector))
        coverage = self._reranker.coverage(query, passage.text)
        confidence = (
            self._settings.confidence_cosine_weight * max(0.0, cosine)
            + self._settings.confidence_coverage_weight * coverage
        )
        return {"cosine": cosine, "coverage": coverage, "confidence": confidence}

    def _dense_search(self, query: str, *, k: int) -> list[tuple[int, float]]:
        """Cosine via the prebuilt unit-norm matrix; zero-score chunks are not candidates."""
        query_vec = self._embedder.embed([query])[0]
        scores = (self._matrix @ query_vec).tolist()
        candidates = [(idx, score) for idx, score in enumerate(scores) if score > 0.0]
        return sorted(candidates, key=lambda item: (-item[1], item[0]))[:k]

    def _passages(self, ranked: list[tuple[int, float]]) -> list[Passage]:
        """(idx, score) pairs arrive score-descending; rank is the position in the output."""
        out: list[Passage] = []
        for rank, (idx, score) in enumerate(ranked):
            chunk = self._chunks[idx]
            out.append(
                Passage(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    section=chunk.section,
                    text=chunk.text,
                    score=score,
                    rank=rank,
                )
            )
        return out
