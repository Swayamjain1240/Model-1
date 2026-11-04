"""Sparse retrieval: BM25 over an inverted index (ATL-TDD-001 s.3).

Query cost is proportional to the postings of the query's terms, not to the
corpus; ties are broken by chunk index so equal scores order deterministically.
"""

from __future__ import annotations

import math

from ..config import SETTINGS, Settings
from ..text.tokenize import tokenize


class BM25Index:
    """Built once per tenant view; queried many times."""

    def __init__(self, chunk_texts: list[str], *, settings: Settings = SETTINGS) -> None:
        self._settings = settings
        token_docs = [tokenize(text) for text in chunk_texts]
        self._doc_len = [len(tokens) for tokens in token_docs]
        self._avgdl = sum(self._doc_len) / len(self._doc_len) if self._doc_len else 0.0
        self.idf: dict[str, float] = {}
        self._postings: dict[str, list[tuple[int, int]]] = {}
        for idx, tokens in enumerate(token_docs):
            for term, tf in _term_counts(tokens).items():
                self._postings.setdefault(term, []).append((idx, tf))
        n_docs = len(self._doc_len)
        for term, postings in self._postings.items():
            self.idf[term] = math.log((n_docs + 1) / (len(postings) + 0.5))

    def search(self, query_terms: list[str], *, k: int) -> list[tuple[int, float]]:
        """Top-k (chunk_index, score), score desc, ties by ascending chunk index (FR-09, FR-12)."""
        scores: dict[int, float] = {}
        for term, _qtf in _term_counts(query_terms).items():
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self.idf[term]
            k1, b, avgdl = self._settings.bm25_k1, self._settings.bm25_b, self._avgdl
            for idx, tf in postings:
                denom = tf + k1 * (1 - b + b * self._doc_len[idx] / avgdl)
                scores[idx] = scores.get(idx, 0.0) + idf * (tf * (k1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return ranked[:k]


def _term_counts(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts
