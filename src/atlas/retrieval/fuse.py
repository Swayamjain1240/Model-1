"""Reciprocal Rank Fusion (ATL-TDD-001 s.5).

Fusion uses ranks only, so a retriever with an unbounded or systematically
overconfident score scale cannot dominate the blend. k = 60 is the standard
value from the original TREC work and is swept in the M3 ablation.
"""

from __future__ import annotations


def rrf(
    ranked_lists: list[list[int]], *, k: int, weights: tuple[float, ...] | None = None
) -> dict[int, float]:
    """score(d) = sum over lists of w[list]/(k + rank + 1) for the rank positioned lists.

    Weights default to 1.0 per list, i.e. classic RRF. They exist so the stage-2
    ablation can price a retriever's evidence differently without inventing a new
    fusion algorithm (results/embeddings.md).
    """
    scores: dict[int, float] = {}
    for position, ranked in enumerate(ranked_lists):
        weight = 1.0 if weights is None else weights[position]
        for rank, idx in enumerate(ranked):
            scores[idx] = scores.get(idx, 0.0) + weight / (k + rank + 1)
    return scores
