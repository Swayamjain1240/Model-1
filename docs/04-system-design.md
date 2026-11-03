# Atlas — System Design Document (SDD)

**Document ID:** ATL-SDD-001 · **Version:** 1.0 · **Status:** design (pre-implementation)
**Related:** [SRS](07-software-requirements.md) · [Architecture](08-architecture.md) · [Technical Design](06-technical-design.md)

---

## 1. Purpose and scope

This document describes **the system as a whole**: its boundaries, the components inside it, how
they communicate, and what it promises under load and failure. It does not describe algorithms
(see the Technical Design Document) or module internals (see the Software Design Document).

**In scope:** the answer service, the ingest path, storage, evaluation harness, and the operational
surface required to run them.

**Out of scope:** model training, multi-modal inputs, cross-region deployment, container
orchestration (deliberately excluded — see §9).

---

## 2. Actors and external systems

| Actor / system | Interaction | Trust level |
|---|---|---|
| End user (student / employee) | asks questions, reads answers and citations | untrusted input |
| Knowledge owner (admin) | uploads and retires documents | authenticated, writes |
| Evaluator / developer | runs the harness, reads reports | trusted, offline |
| Hosted model provider *(stage 2 only)* | receives prompts, returns text | external, rate-limited |
| CI system | runs lint, tests and the quality gate | trusted |

---

## 3. System context

```
        ┌───────────┐        ┌──────────────┐
        │  End user │        │ Knowledge    │
        │ (browser) │        │ owner (CLI)  │
        └─────┬─────┘        └──────┬───────┘
              │ HTTPS               │ ingest
              ▼                     ▼
      ┌───────────────────────────────────────┐
      │            ATLAS SYSTEM               │
      │  ┌─────────┐      ┌────────────────┐  │
      │  │ Answer  │◀────▶│  Ingest path   │  │
      │  │ path    │      └───────┬────────┘  │
      │  └────┬────┘              │           │
      │       └────────┬──────────┘           │
      │                ▼                      │
      │        ┌──────────────┐               │
      │        │ Document     │               │
      │        │ store        │               │
      │        └──────────────┘               │
      └───────────────┬───────────────────────┘
                      │ (stage 2, optional)
                      ▼
              ┌────────────────┐
              │ Model provider │
              └────────────────┘
```

Key context property: **with no model provider configured, the system is fully functional** (offline
extractive answers). The provider is an optional accelerator, never a dependency of the core loop.

---

## 4. Logical decomposition

| # | Component | Responsibility | Owns | Must not |
|---|---|---|---|---|
| 1 | Boundary (API) | validate, authenticate, rate-limit, serialise | HTTP contract | contain business logic |
| 2 | Pipeline | orchestrate one request: guard → retrieve → gate → answer | request flow | touch storage directly |
| 3 | Retriever | find candidate passages for a query | ranking | decide about refusal |
| 4 | Generator | turn passages into a cited answer | wording | fetch extra evidence |
| 5 | Document store | persist documents, chunks, tenant labels | durability, isolation | rank or summarise |
| 6 | Ingest | parse → chunk → write → reindex | corpus lifecycle | serve requests |
| 7 | Evaluation harness | measure quality on the golden set | ground truth, reports | run in the request path |
| 8 | Telemetry | counters, histograms, timings | observability | affect behaviour |

Two invariants follow from this table and are worth enforcing in code review:

- **The answer path performs no writes.** It is safe to reason about latency and tenancy in isolation.
- **Ingest never answers.** A slow ingest can never degrade a live request.

---

## 5. Runtime view — answering a question

```
1  user   → API            POST /v1/ask {query}
2  API    → guard          length, empty-input, tenant resolution          ← reject/annotate
3  API    → pipeline       ask(query, tenant)
4  pipeline→ retriever     search(query, tenant, k=50)                     ← read-only
5  retriever→ store        list_chunks(tenant)  (cached index; first call builds it)
6  retriever→ pipeline     top-50 fused → top-20 reranked → top-5
7  pipeline→ pipeline      confidence = f(top cosine, idf coverage)
8  pipeline→ generator     if confidence ≥ θ: generate(query, passages)    else: refuse
9  pipeline→ API           Answer{text, citations, confidence, timings}
10 API    → user           JSON / rendered page
```

| Step | Typical cost (MVP) | Budget | If exceeded |
|---|---|---|---|
| 2 | <1 ms | 5 ms | reject request |
| 4–6 | 2–8 ms | 50 ms | return degraded (sparse-only) |
| 7 | <1 ms | 2 ms | treat as low confidence → refuse |
| 8 | 1–3 ms (extractive) / 200–1500 ms (stage 2 LLM) | 2 s | stage 2: degrade to extractive |
| 9–10 | <2 ms | 10 ms | — |

