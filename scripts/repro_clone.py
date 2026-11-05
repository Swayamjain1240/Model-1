"""M6 handover proof (FR-28): clean clone -> same commands -> same committed numbers.

Run:  python scripts/repro_clone.py      (writes results/handover.{md,json})

The proof is not "trust me": the script materialises a fresh clone of HEAD with
`git archive` (tracked files only - no working-tree state, no gitignored DB),
builds a new virtualenv in a temp dir, installs the package, and runs the same
operator commands from the README. It then boots the API from the clone and
compares the fresh recall number against the committed baseline. Every step's
command, exit status and duration is captured in the receipt.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS: list[dict] = []
_IS_WIN = sys.platform == "win32"


def run_step(title: str, cwd: Path, command: list[str]) -> None:
    """One recorded subprocess step; the receipt never hides a failure."""
    start = time.perf_counter()
    completed = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=900,
        env=dict(os.environ, PYTHONPATH="src"),
    )
    RECEIPTS.append({
        "step": title,
        "cwd": Path(cwd).name,
        "command": " ".join(str(part).replace(str(ROOT), ".") for part in command),
        "exit": completed.returncode,
        "seconds": round(time.perf_counter() - start, 2),
        "stdout_tail": completed.stdout.strip().splitlines()[-6:],
        "stderr_tail": completed.stderr.strip().splitlines()[-4:],
    })
    if completed.returncode != 0:
        print(completed.stdout[-2000:], completed.stderr[-2000:])
        raise SystemExit(f"step failed: {title} (exit {completed.returncode})")
    print(f"[ok] {title} ({RECEIPTS[-1]['seconds']}s)")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def smoke_serve(venv_python: str, clone: Path) -> None:
    """Boot the API from the clone on a free port, healthz it, ask once, kill it."""
    port = free_port()
    process = subprocess.Popen(
        [venv_python, "-m", "atlas.cli", "serve", "--port", str(port)], cwd=clone,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        status, deadline = None, time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/healthz",
                                            timeout=2) as response:
                    status = response.status
                break
            except OSError as error:
                if process.poll() is not None:
                    raise SystemExit("serve died during startup") from error
                time.sleep(0.3)
        if status != 200:
            raise SystemExit(f"healthz returned {status!r}, not 200")
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/ask?q=What+is+the+minimum+attendance+required",
            timeout=10,
        ) as ask_response:
            body = json.loads(ask_response.read())
        RECEIPTS.append({
            "step": "serve smoke: /v1/healthz + one /v1/ask",
            "exit": 0, "seconds": "-", "healthz_status": status,
            "ask_status": ask_response.status, "ask_refused": body.get("refused"),
            "has_timings": bool(body.get("timings_ms")),
        })
        print(f"[ok] serve smoke (healthz {status}, ask {ask_response.status})")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    baseline = json.loads((ROOT / "results" / "baseline.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="atlas-handover-cl-") as clone_root, \
            tempfile.TemporaryDirectory(prefix="atlas-handover-env-") as venv_root:
        clone = Path(clone_root) / "clean-clone"
        tarball = Path(tempfile.gettempdir()) / "atlas-handover-archive.tar"
        run_step("archive HEAD (tracked files only, like a fresh clone)", ROOT,
                 ["git", "archive", "--format=tar", "--output", str(tarball), "HEAD"])
        clone.mkdir()
        run_step("unpack into clean-clone/", clone_root,
                 ["tar", "-xf", str(tarball), "-C", "clean-clone"])
        venv_python = str(Path(venv_root) / ("Scripts" if _IS_WIN else "bin")
                          / ("python.exe" if _IS_WIN else "python"))
        run_step("setup: fresh virtualenv from the host interpreter", clone_root,
                 [sys.executable, "-m", "venv", venv_root])
        run_step("setup: pip install -e . (numpy only, per NFR-20 budget)", clone_root,
                 [venv_python, "-m", "pip", "install", "-e", str(clone), "--quiet"])
        run_step("ingest: 18 policy documents", clone,
                 [venv_python, "-m", "atlas.cli", "--db", "data/atlas.db",
                  "ingest", "corpus/campus"])
        run_step("eval gate in the clean clone", clone,
                 [venv_python, "-m", "eval.run_eval", "--gate"])
        smoke_serve(venv_python, clone)
        fresh = _compare(clone, baseline)
        verdict = ("PASS" if fresh["recall_at_10"] == fresh["expected_recall"]
                   and fresh["refusal_accuracy"] == fresh["expected_refusal"] else "FAIL")
        _write_receipt(fresh, verdict)
        print(f"handover proof: {verdict}")
        return 0 if verdict == "PASS" else 1


def _compare(clone: Path, baseline: dict) -> dict:
    """Numbers written by the clone itself, against the committed baseline."""
    report = (clone / "results" / "eval_report.json").read_text(encoding="utf-8")
    numbers = {key: float(value) for key, value in
               re.findall(r'"(recall_at_10|refusal_accuracy)":\s*([\d.]+)', report)}
    return {
        "recall_at_10": numbers["recall_at_10"],
        "refusal_accuracy": numbers["refusal_accuracy"],
        "expected_recall": baseline["recall_at_10"],
        "expected_refusal": baseline["refusal_accuracy"],
        "method": "eval_report.json written by the clean clone itself",
    }


def _write_receipt(fresh: dict, verdict: str) -> None:
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    provenance = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    payload = {
        "provenance": {"commit": provenance, "generator": "scripts/repro_clone.py (M6)"},
        "verdict": verdict,
        "steps": RECEIPTS,
        "fresh_eval": fresh,
    }
    (results / "handover.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Handover proof (M6, FR-28): clean clone -> same commands -> same numbers",
        "",
        f"HEAD `{provenance[:12]}` · generator `scripts/repro_clone.py`",
        "",
        "| step | exit | seconds | tail |",
        "|---|---|---|---|",
    ]
    lines += [f"| {entry['step']} | {entry.get('exit', '-')} | {entry.get('seconds', '-')} "
              f"| {' / '.join(entry.get('stdout_tail', [])[-2:]) or 'ok'} |"
              for entry in RECEIPTS]
    lines += [
        "",
        f"Fresh-clone eval vs committed baseline: recall@10 **{fresh['recall_at_10']:.4f}** "
        f"(expected {fresh['expected_recall']:.4f}), refusal accuracy "
        f"**{fresh['refusal_accuracy']:.4f}** (expected "
        f"{fresh['expected_refusal']:.4f}) — verdict: **{verdict}**",
        "",
        "Steps above are the actual operator commands from the README, run in a fresh",
        "`git archive HEAD` clone (tracked files only — no working-tree drift, no old DB)",
        "with a brand-new virtualenv. Single node, no containers.",
    ]
    (results / "handover.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
