# Atlas — Software Requirements Specification (SRS)

**Document ID:** ATL-SRS-001 · **Version:** 1.0 · **Status:** design (pre-implementation)
**Related:** [System Design](04-system-design.md) · [Architecture](08-architecture.md)

Requirements are written so that each one is **testable**: given a defined input, there is an
observable outcome and a way to check it. A requirement that cannot fail a test is not a requirement,
it is a wish.

---

## 1. Purpose, scope, definitions

**Purpose.** Define what the Atlas system must do, and how well, before implementation begins.

**Scope.** A single-node, multi-tenant document question-answering service with citations, refusal,
and a measurement harness. Excludes model training, multi-modal input, and container orchestration.

| Term | Definition |
|---|---|
| passage | a chunk of a document, the unit of retrieval and citation |
| golden set | hand-labeled questions with known relevant documents and an answerable/unanswerable flag |
| recall@k | fraction of the known relevant documents present in the top-k results |
| refused | the system declined to answer because evidence was insufficient |
| confidence | 0–1 score blending embedding similarity and idf-weighted coverage |
| degraded | answered without the primary generation path (fallback used) |
| tenant | an isolated document workspace |

---

## 2. Actors and environment

| ID | Assumption / constraint |
|---|---|
| C-1 | Deployment is a single process on one machine. No containers, no orchestration. |
| C-2 | Python 3.11+, CPU-only; no GPU required for the MVP. |
| C-3 | The MVP must run with **no network access and no API key**. |
| C-4 | Corpus is markdown text; PDF ingestion is a stage-2 extension. |
| C-5 | Traffic is interactive and low-volume; batch ingestion may be slow. |
| C-6 | One operator (developer/owner); no on-call rotation, so the system must fail loudly in logs. |

---

## 3. Functional requirements

### 3.1 Ingestion

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-01 | Ingest a markdown document into a named tenant | after ingest, `stats` reports +1 document and ≥1 chunk |
| FR-02 | Ingest must be idempotent | running the same ingest twice leaves document and chunk counts unchanged |
| FR-03 | Changed content must replace prior chunks | editing a document and re-ingesting leaves no orphan chunks for that doc |
| FR-04 | Chunking must preserve all text | concatenated chunk text contains every paragraph of the source |
| FR-05 | Each chunk must record its section heading | every citation displays a section, or `root` when the document has no headings |
| FR-06 | Ingest must be rejected without a tenant | ingest with an empty tenant returns 400 and writes nothing |

### 3.2 Retrieval

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-07 | Support three retrieval modes: sparse, dense, hybrid | `mode=` accepts each and returns ranked passages |
| FR-08 | Retrieval must be tenant-scoped | a query under tenant A never returns a passage from tenant B (automated test) |
| FR-09 | Retrieval must return at most k passages, sorted | `len(results) ≤ k` and scores are non-increasing |
| FR-10 | A question about a known document must retrieve that document | for each labeled query, the relevant doc appears in the top 10 for hybrid mode |
| FR-11 | Hybrid must not be worse than both single retrievers | recall@10(hybrid) ≥ max(recall@10(sparse), recall@10(dense)) on the golden set |
| FR-12 | Retrieval must be deterministic | identical corpus + query yields identical ranked output across runs |

### 3.3 Answering

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-13 | Produce an answer composed only of sourced text | every sentence in the MVP answer appears in a cited passage |
| FR-14 | Attach ≥1 citation to every non-refused answer | `refused == false ⇒ len(citations) ≥ 1` |
| FR-15 | Citations must reference retrievable evidence | each `chunk_id` exists in the store for the same tenant |
| FR-16 | Refuse when confidence is below the configured threshold | `refused == true` and `citations == []` for those cases |
| FR-17 | Refuse unanswerable questions | refusal accuracy ≥ 0.95 on the unanswerable subset |
| FR-18 | Answer length must be bounded | ≤ `max_sentences` sentences (default 4) |
| FR-19 | Empty or stopword-only query must be rejected | 400 with a machine-readable error code |

### 3.4 Service interface

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-20 | Expose `POST /v1/ask`, `POST /v1/documents`, `GET /health`, `GET /metrics` | endpoints respond with documented schemas |
| FR-21 | Every response must carry `trace_id` and per-stage `timings_ms` | fields present and non-empty on 100% of responses |
| FR-22 | A human-usable page must exist | loading `/` shows an input, an answer area and citations; usable without docs |
| FR-23 | Errors must be structured | non-2xx responses contain `code` and `message`, never a stack trace |

### 3.5 Evaluation and operations

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-24 | An eval command must compute recall@k, precision@k, MRR, nDCG@10 | `make eval` writes `results/eval_report.md` and `.json` |
| FR-25 | Eval must report each retrieval mode side by side | report contains a row per mode, same query set |
| FR-26 | Eval reports must record provenance | report states corpus size, golden-set size, machine, timestamp, generator name |
| FR-27 | CI must fail on quality regression | a >2-point drop in recall@10 fails the build |
| FR-28 | The system must run from a single command | `make setup && make ingest && make eval && make serve` works on a clean clone |

