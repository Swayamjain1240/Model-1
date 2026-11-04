"""Dense stand-in: hashed TF-IDF vectors (ATL-TDD-001 s.4).

Not a trained embedding: a deterministic, offline projection that occupies the
Embedder interface so fusion, reranking and evaluation can be built and measured
before a real encoder is introduced (stage 2). Hashing uses BLAKE2b because
Python's hash() is salted per process and would break reproducibility.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from ..config import SETTINGS, Settings
from ..text.tokenize import bigrams, tokenize


class HashedTFIDFEmbedder:
    """Implements the Embedder Protocol with (1 + ln tf) * IDF weighting (ATL-TDD-001 s.4)."""

    name: str
    dim: int

    def __init__(self, idf: dict[str, float], *, settings: Settings = SETTINGS) -> None:
        """`idf` is corpus-level (built with the sparse index), so query and chunks project
        into the same space and the cosine is meaningful."""
        self.idf = idf
        self.name = settings.embedder_name
        self.dim = settings.dense_dim
        self._settings = settings

    def embed(self, texts: list[str]) -> np.ndarray:
        """(n, dim) float32, L2-normalised rows; cosine becomes a plain dot product."""
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            self._project_into(row, vectors, text)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        with np.errstate(invalid="ignore"):
            return vectors / np.where(norms > 0, norms, 1.0)

    def _project_into(self, row: int, out: np.ndarray, text: str) -> None:
        tokens = tokenize(text)
        combined = tokens + bigrams(tokens)
        counts: dict[str, int] = {}
        for term in combined:
            counts[term] = counts.get(term, 0) + 1
        fallback_idf = math.log(2.0 * (len(self.idf) + 1)) if self.idf else 1.0
        for term, tf in counts.items():
            if " " in term:
                term_idf = self._twogram_idf(term, fallback_idf)
            else:
                term_idf = self.idf.get(term, fallback_idf)
            slot, sign = _hash64(term)
            out[row, slot] += sign * (1.0 + math.log(tf)) * term_idf

    def _twogram_idf(self, term: str, fallback_idf: float) -> float:
        """Bigrams take the mean of their words' IDF plus a phrase bonus - a fixed
        approximation that stage 2's real embedder replaces (ATL-TDD-001 s.10)."""
        left, right = term.split(" ", 1)
        left_idf = self.idf.get(left, fallback_idf)
        right_idf = self.idf.get(right, fallback_idf)
        return (left_idf + right_idf) / 2.0 + 1.0


def _hash64(term: str) -> tuple[int, int]:
    """BlAKE2b over the UTF-8 term -> (slot mod D, sign); stable across runs and processes."""
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % _dense_dim(), 1 if (value >> 63) & 1 else -1


def _dense_dim() -> int:
    """Read from settings once per call; kept tiny so embed() can stay a plain method."""
    return SETTINGS.dense_dim
