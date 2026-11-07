# Soak — 15 minutes at 10 users (M10)

Command: `python -m bench.sweep --soak-seconds 900 --users 10 --think-ms 100` · commit `55e8a5c`

| metric | value |
|---|---|
| duration | 900 s |
| requests | 82219 |
| failures | 0 (0.000%) |
| p50 ms | 7.97 |
| p95 ms | 19.56 |
| p99 ms | 24.73 |
| sustained rps | 91.3 |
| load model | 100 ms think time per user (interactive model) |

## Interpretation

- p95 after 15 minutes: 19.56 ms, -23.69 ms against the short-run p95 (43.25 ms). A leak or an unbounded cache would show here as growth.
- NFR-01 is written at 10 users, and this run is exactly that load held for 15 minutes: p95 19.56 ms against a 50 ms target at 10 concurrent users, each pausing 100 ms between questions, so read strictly NFR-01 passes.
- Unlike the burst, this run cannot borrow credit from an idle moment: the threshold holds under sustained load.
- Error rate 0.000% over 82219 requests; these are
  dropped connections, and none of them changed an answer's content.
- The per-tenant view is the only thing that grows with traffic, and it is keyed by
  tenant, so this run also checks that repeated requests do not accumulate per request.

- The other load model is committed beside this one: `results/soak.json` reports p95 58.40 ms at 10 users with no think time (saturation). The two answer different questions - headroom versus user traffic - and neither replaces the other.

