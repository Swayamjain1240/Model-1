# Atlas — Architecture Document

**Document ID:** ATL-ARCH-001 · **Version:** 1.0 · **Status:** design (pre-implementation)
**Related:** [System Design](04-system-design.md) · [Software Design](05-software-design.md) · [SRS](07-software-requirements.md)

The System Design Document says *what the system is*. This document says *why it is shaped that
way*: the forces acting on it, the views that reveal structure, the decisions that constrained it,
and what would have to change for a different shape to be correct.

---

## 1. Architectural drivers

Ranked, because when two drivers conflict the higher one wins and the reasoning is recorded.

| Rank | Driver | Consequence |
|---|---|---|
| 1 | **Answers must be verifiable** | citations are mandatory, generation is constrained to retrieved text |
| 2 | **Refusal must be possible** | confidence is a first-class component, not a post-hoc filter |
| 3 | **Quality must be measurable** | the eval harness is part of the architecture, not tooling on the side |
| 4 | **Tenant separation must hold** | isolation is enforced in the data layer, never in a prompt |
| 5 | **Must run offline on a laptop** | deterministic local embedder, no provider dependency in the core loop |
| 6 | **Must be explainable in an interview** | boring stack, explicit state machine, no framework magic |
| 7 | Latency, cost, scale | real, but subordinate: an ungrounded fast answer is worth nothing |

Driver 7 being last is deliberate and worth saying out loud: it is the opposite of how a
demo-driven project is built, and it is why the numbers in this project are trustworthy.

---

## 2. View 1 — context

```
   ┌──────────┐   question    ┌───────────────────────────┐   optional    ┌──────────────┐
   │  User    │──────────────▶│  ATLAS                    │──────────────▶│ Model        │
   │          │◀──────────────│  (single process)         │◀──────────────│ provider     │
   └──────────┘  answer +     └────────────┬──────────────┘   (stage 2)    └──────────────┘
                  citations                 │
   ┌──────────┐   documents                │ metrics / logs
   │  Owner   │────────────────────────────┤
   │  (CLI)   │                            ▼
   └──────────┘                     ┌─────────────┐
                                    │ Operator /  │
                                    │ CI          │
                                    └─────────────┘
```

---

## 3. View 2 — container (process) view

| Container | Technology | Responsibility | Scaling |
|---|---|---|---|
| Web process | uvicorn + FastAPI | HTTP boundary, request orchestration | single process (see §7) |
| Index | numpy arrays in process memory | candidate generation | rebuilt per process |
| Database | SQLite file (WAL) | documents, chunks, tenancy | single writer |
| Web page | one static HTML file | demo surface | n/a |
| Eval harness | Python CLI | quality measurement | offline |
| CI | GitHub Actions | lint, tests, quality gate | n/a |

No message broker, no cache server, no object store. Each absence is a decision recorded in §6.

---

## 4. View 3 — component view

```
        ┌────────────────────────────────────────────────────────┐
        │ api.py                                                 │
        │  POST /v1/ask · POST /v1/documents · /health · /metrics│
        └───────────────┬────────────────────────────────────────┘
                        │ (only entry point into logic)
        ┌───────────────▼────────────────────────────────────────┐
        │ pipeline.py — one request, one path                    │
        │  guard → retrieve → rerank → confidence → generate     │
        └───┬──────────────┬──────────────┬──────────────────────┘
            │              │              │
   ┌────────▼───┐   ┌──────▼──────┐  ┌────▼────────┐
   │retrieval.py│   │ generate.py │  │ metrics.py  │
   │BM25 + dense│   │ extractive  │  │ counters    │
   │  + RRF     │   │ (S2: LLM)   │  │ histograms  │
   └────────┬───┘   └─────────────┘  └─────────────┘
            │
   ┌────────▼────────────────────────────────────┐
   │ store.py — tenant-scoped reads, idempotent  │
   │ writes                                      │
   └─────────────────────────────────────────────┘
```

Dependency direction is strictly downward; the arrow from `pipeline` to `retrieval` and `generate`
goes through `interfaces.py` (elided here for readability, enforced in code).

---

## 5. View 4 — quality attribute scenarios

Each scenario is a concrete, testable statement: stimulus → response → measure. These are the
architecture's acceptance criteria, distinct from the functional requirements.

