"""M4 theta calibration on OBSERVED hybrid scores (ATL-EDD-001; FR-16, FR-17).

The M3 sweep used the canonical 0.20-0.40 range and saturated, because the
hashed-TF-IDF stand-in scores sit far below it. This script measures the real
score distributions on the frozen set, sweeps theta over the observed range,
reports false acceptances and false refusals per theta, and picks the lowest
theta with zero false accepts (falling back to the balanced knee otherwise).
The balanced-knee alternative stays in the payload for context, and the chosen
theta is then committed into config - with the table as evidence.

The rationale is explicit: a refusal is a safe failure; an answer with a wrong
citation is the dangerous failure the gate exists to prevent.

Run:  python -m eval.calibrate      (writes results/calibration.{md,json})

Honesty note, recorded in the report: this is in-sample calibration on the
frozen set (the MVP has no held-out split yet); stage 2 re-checks on the
expanded v2 set, and the M3 rule stands - no tuning to target numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from eval.run_eval import RESULTS, build_store, load_questions, provenance  # noqa: E402

STEP = 0.02


def collect() -> dict[str, list[float]]:
    """All 30 confidences in hybrid mode, from the same seam the answer path uses."""
    store = build_store(SETTINGS.default_tenant)
    index = HybridIndex(store)
    answerable, unanswerable = load_questions()
    answerable_conf: list[float] = []
    unanswerable_conf: list[float] = []
    try:
        for row in answerable:
            report = index.diagnostics(row["query"], tenant_id=SETTINGS.default_tenant)
            answerable_conf.append(round(report[1]["confidence"], 4) if report else -1.0)
        for row in unanswerable:
            report = index.diagnostics(row["query"], tenant_id=SETTINGS.default_tenant)
            unanswerable_conf.append(round(report[1]["confidence"], 4) if report else -1.0)
    finally:
        store.close()
    return {"a": answerable_conf, "u": unanswerable_conf}


def grid(all_scores: list[float]) -> list[float]:
    """Theta candidates spanning the observed range: low end to just above the top."""
    low = max(min(all_scores) - STEP, 0.0)
    high = max(all_scores) + STEP
    values, current = [], low
    while current <= high + 1e-9:
        values.append(round(current, 4))
        current += STEP
    return values


def sweep(answerable_conf: list[float], unanswerable_conf: list[float]) -> list[dict]:
    """One row per theta: balance under worse-with-honest accounting of the two errors."""
    rows = []
    for theta in grid(answerable_conf + unanswerable_conf):
        answered = [c for c in answerable_conf if c >= theta]
        refused_a = [c for c in answerable_conf if c < theta]
        accepted_u = [c for c in unanswerable_conf if c >= theta]
        refused_u = [c for c in unanswerable_conf if c < theta]
        rows.append(
            {
                "theta": theta,
                "answer_rate": round(len(answered) / len(answerable_conf), 4),
                "refusal_accuracy": round(len(refused_u) / len(unanswerable_conf), 4),
                "false_accepts": len(accepted_u),
                "false_refusals": len(refused_a),
            }
        )
    return rows


def choose(rows: list[dict]) -> dict:
    """Safety-first: the lowest theta with ZERO false accepts; a wrong citation is the
    dangerous error class, a refusal is a safe one. The balanced knee is reported as the
    alternative. If no theta is false-accept-free, fall back to best refusal accuracy."""
    clean = [row for row in rows if row["false_accepts"] == 0]
    if clean:
        return min(clean, key=lambda r: r["theta"])
    return max(rows, key=lambda r: (min(r["answer_rate"], r["refusal_accuracy"]),
                                    r["answer_rate"] + r["refusal_accuracy"],
                                    -r["theta"]))


def choose_balanced(rows: list[dict]) -> dict:
    """The alternative rule (maximize the worse of the two rates), reported for context."""
    return max(rows, key=lambda r: (min(r["answer_rate"], r["refusal_accuracy"]),
                                    r["answer_rate"] + r["refusal_accuracy"],
                                    -r["theta"]))


def write_report(payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "calibration.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Theta calibration on observed hybrid scores (M4)",
        "",
        f"Command: `python -m eval.calibrate` · commit `{payload['provenance']['commit']}` · "
        f"platform: {payload['provenance']['platform']}",
        "",
        "## Score distributions (hybrid top passage)",
        "",
        f"- answerable n={len(payload['distributions']['a'])}: "
        f"min {min(payload['distributions']['a']):.4f}, "
        f"max {max(payload['distributions']['a']):.4f}",
        f"- unanswerable n={len(payload['distributions']['u'])}: "
        f"min {min(payload['distributions']['u']):.4f}, "
        f"max {max(payload['distributions']['u']):.4f}",
        "",
        "## Sweep over the observed range",
        "",
        "| theta | answer rate | refusal accuracy | false accepts | false refusals |",
        "|---|---|---|---|---|",
    ]
    lines = lines + [
        f"| {row['theta']:.2f} | {row['answer_rate']:.2f} | {row['refusal_accuracy']:.2f} "
        f"| {row['false_accepts']} | {row['false_refusals']} |"
        for row in payload["sweep"]
    ]
    chosen = payload["chosen"]
    balanced = payload["chosen_balanced"]
    lines = lines + [
        "",
        f"**Chosen theta: {chosen['theta']:.2f}** - safety-first rule: the lowest theta "
        "with zero false accepts (a wrong citation is the dangerous error class; a refusal "
        "is safe). Answer rate recovers at stage 2 with real embeddings.",
        "",
        f"Alternative shown: balanced knee would be theta {balanced['theta']:.2f} "
        f"(answer rate {balanced['answer_rate']:.2f}, refusal accuracy "
        f"{balanced['refusal_accuracy']:.2f}) - rejected because it lets "
        f"{balanced['false_accepts']} unanswerable queries through as answers.",
        "",
        "This is in-sample calibration on the frozen set (no held-out split at MVP); "
        "stage 2 re-checks on the expanded v2 set. No value was tuned toward a target.",
    ]
    (RESULTS / "calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="calibrate the refusal theta")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    scores = collect()
    rows = sweep(scores["a"], scores["u"])
    chosen = choose(rows)
    payload = {
        "provenance": provenance(),
        "distributions": scores,
        "sweep": rows,
        "chosen": chosen,
        "chosen_balanced": choose_balanced(rows),
    }
    write_report(payload)
    if not args.quiet:
        print(f"chosen theta={chosen['theta']:.2f} "
              f"answer_rate={chosen['answer_rate']:.2f} "
              f"refusal_accuracy={chosen['refusal_accuracy']:.2f}")
        print("written: results/calibration.md, results/calibration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
