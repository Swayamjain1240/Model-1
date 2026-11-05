"""FR-11 diagnosis (M4): which queries lose when hybrid replaces sparse, and why.

Run:  python -m eval.fr11     (writes results/fr11_diagnosis.md)

For every answerable query this runs sparse and hybrid, records recall@10 and
MRR for both, and marks losing queries (hybrid recall < sparse recall, or a
better sparse best-rank). Losing queries get their top-3 document ids per mode
plus the golden-set note, so the stage-2 reranker/embedding work has concrete
targets instead of an aggregate number to squint at.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import eval.metrics as metrics  # noqa: E402
from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from eval.run_eval import ANSWER_K, RESULTS, build_store, load_questions, provenance  # noqa: E402


def run_one_mode(index: HybridIndex, query: str, relevant: set[str], mode: str) -> dict:
    passages = index.search(query, tenant_id=SETTINGS.default_tenant, k=ANSWER_K, mode=mode)
    docs = metrics.rank_documents(passages)
    return {
        "docs": docs,
        "recall": metrics.recall_at_k(docs, relevant, ANSWER_K),
        "mrr": metrics.mrr(docs, relevant),
    }


def diagnose() -> dict:
    """Every answerable query, both modes: who wins, who loses, and what was ranked."""
    answerable, _ = load_questions()
    store = build_store(SETTINGS.default_tenant)
    index = HybridIndex(store)
    rows: list[dict] = []
    try:
        for question in answerable:
            relevant = set(question["relevant_doc_ids"])
            sparse = run_one_mode(index, question["query"], relevant, "sparse")
            hybrid = run_one_mode(index, question["query"], relevant, "hybrid")
            lost = hybrid["recall"] < sparse["recall"] or hybrid["mrr"] < sparse["mrr"]
            row = {
                "id": question["id"],
                "note": question["note"],
                "sparse_recall": sparse["recall"],
                "hybrid_recall": hybrid["recall"],
                "sparse_mrr": round(sparse["mrr"], 4),
                "hybrid_mrr": round(hybrid["mrr"], 4),
                "lost": lost,
                "sparse_top3": sparse["docs"][:3],
                "hybrid_top3": hybrid["docs"][:3],
            }
            rows.append(row)
    finally:
        store.close()
    losers = [row for row in rows if row["lost"]]
    return {
        "provenance": provenance(),
        "rows": rows,
        "losing_queries": [row["id"] for row in losers],
        "summary": {
            "answerable": len(rows),
            "hybrid_loses": len(losers),
            "hybrid_wins": sum(1 for row in rows
                               if row["hybrid_recall"] > row["sparse_recall"]
                               or row["hybrid_mrr"] > row["sparse_mrr"]),
            "tied": sum(1 for row in rows if not row["lost"]
                        and row["hybrid_recall"] == row["sparse_recall"]
                        and row["hybrid_mrr"] == row["sparse_mrr"]),
        },
    }


def write_report(payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "fr11_diagnosis.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# FR-11 diagnosis: hybrid vs sparse, query by query (M4)",
        "",
        f"Command: `python -m eval.fr11` · commit `{payload['provenance']['commit']}`",
        "",
        f"Hybrid loses on **{len(payload['losing_queries'])} "
        f"of {payload['summary']['answerable']}** answerable queries; "
        f"wins on {payload['summary']['hybrid_wins']}, ties on {payload['summary']['tied']}.",
        "",
        "## Losing queries (the stage-2 targets)",
        "",
        "| id | sparse recall/mrr | hybrid recall/mrr | sparse top-3 | hybrid top-3 | note |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        if not row["lost"]:
            continue
        lines.append(
            f"| {row['id']} | {row['sparse_recall']:.2f}/{row['sparse_mrr']:.2f} "
            f"| {row['hybrid_recall']:.2f}/{row['hybrid_mrr']:.2f} "
            f"| {', '.join(row['sparse_top3']) or '-'} "
            f"| {', '.join(row['hybrid_top3']) or '-'} | {row['note']} |"
        )
    lines = lines + [
        "",
        "Reading: where hybrid loses, the relevant doc is usually pushed below rank 10 by",
        "fused noise from the hashed-TF-IDF list or out-scored by the coverage feature on a",
        "longer neighbor chunk. The M3 ablation (k=10/60/100) already showed fusion alone",
        "cannot fix this - the fix is a meaningful dense vote (stage 2 embeddings) and a",
        "trained reranker that resists partial-coverage neighbors.",
    ]
    (RESULTS / "fr11_diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="FR-11 query-level diagnosis")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    payload = diagnose()
    write_report(payload)
    if not args.quiet:
        summary = payload["summary"]
        print(f"hybrid loses on {summary['hybrid_loses']}/{summary['answerable']} "
              f"answerable queries: {', '.join(payload['losing_queries']) or '-'}")
        print("written: results/fr11_diagnosis.md, results/fr11_diagnosis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