---

## 6. Data view

Three entities, one store, single node (SQLite, WAL mode):

```
documents(doc_id PK, tenant_id, title, source, checksum, ingested_at)
   └── chunks(chunk_id PK, doc_id FK, tenant_id, section, ordinal, text, n_tokens)
```

Rules that make this safe to operate:

- `tenant_id` is stored on **both** tables; filtering never requires a join.
- `checksum` makes ingest idempotent, so a rebuild cannot silently double the corpus.
- `chunk_id` is stable per document version, so citations recorded in logs remain resolvable.
- Deletes are soft in stage 2 (version column), so old citations stay auditable.

Retention: documents and chunks live as long as the workspace; telemetry is in-process only in the
MVP (counters reset on restart), persisted in stage 2.

---

## 7. Deployment topology

```
     laptop / single VM
  ┌─────────────────────────────────────┐
  │  uvicorn (1 process, N threads)     │
  │    ├── FastAPI app  :8000           │
  │    └── in-memory index (per tenant) │
  │                                     │
  │  data/atlas.db      (SQLite, file)  │
  │  corpus/*.md        (source docs)   │
  └─────────────────────────────────────┘
```

- **One process, one port.** No containers, no orchestration, no service mesh.
- **Scale-up, not scale-out.** The index is in memory per process; a second process would serve
  stale data, so horizontal scaling is explicitly *not* supported in the MVP. Saying this out loud
  is part of the design, not a gap in it.
- Restart is fast (<2 s) because the index rebuilds from SQLite on first request.

---

## 8. Service level objectives (targets, to be measured)

| Attribute | Target | Measured by |
|---|---|---|
| Availability (single node) | best-effort; no SLA claimed in MVP | uptime log |
| Latency p95 | ≤ 50 ms MVP · ≤ 1.2 s stage 2 | load test, per stage |
| Quality | recall@10 ≥ 0.90 · faithfulness ≥ 0.90 | golden set |
| Refusal accuracy | ≥ 0.95 on unanswerable subset | golden set |
| Safety | 0 cross-tenant leaks · ≥95% injection block | adversarial suites |
| Degradation | provider failure ⇒ labelled fallback, never 5xx | fault injection |

Numbers are targets until `results/` contains a report that says otherwise.

---

## 9. Deliberate non-goals (architectural)

| Not doing | Why | What we do instead |
|---|---|---|
| Containers / Kubernetes | adds ops surface without adding engineering insight at this scale | one process + one command + runbook |
| Microservices | one team, one deployable; splitting would be theatre | modular monolith with strict internal boundaries |
| Horizontal scaling | in-memory index makes multi-process serving incorrect | documented single-node limit + upgrade path |
| Model training | the problem is retrieval and grounding, not pre-training | pluggable `Embedder` for hosted models |

---

## 10. Failure modes and behaviour

| Failure | Detection | System behaviour | User impact |
|---|---|---|---|
| Corpus empty for tenant | store count = 0 | 409, no index built | clear message |
| Query not answerable | confidence < θ | `refused: true`, no citations | "couldn't find" + escalation hint |
| Index build failure | exception during build | 503 + structured log, old index retained if any | retry |
| SQLite write lock | `database is locked` | one retry with backoff | none or brief latency |
| Process restart | — | index rebuilds lazily | first request slower |
| Provider 429 / timeout *(stage 2)* | error rate threshold | circuit opens → extractive fallback | degraded answer, labelled |
| Prompt injection *(stage 2)* | detector score | request refused, recorded | blocked message |

Every row corresponds to a code path in the Software Design Document; there is no unhandled case
labelled "should not happen".

---

## 11. Security boundaries

- **Tenant boundary** enforced in the store layer (required argument), not in prompts.
- **Authentication** is stage 2; the MVP uses a header-based tenant claim and documents the gap.
- **Input trust:** user text is data. Retrieved passages are data with provenance tags. Neither is
  ever treated as instruction.
- **Secrets:** environment only, never logged, never in the repo (`.env` gitignored from commit one).

---

## 12. Open items carried into stage 2

1. Async offload policy for hosted embeddings (threadpool sizing vs. batching).
2. Whether reranking can meet the latency budget on CPU without quantisation.
3. Index persistence format (pickle vs. on-disk ANN) once the corpus exceeds memory.
4. Multi-process serving requires moving the index out of process — deferred, documented.
