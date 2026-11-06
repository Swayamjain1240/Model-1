# Request trace — where a millisecond goes (M10)

Three real requests through the shipped `ThreadingHTTPServer`, after two warm-up calls,
with the stage timings the server returns in its own response body. `total_ms` is the
handler's wall clock; the stages above it are its parts.

| case | retrieve | gate | extract | serialize | total |
|---|---|---|---|---|---|
| answered | 1.981 | 0.013 | 0.000 | 0.289 | 2.288 |
| refused by gate | 1.275 | 0.005 | 0.000 | 0.133 | 1.417 |
| blocked by guard | 0.000 | 0.000 | 0.000 | 0.102 | 0.106 |

## What each stage is

- `retrieve_ms` — guard already ran; BM25 + dense retrieval, RRF fusion, rerank - the whole. Largest here: 1.981 ms (answered).
- `gate_ms` — confidence from the calibrated blend, compared to `settings.theta`. Largest here: 0.013 ms (answered).
- `extract_ms` — sentence selection from the winning passage, 0 when refused or blocked. Largest here: 0.000 ms (answered).
- `serialize_ms` — remaining handler time: payload assembly and the citation snippet. Largest here: 0.289 ms (answered).

## Reading it honestly

- Refusal is not free: `gate_ms` is paid, `extract_ms` is zero, and the total is smaller
  than an answered request by exactly the extraction cost.
- The blocked case skips retrieval entirely, which is why the guard runs before the index
  is touched: an injection attempt never becomes a query.
- Retrieval dominates every case. That is the design's real cost centre, and the reason
  the M10 curve turns up with concurrency rather than with answer length.
- Retrieval is 87% of an answered request (1.981 of 2.288 ms). Refusal is cheaper, and blocking cheapest, because each skips work - not because
  either path was optimised.
- `extract_ms` rounds to 0.000 on this corpus: selecting sentences from one passage is
  cheaper than the percentile resolution of the load test, so it cannot be the reason
  for any latency number in `bench.md`.
