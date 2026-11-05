"""Every tunable number in the system lives here (ATL-SwDD-001 s.2, s.8).

If a value is typed inline anywhere else, that is a review rejection: the eval
sweeps in M3 can only move numbers they can see.
"""

from __future__ import annotations

import os
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

    # fusion + rerank (ATL-TDD-001 s.5-s.6); rrf_k is swept by the ablation
    rrf_k: int = 60
    rrf_k_candidates: tuple[int, ...] = (10, 60, 100)
    rerank_weight_fuse: float = 0.40
    rerank_weight_coverage: float = 0.40
    rerank_weight_bigram: float = 0.15
    rerank_weight_title: float = 0.05

    # candidate pools (ATL-TDD-001 s.1)
    sparse_candidates: int = 50
    dense_candidates: int = 50
    fused_candidates: int = 50
    rerank_candidates: int = 20

    # confidence gate (ATL-TDD-001 s.7): confidence = 0.65*cosine + 0.35*coverage.
    # 0.13 is the lowest false-accept-free theta (results/calibration.md, M4, in-sample,
    # safety-first: wrong citations refuse-shipped; answer rate recovers at stage 2).
    # theta_candidates is the harness sweep; theta changes only on committed evidence.
    confidence_theta: float = 0.13
    confidence_cosine_weight: float = 0.65
    confidence_coverage_weight: float = 0.35
    theta_candidates: tuple[float, ...] = (0.20, 0.25, 0.30, 0.35, 0.40)

    # answers (ATL-TDD-001 s.8)
    max_answer_sentences: int = 4
    max_citations: int = 5
    citation_snippet_chars: int = 320

    # persistence
    default_db_path: str = "data/atlas.db"
    default_tenant: str = "campus"

    # API (M5): the token comes from the environment, never from the repo
    api_token: str = os.environ.get("ATLAS_API_TOKEN", "")
    serve_host: str = "127.0.0.1"
    serve_port: int = 8070


SETTINGS = Settings()
