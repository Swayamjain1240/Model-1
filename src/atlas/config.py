"""Every tunable number in the system lives here (ATL-SwDD-001 s.2, s.8).

If a value is typed inline anywhere else, that is a review rejection: the eval
sweeps in M3 can only move numbers they can see.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Frozen container; a running process never mutates configuration."""

    # chunking (ATL-TDD-001 s.2)
    chunk_tokens: int = 180
    overlap_paragraphs: int = 1

    # sparse (ATL-TDD-001 s.3)
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    # dense stand-in (ATL-TDD-001 s.4)
    dense_dim: int = 1024
    embedder_name: str = "hashed-tfidf-d1024"

    # fusion + rerank (ATL-TDD-001 s.5-s.6)
    rrf_k: int = 60
    rerank_weight_fuse: float = 0.40
    rerank_weight_coverage: float = 0.40
    rerank_weight_bigram: float = 0.15
    rerank_weight_title: float = 0.05

    # candidate pools (ATL-TDD-001 s.1)
    sparse_candidates: int = 50
    dense_candidates: int = 50
    fused_candidates: int = 50
    rerank_candidates: int = 20

    # confidence gate (ATL-TDD-001 s.7) - theta is swept and measured in M3,
    # never chosen silently; this value is a placeholder until that table exists
    confidence_theta: float = 0.30

    # answers (ATL-TDD-001 s.8)
    max_answer_sentences: int = 4
    max_citations: int = 5
    citation_snippet_chars: int = 320

    # persistence
    default_db_path: str = "data/atlas.db"
    default_tenant: str = "campus"


SETTINGS = Settings()
