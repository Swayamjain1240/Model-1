# Soak — 30 minutes at 10 users (M10)

Command: `python -m bench.sweep --soak-seconds 1800 --users 10` · commit `87a5222`

| metric | value |
|---|---|
| duration | 1800 s |
| requests | 628983 |
| failures | 0 (0.000%) |
| p50 ms | 24.59 |
| p95 ms | 58.40 |
| p99 ms | 83.55 |
| sustained rps | 349.4 |
| load model | no think time (saturation model: the same users, offering far more load) |

## Interpretation

- p95 after 30 minutes: 58.40 ms, +15.14 ms against the short-run p95 (43.25 ms). A leak or an unbounded cache would show here as growth.
- NFR-01 is written at 10 users, and this run is exactly that load held for 30 minutes: p95 58.40 ms against a 50 ms target at 10 concurrent users, with no pause between requests (a saturation test), so read strictly NFR-01 FAILS.
- The short curve meets the same threshold at the same user count, because it lasts a few seconds. Both readings are real: the burst measures the server, the soak measures the server plus a queue that never empties. Quoting only the burst would be choosing the flattering number.
- Error rate 0.000% over 628983 requests; these are
  dropped connections, and none of them changed an answer's content.
- The per-tenant view is the only thing that grows with traffic, and it is keyed by
  tenant, so this run also checks that repeated requests do not accumulate per request.

- The other load model is committed beside this one: `results/soak-interactive.json` reports p95 19.56 ms at 10 users with 100 ms think time. The two answer different questions - headroom versus user traffic - and neither replaces the other.

