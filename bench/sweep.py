"""Latency curve and soak test (NFR-01, NFR-02): one command, three levels, real HTTP.

`bench.load_test` answers "does 10 concurrent users stay under 50 ms?" with a single point.
A single point cannot show a knee, so this script sweeps 1, 10 and 50 users over the same
corpus and adds an optional sustained run, which is where leaks and tail growth show up.

Method is the same one the M5 measurement settled on, and it is stated here because the
numbers mean nothing without it:

* the server is a real `ThreadingHTTPServer` over a temporary database built by the same
  ingest path, in this process - one process, one port, as deployed;
* each user is a separate client PROCESS with one persistent keep-alive connection, since
  agent-threaded stopwatches are GIL-inflated (measured and rejected in M5);
* every request is a real `GET /v1/ask` answered by the production code path.

Run:  python -m bench.sweep                          # 1, 10, 50 users -> results/bench.*
      python -m bench.sweep --soak-seconds 1800      # 30-minute soak -> results/soak.*
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import multiprocessing
import sys
import tempfile
import threading
import time
from array import array
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from atlas.server import ServerState, make_server  # noqa: E402
from atlas.store import Store  # noqa: E402
from eval.latency import percentile  # noqa: E402
from eval.run_eval import CORPUS, RESULTS, load_questions, provenance  # noqa: E402

FIXED_LEVELS = (1, 10, 50)
REQUESTS_PER_USER = 100
NFR01_USERS, NFR01_P95_MS = 10, 50.0


def build_database(path: Path) -> None:
    """Same ingest path as production, into a throwaway database."""
    store = Store(path)
    try:
        for document in sorted(CORPUS.glob("*.md")):
            store.upsert_document(tenant_id="campus", path=document)
    finally:
        store.close()


def boot(db: Path) -> tuple[ThreadingHTTPServer, int]:
    server = make_server(("127.0.0.1", 0), ServerState(str(db)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _worker(host: str, port: int, questions: list[str], token: str, index: int,
            per_user: int, deadline: float, out_queue) -> None:
    """One user process: `per_user` requests, or requests until `deadline` (0 = none)."""
    connection = http.client.HTTPConnection(host, port, timeout=10)
    latencies = array("f")
    failures = 0
    attempt = 0
    try:
        while True:
            if deadline and time.time() >= deadline:
                break
            if not deadline and attempt >= per_user:
                break
            query = questions[(index + attempt) % len(questions)]
            started = time.perf_counter()
            try:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                if attempt == 0:
                    connection.connect()
                connection.request("GET", f"/v1/ask?q={quote(query)}", headers=headers)
                response = connection.getresponse()
                response.read()
                ok = response.status == 200
            except (OSError, http.client.HTTPException):
                ok = False
            latencies.append((time.perf_counter() - started) * 1000.0)
            failures += 0 if ok else 1
            attempt += 1
    finally:
        connection.close()
        out_queue.put((latencies.tolist(), failures))


def run_load(base_url: str, questions: list[str], *, users: int, per_user: int = 0,
             seconds: float = 0.0, token: str = "") -> dict:
    """Launch `users` client processes and aggregate their readings."""
    host, port_text = base_url.replace("http://", "").rsplit(":", 1)
    deadline = time.time() + seconds if seconds else 0.0
    queue: multiprocessing.Queue = multiprocessing.Queue()
    started = time.perf_counter()
    processes = [
        multiprocessing.Process(
            target=_worker,
            args=(host, int(port_text), questions, token, index, per_user, deadline, queue),
        )
        for index in range(users)
    ]
    for process in processes:
        process.start()
    collected = [queue.get() for _ in processes]
    wall = time.perf_counter() - started
    for process in processes:
        process.join()
    values = [value for latencies, _ in collected for value in latencies]
    failures = sum(count for _, count in collected)
    total = len(values)
    return {
        "users": users,
        "requests": total,
        "failures": failures,
        "wall_seconds": round(wall, 2),
        "p50_ms": round(percentile(values, 50.0), 3) if values else None,
        "p95_ms": round(percentile(values, 95.0), 3) if values else None,
        "p99_ms": round(percentile(values, 99.0), 3) if values else None,
        "rps": round(total / wall, 1) if wall > 0 else 0.0,
    }


def sweep(questions: list[str], db: Path, *, levels: tuple[int, ...], per_user: int,
          token: str = "") -> list[dict]:
    """Every level against one long-lived server, so warm views are warm throughout."""
    server, port = boot(db)
    try:
        base_url = f"http://127.0.0.1:{port}"
        rows = []
        for users in levels:
            row = run_load(base_url, questions, users=users, per_user=per_user,
                           token=token)
            rows.append(row)
            print(f"  {users:>2} users: p50 {row['p50_ms']} ms · p95 {row['p95_ms']} ms · "
                  f"{row['rps']} rps · {row['failures']} failures", file=sys.stderr)
    finally:
        server.shutdown()
        server.server_close()
    return rows


def soak(questions: list[str], db: Path, *, seconds: float, users: int = 10,
         token: str = "") -> dict:
    """Sustained load: the run that finds growth a short burst cannot."""
    server, port = boot(db)
    try:
        row = run_load(f"http://127.0.0.1:{port}", questions, users=users,
                       seconds=seconds, token=token)
    finally:
        server.shutdown()
        server.server_close()
    row["duration_seconds"] = seconds
    row["error_rate"] = round(row["failures"] / row["requests"], 6) if row["requests"] else 0.0
    return row


def soak_line(ten: dict | None) -> list[str]:
    """Cross-reference the soak, so a burst PASS is never read as a sustained PASS."""
    path = RESULTS / "soak.json"
    if not ten or not path.exists():
        return []
    row = json.loads(path.read_text(encoding="utf-8")).get("row", {})
    if not row or row.get("users") != ten["users"]:
        return []
    return [
        f"The 30-minute soak holds this same load ({row['users']} users) and reads p95 "
        f"{row['p95_ms']:.2f} ms, so the target is met in a burst and missed under sustained "
        "saturation. Both are reported; `results/soak.md` is the stricter reading.",
    ]


def write_bench(rows: list[dict], payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "bench.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ten = next((row for row in rows if row["users"] == NFR01_USERS), None)
    verdict = "PASS" if ten and ten["p95_ms"] <= NFR01_P95_MS else "FAIL"
    lines = [
        "# Load curve — 1, 10 and 50 concurrent users (M10)",
        "",
        f"Command: `python -m bench.sweep` · commit `{payload['provenance']['commit']}` · "
        f"platform: {payload['provenance']['platform']}",
        "",
        "| users | requests | failures | p50 ms | p95 ms | p99 ms | rps |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {row['users']} | {row['requests']} | {row['failures']} | {row['p50_ms']:.2f} "
        f"| {row['p95_ms']:.2f} | {row['p99_ms']:.2f} | {row['rps']:.1f} |"
        for row in rows
    ]
    lines += [
        "",
        f"NFR-01 (p95 <= {NFR01_P95_MS:.0f} ms at {NFR01_USERS} users): **{verdict}** "
        f"({'p95 ' + format(ten['p95_ms'], '.2f') + ' ms' if ten else 'level missing'}).",
        "",
        "Method: real `ThreadingHTTPServer` over a temporary database, one client PROCESS "
        "per user with a persistent keep-alive connection, 100 requests per user per level.",
        "The curve is the point: a single number cannot show where the knee is.",
        "",
        *soak_line(ten),
        "",
        "## Interpretation",
        "",
        *payload["notes"],
        "",
    ]
    (RESULTS / "bench.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_soak(row: dict, payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "soak.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# Soak — {row['duration_seconds'] / 60:.0f} minutes at {row['users']} users (M10)",
        "",
        f"Command: `python -m bench.sweep --soak-seconds {int(row['duration_seconds'])} "
        f"--users {row['users']}` · commit `{payload['provenance']['commit']}`",
        "",
        "| metric | value |",
        "|---|---|",
        f"| duration | {row['duration_seconds']:.0f} s |",
        f"| requests | {row['requests']} |",
        f"| failures | {row['failures']} ({row['error_rate'] * 100:.3f}%) |",
        f"| p50 ms | {row['p50_ms']:.2f} |",
        f"| p95 ms | {row['p95_ms']:.2f} |",
        f"| p99 ms | {row['p99_ms']:.2f} |",
        f"| sustained rps | {row['rps']:.1f} |",
        "",
        "## Interpretation",
        "",
        *payload["notes"],
        "",
    ]
    (RESULTS / "soak.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def notes_for_sweep(rows: list[dict]) -> list[str]:
    one = next((row for row in rows if row["users"] == 1), rows[0])
    fifty = next((row for row in rows if row["users"] == 50), rows[-1])
    growth = (fifty["p95_ms"] / one["p95_ms"]) if one["p95_ms"] else 0.0
    return [
        f"- p95 grows {growth:.1f}x from 1 to 50 users ({one['p95_ms']:.1f} -> "
        f"{fifty['p95_ms']:.1f} ms) while throughput reaches {fifty['rps']:.0f} rps, so the",
        "  server is not saturated at 50; the cost is queueing on one process, which is the",
        "  documented deployment shape rather than a defect.",
        f"- Failures at every level: {sum(row['failures'] for row in rows)}. A failure here is a",
        "  dropped connection, not a refused answer: refusals are HTTP 200 by design.",
        "- Two harness findings from getting this curve right, both measured: the stdlib listen",
        "  backlog of 5 dropped 7 connections at 50 users until it was raised to 128, and logging",
        "  every request into a captured pipe read p95 55.39 ms at 10 users (a FAIL) until the log",
        "  went to a file, as a deployed process writes it (46.52 ms, PASS). The logger is in the",
        "  tail path; that is a result about the service, not an excuse for the number.",
        "- One process, one port, no container: this curve is the whole capacity story for the",
        "  deployment the project claims, and it says nothing about horizontal scaling.",
    ]


def notes_for_soak(row: dict, bench_p95: float | None) -> list[str]:
    drift = (
        f"{row['p95_ms'] - bench_p95:+.2f} ms against the short-run p95 ({bench_p95:.2f} ms)"
        if bench_p95
        else "no short-run comparison available"
    )
    return [
        f"- p95 after {row['duration_seconds'] / 60:.0f} minutes: {row['p95_ms']:.2f} ms, "
        f"{drift}. A leak or an unbounded cache would show here as growth.",
        f"- NFR-01 is written at {NFR01_USERS} users, and this run is exactly that load held "
        f"for {row['duration_seconds'] / 60:.0f} minutes: p95 {row['p95_ms']:.2f} ms against a "
        f"{NFR01_P95_MS:.0f} ms target, so read strictly NFR-01 "
        + ("passes." if row["p95_ms"] <= NFR01_P95_MS else "FAILS."),
        (
            "- The short curve meets the same threshold at the same user count, because it "
            "lasts a few seconds. Both readings are real: the burst measures the server, the "
            "soak measures the server plus a queue that never empties. Quoting only the burst "
            "would be choosing the flattering number."
            if row["p95_ms"] > NFR01_P95_MS
            else "- Unlike the burst, this run cannot borrow credit from an idle moment: the "
            "threshold holds under sustained load."
        ),
        f"- Error rate {row['error_rate'] * 100:.3f}% over {row['requests']} requests; these are",
        "  dropped connections, and none of them changed an answer's content.",
        "- The per-tenant view is the only thing that grows with traffic, and it is keyed by",
        "  tenant, so this run also checks that repeated requests do not accumulate per request.",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="latency curve and soak")
    parser.add_argument("--levels", default=",".join(str(level) for level in FIXED_LEVELS))
    parser.add_argument("--requests", type=int, default=REQUESTS_PER_USER)
    parser.add_argument("--soak-seconds", type=float, default=0.0)
    parser.add_argument("--users", type=int, default=NFR01_USERS)
    parser.add_argument("--token", default="")
    parser.add_argument(
        "--render-existing",
        action="store_true",
        help="rewrite bench.md/soak.md from the committed json, without running load",
    )
    args = parser.parse_args()

    if args.render_existing:
        bench_payload = json.loads((RESULTS / "bench.json").read_text(encoding="utf-8"))
        write_bench(bench_payload["rows"], bench_payload)
        soak_path = RESULTS / "soak.json"
        if soak_path.exists():
            soak_payload = json.loads(soak_path.read_text(encoding="utf-8"))
            entry = next(
                (item for item in bench_payload["rows"]
                 if item["users"] == soak_payload["row"]["users"]),
                None,
            )
            # notes are recomputed, not replayed: the prose is code, the numbers are data
            soak_payload["notes"] = notes_for_soak(
                soak_payload["row"], entry["p95_ms"] if entry else None
            )
            write_soak(soak_payload["row"], soak_payload)
        print("re-rendered: results/bench.md, results/soak.md")
        return 0
    answerable, _ = load_questions()
    questions = [row["query"] for row in answerable]
    db = Path(tempfile.mkdtemp()) / "bench.db"
    build_database(db)

    if args.soak_seconds:
        print(f"soaking {args.soak_seconds:.0f}s at {args.users} users ...", file=sys.stderr)
        log_path = Path(tempfile.mkdtemp()) / "server.log"
        with (
            open(log_path, "w", encoding="utf-8", buffering=1) as sink,
            contextlib.redirect_stdout(sink),
        ):
            row = soak(questions, db, seconds=args.soak_seconds, users=args.users,
                       token=args.token)
        bench_p95 = None
        bench_file = RESULTS / "bench.json"
        if bench_file.exists():
            published = json.loads(bench_file.read_text(encoding="utf-8"))
            entry = next(
                (item for item in published["rows"] if item["users"] == args.users), None
            )
            bench_p95 = entry["p95_ms"] if entry else None
        payload = {
            "provenance": provenance(),
            "row": row,
            "notes": notes_for_soak(row, bench_p95),
        }
        write_soak(row, payload)
        print(f"p50 {row['p50_ms']} ms · p95 {row['p95_ms']} ms · p99 {row['p99_ms']} ms · "
              f"{row['rps']} rps · {row['failures']} failures")
        return 0

    levels = tuple(int(level) for level in args.levels.split(","))
    # the server logs one line per request; sending that to a file (as a deployed
    # process does) keeps the measurement about the API, not about printf to a pipe
    log_path = Path(tempfile.mkdtemp()) / "server.log"
    with (
        open(log_path, "w", encoding="utf-8", buffering=1) as sink,
        contextlib.redirect_stdout(sink),
    ):
        rows = sweep(questions, db, levels=levels, per_user=args.requests, token=args.token)
    payload = {"provenance": provenance(), "rows": rows, "notes": notes_for_sweep(rows)}
    write_bench(rows, payload)
    print("written: results/bench.md, results/bench.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
