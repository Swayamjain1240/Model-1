"""M5 latency benchmark (NFR-01 evidence): mean and p95 per mode + end-to-end answer.

Run:  python -m eval.latency      (writes results/latency.{md,json})

Stated method: the frozen-set answerable queries on one warm index, one warmup
pass excluded, then N timed passes in-process (no HTTP hop; the API adds only
serialization, see the load test for the concurrent picture).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from atlas.answer import answer_query  # noqa: E402
from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from eval.run_eval import RESULTS, build_store, load_questions, provenance  # noqa: E402

MODES = ("sparse", "dense", "hybrid")
WARMUP_PASSES = 1


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile over a small sample; deterministic."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    share = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * share


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def collect(index: HybridIndex, passes: int) -> dict[str, list[float]]:
    """Per-mode retrieval timings plus answer_query end-to-end, per timed pass."""
    answerable, _ = load_questions()
    readings: dict[str, list[float]] = {**{mode: [] for mode in MODES}, "answer_e2e": []}
    for _ in range(passes):
        for question in answerable:
            for mode in MODES:
                start = time.perf_counter()
                index.search(question["query"], tenant_id=SETTINGS.default_tenant, k=10, mode=mode)
                readings[mode].append((time.perf_counter() - start) * 1000.0)
            start = time.perf_counter()
            answer_query(index, question["query"], tenant_id=SETTINGS.default_tenant)
            readings["answer_e2e"].append((time.perf_counter() - start) * 1000.0)
    return readings


def summarize(readings: dict[str, list[float]]) -> dict:
    """One row per measurement: mean, p50, p95 in ms."""
    summary = {}
    for key, values in readings.items():
        summary[key] = {
            "n": len(values),
            "mean_ms": round(mean(values), 3),
            "p50_ms": round(percentile(values, 50.0), 3),
            "p95_ms": round(percentile(values, 95.0), 3),
        }
    return summary


def write_report(payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "latency.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Latency benchmark (M5, NFR-01 evidence)",
        "",
        f"Command: `python -m eval.latency` · commit `{payload['provenance']['commit']}` · "
        f"{payload['passes']} timed passes after {WARMUP_PASSES} warmup pas"
        f"{'s' if WARMUP_PASSES != 1 else ''}, in-process (no HTTP hop)",
        "",
        "| measurement | n | mean ms | p50 ms | p95 ms |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {key} | {row['n']} | {row['mean_ms']:.3f} | {row['p50_ms']:.3f} | {row['p95_ms']:.3f} |"
        for key, row in payload["summary"].items()
    ]
    lines += [
        "",
        "Concurrent load and the API hop are covered separately by "
        "`python -m bench.load_test` (10 workers, NFR-01).",
    ]
    (RESULTS / "latency.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="single-process latency benchmark")
    parser.add_argument("--passes", type=int, default=5)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    store = build_store(SETTINGS.default_tenant)
    index = HybridIndex(store)
    try:
        collect(index, WARMUP_PASSES)  # warmup: first pass pays one-time build costs
        readings = collect(index, args.passes)
    finally:
        store.close()
    payload = {
        "provenance": provenance(),
        "passes": args.passes,
        "warmup_passes": WARMUP_PASSES,
        "summary": summarize(readings),
    }
    write_report(payload)
    if not args.quiet:
        for key, row in payload["summary"].items():
            print(f"{key:10} mean={row['mean_ms']:.2f}ms p95={row['p95_ms']:.2f}ms")
        print("written: results/latency.md, results/latency.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
