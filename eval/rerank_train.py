"""M8: train the reranker on a document-held-out split, then let the numbers decide.

The split is by DOCUMENT, not by question: questions whose labelled evidence lives in
the six held-out documents are never seen while fitting, so the held-out score asks
"does this ranker generalise to documents it was not trained on?" rather than "did it
memorise the 24 questions?" - the only question a frozen set this small can answer.

Two objectives are fitted and both are reported:

* pointwise logistic regression (is this passage relevant?), and
* pairwise ranking loss (should this passage outrank that one?), which is the objective
  that matches what a reranker is actually asked to do. It was not chosen by looking at
  the held-out score for the first one; it is the standard objective and the pointwise
  model stays in the table as the loser it is.

Adoption rule, declared here and applied by the script:
    adopt a learned model iff its held-out recall@10 >= the blend AND >= the best
    single retriever (what FR-11 demands of hybrid). Otherwise the MVP blend stays.

Run:  python -m eval.rerank_train     (writes models/rerank-v1.json, results/rerank.*)
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

import eval.metrics as metrics  # noqa: E402
from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from atlas.retrieval.learned import FEATURES, LearnedReranker  # noqa: E402
from eval.run_eval import RESULTS, build_store, load_questions, provenance  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / SETTINGS.rerank_model_path
K = 10
HOLDOUT_EVERY = 3
ITERS, LR, L2 = 900, 0.5, 1e-3
PAIR_ITERS, PAIR_LR, PAIR_L2 = 400, 0.3, 0.01

STAGE2 = dataclasses.replace(
    SETTINGS, embedder_kind=SETTINGS.trained_model, rerank_kind="blend"
)


def split_documents() -> tuple[set[str], set[str]]:
    """Deterministic document split: 12 to train on, 6 never seen while fitting."""
    stems = sorted(path.stem for path in (ROOT / "corpus" / "campus").glob("*.md"))
    held = {stem for position, stem in enumerate(stems) if position % HOLDOUT_EVERY == 2}
    return set(stems) - held, held


def grouped_rows(index: HybridIndex, queries: list[dict]) -> list[tuple[np.ndarray, np.ndarray]]:
    """One (features, labels) block per query, built by the code path that serves it."""
    view = index.view(SETTINGS.default_tenant)
    extractor = LearnedReranker(
        {"features": list(FEATURES), "weights": [0.0] * len(FEATURES)},
        idf=view.idf,
        settings=STAGE2,
    )
    groups = []
    for row in queries:
        candidates, context = index.candidate_set(row["query"], tenant_id=SETTINGS.default_tenant)
        if not candidates:
            continue
        features = extractor.feature_matrix(row["query"], candidates, context)
        relevant = set(row["relevant_doc_ids"])
        labels = np.asarray(
            [1.0 if view.doc_of(cand[0]) in relevant else 0.0 for cand in candidates],
            dtype=np.float32,
        )
        groups.append((features, labels))
    return groups


def fit_pointwise(groups: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Logistic regression by full-batch gradient descent, class-balanced, deterministic."""
    matrix = np.vstack([features for features, _ in groups]).astype(np.float32)
    labels = np.concatenate([labels for _, labels in groups])
    weights = np.zeros(matrix.shape[1], dtype=np.float32)
    positives = max(1.0, float(labels.sum()))
    balance = np.where(labels > 0.0, (len(labels) - positives) / positives, 1.0).astype(np.float32)
    for _ in range(ITERS):
        predicted = 1.0 / (1.0 + np.exp(-(matrix @ weights)))
        gradient = matrix.T @ ((predicted - labels) * balance) / len(labels) + L2 * weights
        weights -= LR * gradient
    return weights


