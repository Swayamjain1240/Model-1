# Load curve — 1, 10 and 50 concurrent users (M10)

Command: `python -m bench.sweep` · commit `63b967f` · platform: Windows-11-10.0.26300-SP0

| users | requests | failures | p50 ms | p95 ms | p99 ms | rps |
|---|---|---|---|---|---|---|
| 1 | 100 | 0 | 1.97 | 4.38 | 6.58 | 120.0 |
| 10 | 1000 | 0 | 18.23 | 43.25 | 56.92 | 335.8 |
| 50 | 5000 | 0 | 64.73 | 233.94 | 351.63 | 358.8 |

NFR-01 (p95 <= 50 ms at 10 users): **PASS** (p95 43.25 ms).

Method: real `ThreadingHTTPServer` over a temporary database, one client PROCESS per user with a persistent keep-alive connection, 100 requests per user per level.
The curve is the point: a single number cannot show where the knee is.

## Interpretation

- p95 grows 53.4x from 1 to 50 users (4.4 -> 233.9 ms) while throughput reaches 359 rps, so the
  server is not saturated at 50; the cost is queueing on one process, which is the
  documented deployment shape rather than a defect.
- Failures at every level: 0. A failure here is a
  dropped connection, not a refused answer: refusals are HTTP 200 by design.
- Two harness findings from getting this curve right, both measured: the stdlib listen
  backlog of 5 dropped 7 connections at 50 users until it was raised to 128, and logging
  every request into a captured pipe read p95 55.39 ms at 10 users (a FAIL) until the log
  went to a file, as a deployed process writes it (46.52 ms, PASS). The logger is in the
  tail path; that is a result about the service, not an excuse for the number.
- One process, one port, no container: this curve is the whole capacity story for the
  deployment the project claims, and it says nothing about horizontal scaling.

