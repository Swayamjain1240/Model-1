"""Prove the CI gate fails, without breaking the code to do it.

A gate that has only ever printed "gate ok" is a claim, not a control. The failure path is
demonstrated the honest way: run the gate twice, once against the committed baseline and once
against a *deliberately inflated* copy of it (recall@10 raised above what any retrieval here
can reach). The second run is exactly what a real regression would look like to the gate -
same comparison, same threshold, same exit code - and nothing in `results/` is modified.

Writes `results/ci_gate.md` with both transcripts and the exit codes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
TMP = RESULTS / ".baseline_inflated.json"


def run_gate(baseline: Path | None) -> tuple[int, str]:
    command = [sys.executable, "-m", "eval.run_eval", "--gate"]
    if baseline is not None:
        command += ["--baseline", str(baseline)]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(["src", "."])
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    committed = json.loads((RESULTS / "baseline.json").read_text(encoding="utf-8"))
    ok_code, ok_out = run_gate(None)

    inflated = dict(committed)
    inflated["recall_at_10"] = round(min(1.0, committed["recall_at_10"] + 0.08), 4)
    inflated["_note"] = "synthetic: committed baseline with recall@10 raised, for the failure demo"
    TMP.write_text(json.dumps(inflated, indent=2), encoding="utf-8")
    try:
        fail_code, fail_out = run_gate(TMP)
    finally:
        TMP.unlink(missing_ok=True)

    lines = [
        "# CI gate — the failure path, demonstrated (M10)",
        "",
        "`make ci` ends with `python -m eval.run_eval --gate`, which re-runs hybrid retrieval and",
        "fails the build when recall@10 drops by more than 0.02 or refusal accuracy falls below",
        "0.90 against `results/baseline.json`. A checker that has only ever passed proves nothing,",
        "so this records both paths.",
        "",
        "## Run 1 — committed baseline (expected: pass)",
        "",
        "```",
        "$ python -m eval.run_eval --gate",
        ok_out,
        f"# exit code {ok_code}",
        "```",
        "",
        "## Run 2 — inflated baseline (expected: fail)",
        "",
        "The baseline copy is the committed one with `recall_at_10` raised to "
        f"`{inflated['recall_at_10']:.4f}`. Nothing in `results/baseline.json` is touched,",
        "and no retrieval code is sabotaged: to the gate this is indistinguishable from a",
        "real regression, because it is the same comparison against a number the current",
        "system no longer reaches.",
        "",
        "```",
        "$ python -m eval.run_eval --gate --baseline results/.baseline_inflated.json",
        fail_out,
        f"# exit code {fail_code}",
        "```",
        "",
        "## Verdict",
        "",
        f"- Passing run exit code: {ok_code} (0 = gate ok).",
        f"- Failing run exit code: {fail_code} (1 = build fails; CI marks the step red).",
        "- The temporary baseline file is deleted after the run, so the repository's",
        "  baseline is never the inflated one. `--baseline` exists only to make this demonstrable.",
        "",
    ]
    (RESULTS / "ci_gate.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"pass run exit={ok_code} | fail run exit={fail_code}")
    print(f"written: {(RESULTS / 'ci_gate.md').relative_to(ROOT)}")
    return 0 if ok_code == 0 and fail_code == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
