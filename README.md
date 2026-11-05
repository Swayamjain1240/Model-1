# Atlas — a multi-tenant knowledge assistant that refuses to guess

**Status: implementation started.** M1–M5 are complete: corpus, hand-labeled question set, the
index layer (ingest, chunking, store, hybrid retrieval), the first **measured baseline** on the
frozen set (recall@10: sparse 0.96 · hybrid 0.88 · dense 0.75, ablations in `results/`), the
**answer path** (extractive cited answers, calibrated safety-first refusal gate, theta 0.13,
`results/calibration.md`), and the **HTTP API**: `GET /v1/ask` with token auth, machine-readable
errors, four stage timings per response, one-page demo at `/`, and the NFR-01 load test
**PASS** (p95 = 37.2 ms <= 50 ms at 10 concurrent users, `results/loadtest.md`).
Handover is next (M6).

---

## The problem

Every institution already owns the answers to most of the questions it receives — in handbooks,
policy circulars, wikis and old ticket threads. What it does not own is a reliable way to retrieve
them. So the same questions get re-asked to humans, and the answers drift.

Generic search fails because it matches keywords rather than meaning. Generic chatbots fail
differently: they answer fluently whether or not a source supports the claim. Both are unusable for
policy questions, where a wrong answer has consequences.

## What Atlas does

Upload your own documents, ask a question in plain language, and get:

| Behaviour | Why it matters |
|---|---|
| An answer **built only from your documents** | The system has no outside knowledge to invent from |
| **Passage-level citations** (`[1]`, `[2]` → document + section) | Every claim can be checked by a human |
| **Refusal** when the evidence is weak | "I don't know" is a feature; a confident wrong answer is not |
| **Escalation** to a person when confidence is low | The system assists the decision, it does not make it |
| **Strict tenant separation** | One organisation's documents can never surface in another's answers |

## What this project is actually about

The chatbot is the demo. The point is that its behaviour is **measured, explainable and
reproducible**:

- a hand-labeled question set with known correct documents, so retrieval quality is a number, not an opinion;
- an ablation table showing what each architectural choice (hybrid retrieval, reranking) actually bought;
- per-stage timings, so a latency regression has an address instead of a vague feeling;
- a committed report file for every claim, stating the machine, corpus and commit that produced it.

A design decision without a measurement attached is treated as unfinished work.

## Architecture (planned)

```
documents (*.md)
      │
      ▼
  parse → structure-aware chunking → two indexes
      │                                ├── sparse (BM25, keyword)
      │                                └── dense  (vectors, meaning)
      ▼
   SQLite (tenant-partitioned)
      │
user ─┴─▶ API ─▶ guard ─▶ retrieve top-50 ─▶ fuse (RRF) ─▶ rerank top-20
                                                                │
                                                                ▼
                                            confidence gate ──▶ answer + citations
                                                    │
                                                    └──────────▶ refuse / escalate
```

Ingest and query are separate paths that share a store. The query path never writes, which is what
makes its latency and safety analysable on their own.

## Metrics this project will report

Targets, not results. Each one is produced by a script and written to a committed report before it
appears anywhere else.

| Dimension | Metric | Measured by |
|---|---|---|
| Retrieval | recall@10, precision@5, nDCG@10, MRR | hand-labeled question set |
| Retrieval | hybrid vs. single-retriever uplift | ablation table, same question set |
| Behaviour | refusal accuracy on unanswerable questions | held-out unanswerable subset |
| Grounding | citation coverage; unsupported-claim rate | verifier + sampled manual audit |
| Performance | p50 / p95 / p99, throughput, error rate | staged load test |
| Safety | prompt-injection block rate, cross-tenant leaks | adversarial suites in CI |
| Cost | tokens per query | instrumented counters |

**First results exist** and live in `results/eval_report.md` with provenance (machine, commit,
corpus) and regeneration command. The headline, so anyone can check it in 10 seconds:
recall@10 on the 24 answerable queries is **0.96 (sparse) / 0.88 (hybrid) / 0.75 (dense)**; hybrid
is currently *worse than sparse alone* (FR-11 not yet met, recorded with query-level evidence in
`results/fr11_diagnosis.md`). The M4 calibration report (`results/calibration.md`) shows the
stand-in scores overlap between answerable and unanswerable queries, so the gate is set
safety-first (theta 0.13, zero false accepts, refusal accuracy 1.00) — the answer rate recovers
when stage-2 embeddings separate the scores. Later changes re-run the same frozen set and report
themselves as deltas against `results/baseline.json`.

## Repository layout

Now:```
README.md
Makefile                              corpus / limits / test targets (ATL-EDD-001 §2)
pyproject.toml                        package, ruff, pytest configuration
corpus/campus/                        18 policy documents (the measured source of truth)
eval/golden_set.jsonl                 hand-labeled question set (frozen)
eval/README.md                        schema, frozen rule, targets
src/atlas/
├── config.py · interfaces.py        every tunable · the stage-2 seams
├── text/{tokenize,chunk}.py         deterministic tokens · structure-aware chunking
├── store.py                         SQLite; idempotent, tenant-scoped
├── retrieval/{sparse,dense,fuse,rerank,hybrid}.py    BM25 · hashed TF-IDF · RRF · blend
├── answer.py                        gate → extract → cite, or refuse (M4)
├── server.py                        /v1/ask JSON API, stdlib only (M5)
└── cli.py                           ingest · ask · stats · serve
tests/                                unit, contract and integration (pytest)
web/demo.html                         the one-page demo served at /
bench/load_test.py                    NFR-01 concurrent load test
results/                              committed evidence: eval_report, calibration,
                                      fr11_diagnosis, latency, loadtest, robustness
docs/
├── … 12 design documents (01–12) …
├── 13-handover-runbook.md           how to run, prove, and extend (M6)
scripts/check_corpus.py               corpus gate
scripts/check_limits.py               200-line ceiling gate
.github/workflows/ci.yml              lint → size ceiling → tests → corpus → eval gate
```

