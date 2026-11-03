# Atlas — a multi-tenant knowledge assistant that refuses to guess

**Status: design phase.** The MVP is not implemented yet. This repository currently contains the
design and build documents; the code arrives in the next stage.

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

**No results exist yet.** When they do, they will be reported here with the machine and corpus that
produced them — never invented.

## Repository layout

Now:

```
README.md
docs/
├── 01-problem-and-solution.md            the problem, the design, the success criteria
├── 02-deliverables-and-resume-output.md  what ships, and how it is presented
├── 03-build-plan.md                      workflow, architecture, folder structure
├── 04-system-design.md                   components, boundaries, runtime, SLOs
├── 05-software-design.md                 modules, layering, types, errors, concurrency
├── 06-technical-design.md                algorithms: chunking, BM25, RRF, reranking
├── 07-software-requirements.md           testable requirements + acceptance criteria
├── 08-architecture.md                    drivers, views, quality scenarios, ADRs
├── 09-project-plan.md                    work packages, milestones, commit policy
├── 10-engineering-design.md              build, test, CI, logging, release, runbook
├── 11-rfc-0001-mvp-retrieval-and-refusal.md   proposal with alternatives and rollback
└── 12-solution-design.md                 problem → journeys → cost → rollout
```

Later, when the MVP lands:

```
corpus/            documents (as code)
src/atlas/         config · text · store · retrieval · generate · pipeline · api · cli
eval/              golden_set.jsonl · run_eval.py
results/           committed evidence: eval_report.md, ablation tables
tests/             unit · contract · integration
scripts/           corpus generator · one-command local server
```

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

Design complete, implementation not started. Nothing in this repository is benchmarked, deployed or
production-hardened, and it will not be described as if it were.
