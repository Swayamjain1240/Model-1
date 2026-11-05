# Latency benchmark (M5, NFR-01 evidence)

Command: `python -m eval.latency` · commit `2f792d0` · 5 timed passes after 1 warmup pas, in-process (no HTTP hop)

| measurement | n | mean ms | p50 ms | p95 ms |
|---|---|---|---|---|
| sparse | 120 | 0.077 | 0.065 | 0.159 |
| dense | 120 | 0.142 | 0.111 | 0.279 |
| hybrid | 120 | 0.600 | 0.548 | 0.962 |
| answer_e2e | 120 | 1.041 | 0.881 | 1.922 |

Concurrent load and the API hop are covered separately by `python -m bench.load_test` (10 workers, NFR-01).
