"""Retrieval metric definitions, frozen with the golden set (eval/README.md).

Metric definitions do not change between the MVP and stage 2; changing one
means changing the ruler, and that is a documented baseline reset, never a
silent edit.
"""

from __future__ import annotations

import math

from atlas.interfaces import Passage


def rank_documents(passages: list[Passage]) -> list[str]:
    """Unique doc ids in score order; the best rank of each doc wins."""
    seen: list[str] = []
    for passage in passages:
        if passage.doc_id not in seen:
            seen.append(passage.doc_id)
    return seen


def recall_at_k(docs: list[str], relevant: set[str], k: int) -> float:
    """|relevant n top-k| / |relevant|; 0.0 when there is nothing relevant to find."""
    if not relevant:
        return 0.0
    return len(relevant & set(docs[:k])) / len(relevant)


def precision_at_k(docs: list[str], relevant: set[str], k: int) -> float:
    """|relevant n top-k| / k over full slots, so result padding hurts (the honest variant)."""
    if k <= 0:
        return 0.0
    return len(relevant & set(docs[:k])) / k


def precision_capped_at_k(docs: list[str], relevant: set[str], k: int) -> float:
    """|relevant n top-k| / min(k, |relevant|) - the capped variant the 0.80 target refers to
    (see eval/README.md, M3 clarification; with single-doc labels its ceiling is 1.0)."""
    denominator = min(k, len(relevant))
    if denominator <= 0:
        return 0.0
    return len(relevant & set(docs[:k])) / denominator


def mrr(docs: list[str], relevant: set[str]) -> float:
    """1 / first rank of a relevant doc; 0.0 when none appears."""
    for rank, doc in enumerate(docs, start=1):
        if doc in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(docs: list[str], relevant: set[str], k: int) -> float:
    """Binary nDCG@k: gain 1.0 at each rank where a relevant doc appears."""
    if not relevant:
        return 0.0
    gains = [1.0 if doc in relevant else 0.0 for doc in docs[:k]]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_hits = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal > 0.0 else 0.0


def mean(values: list[float]) -> float:
    """Plain mean; 0.0 for an empty slice so aggregates stay total-safe."""
    return sum(values) / len(values) if values else 0.0


def refusal_counts(
    answerable: list[float], unanswerable: list[float], theta: float
) -> dict[str, float]:
    """Top-passage confidences into gate outcomes at one threshold.

    A passing confidence means "answered"; below theta or no passage at all is
    a refusal. The returned rates are answer share (of answerable queries) and
    refusal accuracy (of unanswerable queries).
    """
    answered_a = mean([1.0 if c >= theta else 0.0 for c in answerable]) if answerable else 0.0
    refused_u = mean([1.0 if c < theta else 0.0 for c in unanswerable]) if unanswerable else 0.0
    return {"answer_rate": round(answered_a, 4), "refusal_accuracy": round(refused_u, 4)}
