"""Reciprocal Rank Fusion (ATL-TDD-001 s.5).

Fusion uses ranks only, so a retriever with an unbounded or systematically
overconfident score scale cannot dominate the blend. k = 60 is the standard
value from the original TREC work and is swept in the M3 ablation.
"""

from __future__ import annotations


def rrf(ranked_lists: list[list[int]], *, k: int) -> dict[int, float]:
    """score(d) = sum over lists of 1/(k + rank + 1) for the rank positioned lists."""
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, idx in enumerate(ranked):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores
