# Load test — 10 concurrent users (M5, NFR-01)

Command: `python -m bench.load_test --users 10 --requests 30` · commit `2f792d0`

| metric | value |
|---|---|
| successful requests | 300 |
| failures | 0 |
| p50 ms | 16.05 |
| p95 ms | 37.22 |
| p99 ms | 101.55 |
| effective RPS | 216.7 |

NFR-01 target: p95 <= 50 ms at 10 concurrent users — **PASS** (dev machine, local HTTP, one persistent keep-alive connection per user, one client PROCESS per user - threaded-client stopwatches are GIL-inflated and both earlier variants are recorded below)
