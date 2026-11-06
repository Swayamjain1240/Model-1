"""Five configurations, one change at a time, on the frozen set (FR-11).

The M3 report compared three retrieval modes and swept the fusion constant; that answers
"which mode wins" but not "what did each layer buy", because the layers were never varied
independently. This harness holds everything else fixed and moves one thing per row:

    sparse            BM25 only
    dense             the configured encoder only
    hybrid            fusion, no reranker          <- the control arm
    hybrid + blend    fusion + the hand weights shipped since M2
    hybrid + learned  fusion + the trained weights, scored in place (unadopted)

The last row is the reason `rerank_allow_unadopted` exists: the production loader refuses
those weights, and the ablation has to ask for them by name to measure what they would have
done. Nothing here can flip the shipped default.

Every rate carries n and a 95% Wilson interval, because 24 questions is a small sample and a
point estimate without its interval invites over-reading.

Writes `results/ablation.md` and `results/ablation.json`.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval.hybrid import HybridIndex  # noqa: E402
from eval import metrics  # noqa: E402
from eval.run_eval import ANSWER_K, RESULTS, build_store, load_questions, provenance  # noqa: E402

CONFIGS = (
    ("sparse", "sparse", {"rerank_kind": "none"}),
    ("dense", "dense", {"rerank_kind": "none"}),
    ("hybrid", "hybrid", {"rerank_kind": "none"}),
    ("hybrid + blend", "hybrid", {"rerank_kind": "blend"}),
    ("hybrid + learned", "hybrid", {"rerank_kind": "learned", "rerank_allow_unadopted": True}),
)
CONTROL = "hybrid"
# Both encoders, because the stage-2 claim is an *interaction*: the hand-weighted blend only
# double-counts once the dense side carries real meaning (M7). One encoder would hide that.
ENCODERS = (
    ("hashed stand-in (default, offline)", SETTINGS.embedder_kind),
    ("trained encoder (potion-base-8M)", "potion-base-8M"),
)


def measure(store, tenant: str, mode: str, overrides: dict) -> dict:
    """One configuration over every answerable question, with per-metric intervals."""
    settings = dataclasses.replace(SETTINGS, **overrides)
    index = HybridIndex(store, settings=settings)
    columns: dict[str, list[float]] = {"recall": [], "precision5c": [], "ndcg": [], "mrr": []}
    misses: list[str] = []
    for question in load_questions()[0]:
        passages = index.search(question["query"], tenant_id=tenant, k=ANSWER_K, mode=mode)
        docs = metrics.rank_documents(passages)
        relevant = set(question["relevant_doc_ids"])
        recall = metrics.recall_at_k(docs, relevant, ANSWER_K)
        columns["recall"].append(recall)
        columns["precision5c"].append(metrics.precision_capped_at_k(docs, relevant, 5))
        columns["ndcg"].append(metrics.ndcg_at_k(docs, relevant, ANSWER_K))
        columns["mrr"].append(metrics.mrr(docs, relevant))
        if recall < 1.0:
            misses.append(question["id"])
    return {
        "mode": mode,
        "overrides": overrides,
        "recall": metrics.rate_with_ci(columns["recall"]),
        "precision5c": metrics.rate_with_ci(columns["precision5c"]),
        "ndcg": metrics.rate_with_ci(columns["ndcg"]),
        "mrr": metrics.rate_with_ci(columns["mrr"]),
        "missed_questions": misses,
    }


def _delta(value: float, control: float) -> str:
    diff = value - control
    return f"{diff:+.4f}" if abs(diff) >= 0.00005 else "0.0000"


def main() -> int:
    store = build_store(SETTINGS.default_tenant)
    try:
        results = {
            label: {
                name: measure(
                    store,
                    SETTINGS.default_tenant,
                    mode,
                    {**overrides, "embedder_kind": embedder},
                )
                for name, mode, overrides in CONFIGS
            }
            for label, embedder in ENCODERS
        }
    finally:
        store.close()

    control = results[ENCODERS[0][0]][CONTROL]["recall"]["mean"]
    payload = {
        "provenance": provenance(),
        "method": __doc__.strip(),
        "control": CONTROL,
        "configs": results,
    }
    (RESULTS / "ablation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Ablation — what each layer bought (M10)",
        "",
        "Frozen set, 24 answerable questions, doc-level labels, k=10. One change per row;",
        "`hybrid` is the control arm (fusion, no reranker). Intervals are 95% Wilson on n=24,",
        "so a difference smaller than the overlap is not a finding.",
        "",
        "The table runs twice on purpose. The stage-2 claim is an interaction — the hand-weighted",
        "blend only double-counts once the dense side carries real meaning — and one encoder",
        "would hide exactly the thing this table is for.",
        "",
    ]
    for label, _embedder in ENCODERS:
        block_set = results[label]
        control = block_set[CONTROL]["recall"]["mean"]
        lines += [
            f"## {label}",
            "",
            "| configuration | recall@10 (95% CI) | Δ recall | p@5 capped | nDCG@10 | MRR |",
            "|---|---|---|---|---|---|",
        ]
        for name, block in block_set.items():
            recall = block["recall"]
            lines.append(
                f"| {name} | {recall['mean']:.4f} "
                f"[{recall['ci_low']:.4f}, {recall['ci_high']:.4f}] | "
                f"{_delta(recall['mean'], control)} | {block['precision5c']['mean']:.4f} | "
                f"{block['ndcg']['mean']:.4f} | {block['mrr']['mean']:.4f} |"
            )
        miss_lines = [
            f"- {name}: {', '.join(block['missed_questions']) or 'none'}"
            for name, block in block_set.items()
        ]
        lines += [
            "",
            "Misses at k=10, by configuration:",
            "",
            *miss_lines,
            "",
        ]

    lines += [
        "## What the two tables say together",
        "",
    ]
    for label, _embedder in ENCODERS:
        block_set = results[label]
        control = block_set[CONTROL]["recall"]["mean"]
        dense = block_set["dense"]["recall"]["mean"]
        sparse = block_set["sparse"]["recall"]["mean"]
        blend = block_set["hybrid + blend"]["recall"]["mean"]
        learned = block_set["hybrid + learned"]["recall"]["mean"]
        best_single = max(dense, sparse)
        lines += [
            f"**{label}.** Fusion {control:.4f} vs best single retriever {best_single:.4f} "
            f"(sparse {sparse:.4f}, dense {dense:.4f}). The blend scores {blend:.4f} "
            f"({_delta(blend, control)} vs control) and the learned weights {learned:.4f} "
            f"({_delta(learned, control)}). "
            + (
                "Here the blend *helps*, because with a hashed encoder it is the only "
                "semantic-ish signal left after fusion."
                if blend >= control
                else "Here the blend *costs* recall: with a real encoder it double-counts "
                "the lexical evidence and demotes correct chunks — the M7 diagnosis, measured "
                "by holding fusion fixed rather than inferred from fusion weights."
            ),
            "",
        ]
    lines += ["## Where the FR-11 gap actually comes from", ""]
    for label, _embedder in ENCODERS:
        block_set = results[label]
        control = block_set[CONTROL]["recall"]["mean"]
        best_single = max(block_set["sparse"]["recall"]["mean"],
                          block_set["dense"]["recall"]["mean"])
        best_reranked = max(block_set["hybrid + blend"]["recall"]["mean"],
                            block_set["hybrid + learned"]["recall"]["mean"])
        lines += [
            f"- **{label}.** Best single retriever {best_single:.4f}; fusion alone "
            f"{control:.4f} ({_delta(control, best_single)}); best reranked configuration "
            f"{best_reranked:.4f} ({_delta(best_reranked, best_single)}). "
            + (
                "Hybrid matches or beats the best single retriever here."
                if best_reranked >= best_single
                else "Fusion alone already reaches it; the loss is in reranking."
                if control >= best_single
                else "Fusion alone already trails it, and reranking does not close the gap - "
                "so the shortfall is not the ranker's alone."
            ),
        ]
    lines += [
        "",
        "FR-11 stays open in the README for any row above where hybrid trails the best single",
        "retriever. What this table adds is attribution: fusion and reranking are measured",
        "separately instead of blamed together.",
        "",
    ]

    (RESULTS / "ablation.md").write_text("\n".join(lines), encoding="utf-8")
    print("written: results/ablation.md, results/ablation.json")
    for label in results:
        for name, block in results[label].items():
            print(f"  {label[:22]:<22} {name:<18} recall@10 {block['recall']['mean']:.4f} "
                  f"[{block['recall']['ci_low']:.4f}, {block['recall']['ci_high']:.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
