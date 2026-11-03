# Atlas — Software Design Document (SwDD)

**Document ID:** ATL-SwDD-001 · **Version:** 1.0 · **Status:** design (pre-implementation)
**Related:** [System Design](04-system-design.md) · [Technical Design](06-technical-design.md)

This document is about **code**: what modules exist, what each may depend on, which types cross
boundaries, how errors travel, and how concurrency is handled. It is the document you read before
adding a file.

---

## 1. Layering and dependency rules

```
┌──────────────────────────────────────────────────────────┐
│ api.py            boundary: HTTP, validation, auth        │  may import: pipeline, schemas
├──────────────────────────────────────────────────────────┤
│ pipeline.py       orchestration of one request            │  may import: interfaces, config
├──────────────────────────────────────────────────────────┤
│ interfaces.py     Protocols: Embedder, Retriever,         │  imports nothing from above
│                   Generator, Verifier, Store              │
├──────────────────────────────────────────────────────────┤
│ retrieval.py · generate.py · store.py · guard.py          │  implementations of the Protocols
├──────────────────────────────────────────────────────────┤
│ text.py · config.py · metrics.py                          │  leaf utilities, no upward imports
└──────────────────────────────────────────────────────────┘
```

**The three rules, enforceable by an import linter:**

1. `pipeline.py` never imports a concrete implementation — it receives `Embedder`, `Generator` and
   `Retriever` through its constructor. This is why stage 2 is a swap, not a rewrite.
2. `api.py` never imports `store.py` or `retrieval.py`. All access goes through the pipeline, so
   there is exactly one place where tenancy and refusal policy are enforced.
3. `text.py` and `config.py` import nothing from the package. Leaf modules stay leaf modules.

Any PR that breaks a rule is rejected on the rule, not on taste.

---

## 2. Module responsibilities

| Module | Owns | Public surface | Explicitly not its job |
|---|---|---|---|
| `config.py` | every tunable number | `Settings`, `SETTINGS` | reading business data |
| `interfaces.py` | the seams | `Embedder`, `Retriever`, `Generator`, `Verifier`, `Passage`, `Hit`, `Citation`, `Answer` | behaviour |
| `text.py` | text→tokens, text→chunks | `tokenize`, `sentences`, `chunk_document`, `best_sentences` | scoring, storage |
| `store.py` | persistence, tenancy | `Store.upsert_document`, `list_chunks`, `stats` | ranking, formatting |
| `retrieval.py` | candidate generation + ranking | `HybridIndex.search` | deciding to refuse |
| `generate.py` | passages → cited answer | `ExtractiveGenerator.generate` | fetching more passages |
| `pipeline.py` | request flow, confidence, refusal | `Answerer.ask` | HTTP concerns |
| `api.py` | HTTP contract | FastAPI app, routes, error mapping | business rules |
| `cli.py` | operator interface | `ingest`, `ask`, `eval`, `serve`, `stats` | business rules |
| `metrics.py` | instrumentation | `REQUESTS`, `ANSWER_LATENCY`, … | formatting output |
| `verify.py` *(S2)* | claim support check | `Verifier.verify` | rewriting the answer |
| `fsm.py` *(S2)* | workflow states | `run(query) → Answer` | retrieval internals |

---

## 3. Core data types

```python
@dataclass(frozen=True)
class Passage:            # a retrieved candidate, before generation
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    score: float
    rank: int

@dataclass(frozen=True)
class Citation:           # a passage the answer actually leaned on
    chunk_id: str
    doc_id: str
    title: str
    section: str
    snippet: str          # ≤ 320 chars, safe to render

@dataclass(frozen=True)
class Answer:             # the only thing that leaves the pipeline
    query: str
    text: str
    citations: tuple[Citation, ...]
    confidence: float     # 0..1
    refused: bool
    mode: str             # dense | sparse | hybrid | hybrid_rerank
    degraded: bool        # stage 2: fallback used
    timings_ms: dict[str, float]
    trace_id: str
```

Design notes worth defending:

- **Frozen dataclasses, tuples inside.** An answer is a value; nothing downstream mutates it, which
  makes caching and logging safe by construction.
- **`citations` and `passages` are separate concepts.** Everything retrieved is a passage; only what
  the answer used becomes a citation. Conflating them is how systems end up "citing" evidence they
  never read.
- **`refused` is a field, not an exception.** Refusal is an outcome with a payload, so the API,
  the eval harness and the UI all handle it identically.
- **`timings_ms` travels with the answer.** Observability is a property of the value, not a
  side-channel bolted on later.

---

## 4. Interface contracts (the seams)

```python
class Embedder(Protocol):
    name: str
    dim: int
    def embed(self, texts: Sequence[str]) -> np.ndarray: ...      # (n, dim), L2-normalised

class Retriever(Protocol):
    def search(self, query: str, *, tenant_id: str, k: int,
               mode: str = "hybrid") -> list[Passage]: ...        # tenant_id required, no default

class Generator(Protocol):
    name: str
    def generate(self, query: str,
                 passages: Sequence[Passage]) -> tuple[str, list[Citation]]: ...

class Verifier(Protocol):                                          # stage 2
    def verify(self, answer: str, citations: Sequence[Citation]) -> "Verdict": ...
```