Later, when the MVP lands:

```
src/atlas/         config · text · store · retrieval · generate · pipeline · api · cli
results/           committed evidence: eval_report.md, ablation tables
tests/             unit · contract · integration
```

## Run the API (60-second demo)

```bash
python -m atlas.cli serve                  # default dev server on 127.0.0.1:8070
# with auth:  ATLAS_API_TOKEN=mytoken python -m atlas.cli serve
curl "http://127.0.0.1:8070/v1/ask?q=What%20is%20the%20minimum%20attendance" \
     -H "Authorization: Bearer mytoken"
# or open http://127.0.0.1:8070/ for the one-page demo
```

Every answer is a verbatim span with its citation or an explicit refusal (theta 0.13 gate);
wrong-token requests get `401 AUTH_REQUIRED`; empty/stopword-only queries get
`400 INPUT_INVALID` (FR-19). The concurrent load test: start the server, then run
`python -m bench.load_test --token mytoken` (results committed in `results/loadtest.md`).

## Roadmap

**MVP** — six steps, each ending in something measurable:

1. Corpus + hand-labeled question set (the measuring instrument)
2. Ingest + hybrid index (sparse + dense, fused)
3. Answer path: citations, and refusal when evidence is weak
4. Eval harness → recall@10, precision@5, refusal accuracy
5. One HTTP endpoint + one page (demonstrable in 60 seconds)
6. README with the measured baseline

**After the MVP** — each layer reported as a delta against that baseline:

- real embedding model + trained reranker (retrieval quality)
- LLM generation + claim-level grounding verifier (faithfulness, cost)
- explicit workflow states: route → rewrite → retrieve → rerank → verify → answer/refuse/escalate
- safety: tenant isolation in the data layer, roles, PII masking, injection suite
- performance: batching, cache, circuit breaker, load tests, soak test
- operations: metrics dashboard, CI quality gate, runbook, decision records

## Design constraints

- **No containers, no orchestration.** One process, one port, one command. Operations come from
  metrics, an automated quality gate and a written runbook — not from a Dockerfile nobody can
  explain in an interview.
- **Local-first and offline-capable.** The core system runs on a laptop with no API key. Hosted
  models are an upgrade, not a requirement.
- **Boring dependencies.** SQLite, FastAPI, numpy. Complexity is spent on retrieval design and
  measurement, not on the stack.

## Documentation

| # | Document | What it answers |
|---|---|---|
| 01 | [Problem & Solution](docs/01-problem-and-solution.md) | why this exists, and what success means in numbers |
| 02 | [Deliverables & Resume Output](docs/02-deliverables-and-resume-output.md) | what the finished project consists of, and the evidence each claim carries |
| 03 | [Build Plan](docs/03-build-plan.md) | workflow, architecture, folder structure, definition of done |
| 04 | [System Design](docs/04-system-design.md) | components, boundaries, runtime view, SLOs, failure modes |
| 05 | [Software Design](docs/05-software-design.md) | modules, layering rules, types, error model, concurrency |
| 06 | [Technical Design](docs/06-technical-design.md) | algorithms: chunking, BM25, RRF, reranking, confidence gate |
| 07 | [Requirements (SRS)](docs/07-software-requirements.md) | testable functional and non-functional requirements |
| 08 | [Architecture](docs/08-architecture.md) | drivers, views, quality scenarios, ADR register, limits |
| 09 | [Project Plan](docs/09-project-plan.md) | work packages, milestones, risks, commit policy |
| 10 | [Engineering Design](docs/10-engineering-design.md) | build, test, CI, logging, metrics, release, runbook |
| 11 | [RFC-0001](docs/11-rfc-0001-mvp-retrieval-and-refusal.md) | the proposal for hybrid retrieval + refusal, with alternatives |
| 12 | [Solution Design](docs/12-solution-design.md) | the problem in business terms, journeys, cost, rollout |

## Status

Design (M0), the measuring instrument (M1), the index layer (M2), the measured baseline (M3),
the calibrated answer path (M4), the HTTP API with its load test (M5) and the handover proof
(M6) are complete; every number lives in `results/`. The FR-28 proof is re-runnable by anyone:
`python scripts/repro_clone.py` materialises a clean HEAD clone in a fresh venv, re-ingests,
re-evaluates and demos the live API, then compares against the committed baseline —
latest receipt: recall@10 0.8750 = 0.8750, refusal accuracy 1.0000 = 1.0000, **PASS**
(`results/handover.md`). The runbook (`docs/13-handover-runbook.md`) states the limitations
openly: single node, single process, not deployed, answer rate limited by the calibrated gate
until stage-2 embeddings.