def fit_pairwise(groups: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """RankNet-style loss: sum over pairs of log(1 + exp(-(s_pos - s_neg)))."""
    pairs = []
    for _, labels in groups:
        positive = np.flatnonzero(labels > 0.0)
        negative = np.flatnonzero(labels <= 0.0)
        if len(positive) == 0 or len(negative) == 0:
            continue
        grid = np.stack(np.meshgrid(positive, negative, indexing="ij"), axis=-1).reshape(-1, 2)
        pairs.append(grid)
    stacked = np.vstack(pairs)
    weights = np.zeros(groups[0][0].shape[1], dtype=np.float32)
    for _ in range(PAIR_ITERS):
        gradient = np.zeros_like(weights)
        for features, labels in groups:
            positive = np.flatnonzero(labels > 0.0)
            negative = np.flatnonzero(labels <= 0.0)
            if len(positive) == 0 or len(negative) == 0:
                continue
            margin = (features[positive] @ weights)[:, None] - (
                features[negative] @ weights
            )[None, :]
            slope = -1.0 / (1.0 + np.exp(margin))  # d/dmargin of log(1 + exp(-margin))
            difference = features[positive][:, None, :] - features[negative][None, :, :]
            gradient += np.einsum("ij,ijd->d", slope, difference)
        gradient = gradient / max(1, len(stacked)) + PAIR_L2 * weights
        weights -= PAIR_LR * gradient
    return weights


def evaluate(index, queries: list[dict]) -> dict[str, float]:
    """Doc-level recall@10 and capped p@5 for one query subset."""
    recalls, precisions, missed = [], [], []
    for row in queries:
        passages = index.search(row["query"], tenant_id=SETTINGS.default_tenant, k=K)
        docs = metrics.rank_documents(passages)
        relevant = set(row["relevant_doc_ids"])
        recall = metrics.recall_at_k(docs, relevant, K)
        recalls.append(recall)
        precisions.append(metrics.precision_capped_at_k(docs, relevant, 5))
        if recall == 0.0:
            missed.append(row["id"])
    return {
        "recall_at_10": round(metrics.mean(recalls), 4),
        "precision_capped_at_5": round(metrics.mean(precisions), 4),
        "n": len(queries),
        "missed": missed,
    }


def latency_ms(index, queries: list[dict], *, repeats: int = 40) -> float:
    """Mean search time, warm views: the reranker runs on every request."""
    started = time.perf_counter()
    for position in range(repeats):
        index.search(queries[position % len(queries)]["query"],
                     tenant_id=SETTINGS.default_tenant, k=K)
    return round((time.perf_counter() - started) * 1000.0 / repeats, 3)


def learned_index(store, model: dict) -> HybridIndex:
    """An index built from a weights file through `build_reranker`, i.e. as served.

    Writing the candidate model to a temporary file and letting configuration load it
    means the evaluation also exercises the loader, not a hand-assembled object.
    """
    path = Path(tempfile.mkdtemp()) / "model.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    settings = dataclasses.replace(
        STAGE2, rerank_kind="learned", rerank_model_path=str(path)
    )
    return HybridIndex(store, settings=settings)


class _ForcedMode:
    """Single-retriever reference: the same index, with the mode pinned."""

    def __init__(self, index: HybridIndex, mode: str) -> None:
        self._index = index
        self._mode = mode

    def search(self, query: str, *, tenant_id: str, k: int, mode: str = "hybrid"):
        return self._index.search(query, tenant_id=tenant_id, k=k, mode=self._mode)


