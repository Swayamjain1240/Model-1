# 14 — The life of one request

The load curve in `results/bench.md` says how slow the service is; it cannot say where the
time goes. This document follows a single request through the process, with the measured
per-stage breakdown in `results/trace.md` (regenerate it with
`python scripts/trace_sample.py`, which talks to the shipped server over HTTP and reads the
`timings` block the server returns in its own response).

## The stages, in order

1. **Accept and parse.** `ThreadingHTTPServer` accepts the connection (listen backlog 128 -
   it was 5, and that dropped connections at 50 users) and reads `GET /v1/ask?q=...`.
2. **Authenticate and scope.** A wrong bearer token is `401 AUTH_REQUIRED` (only when
   `ATLAS_API_TOKEN` is configured); otherwise the tenant comes from `X-Tenant`, defaulting to
   the configured tenant. From here on every read passes that tenant into the store, so a
   scoped read is a parameter, never a filter applied afterwards - an unknown tenant is a
   refusal, never a fallback to someone else's corpus.
3. **Validate.** Empty or stopword-only input is a 400 (`FR-19`), not an empty answer.
4. **Guard.** `scan(query)` runs before the index is touched. A blocked query returns
   `mode="blocked"` with no text and no citations - a deliberate refusal, not an error, and
   the cheapest path in the system because retrieval never happens.
5. **Retrieve.** The tenant's view is built once and reused: BM25 and the dense side each
   return 50 candidates, RRF fuses them by rank, the reranker reorders the fused pool, and the
   top passage plus the confidence components come back together (`diagnostics`).
   This is the shape that matters: retrieval returns *evidence and its own quality estimate*
   in one call, so the gate costs nothing extra.
6. **Gate.** `confidence >= settings.theta`, with theta owned by the encoder's score scale
   (`ADR-0004`). Failing the gate returns a refusal with the confidence attached, which is
   what makes "why was I refused?" answerable without a debugger.
7. **Extract.** Sentence selection from the winning passage only. No generation, so grounding
   is true by construction (`ADR-0003`).
8. **Serialize.** Citations and timings assembled into the JSON body. `serialize_ms` is
   measured as handler time minus the stages above - and while writing this document that
   arithmetic was found subtracting `total_ms` twice, so the field was negative. Fixed in the
   server, not in the report.

## What the numbers say

| case | total | dominant stage |
|---|---|---|
| answered | ~1.5-2.3 ms | retrieval, 80-90% of the request |
| refused by gate | ~1.2-1.4 ms | retrieval, because the gate reuses its output |
| blocked by guard | ~0.1 ms | serialization; retrieval never ran |

Three conclusions that only a trace gives you:

- **Retrieval is the cost centre**, not extraction and not serialization. Any future latency
  work belongs there (index build, candidate count), and the concurrency curve in
  `results/bench.md` is queueing on top of this same stage.
- **Refusal is not cheaper than answering by much**, because the gate runs after retrieval.
  A cheaper refusal would have to refuse *before* retrieving, which would mean guessing from
  the query alone - exactly the confident-answer failure the gate exists to prevent.
- **Blocking is 10-20x cheaper**, which is a side effect of where the guard sits. It is also
  the reason an injection attempt can never consume retrieval capacity: it is rejected before
  it can become a query.

## Failure paths in the same pipeline

- **Empty query** - 400 before any stage above (validation, not refusal).
- **Injection** - stage 4, `mode="blocked"`.
- **Low confidence** - stage 6, `mode="hybrid"`, `refused=true`, no text.
- **Generator failure** - stage 7 with the breaker open: the answer degrades to the retrieved
  passage verbatim and says `degraded=true` (`NFR-16`, measured in `results/safety.md`).
- **Bad token** - 401 before stage 4. **Unknown tenant** - a normal refusal at stage 6 with
  no citations, so a scoping bug cannot hide behind a retrieval miss or leak in an error body.
