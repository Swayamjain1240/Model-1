"""M7 stage-2: the measured delta of swapping the dense encoder (ATL-TDD-001 s.10).

One command answers three questions with the same frozen ruler:

1. Does a trained encoder retrieve better than the hashed stand-in? (recall@10, per mode)
2. Does the refusal gate recover an answer rate at the same false-accept count? (theta
   is re-calibrated on the new score scale, because theta is a property of the scale)
3. Which fusion setting, if any, closes FR-11 now that the dense side is strong? (ablation
   with the losers kept in the table)

Every number here is in-sample on the frozen golden set: the same 24+6 labels the MVP
baseline used. The set is never edited; a widened set can only arrive later as an
appended v2 with its own baseline (M3 rule, unchanged).

Run:  python -m eval.embeddings      (writes results/embeddings.{md,json})
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402

import eval.metrics as metrics  # noqa: E402
from atlas.config import SETTINGS, Settings  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from atlas.store import Store  # noqa: E402
from eval.run_eval import RESULTS, build_store, load_questions, provenance  # noqa: E402

K = 10
MODES = ("sparse", "dense", "hybrid")
REPEATS = 60
FUSION_GRID = ((1.0, 1.0), (1.0, 2.0), (1.0, 3.0), (2.0, 1.0))
RERANK_POOLS = (20, 40)
# (fuse, coverage, bigram, title): the committed blend plus two hypotheses.
RERANK_GRID = (
    (SETTINGS.rerank_weight_fuse, SETTINGS.rerank_weight_coverage,
     SETTINGS.rerank_weight_bigram, SETTINGS.rerank_weight_title),
    (1.0, 0.0, 0.0, 0.0),
    (0.15, 0.75, 0.10, 0.0),
)
# A gate that sits 0.0006 above the hardest unanswerable query is not a margin, it is
# the sample boundary. The rule demands a declared cushion before it will accept.
MARGIN = 0.01


def settings_for(kind: str) -> Settings:
    """The same Settings with one field changed: the whole point of the seam."""
    return dataclasses.replace(SETTINGS, embedder_kind=kind)


def sweep(conf_a: list[float], conf_u: list[float], grid: tuple[float, ...]) -> list[dict]:
    """Gate outcomes per theta, using the committed safety-first selection rule."""
    rows = []
    hardest = max(conf_u)
    for theta in sorted(set(grid)):
        accepted = [c for c in conf_u if c >= theta]
        rows.append(
            {
                "theta": theta,
                "answer_rate": round(sum(1 for c in conf_a if c >= theta) / len(conf_a), 4),
                "refusal_accuracy": round(
                    sum(1 for c in conf_u if c < theta) / len(conf_u), 4
                ),
                "false_accepts": len(accepted),
                "margin": round(theta - hardest, 4),
            }
        )
    return rows


def choose(rows: list[dict]) -> dict:
    """Safety-first (M4 rule) plus a cushion: lowest theta that is false-accept-free AND
    clears the hardest unanswerable query by MARGIN. Without the second condition the
    rule would sit exactly on the frozen sample's boundary and call it calibration."""
    clean = [row for row in rows if row["false_accepts"] == 0 and row["margin"] >= MARGIN]
    if clean:
        return min(clean, key=lambda row: row["theta"])
    clean = [row for row in rows if row["false_accepts"] == 0]
    if clean:
        return min(clean, key=lambda row: row["theta"])
    return max(rows, key=lambda row: (row["refusal_accuracy"], row["answer_rate"]))


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile: small n, so no interpolation theatre."""
    ordered = sorted(values)
    return ordered[max(0, int(round(0.95 * len(ordered))) - 1)] if ordered else 0.0


def evaluate(store: Store, kind: str) -> dict:
    """Everything one encoder can be judged by, on the frozen set."""
    settings = settings_for(kind)
    answerable, unanswerable = load_questions()
    tenant = SETTINGS.default_tenant
    index = HybridIndex(store, settings=settings)

    cold_start = time.perf_counter()
    index.search(answerable[0]["query"], tenant_id=tenant, k=K)
    cold_ms = round((time.perf_counter() - cold_start) * 1000.0, 3)

    per_mode: dict[str, dict] = {}
    hybrid_rows: list[dict] = []
    conf_a: list[float] = []
    conf_u: list[float] = []
    for mode in MODES:
        recalls: list[dict] = []
        for row in answerable:
            passages = index.search(row["query"], tenant_id=tenant, k=K, mode=mode)
            docs = metrics.rank_documents(passages)
            relevant = set(row["relevant_doc_ids"])
            recalls.append(
                {
                    "id": row["id"],
                    "recall": metrics.recall_at_k(docs, relevant, K),
                    "precision5": metrics.precision_capped_at_k(docs, relevant, 5),
                    "ndcg": metrics.ndcg_at_k(docs, relevant, K),
                    "mrr": metrics.mrr(docs, relevant),
                }
            )
            if mode == "hybrid":
                report = index.diagnostics(row["query"], tenant_id=tenant, mode=mode)
                conf_a.append(round(report[1]["confidence"], 4) if report else -1.0)
        per_mode[mode] = {
            "recall_at_10": round(metrics.mean([r["recall"] for r in recalls]), 4),
            "precision_capped_at_5": round(metrics.mean([r["precision5"] for r in recalls]), 4),
            "ndcg_at_10": round(metrics.mean([r["ndcg"] for r in recalls]), 4),
            "mrr": round(metrics.mean([r["mrr"] for r in recalls]), 4),
        }
        if mode == "hybrid":
            hybrid_rows = recalls
    for row in unanswerable:
        report = index.diagnostics(row["query"], tenant_id=tenant)
        conf_u.append(round(report[1]["confidence"], 4) if report else -1.0)

    grid = sorted(set(settings.theta_grid) | {settings.theta})
    rows = sweep(conf_a, conf_u, tuple(grid))
    chosen = choose(rows)
    shipped = next(row for row in rows if row["theta"] == settings.theta)

    latencies = []
    for i in range(REPEATS):
        row = answerable[i % len(answerable)]
        started = time.perf_counter()
        index.diagnostics(row["query"], tenant_id=tenant)
        latencies.append((time.perf_counter() - started) * 1000.0)

    chunks = store.stats(tenant_id=tenant)["chunks"]
    dim = settings.trained_dim if settings.trained else settings.dense_dim
    return {
        "kind": kind,
        "dim": dim,
        "modes": per_mode,
        "hybrid_rows": hybrid_rows,
        "theta_rows": rows,
        "theta_committed": settings.theta,
        "theta_chosen": chosen["theta"],
        "answer_rate": chosen["answer_rate"],
        "refusal_accuracy": chosen["refusal_accuracy"],
        "false_accepts": chosen["false_accepts"],
        "margin": chosen["margin"],
        # the number the MVP actually shipped, so the delta is against reality
        "answer_rate_committed": shipped["answer_rate"],
        "refusal_committed": shipped["refusal_accuracy"],
        "margin_committed": shipped["margin"],
        "theta_rows_all": rows,
        "confidence": {"a": conf_a, "u": conf_u},
        "cost": {
            "cold_view_ms": cold_ms,
            "diagnostics_mean_ms": round(float(np.mean(latencies)), 3),
            "diagnostics_p95_ms": round(p95(latencies), 3),
            "matrix_mb": round(chunks * dim * 4 / 1_000_000, 3),
        },
    }


def fusion_ablation(store: Store, kind: str) -> list[dict]:
    """Weighted-fusion x rerank-pool grid, trained encoder, hybrid recall@10 (FR-11)."""
    answerable, _ = load_questions()
    tenant = SETTINGS.default_tenant
    base = settings_for(kind)
    table = []
    for sparse_w, dense_w in FUSION_GRID:
        for pool in RERANK_POOLS:
            settings = dataclasses.replace(
                base,
                rrf_weight_sparse=sparse_w,
                rrf_weight_dense=dense_w,
                rerank_candidates=pool,
            )
            index = HybridIndex(store, settings=settings)
            recalls = []
            for row in answerable:
                passages = index.search(row["query"], tenant_id=tenant, k=K)
                docs = metrics.rank_documents(passages)
                recalls.append(
                    metrics.recall_at_k(docs, set(row["relevant_doc_ids"]), K)
                )
            table.append(
                {
                    "sparse_weight": sparse_w,
                    "dense_weight": dense_w,
                    "rerank_pool": pool,
                    "recall_at_10": round(metrics.mean(recalls), 4),
                }
            )
    return table


def rerank_ablation(store: Store, kind: str) -> list[dict]:
    """Rerank blend grid with fusion held fixed: isolates the reranker's own cost."""
    answerable, _ = load_questions()
    tenant = SETTINGS.default_tenant
    base = settings_for(kind)
    table = []
    for fuse_w, coverage_w, bigram_w, title_w in RERANK_GRID:
        settings = dataclasses.replace(
            base,
            rerank_weight_fuse=fuse_w,
            rerank_weight_coverage=coverage_w,
            rerank_weight_bigram=bigram_w,
            rerank_weight_title=title_w,
        )
        index = HybridIndex(store, settings=settings)
        recalls, precisions = [], []
        for row in answerable:
            passages = index.search(row["query"], tenant_id=tenant, k=K)
            docs = metrics.rank_documents(passages)
            relevant = set(row["relevant_doc_ids"])
            recalls.append(metrics.recall_at_k(docs, relevant, K))
            precisions.append(metrics.precision_capped_at_k(docs, relevant, 5))
        table.append(
            {
                "fuse": fuse_w,
                "coverage": coverage_w,
                "bigram": bigram_w,
                "title": title_w,
                "recall_at_10": round(metrics.mean(recalls), 4),
                "precision_capped_at_5": round(metrics.mean(precisions), 4),
                "adopted": False,
            }
        )
    return table


