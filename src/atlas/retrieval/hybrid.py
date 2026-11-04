"""HybridIndex: one tenant's in-memory view over the store, exposing the Retriever seam.

(ATL-SwDD-001 s.6-s.7.) The view is built lazily per tenant and invalidated
coarsely (whole tenant) on ingest - fine-grained invalidation is a stage-2
optimisation with a measurable target, not an M2 habit.
"""

from __future__ import annotations

from ..config import SETTINGS, Settings
from ..interfaces import InputError, Passage
from ..store import Store, StoredChunk
from ..text.tokenize import tokenize
from .dense import HashedTFIDFEmbedder
from .fuse import rrf
from .rerank import Reranker
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
        self._sparse = BM25Index(texts, settings=settings)
        self._embedder = HashedTFIDFEmbedder(self._sparse.idf, settings=settings)
        self._matrix = self._embedder.embed(texts)
        self._reranker = Reranker(self._sparse.idf, settings=settings)

    def search(self, query: str, *, k: int, mode: str) -> list[Passage]:
        s = self._settings
        if mode == "sparse":
            return self._passages(self._sparse.search(tokenize(query), k=k)[:k])
        if mode == "dense":
            return self._passages(self._dense_search(query, k=k)[:k])
        sparse_pool = self._sparse.search(tokenize(query), k=s.sparse_candidates)
        dense_pool = self._dense_search(query, k=s.dense_candidates)
        lists = [[idx for idx, _ in sparse_pool], [idx for idx, _ in dense_pool]]
        fused = rrf(lists, k=s.rrf_k)
        fused_top = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
        fused_top = fused_top[: s.fused_candidates]
        candidates = [
            (idx, score, self._chunks[idx].text, self._chunks[idx].title)
            for idx, score in fused_top
        ]
        reranked = self._reranker.rerank(query, candidates, k=min(k, s.rerank_candidates))
        return self._passages(reranked)

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