Preconditions and postconditions are part of the contract, not documentation folklore:

| Method | Precondition | Postcondition | On violation |
|---|---|---|---|
| `embed` | `len(texts) ≥ 0` | rows are unit-norm, dtype float32 | raises `ValueError` |
| `search` | `k ≥ 1`, tenant exists | `len(result) ≤ k`, all same tenant, sorted by score desc | raises `TenantError` if empty tenant |
| `generate` | passages non-empty and same tenant | every sentence appears in, or is supported by, a cited passage | returns `(REFUSAL_TEXT, [])` |
| `verify` | answer non-empty | verdict names the unsupported claims | — |

---

## 5. Error model

```
AtlasError
├── ConfigurationError      bad/missing settings            → 500, logged, no user detail
├── InputError              empty query, too long, bad JSON → 400 with code + message
├── TenantError             unknown tenant, no documents    → 409 / 404
└── DependencyError         store unavailable, provider down → 503 or degrade
```

Mapping rules:

- **One exception type per HTTP status**, mapped in a single `@app.exception_handler`. Handlers stay
  declarative; no route contains a `try/except` that turns errors into 200s.
- **Never leak internals.** `ConfigurationError` and unexpected exceptions return a generic message
  and a `trace_id`; details go to the log only.
- **Degradation beats failure.** `DependencyError` from a hosted provider triggers the fallback path
  and returns a valid `Answer` with `degraded=True`. Only the store being unavailable is a 5xx.

---

## 6. Concurrency model

| Concern | MVP | Stage 2 |
|---|---|---|
| HTTP | async (uvicorn, one loop) | same |
| CPU work (embed, rank) | executed in a bounded thread pool via `anyio.to_thread` | batched, same pool, sized by `settings.workers` |
| Index build | once per tenant, behind an `asyncio.Lock` (double-checked) | prebuilt at startup |
| Provider calls | none | async httpx client, one connection pool, per-request timeout |
| Cache | none | per-tenant dict + LRU, bounded; async-safe snapshots |
| Shared mutable state | index cache only | index + cache + circuit breaker |

Rules:

1. **Never block the event loop on CPU work.** A 20 ms cosine loop inside an async route is fine at
   10 concurrent users and catastrophic at 200 — so it's offloaded from the start, not after the
   load test.
2. **One lock per tenant index**, not a global one: tenant A rebuilding must not stall tenant B.
3. **Bounded queues only.** When the pool is saturated, requests wait with a timeout and then get
   `503 + Retry-After` — latency degrades predictably instead of growing without limit.

---

## 7. State and lifecycle

```
process start → settings load → store connect → (index lazy per tenant)
ingest         → upsert rows → invalidate(tenant) → next request rebuilds
delete         → soft delete → invalidate(tenant)
restart        → no persistence of index → rebuild on first request
```

`invalidate()` is deliberately coarse (whole tenant). Fine-grained invalidation is a stage-2
optimisation with a measurable target; doing it early adds cache-coherence bugs for no number.

---

## 8. Coding conventions

- Python 3.11+, type hints on every public function, `from __future__ import annotations`.
- `ruff` for lint/format, line length 100, rules `E,F,I,UP,B,SIM`.
- No global mutable state except the settings object and the metric registry.
- No `print`; structured logging via one `log = logging.getLogger("atlas.<module>")`.
- No bare `except:`; catch the narrowest type and re-raise as an `AtlasError` subclass.
- Every tunable comes from `config.py`. A literal `k=5` inline is a review rejection.
- Docstrings state *why*, not *what*: the code already says what.

---

## 9. Testing hooks

The design deliberately leaves three seams that make testing cheap:

| Hook | Enables |
|---|---|
| Inject `Generator` | test the pipeline with a stub generator, no model required |
| Inject `Store` (temp DB path) | integration tests without touching real data |
| `mode=` parameter on `search` | ablation tests, and degradation tests (`mode="sparse"`) |

Every behaviour in the SRS must be reachable through one of these hooks without mocking internals
— if a test needs `unittest.mock.patch`, the seam is in the wrong place.

---

## 10. Extension points reserved for stage 2

| Extension | Where | Impact on existing code |
|---|---|---|
| Real embeddings | new `Embedder` implementation | config value only |
| LLM generation | new `Generator` implementation | config value only |
| Grounding check | `Verifier` + one call in `pipeline` | ~10 lines |
| Workflow states | `fsm.py` replaces `pipeline.ask` body | retrieval/generate calls unchanged |
| Cache | decorator around `search` + `generate` | none |
| Metrics depth | `metrics.py` + `obs.py` | none |

If a stage-2 change requires touching more than the listed surface, that is a design defect to fix
before writing the feature.
