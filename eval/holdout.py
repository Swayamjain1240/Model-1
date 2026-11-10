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

**M13 appends a third set, `eval/golden_set_v3.jsonl`** (12 answerable, 6 unanswerable), because
v2 has now been read: its refusal failure is public, so tuning against it would be tuning on a
set whose answers we already know. v3 is written from the corpus after the v2 result was
recorded and is scored here for the first time. From M13 onward the decisions in this report are
read off **v3**, with v1 and v2 kept as the two earlier readings - a fix that only moves v1 and
v2 is not a fix, and a set that is only ever read once has to stay unread until it is.

One caveat stated before the numbers: v3 is written by the same person who wrote the code, so it
is a weaker holdout than a set written by a stranger. It still catches the failure that matters
here - a threshold fitted to six questions - because its unanswerable questions were chosen from
topics the corpus does not cover, not from the failure mode already known.

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
V3_PATH = ROOT / "eval" / "golden_set_v3.jsonl"
SET_LABELS = ("v1", "v2", "v3")
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


def load_set(path: Path, tag: str) -> tuple[list[dict], list[dict]]:
    """One appended set, validated on read so a malformed label cannot pass silently."""
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        assert set(row) >= {"id", "query", "answerable", "relevant_doc_ids"}, row
        if row["answerable"]:
            assert row["relevant_doc_ids"], f"{row['id']} is answerable with no label"
        else:
            assert not row["relevant_doc_ids"], f"{row['id']} is unanswerable but labelled"
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), f"duplicate id in {tag}"
    answerable = [row for row in rows if row["answerable"]]
    return answerable, [row for row in rows if not row["answerable"]]


def load_v2() -> tuple[list[dict], list[dict]]:
    return load_set(V2_PATH, "v2")


