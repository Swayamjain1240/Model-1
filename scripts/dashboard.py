"""One static HTML page built from the committed reports (no server, no Docker).

Grafana was the obvious dashboard and the wrong one for this project: it needs a running
stack to look at, and the evidence here is already files in `results/`. So the dashboard is
generated *from* those files - `python scripts/dashboard.py` writes `dashboard.html`, which
opens from disk and shows exactly the numbers a reviewer would otherwise have to open six
reports to compare.

Every panel names its source file, so a number that looks wrong can be traced in one step.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUTPUT = ROOT / "dashboard.html"


def load(name: str) -> dict:
    """Missing or unreadable reports are shown as missing, never as zero."""
    path = RESULTS / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{cell}</th>" for cell in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def panel(title: str, source: str, body: str, note: str = "") -> str:
    footnote = f"<p class='note'>{note}</p>" if note else ""
    return (
        f"<section><h2>{title}</h2><p class='src'>source: <code>results/{source}</code></p>"
        f"{body}{footnote}</section>"
    )


def retrieval_panel() -> str:
    report = load("eval_report.json")
    modes = report.get("modes", {})
    if not modes:
        return panel("Retrieval baseline", "eval_report.json", "<p class='missing'>not run</p>")
    rows = [
        [
            mode,
            f"{block['aggregate']['recall_at_10']:.4f}",
            f"{block['aggregate']['precision_capped_at_5']:.4f}",
            f"{block['aggregate']['ndcg_at_10']:.4f}",
            f"{block['aggregate']['mrr']:.4f}",
        ]
        for mode, block in modes.items()
    ]
    body = table(["mode", "recall@10", "p@5 capped", "nDCG@10", "MRR"], rows)
    return panel("Retrieval baseline (frozen set, 24 answerable)", "eval_report.json", body)


def embeddings_panel() -> str:
    report = load("embeddings.json")
    encoders = report.get("encoders", {})
    if not encoders:
        return panel("Encoder swap", "embeddings.json", "<p class='missing'>not run</p>")
    rows = []
    for name, block in encoders.items():
        rows.append(
            [
                name,
                str(block["dim"]),
                f"{block['modes']['dense']['recall_at_10']:.4f}",
                f"{block['modes']['hybrid']['recall_at_10']:.4f}",
                f"{block['theta_chosen']:.2f}",
                f"{block['answer_rate']:.4f}",
                f"{block['refusal_accuracy']:.4f}",
            ]
        )
    body = table(
        ["encoder", "dim", "dense recall@10", "hybrid recall@10", "theta", "answer rate",
         "refusal"], rows
    )
    note = (
        "theta is per encoder: a trained encoder's cosines are not comparable to the hashed "
        "stand-in's, so re-using one threshold would measure the scale, not the system."
    )
    return panel("Stage-2 encoder delta", "embeddings.json", body, note)


def rerank_panel() -> str:
    report = load("rerank.json")
    scores = report.get("scores", {})
    if not scores:
        return panel("Reranker decision", "rerank.json", "<p class='missing'>not run</p>")
    rows = [
        [name, f"{block['recall_at_10']:.4f}", f"{block['precision_capped_at_5']:.4f}"]
        for name, block in scores["heldout"].items()
    ]
    body = table(["configuration (held-out documents)", "recall@10", "p@5 capped"], rows)
    verdict = report.get("verdict", "unknown")
    return panel(
        "Reranker: trained, judged out of sample",
        "rerank.json",
        body,
        f"decision: <strong>{verdict}</strong> — {report.get('decision_reason', '')}",
    )


def ablation_panel() -> str:
    report = load("ablation.json")
    configs = report.get("configs", {})
    if not configs:
        return panel("Ablation", "ablation.json", "<p class='missing'>not run</p>")
    rows = []
    for encoder, block in configs.items():
        for name, entry in block.items():
            recall = entry["recall"]
            rows.append(
                [
                    encoder.split(" (")[0],
                    name,
                    f"{recall['mean']:.4f} [{recall['ci_low']:.4f}, {recall['ci_high']:.4f}]",
                    f"{entry['precision5c']['mean']:.4f}",
                    f"{entry['mrr']['mean']:.4f}",
                ]
            )
    body = table(
        ["encoder", "configuration", "recall@10 (95% CI)", "p@5 capped", "MRR"], rows
    )
    return panel(
        "Ablation: one change per row, n=24",
        "ablation.json",
        body,
        "`hybrid` is the control arm (fusion, no reranker); every rate carries a Wilson interval.",
    )


def safety_panel() -> str:
    report = load("safety.json")
    summary = report.get("summary", {})
    if not summary:
        return panel("Safety", "safety.json", "<p class='missing'>not run</p>")
    rows = [
        ["attacks blocked, guard only", f"{summary['guard_blocks']}/{summary['attacks_total']}",
         f"{summary['guard_block_rate']:.0%}", ">= 95%"],
        ["attacks blocked, end to end", f"{summary['attacks_blocked']}/{summary['attacks_total']}",
         f"{summary['attack_block_rate']:.0%}", ">= 95%"],
        ["cross-tenant leaks", str(summary["tenant_leaks"]),
         f"{summary['tenant_probes']} probes", "0"],
        ["raw PII in logs", str(summary["pii_leaks"]), "live server", "0"],
        ["guard false positives", str(summary["guard_false_positives"]), "frozen questions", "0"],
        ["degraded answers", str(summary["degraded_answers"]), "simulated failure", "3 of 3"],
    ]
    body = table(["measurement", "value", "scope", "target"], rows)
    return panel("Safety (NFR-09, NFR-10, NFR-11, NFR-16)", "safety.json", body)


def load_panel() -> str:
    bench = load("bench.json")
    rows = [
        [str(row["users"]), str(row["requests"]), f"{row['p50_ms']:.2f}",
         f"{row['p95_ms']:.2f}", f"{row['p99_ms']:.2f}", f"{row['rps']:.1f}",
         str(row["failures"])]
        for row in bench.get("rows", [])
    ]
    body = table(["users", "requests", "p50 ms", "p95 ms", "p99 ms", "rps", "failures"], rows)
    return panel("Load curve (NFR-01: p95 <= 50 ms at 10 users)", "bench.json", body)


def soak_panel() -> str:
    report = load("soak.json")
    row = report.get("row", {})
    if not row:
        return panel("Soak", "soak.json", "<p class='missing'>not run</p>")
    rows = [
        ["duration", f"{row['duration_seconds'] / 60:.0f} min"],
        ["requests", str(row["requests"])],
        ["failures", f"{row['failures']} ({row['error_rate'] * 100:.3f}%)"],
        ["p95 ms", f"{row['p95_ms']:.2f}"],
        ["sustained rps", f"{row['rps']:.1f}"],
    ]
    return panel("Soak", "soak.json", table(["metric", "value"], rows))


def holdout_panel() -> str:
    """The finding that matters most for anyone trusting a number on this page."""
    report = load("holdout.json")
    if not report:
        return panel("Holdout", "holdout.json", "<p class='missing'>not run</p>")
    sets = report.get("sets", {})
    shipped = report.get("configs", {}).get("hybrid + blend (shipped)", {})
    gate = report.get("confidence", {}).get("shipped", {})
    decision = report.get("decision", {})
    rows = []
    for label in ("v1", "v2"):
        recall = shipped.get(label, {}).get("recall", {})
        rows.append([
            f"{label} (n={sets.get(label, {}).get('answerable', 0)}+"
            f"{sets.get(label, {}).get('unanswerable', 0)})",
            f"{recall.get('mean', 0):.3f}",
            f"{gate.get(label, {}).get('answer_rate', 0):.3f}",
            f"{gate.get(label, {}).get('refusal_accuracy', 0):.3f}",
        ])
    verdict = (
        "refusal does <strong>not</strong> generalise: theta was fitted to six questions"
        if not decision.get("refusal_generalises") else "refusal holds out of sample"
    )
    return panel(
        "Holdout — fit on v1, decide on v2", "holdout.json",
        table(["set", "recall@10", "answer rate", "refusal acc."], rows),
        f"{verdict}. FR-11 on v2: "
        f"{'met, but v2 saturates' if decision.get('fr11_met_on_v2') else 'not met'}.",
    )


def handover_panel() -> str:
    report = load("handover.json")
    steps = report.get("steps", [])
    if not steps:
        return panel("Handover proof", "handover.json", "<p class='missing'>not run</p>")
    rows = [[step.get("step", ""), step.get("status", "")] for step in steps]
    # repro_clone.py writes "verdict"; older payloads used a boolean
    passed = report.get("verdict", "PASS" if report.get("passed") else "FAIL") == "PASS"
    return panel(
        "Clean-clone handover (FR-28)", "handover.json",
        table(["step", "status"], rows),
        f"verdict: <strong>{'PASS' if passed else 'FAIL'}</strong>",
    )


def main() -> int:
    sections = [
        handover_panel(),
        retrieval_panel(),
        ablation_panel(),
        embeddings_panel(),
        rerank_panel(),
        safety_panel(),
        load_panel(),
        soak_panel(),
        holdout_panel(),
    ]
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Atlas — measured status</title>
<style>
 body {{ font: 15px/1.55 -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
        background: #0f1216; color: #e6e9ef; }}
 header {{ padding: 28px 32px 8px; }}
 h1 {{ margin: 0 0 6px; font-size: 24px; }}
 h2 {{ margin: 0 0 4px; font-size: 17px; }}
 .sub {{ color: #9aa4b2; margin: 0; }}
 main {{ padding: 8px 32px 40px; display: grid; gap: 20px;
         grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); }}
 section {{ background: #171c22; border: 1px solid #232b35; border-radius: 10px; padding: 16px; }}
 .src, .note {{ color: #8b95a5; font-size: 12.5px; margin: 4px 0 10px; }}
 .missing {{ color: #f0a35e; }}
 table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
 th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #232b35; }}
 th {{ color: #9aa4b2; font-weight: 600; }}
 code {{ background: #0f1216; padding: 1px 5px; border-radius: 4px; }}
</style></head><body>
<header>
  <h1>Atlas — measured status</h1>
  <p class="sub">Generated from the committed reports in <code>results/</code>.
  Regenerate with <code>python scripts/dashboard.py</code>.</p>
</header>
<main>{''.join(sections)}</main>
</body></html>
"""
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"written: {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