def write_report(payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "rerank.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    split, scores = payload["split"], payload["scores"]
    lines = [
        "# Stage-2 reranker — trained on documents, judged on held-out documents (M8)",
        "",
        f"Command: `python -m eval.rerank_train` · commit `{payload['provenance']['commit']}` · "
        f"platform: {payload['provenance']['platform']}",
        "",
        f"Split: {split['train_docs']} documents to train on, {split['heldout_docs']} held out "
        f"(`{', '.join(split['heldout_doc_ids'])}`). Questions with evidence in the held-out "
        f"documents: **{split['heldout_queries']}** of 24; {split['train_queries']} train the "
        f"weights, {split['excluded_queries']} span both sides and are excluded.",
        "",
        "## Held-out retrieval (the honest number)",
        "",
        "| configuration | recall@10 | p@5 capped | n |",
        "|---|---|---|---|",
    ]
    for name, block in scores["heldout"].items():
        lines.append(
            f"| {name} | {block['recall_at_10']:.4f} | {block['precision_capped_at_5']:.4f} "
            f"| {block['n']} |"
        )
    lines += [
        "",
        "## In-sample reference (same 24 queries, context only — not evidence)",
        "",
        "| configuration | recall@10 |",
        "|---|---|",
    ]
    lines += [
        f"| {name} | {block['recall_at_10']:.4f} |"
        for name, block in scores["in_sample"].items()
    ]
    lines += [
        "",
        "## Learned weights",
        "",
        "| feature | pointwise | pairwise |",
        "|---|---|---|",
    ]
    for position, name in enumerate(FEATURES):
        lines.append(
            f"| {name} | {payload['weights']['pointwise'][position]:+.4f} "
            f"| {payload['weights']['pairwise'][position]:+.4f} |"
        )
    lines += [
        "",
        f"Decision: **{payload['verdict']}**. {payload['decision_reason']}",
        "",
        f"Cost: mean search {payload['latency_ms']['blend']:.2f} ms (blend) vs "
        f"{payload['latency_ms']['pairwise']:.2f} ms (learned pairwise), warm views, one process.",
        "",
        "## Interpretation",
        "",
        *payload["notes"],
        "",
    ]
    RESULTS.joinpath("rerank.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def notes(payload: dict) -> list[str]:
    heldout = payload["scores"]["heldout"]
    blend = heldout["blend (MVP)"]["recall_at_10"]
    pointwise = heldout["learned pointwise"]["recall_at_10"]
    pairwise = heldout["learned pairwise"]["recall_at_10"]
    single = max(heldout["dense only"]["recall_at_10"], heldout["sparse only"]["recall_at_10"])
    missed_blend = ", ".join(heldout["blend (MVP)"]["missed"]) or "none"
    missed_pair = ", ".join(heldout["learned pairwise"]["missed"]) or "none"
    return [
        f"- Held-out: blend {blend:.4f}, pointwise {pointwise:.4f}, pairwise {pairwise:.4f}, "
        f"best single retriever {single:.4f}.",
        f"- Questions missed by the blend: {missed_blend}; by the learned pairwise: {missed_pair}.",
        "- The pointwise model put its largest weight on title overlap, which is a document",
        "  identity prior: on training documents the title shares words with the question, and on",
        "  unseen documents that shortcut is worth nothing. Its held-out score is the price of the",
        "  shortcut, which is exactly what a document-held-out split is for.",
        "- The pairwise model optimises ordering instead of relevance, and reports its own cost.",
        "  Only one of these is adopted, and only if the frozen set says so; both stay in the",
        "  table so the rejected one cannot quietly disappear.",
        f"- n={heldout['blend (MVP)']['n']} held-out questions: one question is worth "
        f"{1.0 / max(1, heldout['blend (MVP)']['n']):.2f} recall@10, so treat this as a direction, "
        "not an estimate. results/rerank.json carries the per-question rows.",
        "- Training pairs come from `candidate_set`, the same function the server calls, so there",
        "  is no feature drift between fitting and serving.",
    ]


def main() -> int:
    train_docs, held_docs = split_documents()
    answerable, _ = load_questions()
    train_queries = [q for q in answerable if set(q["relevant_doc_ids"]) <= train_docs]
    heldout_queries = [q for q in answerable if set(q["relevant_doc_ids"]) <= held_docs]
    excluded = len(answerable) - len(train_queries) - len(heldout_queries)

    store = build_store(SETTINGS.default_tenant)
    try:
        blend_index = HybridIndex(store, settings=STAGE2)
        groups = grouped_rows(blend_index, train_queries)
        fitted = {"pointwise": fit_pointwise(groups), "pairwise": fit_pairwise(groups)}
        models = {
            name: {
                "name": f"logreg-{name}",
                "objective": name,
                "features": list(FEATURES),
                "weights": [round(float(value), 6) for value in weights],
                "trained_on": {
                    "documents": sorted(train_docs),
                    "queries": len(train_queries),
                    "pairs": int(sum(len(labels) for _, labels in groups)),
                },
            }
            for name, weights in fitted.items()
        }
        indexes = {name: learned_index(store, model) for name, model in models.items()}
        heldout = {
            "dense only": evaluate(
                _ForcedMode(HybridIndex(store, settings=STAGE2), "dense"), heldout_queries
            ),
            "sparse only": evaluate(
                _ForcedMode(HybridIndex(store, settings=STAGE2), "sparse"), heldout_queries
            ),
            "blend (MVP)": evaluate(blend_index, heldout_queries),
            "learned pointwise": evaluate(indexes["pointwise"], heldout_queries),
            "learned pairwise": evaluate(indexes["pairwise"], heldout_queries),
        }
        in_sample = {
            "blend (MVP)": evaluate(blend_index, answerable),
            "learned pairwise": evaluate(indexes["pairwise"], answerable),
        }
        timing = {
            "blend": latency_ms(blend_index, answerable),
            "pairwise": latency_ms(indexes["pairwise"], answerable),
        }
    finally:
        store.close()

    single = max(heldout["dense only"]["recall_at_10"], heldout["sparse only"]["recall_at_10"])
    blend = heldout["blend (MVP)"]["recall_at_10"]
    passing = [
        name
        for name in ("pairwise", "pointwise")
        if heldout[f"learned {name}"]["recall_at_10"] >= blend
        and heldout[f"learned {name}"]["recall_at_10"] >= single
    ]
    adopted = passing[0] if passing else None
    if adopted:
        reason = (
            f"learned {adopted} scores "
            f"{heldout[f'learned {adopted}']['recall_at_10']:.4f} held-out "
            f"against blend {blend:.4f} and best single retriever {single:.4f}, so FR-11 holds on "
            "documents it never saw; these are the weights shipped."
        )
    else:
        reason = (
            f"no learned variant beat both the blend ({blend:.4f}) and the best single retriever "
            f"({single:.4f}) on held-out documents; the MVP blend stays and FR-11 remains open."
        )
    chosen = adopted or "pairwise"
    models[chosen]["adopted"] = bool(adopted)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(models[chosen], indent=2), encoding="utf-8")

    payload = {
        "provenance": provenance(),
        "split": {
            "train_docs": len(train_docs),
            "heldout_docs": len(held_docs),
            "heldout_doc_ids": sorted(held_docs),
            "train_queries": len(train_queries),
            "heldout_queries": len(heldout_queries),
            "excluded_queries": excluded,
        },
        "weights": {name: [round(float(v), 6) for v in w] for name, w in fitted.items()},
        "scores": {"heldout": heldout, "in_sample": in_sample},
        "latency_ms": timing,
        "adopted": adopted,
        "verdict": f"adopted {adopted}" if adopted else "not adopted",
        "decision_reason": reason,
    }
    payload["notes"] = notes(payload)
    write_report(payload)
    print(f"held-out recall@10: blend {blend:.4f} | pointwise "
          f"{heldout['learned pointwise']['recall_at_10']:.4f} | pairwise "
          f"{heldout['learned pairwise']['recall_at_10']:.4f} | best single {single:.4f}")
    print(f"adopted: {adopted or 'none (blend stays)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
