"""Metric-definition tests: the ruler itself is tested before it measures (ATL-EDD-001 §6)."""

from __future__ import annotations

from atlas.interfaces import Passage
from eval.metrics import (
    mrr,
    ndcg_at_k,
    precision_at_k,
    precision_capped_at_k,
    rank_documents,
    rate_with_ci,
    recall_at_k,
    refusal_counts,
    wilson_interval,
)


def _docs(*ids: str) -> list[str]:
    return list(ids)


def _passage(doc_id: str) -> Passage:
    return Passage(
        chunk_id=doc_id, doc_id=doc_id, title=doc_id, section="root", text="text", score=1.0, rank=0
    )


def test_rank_documents_takes_best_rank_per_doc():
    docs = rank_documents([_passage("d1"), _passage("d2"), _passage("d1")])
    assert docs == ["d1", "d2"]


def test_recall_at_k_counts_relevant_in_top_k():
    assert recall_at_k(_docs("d1", "d2", "d3"), {"d1", "d3"}, k=2) == 0.5
    assert recall_at_k(_docs("d1", "d3", "d2"), {"d1", "d3"}, k=2) == 1.0
    assert recall_at_k(_docs("x"), {"d1"}, k=5) == 0.0
    assert recall_at_k([], set(), k=5) == 0.0


def test_precision_at_5_punishes_padding():
    assert precision_at_k(_docs("d1", "x", "x", "x", "d2"), {"d1", "d2"}, k=5) == 0.4
    assert precision_at_k(_docs("d1"), {"d1"}, k=5) == 0.2


def test_mrr_is_inverse_first_relevant_rank():
    assert mrr(_docs("x", "d1", "d2"), {"d1"}) == 0.5
    assert mrr(_docs("x", "y"), {"d1"}) == 0.0
    assert mrr(_docs("d1"), {"d1"}) == 1.0


def test_precision_capped_ceils_correctly():
    """The capped variant the >= 0.80 target refers to (eval/README.md M3 clarification)."""
    assert precision_capped_at_k(_docs("d1", "x"), {"d1"}, k=5) == 1.0
    assert precision_capped_at_k(_docs("x", "d1"), {"d1", "d2"}, k=5) == 0.5


def test_ndcg_at_k_binary_gains():
    docs = _docs("d1", "x", "d2")
    relevant = {"d1", "d2"}
    value = ndcg_at_k(docs, relevant, k=3)
    assert 0.0 < value <= 1.0
    assert ndcg_at_k(_docs("d1"), {"d1"}, k=1) == 1.0
    assert ndcg_at_k(_docs("x", "x"), {"d1"}, k=2) == 0.0


def test_refusal_counts_gate_outcomes():
    outcome = refusal_counts(answerable=[0.9, 0.1], unanswerable=[0.05, 0.3], theta=0.25)
    assert outcome == {"answer_rate": 0.5, "refusal_accuracy": 0.5}
    all_refused = refusal_counts([0.9], [0.01, 0.02], theta=0.25)
    assert all_refused["refusal_accuracy"] == 1.0


def test_wilson_interval_stays_inside_zero_and_one():
    """Near-1.0 rates are why the normal approximation was rejected: it overshoots."""
    low, high = wilson_interval(24, 24)
    assert 0.0 <= low < 1.0
    assert high <= 1.0
    assert low > 0.8


def test_wilson_interval_brackets_the_point_estimate():
    low, high = wilson_interval(18, 24)
    assert low < 0.75 < high
    assert low > 0.5 and high < 0.95


def test_rate_with_ci_reports_n_and_mean():
    stats = rate_with_ci([1.0, 0.0, 1.0, 1.0])
    assert stats["n"] == 4
    assert stats["mean"] == 0.75
    assert stats["ci_low"] < stats["mean"] < stats["ci_high"]
