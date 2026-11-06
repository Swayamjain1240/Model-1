"""Rerank blend, MVP-lite (ATL-TDD-001 s.6).

Cheap, explainable, and deliberately replaceable: stage 2 swaps this for a
trained cross-encoder and re-measures precision@5 against the same golden set.
All four weights come from config so the ablation can move them, and every
feature is deterministic, so two runs produce identical orderings.
"""

from __future__ import annotations

from ..config import SETTINGS, Settings
from ..text.tokenize import bigrams, tokenize


class Reranker:
    """Scores candidates by a weighted blend of four deterministic features."""

    def __init__(self, idf: dict[str, float], *, settings: Settings = SETTINGS) -> None:
        self._idf = idf
        self._settings = settings
        # Precomputed per-chunk (token set, bigram set) by the owning view; chunk
        # features never change between searches, so recomputing them per request
        # was one of the M5 findings (load test showed it dominating p95).
        self._chunk_features: dict[int, tuple[set[str], set[str]]] | None = None

    def attach_features(self, features: dict[int, tuple]) -> None:
        """Cache per-chunk token sets keyed by candidate index (M5 perf).

        The tuple is (text tokens, text bigrams, title tokens, section tokens); the
        reranker reads the first two and ignores the rest, which the learned ranker uses.
        """
        self._chunk_features = features

    def rerank(
        self,
        query: str,
        candidates: list[tuple[int, float, str, str, str]],
        *,
        k: int,
        context: dict | None = None,
    ) -> list[tuple[int, float]]:
        """Candidates are (idx, fuse_score, chunk_text, title); out is top-k (idx, score).

        Ties are broken by ascending idx, keeping equal-scored candidates in
        chunk order - the same determinism contract the retrievers give us.
        When the owning view attached precomputed features, per-candidate
        tokenisation is skipped (identical results, just cheaper).
        """
        query_tokens = tokenize(query)
        query_bigrams = bigrams(query_tokens)
        title_set = set(query_tokens)
        max_fuse = max((candidate[1] for candidate in candidates), default=0.0)
        scored: list[tuple[int, float]] = []
        for idx, fuse_score, text, title, *_section in candidates:
            fuse_norm = (fuse_score / max_fuse) if max_fuse > 0.0 else 0.0
            if self._chunk_features is not None and idx in self._chunk_features:
                chunk_set, chunk_bigrams, *_ = self._chunk_features[idx]
            else:
                chunk_set = set(tokenize(text))
                chunk_bigrams = set(bigrams(list(chunk_set)))
            coverage = self._coverage(query_tokens, query_bigrams, chunk_set, chunk_bigrams)
            bigram_overlap = _ratio(query_bigrams, chunk_bigrams)
            title_match = _ratio(title_set, set(tokenize(title)))
            combined = (
                self._settings.rerank_weight_fuse * fuse_norm
                + self._settings.rerank_weight_coverage * coverage
                + self._settings.rerank_weight_bigram * bigram_overlap
                + self._settings.rerank_weight_title * title_match
            )
            scored.append((idx, combined))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:k]

    def coverage(self, query: str, text: str) -> float:
        """Public idf_coverage(query, chunk) for the confidence gate (ATL-TDD-001 s.7)."""
        tokens = tokenize(query)
        chunk_tokens = set(tokenize(text))
        return self._coverage(
            tokens, bigrams(tokens), chunk_tokens, set(bigrams(list(chunk_tokens)))
        )

    def _coverage(
        self,
        query_tokens: list[str],
        query_bigrams: list[str],
        chunk_set: set[str],
        chunk_bigrams: set[str],
    ) -> float:
        """idf_coverage: weight of the query terms found in the chunk / weight of all of them.

        The phrase part uses bigram IDF approximated as the mean of its words'
        IDF plus 1.0 - the same fixed approximation the dense projector uses.
        """
        weighed_total = 0.0
        weighed_found = 0.0
        for term in set(query_tokens):
            term_idf = self._idf.get(term, 1.0)
            weighed_total += term_idf
            if term in chunk_set:
                weighed_found += term_idf
        for phrase in set(query_bigrams):
            phrase_idf = self._phrase_idf(phrase)
            weighed_total += phrase_idf
            if phrase in chunk_bigrams:
                weighed_found += phrase_idf
        return (weighed_found / weighed_total) if weighed_total > 0.0 else 0.0

    def _phrase_idf(self, phrase: str) -> float:
        left, right = phrase.split(" ", 1)
        return (self._idf.get(left, 1.0) + self._idf.get(right, 1.0)) / 2.0 + 1.0


def _ratio(needles: list[str], haystack: set[str]) -> float:
    """Fraction of the needles present in the haystack; 0.0 when there is nothing to match."""
    if not needles:
        return 0.0
    hits = sum(1 for needle in needles if needle in haystack)
    return hits / len(needles)