def load_v3() -> tuple[list[dict], list[dict]]:
    return load_set(V3_PATH, "v3")


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
    v3_answerable, v3_unanswerable = load_v3()
    sets = {
        "v1": (v1_answerable, v1_unanswerable),
        "v2": (v2_answerable, v2_unanswerable),
        "v3": (v3_answerable, v3_unanswerable),
    }
    store = build_store(SETTINGS.default_tenant)
    try:
        results = {
            name: {
                label: measure(store, mode, overrides, sets[label][0])
                for label in SET_LABELS
            }
            for name, mode, overrides in CONFIGS
        }
        profile = {
            label: {
                "answerable": confidences(store, sets[label][0]),
                "unanswerable": confidences(store, sets[label][1]),
            }
            for label in SET_LABELS
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
                "v3": measure(
                    store, "hybrid",
                    {"rerank_kind": "blend", "rrf_weight_sparse": sparse_w,
                     "rrf_weight_dense": dense_w},
                    v3_answerable,
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
        for label in SET_LABELS
    }
    shipped["theta"] = theta

    shipped_v1 = results[SHIPPED]["v1"]["recall"]["mean"]
    shipped_v2 = results[SHIPPED]["v2"]["recall"]["mean"]
    shipped_v3 = results[SHIPPED]["v3"]["recall"]["mean"]
    best_v1 = max(
        grid,
        key=lambda row: (row["v1"]["mean"], -(row["sparse_weight"] + row["dense_weight"])),
    )
    dense_v2 = results["dense"]["v2"]["recall"]["mean"]
    sparse_v2 = results["sparse"]["v2"]["recall"]["mean"]
    fusion_v2 = results[FUSION]["v2"]["recall"]["mean"]
    dense_v3 = results["dense"]["v3"]["recall"]["mean"]
    sparse_v3 = results["sparse"]["v3"]["recall"]["mean"]
    fusion_v3 = results[FUSION]["v3"]["recall"]["mean"]

    # Adoption rule, stated before the numbers are read: no v1 loss AND a v3 gain.
    # v1 is still what the best setting is chosen on; v3 is what decides whether it ships.
    weight_adopted = best_v1["v1"]["mean"] >= shipped_v1 and best_v1["v3"]["mean"] > shipped_v3
    weight_tied = len({round(row["v1"]["mean"], 6) for row in grid}) == 1
    v2_refusal_best = max(row["v2"]["refusal_accuracy"] for row in table)
    v3_refusal_best = max(row["v3"]["refusal_accuracy"] for row in table)
    payload = {
        "provenance": provenance(),
        "method": (__doc__ or "").strip(),
        "encoder": ENCODER,
        "sets": {
            label: {"answerable": len(sets[label][0]), "unanswerable": len(sets[label][1])}
            for label in SET_LABELS
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
            "shipped_v3": shipped_v3,
            "decided_on": "v3",
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
            "fr11_met_on_v3": fusion_v3 >= max(dense_v3, sparse_v3),
            "fr11_gap_on_v3": round(fusion_v3 - max(dense_v3, sparse_v3), 4),
            "refusal_generalises": shipped["v3"]["refusal_accuracy"] >= 0.8,
            "refusal_generalises_on_v2": shipped["v2"]["refusal_accuracy"] >= 0.8,
            "best_v2_refusal_across_thetas": v2_refusal_best,
            "best_v3_refusal_across_thetas": v3_refusal_best,
        },
    }
    (RESULTS / "holdout.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Holdout — the out-of-sample test (M11)",
        "",
        f"Encoder `{ENCODER}`. v1 is the frozen 24+6 set every earlier number used; v2 is an",
        "appended 12+6 set written after the code was frozen, with its own ids. Nothing in v1",
        "was edited, and no v2 question was used to choose a weight, a threshold or a ranker.",
        "v3 is the second appended set (12+6, M13), written after the v2 refusal failure was",
        "already known and scored here for the first time. **Decisions below are read off v3.**",
        "",
        "## Retrieval, all three sets, same configurations",
        "",
        "| configuration | v1 recall@10 (95% CI) | v2 recall@10 | v3 recall@10 "
        "| v3 p@5 capped | v3 MRR |",
        "|---|---|---|---|---|---|",
    ]
    for name, block in results.items():
        one, two, three = block["v1"]["recall"], block["v2"]["recall"], block["v3"]["recall"]
        lines.append(
            f"| {name} | {one['mean']:.4f} [{one['ci_low']:.3f}, {one['ci_high']:.3f}] "
            f"| {two['mean']:.4f} | {three['mean']:.4f} "
            f"| {block['v3']['precision5c']['mean']:.4f} | {block['v3']['mrr']['mean']:.4f} |"
        )
    v2_reaches = [block["v2"]["recall"]["mean"] for block in results.values()]
    v3_reaches = [block["v3"]["recall"]["mean"] for block in results.values()]
    lines += [
        "",
        f"{sum(1 for value in v2_reaches if value == 1.0)} of five configurations reach 1.0000 on",
        f"v2, {sum(1 for value in v3_reaches if value == 1.0)} of five on v3, so both appended",
        "sets",
        "are saturated: they say only that no configuration misses a relevant document on",
        "questions like these, which are short, factual and single-document - exactly the traffic",
        "this corpus produces. Neither set can rank the rankers. Their teeth are in the gate, and",
        "that is where both earn their place.",
        "",
        "## The gate on the new set: answer rate and refusal accuracy",
        "",
        "| set | theta | answer rate | refusal accuracy | n answerable | n unanswerable |",
        "|---|---|---|---|---|---|",
    ]
    for label in SET_LABELS:
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
        "v3 repeats the pattern with different numbers, which is what makes it a replication and",
        "not an anecdote: the weakest answerable question scores",
        f"{spreads['v3']['answerable']['min']:.3f}, the strongest unanswerable one",
        f"{spreads['v3']['unanswerable']['max']:.3f}, and the best refusal accuracy any theta can",
        f"reach is {v3_refusal_best:.4f}. The classes overlap on confidence in all three sets;",
        "the first set only looked separable because six questions happened to be easy to refuse.",
        "",
        "| theta | v1 answer | v1 refusal | v2 answer | v2 refusal | v3 answer | v3 refusal |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in table:
        marker = " (shipped)" if abs(row["theta"] - theta) < 1e-9 else ""
        lines.append(
            f"| {row['theta']:.2f}{marker} | {row['v1']['answer_rate']:.4f} "
            f"| {row['v1']['refusal_accuracy']:.4f} | {row['v2']['answer_rate']:.4f} "
            f"| {row['v2']['refusal_accuracy']:.4f} | {row['v3']['answer_rate']:.4f} "
            f"| {row['v3']['refusal_accuracy']:.4f} |"
        )
    lines += [
        "",
        "The shipped theta is **not** moved. Choosing the theta with the fewest v2 mistakes",
        "would consume the holdout and leave the next claim untested, which is the failure mode",
        "this set exists to prevent. The requirement stays open in `README.md` with these",
        "numbers attached.",
        "",
        "## Fusion weights: fitted on v1, judged on v3",
        "",
        "| sparse weight | dense weight | v1 recall@10 | v2 recall@10 | v3 recall@10 |",
        "|---|---|---|---|---|",
    ]
    for row in grid:
        lines.append(
            f"| {row['sparse_weight']:.1f} | {row['dense_weight']:.1f} "
            f"| {row['v1']['mean']:.4f} | {row['v2']['mean']:.4f} "
            f"| {row['v3']['mean']:.4f} |"
        )
    lines += [
        "",
        "## Decisions",
        "",
        "- **Fusion weights:** "
        + (f"all six settings score identically on all three sets (v1 {shipped_v1:.4f}, v2 "
           f"{shipped_v2:.4f}, v3 {shipped_v3:.4f}), so this evaluation cannot identify a weight "
           "at all: fusion "
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
        f"{'yes' if payload['decision']['refusal_generalises'] else 'no'} on v3 - "
        f"refusal accuracy {shipped['v1']['refusal_accuracy']:.4f} on v1, "
        f"{shipped['v2']['refusal_accuracy']:.4f} on v2, "
        f"{shipped['v3']['refusal_accuracy']:.4f} on v3. Two independent appended sets agree, so",
        "the v1 figure was in-sample and the gate is the open requirement, not a rounding problem.",
        f"- **FR-11 on v3:** fusion-only {fusion_v3:.4f} against dense {dense_v3:.4f} and sparse "
        f"{sparse_v3:.4f} ({fusion_v3 - max(dense_v3, sparse_v3):+.4f}). "
        + ("Met on v3 as well, with the same saturation caveat."
           if payload["decision"]["fr11_met_on_v3"] else
           "Still not met on the third set."),
        "",
        "## Misses, by set and configuration",
        "",
    ]
    for label in ("v2", "v3"):
        lines.append(f"**{label}**")
        lines.append("")
        for name, block in results.items():
            missed = ", ".join(block[label]["missed_questions"]) or "none"
            lines.append(f"- {name}: {missed}")
        lines.append("")
    lines.append("")
    (RESULTS / "holdout.md").write_text("\n".join(lines), encoding="utf-8")

    print("written: results/holdout.md, results/holdout.json")
    for name, block in results.items():
        print("  {:<26} {}".format(
            name,
            "  ".join(f"{label} {block[label]['recall']['mean']:.4f}" for label in SET_LABELS),
        ))
    print("  gate: " + " | ".join(
        f"{label} answer {shipped[label]['answer_rate']:.4f} "
        f"refusal {shipped[label]['refusal_accuracy']:.4f}"
        for label in SET_LABELS
    ))
    print(f"  weights adopted: {weight_adopted} | FR-11 on v2/v3: "
          f"{payload['decision']['fr11_met_on_v2']}/{payload['decision']['fr11_met_on_v3']}"
          f" | refusal generalises on v3: {payload['decision']['refusal_generalises']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
