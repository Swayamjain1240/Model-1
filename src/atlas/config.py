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

    # stage-2 trained encoder (ATL-TDD-001 s.10). Opt-in, because C-3/NFR-17 make the
    # offline hashed stand-in the default: ATLAS_EMBEDDER=potion-base-8M selects the real
    # one. results/embeddings.md is the only place the swap is allowed to argue.
    embedder_kind: str = os.environ.get("ATLAS_EMBEDDER", "hashed-tfidf-d1024")
    trained_model: str = "minishlab/potion-base-8M"
    trained_dim: int = 256
    embedder_cache_dir: str = "data/embedder_cache"  # vectors, never committed

    # fusion + rerank (ATL-TDD-001 s.5-s.6); rrf_k is swept by the ablation
    rrf_k: int = 60
    rrf_k_candidates: tuple[int, ...] = (10, 60, 100)
    # per-retriever evidence weights in the fusion blend; 1.0/1.0 is classic RRF,
    # and the stage-2 ablation (results/embeddings.md) is the only thing that may move them
    rrf_weight_sparse: float = 1.0
    rrf_weight_dense: float = 1.0
    rerank_weight_fuse: float = 0.40
    rerank_weight_coverage: float = 0.40
    rerank_weight_bigram: float = 0.15
    rerank_weight_title: float = 0.05
    # M8: "learned" loads committed weights trained on a document-held-out split, but the
    # loader only honours a file marked "adopted": true, so an experiment cannot ship by
    # accident. "blend" is the MVP hand weighting and the fallback in every other case.
    rerank_kind: str = "learned"
    rerank_model_path: str = "models/rerank-v1.json"

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

    # theta is a property of the SCORE SCALE, so each embedder carries its own
    # calibrated knee (results/embeddings.md, M7). Sharing one number across two
    # embedders would silently compare two different rulers.
    confidence_theta_trained: float = 0.31
    theta_candidates_trained: tuple[float, ...] = (
        0.20,
        0.25,
        0.28,
        0.30,
        0.31,
        0.33,
        0.35,
        0.38,
        0.40,
    )

    # answers (ATL-TDD-001 s.8)
    max_answer_sentences: int = 4
    max_citations: int = 5
    citation_snippet_chars: int = 320

    # persistence
    default_db_path: str = "data/atlas.db"
    default_tenant: str = "campus"

    # degraded mode (NFR-16): consecutive generation failures before the breaker opens
    breaker_threshold: int = 2
    breaker_cooldown_s: float = 30.0

    # API (M5): the token comes from the environment, never from the repo
    api_token: str = os.environ.get("ATLAS_API_TOKEN", "")
    serve_host: str = "127.0.0.1"
    serve_port: int = 8070

    @property
    def trained(self) -> bool:
        """True when a trained encoder is selected instead of the hashed stand-in."""
        return self.embedder_kind not in (self.embedder_name, "hashed")

    @property
    def theta(self) -> float:
        """The calibrated gate threshold for the selected embedder's score scale."""
        return self.confidence_theta_trained if self.trained else self.confidence_theta

    @property
    def theta_grid(self) -> tuple[float, ...]:
        """Sweep grid matching the selected scale (harness and calibration read this)."""
        return self.theta_candidates_trained if self.trained else self.theta_candidates


SETTINGS = Settings()
