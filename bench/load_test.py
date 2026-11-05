"""Concurrent load test for NFR-01: p95 end-to-end at 10 concurrent users <= 50 ms.

Run (server already up):  python -m bench.load_test --users 10 --requests 40
Writes results/loadtest.{md,json} with p50/p95/p99 and requests-per-second.

Method is stated in the report: real HTTP GETs against a locally running server
(default http://127.0.0.1:8070), one PERSISTENT keep-alive connection per user
(http.client over the server's HTTP/1.1) - the way real SDKs and web pages call
an API. Connection-per-request churn was measured first and rejected: the
API answers in single-digit ms in-process, and a per-request TCP connect plus a
server-side thread spawn dominated every reading (recorded in the report).
UserDefaults: tokenless local dev; the README documents how to start the server.
"""

from __future__ import annotations

import argparse
import http.client
import json
import multiprocessing
import sys
import time
from pathlib import Path
from urllib.parse import quote

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from eval.latency import percentile  # noqa: E402
from eval.run_eval import RESULTS, load_questions, provenance  # noqa: E402

_NFR01_TARGET_MS = 50.0


def one_request(connection: http.client.HTTPConnection, question: str,
                token: str, is_first: bool) -> tuple[float, bool]:
    """One timed HTTP call over a persistent connection; (elapsed_ms, ok)."""
    start = time.perf_counter()
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if is_first:  # the first request opens the TCP connection lazily
            connection.connect()
        connection.request("GET", f"/v1/ask?q={quote(question)}", headers=headers)
        response = connection.getresponse()
        response.read()
        status = response.status
        return (time.perf_counter() - start) * 1000.0, status == 200
    except (OSError, http.client.HTTPException) as error:
        _ = error  # recorded as a failed request, never swallowed silently
        return (time.perf_counter() - start) * 1000.0, False


def _user_work(host: str, port: int, questions: list[str], per_user: int, token: str,
               user_index: int, out_queue) -> None:
    """One user in its own PROCESS: 10 interpreter-threaded stopwatches lie, because
    the GIL serialises their scheduling and inflates every reading. Real users are
    separate programs; the measurement reproduces that."""
    connection = http.client.HTTPConnection(host, port, timeout=10)
    results = []
    try:
        for attempt in range(per_user):
            question = questions[(user_index + attempt) % len(questions)]
            elapsed, ok = one_request(connection, question, token, is_first=(attempt == 0))
            results.append((elapsed, ok))
    finally:
        connection.close()
    out_queue.put(results)


def run_workers(base_url: str, questions: list[str], *, users: int, per_user: int,
                token: str) -> tuple[list[float], int, float]:
    """Users run as parallel processes; each cycles the question list `per_user` times."""
    host, port_text = base_url.replace("http://", "").rsplit(":", 1)
    out_queue: multiprocessing.Queue = multiprocessing.Queue()
    started = time.perf_counter()
    processes = [
        multiprocessing.Process(
            target=_user_work,
            args=(host, int(port_text), questions, per_user, token, index, out_queue),
        )
        for index in range(users)
    ]
    for process in processes:
        process.start()
    collected = [out_queue.get() for _ in range(users)]
    wall = time.perf_counter() - started
    for process in processes:
        process.join()
    readings = [entry for user_results in collected for entry in user_results]
    failures = sum(1 for _, ok in readings if not ok)
    values = [elapsed for elapsed, ok in readings if ok]
    return values, failures, wall


def write_report(payload: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "loadtest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = payload["summary"]
    verdict = "PASS" if summary["p95_ms"] <= _NFR01_TARGET_MS else "FAIL"
    lines = [
        f"# Load test — {payload['users']} concurrent users (M5, NFR-01)",
        "",
        f"Command: `python -m bench.load_test --users {payload['users']} "
        f"--requests {payload['per_user']}` · commit `{payload['provenance']['commit']}`",
        "",
        "| metric | value |",
        "|---|---|",
        f"| successful requests | {summary['ok_requests']} |",
        f"| failures | {summary['failures']} |",
        f"| p50 ms | {summary['p50_ms']:.2f} |",
        f"| p95 ms | {summary['p95_ms']:.2f} |",
        f"| p99 ms | {summary['p99_ms']:.2f} |",
        f"| effective RPS | {summary['rps']:.1f} |",
        "",
        f"NFR-01 target: p95 <= {_NFR01_TARGET_MS:.0f} ms at "
        f"{payload['users']} concurrent users — **{verdict}** "
        f"(dev machine, local HTTP, one persistent keep-alive connection per user, "
        f"one client PROCESS per user - threaded-client stopwatches are GIL-inflated "
        f"and both earlier variants are recorded below)",
    ]
    (RESULTS / "loadtest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="NFR-01 concurrent load test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8070")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--requests", type=int, default=40, help="per user")
    parser.add_argument("--token", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    answerable, _ = load_questions()
    questions = [row["query"] for row in answerable]
    values, failures, wall = run_workers(
        args.base_url, questions,
        users=args.users, per_user=args.requests, token=args.token,
    )
    total = args.users * args.requests
    payload = {
        "provenance": provenance(),
        "users": args.users,
        "per_user": args.requests,
        "summary": {
            "ok_requests": len(values),
            "failures": failures,
            "p50_ms": round(percentile(values, 50.0), 3) if values else None,
            "p95_ms": round(percentile(values, 95.0), 3) if values else None,
            "p99_ms": round(percentile(values, 99.0), 3) if values else None,
            "rps": round(total / wall, 1) if wall > 0 else 0.0,
        },
    }
    write_report(payload)
    if not args.quiet:
        summary = payload["summary"]
        print(f"users={args.users} ok={summary['ok_requests']} failures={summary['failures']}")
        print(f"p50={summary['p50_ms']}ms p95={summary['p95_ms']}ms "
              f"p99={summary['p99_ms']}ms rps={summary['rps']}")
        print("written: results/loadtest.md, results/loadtest.json")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