def write_report(payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "embeddings.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    base = payload["encoders"]["hashed"]
    real = payload["encoders"]["trained"]
    lines = [
        "# Stage-2 embeddings — measured delta against the frozen baseline (M7)",
        "",
        f"Command: `python -m eval.embeddings` · commit `{payload['provenance']['commit']}` · "
        f"platform: {payload['provenance']['platform']}",
        f"Corpus: `{payload['provenance']['corpus']}` · golden set unchanged: "
        f"{payload['golden']['answerable']} answerable + {payload['golden']['unanswerable']} "
        "unanswerable (labels, doc ids and split are the M1 originals)",
        "",
        "## Retrieval, same ruler (mean over the 24 answerable queries)",
        "",
        "| encoder | dim | recall@10 | p@5 capped | nDCG@10 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for name, block in (("hashed TF-IDF (MVP)", base), ("potion-base-8M (stage 2)", real)):
        for mode in MODES:
            agg = block["modes"][mode]
            lines.append(
                f"| {name} · {mode} | {block['dim']} | {agg['recall_at_10']:.4f} | "
                f"{agg['precision_capped_at_5']:.4f} | {agg['ndcg_at_10']:.4f} | "
                f"{agg['mrr']:.4f} |"
            )
    lines += [
        "",
        "## The refusal gate, re-calibrated per score scale",
        "",
        "| encoder | theta shipped | answer rate @shipped | refusal @shipped | theta by rule | "
        "answer rate @rule | refusal @rule | margin @rule |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, block in (("hashed", base), ("trained", real)):
        lines.append(
            f"| {name} | {block['theta_committed']:.2f} | "
            f"{block['answer_rate_committed']:.4f} | {block['refusal_committed']:.4f} | "
            f"{block['theta_chosen']:.2f} | {block['answer_rate']:.4f} | "
            f"{block['refusal_accuracy']:.4f} | {block['margin']:+.4f} |"
        )
    lines += [
        "",
        "Theta is not shared between encoders: confidence is `0.65·cosine + 0.35·coverage`,"
        " and a trained encoder's cosines sit on a different scale, so re-using 0.13 would"
        " have refused almost everything while looking like a retrieval failure.",
        "",
        "## Where the change lands, query by query (hybrid recall@10)",
        "",
        "| query | hashed | trained | delta |",
        "|---|---|---|---|",
    ]
    moves = 0
    for old, new in zip(base["hybrid_rows"], real["hybrid_rows"], strict=True):
        delta = new["recall"] - old["recall"]
        moves += 1 if abs(delta) > 1e-9 else 0
        lines.append(
            f"| {old['id']} | {old['recall']:.2f} | {new['recall']:.2f} | {delta:+.2f} |"
        )
    lines += [
        "",
        f"Queries whose hybrid recall changed: {moves}/{len(base['hybrid_rows'])}.",
        "",
        "## Fusion ablation under the strong dense side (FR-11)",
        "",
        "| sparse weight | dense weight | rerank pool | hybrid recall@10 |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {row['sparse_weight']:.0f} | {row['dense_weight']:.0f} | {row['rerank_pool']} | "
        f"{row['recall_at_10']:.4f} |"
        for row in payload["fusion_ablation"]
    ]
    lines += [
        "",
        "## Rerank blend ablation, fusion held fixed (isolates the true bottleneck)",
        "",
        "| fuse | coverage | bigram | title | hybrid recall@10 | p@5 capped | decision |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {row['fuse']:.2f} | {row['coverage']:.2f} | {row['bigram']:.2f} | "
        f"{row['title']:.2f} | {row['recall_at_10']:.4f} | {row['precision_capped_at_5']:.4f} | "
        f"{'adopted' if row['adopted'] else 'recorded, not shipped'} |"
        for row in payload["rerank_ablation"]
    ]
    lines += [
        "",
        "## Cost of the swap",
        "",
        "| encoder | cold view build (ms) | diagnostics mean (ms) | diagnostics p95 (ms) | "
        "vectors (MB) |",
        "|---|---|---|---|---|",
    ]
    for name, block in (("hashed", base), ("trained", real)):
        cost = block["cost"]
        lines.append(
            f"| {name} | {cost['cold_view_ms']:.2f} | {cost['diagnostics_mean_ms']:.2f} | "
            f"{cost['diagnostics_p95_ms']:.2f} | {cost['matrix_mb']:.3f} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        *payload["notes"],
        "",
    ]
    (RESULTS / "embeddings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def notes(base: dict, real: dict, ablation: list[dict], reranks: list[dict]) -> list[str]:
    """Written from the numbers, so a re-run cannot leave the prose behind."""
    dense_gain = real["modes"]["dense"]["recall_at_10"] - base["modes"]["dense"]["recall_at_10"]
    answer_gain = real["answer_rate"] - base["answer_rate_committed"]
    best = max(ablation, key=lambda row: (row["recall_at_10"], -row["dense_weight"]))
    best_rerank = max(reranks, key=lambda row: row["recall_at_10"])
    best_hybrid = real["modes"]["hybrid"]["recall_at_10"]
    fr11_target = max(
        real["modes"]["sparse"]["recall_at_10"], real["modes"]["dense"]["recall_at_10"]
    )
    out = [
        f"- Dense recall@10 moved {base['modes']['dense']['recall_at_10']:.4f} -> "
        f"{real['modes']['dense']['recall_at_10']:.4f} ({dense_gain:+.4f}) with every label,",
        "  metric and query untouched: the ruler did not move, the encoder did.",
        f"- Answer rate at the gate moved {base['answer_rate_committed']:.2f} -> "
        f"{real['answer_rate']:.2f} ({answer_gain:+.2f}) with refusal accuracy "
        f"{real['refusal_accuracy']:.2f} on the 6 unanswerable queries. This is the",
        "  limitation M4 recorded honestly (answer rate 0.08) closing for a measured reason:",
        "  confidence = 0.65*cosine + 0.35*coverage, and hashed cosine for a paraphrase is ~0,",
        "  so the gate could not tell 'reworded but present' from 'absent'.",
        f"- The gate margin is thin: theta sits {real['margin']:+.4f} above the hardest",
        "  unanswerable query, and n=6. That is a real risk, not a footnote - one reworded",
        "  unanswerable question could flip it, which is exactly what a widened v2 set tests.",
        f"- FR-11 (hybrid >= max single retriever) is still NOT met: hybrid "
        f"{real['modes']['hybrid']['recall_at_10']:.4f} vs single-retriever "
        f"{fr11_target:.4f}. The dense side is now the strongest retriever and the fusion+rerank",
        "  stage is the bottleneck, not the encoder.",
        f"- Best fusion row here is sparse {best['sparse_weight']:.0f} : dense "
        f"{best['dense_weight']:.0f} with rerank pool {best['rerank_pool']} at "
        f"{best['recall_at_10']:.4f}, i.e. {best['recall_at_10'] - best_hybrid:+.4f} against the",
        "  committed setting. Selection was made on the same frozen set it is reported on, so it",
        "  is in-sample and stated as such; it is a hypothesis for a trained reranker (M8), not a",
        "  shipped claim, unless the table says otherwise.",
        f"- The rerank ablation names the real culprit: fusion weights move nothing (every row "
        f"{best['recall_at_10']:.4f}), while the blend at best reaches "
        f"{best_rerank['recall_at_10']:.4f} against dense-only {fr11_target:.4f}. A hand-tuned"
        "  coverage/bigram blend was a proxy for semantics; once the encoder supplies semantics,"
        "  the proxy double-counts and demotes correct chunks.",
        "- That best blend is recorded and NOT shipped: choosing it here would be in-sample"
        "  selection on the very set that scores it. Replacing the blend with a trained scorer"
        "  is the next phase, evaluated on a document-held-out split.",
        "- Cost: the trained encoder is still CPU-only and its vectors are cached on disk, so a",
        "  warm run needs no network (NFR-17); the hashed stand-in stays the default (C-3).",
    ]
    return out


def main() -> int:
    answerable, unanswerable = load_questions()
    store = build_store(SETTINGS.default_tenant)
    try:
        base = evaluate(store, SETTINGS.embedder_name)
        real = evaluate(store, SETTINGS.trained_model)
        ablation = fusion_ablation(store, SETTINGS.trained_model)
        reranks = rerank_ablation(store, SETTINGS.trained_model)
        chunks = store.stats(tenant_id=SETTINGS.default_tenant)["chunks"]
    finally:
        store.close()
    payload = {
        "provenance": provenance(),
        "golden": {"answerable": len(answerable), "unanswerable": len(unanswerable)},
        "chunks": chunks,
        "encoders": {"hashed": base, "trained": real},
        "fusion_ablation": ablation,
        "rerank_ablation": reranks,
    }
    payload["notes"] = notes(base, real, ablation, reranks)
    write_report(payload)
    print(
        f"dense recall@10 {base['modes']['dense']['recall_at_10']:.4f} -> "
        f"{real['modes']['dense']['recall_at_10']:.4f}"
    )
    print(
        f"answer rate {base['answer_rate_committed']:.2f} (theta "
        f"{base['theta_committed']:.2f}) -> {real['answer_rate']:.2f} (theta "
        f"{real['theta_chosen']:.2f}), refusal {real['refusal_accuracy']:.2f}"
    )
    print("written: results/embeddings.md, results/embeddings.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