| ID | Attribute | Scenario | Response | Measure |
|---|---|---|---|---|
| QS-1 | Performance | 20 users ask distinct questions concurrently | all answered within budget | p95 latency |
| QS-2 | Performance | 200 users send bursts | excess rejected with 503 + Retry-After | 0 timeouts > 30 s |
| QS-3 | Correctness | user asks a policy question covered by one document | that document is cited | recall@10 on golden set |
| QS-4 | Correctness | user asks about a topic absent from the corpus | system refuses, no invented answer | refusal accuracy |
| QS-5 | Security | user in tenant A names a document from tenant B | no passage from B returned | leak count = 0 |
| QS-6 | Security | document contains "ignore previous instructions" | content treated as data; no policy change | injection suite result |
| QS-7 | Availability | model provider returns 429 for 60 s | answers continue in degraded mode | 0 user-facing 5xx |
| QS-8 | Operability | latency doubles after a deploy | the slow stage is identifiable from one response | stage timing present |
| QS-9 | Modifiability | embedding model is replaced | only a config value changes | diff size ≤ 2 files |
| QS-10 | Reproducibility | evaluator reruns `make eval` on their machine | same metrics within tolerance | diff of two reports |

QS-9 is the scenario that proves the seams work. If swapping the embedder touches more than two
files, the architecture has failed its own criterion — regardless of how good recall becomes.

---

## 6. Architectural decisions (ADR index)

Full ADRs live in `docs/adr/`; this is the register. Each entry: decision → alternative rejected →
consequence accepted.

| ADR | Decision | Rejected alternative | Consequence |
|---|---|---|---|
| 0001 | Modular monolith, one process | microservices | cannot scale out; can be understood fully by one person |
| 0002 | SQLite as the store | Postgres + pgvector | no ANN search; single-writer; trivial ops |
| 0003 | Hybrid retrieval with RRF | dense-only | two indexes to keep consistent; better paraphrase recall |
| 0004 | Deterministic local embedder in MVP | hosted embeddings from day one | weaker semantics; offline reproducibility and zero cost |
| 0005 | Refusal as a first-class outcome | always answer | some answerable questions are refused |
| 0006 | Extractive generation in MVP | LLM from day one | robotic phrasing; perfect grounding; no cost |
| 0007 | Hand-rolled state machine (stage 2) | LangGraph / LlamaIndex | more code to own; every transition is observable |
| 0008 | Tenancy enforced in the store signature | tenant filter in prompt | storage API must always be threaded with tenant |
| 0009 | No containers or orchestration | Docker + compose | no industry-standard packaging; one-command run instead |
| 0010 | Eval harness before retrieval tuning | tune first, evaluate later | 2 extra days before the first feature |

ADR 0009 is recorded honestly: it is a project constraint (operator skill), not a claim that
containers are unnecessary. Reviewers respond better to a documented constraint than to a gap.

---

## 7. Explicit architectural limits

| Limit | Cause | Upgrade path |
|---|---|---|
| Single process only | in-memory index | move index behind a service / use an external vector store |
| ~10k chunks | brute-force cosine | ANN index (HNSW/IVF) |
| One writer | SQLite | Postgres with connection pooling |
| No horizontal scaling | index is process-local | shared index + stateless app tier |
| No HA | single node | replication, load balancer, health checks |
| Text-only | parser scope | PDF/OCR pipeline |

Publishing these limits is part of the architecture: a reviewer who finds an undocumented limit
assumes there are more.

---

## 8. Evolution path (MVP → stage 2 → beyond)

```
 v0.1 MVP            v0.2 quality          v0.3 workflow+safety      v0.4 scale
 ─────────           ─────────────         ─────────────────────     ─────────────
 hybrid retrieval →  real embeddings   →   FSM + guardrails      →   ANN store
 extractive gen      trained reranker      LLM + verifier            batching
 eval harness        faithfulness          cache + breaker           load tests
 single node         ablation table        injection suite           soak test
```

Each arrow is gated on a number: stage 2 does not begin until the MVP baseline report exists,
because otherwise "improvement" has no referent.

---

## 9. Risks to the architecture

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hashed embeddings make the MVP look weak | high | reviewers dismiss retrieval quality | report the limitation explicitly and show the stage-2 delta |
| Golden set too small ⇒ noisy metrics | medium | tuning chases noise | ≥150 queries in stage 2, bootstrap CIs |
| Latency budget unachievable with reranking on CPU | medium | must cut candidates | measure early; document the tradeoff rather than hide it |
| Scope creep into a general assistant | high | project never finishes | non-goals list in SRS §6 is enforced in review |
| Single-node limit feels unambitious | low | weaker resume line | state it as a documented tradeoff with a named upgrade path |

---

## 10. Glossary

| Term | Meaning |
|---|---|
| RRF | Reciprocal Rank Fusion — merges ranked lists using ranks only |
| ANN | Approximate Nearest Neighbour — trade recall for speed at scale |
| HITL | Human-in-the-loop — the escalation path |
| SLO | Service Level Objective — a target with a measurement method |
| degraded | answered via fallback because the primary path failed |
| seam | an interface designed to be replaced without touching callers |
