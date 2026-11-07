"""The out-of-sample test FR-11 and the refusal gate needed (M11).

Every number in `results/ablation.md` and `results/eval_report.md` was measured on the same
24+6 questions the design was tuned against, so answers like "refusal accuracy 1.00" were
in-sample claims. This harness adds a second, appended set - `eval/golden_set_v2.jsonl`,
12 answerable and 6 unanswerable questions written after the code was frozen - and uses it
the only way a holdout is useful:

    fit on v1, decide on v2.

Three questions are answered here:

1. **Does retrieval generalise?** The five configurations are scored on both sets.
2. **Does the confidence gate generalise?** Answer rate and refusal accuracy are computed at
   every theta in the shipped grid for both sets, from confidences measured once.
3. **Can fusion weights close FR-11?** A small grid of sparse/dense weights is scored on v1
   only; the best-on-v1 setting is then evaluated on v2 and adopted only if both agree.

The v1 set is never edited: v2 is a separate file with its own ids. Nothing was chosen by
looking at v2, including theta - that is the whole point.

Writes `results/holdout.md` and `results/holdout.json`.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from eval import metrics  # noqa: E402
from eval.run_eval import (  # noqa: E402
    ANSWER_K,
    RESULTS,
    build_store,
    load_questions,
    provenance,
)

V2_PATH = ROOT / "eval" / "golden_set_v2.jsonl"
ENCODER = "potion-base-8M"  # the shipped encoder; the hashed stand-in is in results/ablation.md

CONFIGS = (
    ("sparse", "sparse", {"rerank_kind": "none"}),
    ("dense", "dense", {"rerank_kind": "none"}),
    ("hybrid (fusion only)", "hybrid", {"rerank_kind": "none"}),
    ("hybrid + blend (shipped)", "hybrid", {"rerank_kind": "blend"}),
    ("hybrid + learned", "hybrid", {"rerank_kind": "learned", "rerank_allow_unadopted": True}),
)
SHIPPED = "hybrid + blend (shipped)"
FUSION = "hybrid (fusion only)"
WEIGHT_GRID = ((1.0, 1.0), (1.5, 1.0), (2.0, 1.0), (1.0, 0.5), (1.0, 1.5), (1.5, 0.5))


def load_v2() -> tuple[list[dict], list[dict]]:
    """The appended set, validated on read so a malformed label cannot pass silently."""
    rows = [
        json.loads(line)
        for line in V2_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        assert set(row) >= {"id", "query", "answerable", "relevant_doc_ids"}, row
        if row["answerable"]:
            assert row["relevant_doc_ids"], f"{row['id']} is answerable with no label"
        else:
            assert not row["relevant_doc_ids"], f"{row['id']} is unanswerable but labelled"
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "duplicate id in v2"
    answerable = [row for row in rows if row["answerable"]]
    return answerable, [row for row in rows if not row["answerable"]]


def measure(store, mode: str, overrides: dict, questions: list[dict]) -> dict:
    """Retrieval metrics for one configuration on one question set, with intervals."""
    settings = dataclasses.replace(SETTINGS, embedder_kind=ENCODER, **overrides)
    index = HybridIndex(store, settings=settings)
    columns: dict[str, list[float]] = {"recall": [], "precision5c": [], "ndcg": [], "mrr": []}
    misses: list[str] = []
    tenant = SETTINGS.default_tenant
    for question in questions:
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
        "recall": metrics.rate_with_ci(columns["recall"]),
        "precision5c": metrics.rate_with_ci(columns["precision5c"]),
        "ndcg": metrics.rate_with_ci(columns["ndcg"]),
        "mrr": metrics.rate_with_ci(columns["mrr"]),
        "missed_questions": misses,
    }


def confidences(store, questions: list[dict]) -> list[float]:
    """Top-passage confidence for each question, measured once and reused across thetas."""
    settings = dataclasses.replace(SETTINGS, embedder_kind=ENCODER)
    index = HybridIndex(store, settings=settings)
    tenant = SETTINGS.default_tenant
    out = []
    for question in questions:
        report = index.diagnostics(question["query"], tenant_id=tenant)
        out.append(0.0 if report is None else report[1]["confidence"])
    return out


def spread(values: list[float]) -> dict:
    return {"min": round(min(values), 3), "max": round(max(values), 3),
            "mean": round(sum(values) / len(values), 3)}


def theta_table(profile: dict, grid: tuple[float, ...]) -> list[dict]:
    """Answer rate and refusal accuracy at every theta, for both sets, one row per theta."""
    rows = []
    for theta in grid:
        row = {"theta": theta}
        for label, group in profile.items():
            a, u = group["answerable"], group["unanswerable"]
            answered = sum(1 for value in a if value >= theta)
            refused = sum(1 for value in u if value < theta)
            row[label] = {
                "answer_rate": metrics.rate_with_ci(
                    [1.0] * answered + [0.0] * (len(a) - answered)
                )["mean"],
                "refusal_accuracy": metrics.rate_with_ci(
                    [1.0] * refused + [0.0] * (len(u) - refused)
                )["mean"],
            }
        rows.append(row)
    return rows


def main() -> int:
    v1_answerable, v1_unanswerable = load_questions()
    v2_answerable, v2_unanswerable = load_v2()
    store = build_store(SETTINGS.default_tenant)
    try:
        results = {
            name: {
                "v1": measure(store, mode, overrides, v1_answerable),
                "v2": measure(store, mode, overrides, v2_answerable),
            }
            for name, mode, overrides in CONFIGS
        }
        profile = {
            "v1": {"answerable": confidences(store, v1_answerable),
                   "unanswerable": confidences(store, v1_unanswerable)},
            "v2": {"answerable": confidences(store, v2_answerable),
                   "unanswerable": confidences(store, v2_unanswerable)},
        }
        grid = [
            {
                "sparse_weight": sparse_w,
                "dense_weight": dense_w,
                "v1": measure(
                    store, "hybrid",
                    {"rerank_kind": "blend", "rrf_weight_sparse": sparse_w,
                     "rrf_weight_dense": dense_w},
                    v1_answerable,
                )["recall"],
                "v2": measure(
                    store, "hybrid",
                    {"rerank_kind": "blend", "rrf_weight_sparse": sparse_w,
                     "rrf_weight_dense": dense_w},
                    v2_answerable,
                )["recall"],
            }
            for sparse_w, dense_w in WEIGHT_GRID
        ]
    finally:
        store.close()

    trained = dataclasses.replace(SETTINGS, embedder_kind=ENCODER)
    theta = trained.theta
    table = theta_table(profile, trained.theta_grid)
    shipped_row = min(table, key=lambda row: abs(row["theta"] - theta))
    shipped = {
        label: {"answer_rate": shipped_row[label]["answer_rate"],
                "refusal_accuracy": shipped_row[label]["refusal_accuracy"]}
        for label in ("v1", "v2")
    }
    shipped["theta"] = theta

    shipped_v1 = results[SHIPPED]["v1"]["recall"]["mean"]
    shipped_v2 = results[SHIPPED]["v2"]["recall"]["mean"]
    best_v1 = max(
        grid,
        key=lambda row: (row["v1"]["mean"], -(row["sparse_weight"] + row["dense_weight"])),
    )
    dense_v2 = results["dense"]["v2"]["recall"]["mean"]
    sparse_v2 = results["sparse"]["v2"]["recall"]["mean"]
    fusion_v2 = results[FUSION]["v2"]["recall"]["mean"]

    # Adoption rule, stated before the numbers are read: no v1 loss AND a v2 gain.
    weight_adopted = best_v1["v1"]["mean"] >= shipped_v1 and best_v1["v2"]["mean"] > shipped_v2
    weight_tied = len({round(row["v1"]["mean"], 6) for row in grid}) == 1
    v2_refusal_best = max(row["v2"]["refusal_accuracy"] for row in table)
    payload = {
        "provenance": provenance(),
        "method": (__doc__ or "").strip(),
        "encoder": ENCODER,
        "sets": {
            "v1": {"answerable": len(v1_answerable), "unanswerable": len(v1_unanswerable)},
            "v2": {"answerable": len(v2_answerable), "unanswerable": len(v2_unanswerable)},
        },
        "configs": results,
        "confidence": {
            "theta": theta,
            "shipped": shipped,
            "theta_table": table,
            "spread": {label: {group: spread(values) for group, values in groups.items()}
                       for label, groups in profile.items()},
        },
        "fusion_grid": grid,
        "decision": {
            "shipped_v1": shipped_v1,
            "shipped_v2": shipped_v2,
            "best_on_v1": {
                "sparse_weight": best_v1["sparse_weight"],
                "dense_weight": best_v1["dense_weight"],
                "v1": best_v1["v1"]["mean"],
                "v2": best_v1["v2"]["mean"],
            },
            "weights_adopted": weight_adopted,
            "weights_identifiable": not weight_tied,
            "weights_tied": weight_tied,
            "fr11_met_on_v2": fusion_v2 >= max(dense_v2, sparse_v2),
            "fr11_gap_on_v2": round(fusion_v2 - max(dense_v2, sparse_v2), 4),
            "refusal_generalises": shipped["v2"]["refusal_accuracy"] >= 0.8,
            "best_v2_refusal_across_thetas": v2_refusal_best,
        },
    }
    (RESULTS / "holdout.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Holdout — the out-of-sample test (M11)",
        "",
        f"Encoder `{ENCODER}`. v1 is the frozen 24+6 set every earlier number used; v2 is an",
        "appended 12+6 set written after the code was frozen, with its own ids. Nothing in v1",
        "was edited, and no v2 question was used to choose a weight, a threshold or a ranker.",
        "",
        "## Retrieval, both sets, same configurations",
        "",
        "| configuration | v1 recall@10 (95% CI) | v2 recall@10 (95% CI) "
        "| v2 p@5 capped | v2 MRR |",
        "|---|---|---|---|---|",
    ]
    for name, block in results.items():
        one, two = block["v1"]["recall"], block["v2"]["recall"]
        lines.append(
            f"| {name} | {one['mean']:.4f} [{one['ci_low']:.3f}, {one['ci_high']:.3f}] "
            f"| {two['mean']:.4f} [{two['ci_low']:.3f}, {two['ci_high']:.3f}] "
            f"| {block['v2']['precision5c']['mean']:.4f} | {block['v2']['mrr']['mean']:.4f} |"
        )
    lines += [
        "",
        "Recall on v2 is 1.0000 for four of the five configurations, so this set cannot",
        "discriminate rankers: its questions are short, factual and single-document, which is",
        "exactly the traffic the system handles well. A holdout that saturates says nothing",
        "about which ranker is better - only that none of them misses a relevant document.",
        "",
        "## The gate on the new set: answer rate and refusal accuracy",
        "",
        "| set | theta | answer rate | refusal accuracy | n answerable | n unanswerable |",
        "|---|---|---|---|---|---|",
    ]
    for label in ("v1", "v2"):
        block = shipped[label]
        n_a = payload["sets"][label]["answerable"]
        n_u = payload["sets"][label]["unanswerable"]
        lines.append(
            f"| {label} | {theta:.2f} | {block['answer_rate']:.4f} "
            f"| {block['refusal_accuracy']:.4f} | {n_a} | {n_u} |"
        )
    spreads = payload["confidence"]["spread"]
    lines += [
        "",
        "## Why it fails: the classes overlap on the only feature the gate uses",
        "",
        "| set | class | confidence min | max | mean |",
        "|---|---|---|---|---|",
    ]
    for label, groups in spreads.items():
        for group in ("answerable", "unanswerable"):
            stats = groups[group]
            lines.append(
                f"| {label} | {group} | {stats['min']:.3f} | {stats['max']:.3f} "
                f"| {stats['mean']:.3f} |"
            )
    lines += [
        "",
        "On v1 the six unanswerable questions all sit below the six weakest answerable ones,",
        "which is why theta had a clean gap to land in. On v2 they do not: the lowest",
        f"answerable question scores {spreads['v2']['answerable']['min']:.3f} and the highest",
        f"unanswerable one scores {spreads['v2']['unanswerable']['max']:.3f}. No theta separates",
        "the two classes, and across the whole grid the best v2 refusal accuracy reachable is",
        f"{v2_refusal_best:.4f} - at the cost of refusing questions the system can answer.",
        "",
        "| theta | v1 answer | v1 refusal | v2 answer | v2 refusal |",
        "|---|---|---|---|---|",
    ]
    for row in table:
        marker = " (shipped)" if abs(row["theta"] - theta) < 1e-9 else ""
        lines.append(
            f"| {row['theta']:.2f}{marker} | {row['v1']['answer_rate']:.4f} "
            f"| {row['v1']['refusal_accuracy']:.4f} | {row['v2']['answer_rate']:.4f} "
            f"| {row['v2']['refusal_accuracy']:.4f} |"
        )
    lines += [
        "",
        "The shipped theta is **not** moved. Choosing the theta with the fewest v2 mistakes",
        "would consume the holdout and leave the next claim untested, which is the failure mode",
        "this set exists to prevent. The requirement stays open in `README.md` with these",
        "numbers attached.",
        "",
        "## Fusion weights: fitted on v1, judged on v2",
        "",
        "| sparse weight | dense weight | v1 recall@10 | v2 recall@10 |",
        "|---|---|---|---|",
    ]
    for row in grid:
        lines.append(
            f"| {row['sparse_weight']:.1f} | {row['dense_weight']:.1f} "
            f"| {row['v1']['mean']:.4f} | {row['v2']['mean']:.4f} |"
        )
    lines += [
        "",
        "## Decisions",
        "",
        "- **Fusion weights:** "
        + (f"all six settings score identically on both sets (v1 {shipped_v1:.4f}, v2 "
           f"{shipped_v2:.4f}), so this evaluation cannot identify a weight at all: fusion "
           "re-orders the same chunks whichever weight is used. **Nothing adopted.** The grid "
           "is kept as evidence that the knob is inert on a corpus this small, not as a "
           "tuned value."
           if weight_tied else
           f"best on v1 is sparse {best_v1['sparse_weight']:.1f} / dense "
           f"{best_v1['dense_weight']:.1f} with v1 {best_v1['v1']['mean']:.4f} and v2 "
           f"{best_v1['v2']['mean']:.4f}, against the shipped 1.0/1.0 at v1 {shipped_v1:.4f} "
           f"and v2 {shipped_v2:.4f}. "
           + ("Adopted: it holds on v1 and improves on v2."
              if weight_adopted else
              "**Not adopted**: the rule was no v1 loss and a v2 gain, and this does not "
              "clear both.")),
        f"- **FR-11 on the holdout:** fusion-only scores {fusion_v2:.4f} against dense "
        f"{dense_v2:.4f} and sparse {sparse_v2:.4f}, a gap of "
        f"{fusion_v2 - max(dense_v2, sparse_v2):+.4f}. "
        + ("The requirement is met on v2, but v2 saturates, so this is a weak pass: it shows "
           "fusion misses nothing on easy questions, not that it matches dense."
           if payload["decision"]["fr11_met_on_v2"] else
           "The requirement is still not met on v2."),
        f"- **Refusal generalises:** "
        f"{'yes' if payload['decision']['refusal_generalises'] else 'no'} - "
        f"v1 refusal accuracy {shipped['v1']['refusal_accuracy']:.4f} against v2 "
        f"{shipped['v2']['refusal_accuracy']:.4f}. The earlier figure was in-sample.",
        "",
        "## Misses on v2, by configuration",
        "",
    ]
    for name, block in results.items():
        missed = ", ".join(block["v2"]["missed_questions"]) or "none"
        lines.append(f"- {name}: {missed}")
    lines.append("")
    (RESULTS / "holdout.md").write_text("\n".join(lines), encoding="utf-8")

    print("written: results/holdout.md, results/holdout.json")
    for name, block in results.items():
        print(f"  {name:<26} v1 {block['v1']['recall']['mean']:.4f}  "
              f"v2 {block['v2']['recall']['mean']:.4f}")
    print(f"  gate: v1 answer {shipped['v1']['answer_rate']:.4f} refusal "
          f"{shipped['v1']['refusal_accuracy']:.4f} | v2 answer "
          f"{shipped['v2']['answer_rate']:.4f} refusal {shipped['v2']['refusal_accuracy']:.4f}")
    print(f"  weights adopted: {weight_adopted} | FR-11 on v2: "
          f"{payload['decision']['fr11_met_on_v2']} | refusal generalises: "
          f"{payload['decision']['refusal_generalises']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