---

## 4. Non-functional requirements

| ID | Category | Requirement | Target / criterion | Verification |
|---|---|---|---|---|
| NFR-01 | Performance | p95 end-to-end latency, MVP | ≤ 50 ms at 10 concurrent users on the dev machine | load test |
| NFR-02 | Performance | p95 latency, stage 2 (with LLM) | ≤ 1200 ms at 20 concurrent users | load test |
| NFR-03 | Scalability | documented limit | 10k chunks / single node; beyond that, ANN storage required | benchmark note |
| NFR-04 | Quality | recall@10 | ≥ 0.90 on the golden set | eval harness |
| NFR-05 | Quality | precision@5 | ≥ 0.80 | eval harness |
| NFR-06 | Quality | faithfulness (stage 2, generative) | ≥ 0.90 | verifier + audit |
| NFR-07 | Reliability | crash-free operation under load | 0 unhandled exceptions in a 30-min soak | soak test |
| NFR-08 | Reliability | degradation on provider failure | valid answer with `degraded=true`, never 5xx | fault injection |
| NFR-09 | Security | tenant isolation | 0 cross-tenant leaks | automated probe suite |
| NFR-10 | Security | prompt injection (stage 2) | ≥ 95% of ~40 attacks blocked | adversarial suite |
| NFR-11 | Privacy | PII in logs | 0 raw emails/phones/card numbers in log output | log audit test |
| NFR-12 | Maintainability | module independence | pipeline imports no concrete implementation | import linter in CI |
| NFR-13 | Maintainability | test coverage of behaviour | every FR-* has ≥1 automated test | traceability check |
| NFR-14 | Observability | per-stage timing visibility | every response exposes ≥4 stage timings | API contract test |
| NFR-15 | Reproducibility | identical results | same corpus + query ⇒ identical eval report (modulo timestamps) | run twice, diff |
| NFR-16 | Operability | documented failure handling | every row of the system failure matrix has a code path and a test | review |
| NFR-17 | Portability | no required network | MVP fully functional offline | run with network disabled |
| NFR-18 | Cost | zero marginal cost in MVP | ₹0 per query without a provider key | design review |
| NFR-19 | Documentation | every number traceable | each reported metric names the command that produced it | README + results audit |
| NFR-20 | Simplicity | dependency budget | ≤ 8 runtime dependencies, each justified in the README | dependency review |

---

## 5. Traceability matrix

| Requirement group | Design section | Test(s) | Reported metric |
|---|---|---|---|
| FR-01…FR-06 (ingest) | SDD §4, TDD §2 | `test_store.py` | chunk count, tokens/chunk |
| FR-07…FR-12 (retrieval) | TDD §3–§6 | `test_retrieval.py` | recall@10, precision@5, nDCG |
| FR-13…FR-19 (answering) | TDD §7–§8 | `test_pipeline.py` | citation coverage, refusal accuracy |
| FR-20…FR-23 (API) | SwDD §5 | `test_api.py` | contract checks in CI |
| FR-24…FR-27 (eval) | SDD §5, TDD §9 | `run_eval.py` | `results/eval_report.md` |
| FR-28 (reproducibility) | Build plan §5 | CI job | green pipeline on clean clone |
| NFR-01…NFR-03 (perf) | SDD §5 | `bench/load_test.py` | p50/p95/p99, RPS |
| NFR-09, NFR-10 (security) | SDD §11 | `test_guard.py`, probes | leak count, block rate |
| NFR-12, NFR-13 (structure) | SwDD §1, §9 | import linter, coverage | CI status |

**Rule:** a requirement with no test row is not implemented, regardless of whether the code exists.

---

## 6. Explicitly out of scope (v1)

- Training or fine-tuning any model.
- Image, audio or scanned-PDF understanding.
- Writing actions (creating tickets, sending email) on the user's behalf.
- Multi-node deployment, horizontal scaling, or zero-downtime upgrades.
- Real-time collaborative editing of the corpus.
- A public multi-tenant SaaS with billing.

---

## 7. Assumptions and open questions

| # | Item | Impact if wrong |
|---|---|---|
| A-1 | Corpus fits in memory (≤10k chunks) | architecture changes to ANN storage |
| A-2 | Questions are single-turn and self-contained | multi-turn requires conversation state in the pipeline |
| A-3 | Documents are markdown/text | PDF parsing becomes an additional component |
| A-4 | Evaluators accept document-level relevance labels | chunk-level labels needed for finer precision metrics |
| A-5 | One operator can act on logs within hours | needs alerting, which is out of scope for v1 |

---

## 8. Verification method summary

| Requirement class | Method | Artefact |
|---|---|---|
| Functional | automated tests + eval harness | `make test`, `results/eval_report.md` |
| Performance | staged load test, 30-min soak | `results/bench_report.md` |
| Security | adversarial suites in CI | `results/safety_report.md` |
| Reproducibility | clean-clone run in CI | CI log |

A requirement is "met" only when its artefact exists in `results/` or the CI log. Statements in a
README without a corresponding artefact do not count as verification.
