# Atlas — a multi-tenant knowledge assistant that refuses to guess

**Status: MVP and stage 2 complete except FR-11; two independent holdout sets say the refusal
gate does not generalise (M11, replicated in M13), and M14 added a second signal that recovers
part of it: v3 refusal 0.50 → 0.67 with no answer lost, still open as FR-16; M15 removed the
topic-list answer (5 → 0) and measured the ranking defect it cannot reach (top-1 passage from the
labelled document 39/48).** M1–M6 built the measured MVP: corpus, hand-labeled
question set, index layer (ingest, chunking, store, hybrid retrieval), the first **measured
baseline** on the frozen set (recall@10: sparse 0.96 · hybrid 0.88 · dense 0.75), the **answer
path** (extractive cited answers, safety-first refusal gate), the **HTTP API** (`GET /v1/ask`,
token auth, machine-readable errors, four stage timings, one-page demo at `/`, NFR-01 load test
**PASS** p95 = 37.2 ms at 10 users), and the **handover proof** (clean-clone reproduction,
`results/handover.md`).

M7 replaced the hashed stand-in with a **real pretrained encoder** (`potion-base-8M`, 256-d,
CPU-only) and re-measured the same frozen set: **dense recall@10 0.75 → 1.00**, and the gate's
honest **answer rate 0.29 → 0.96** at refusal accuracy 1.00 — measured on the same six
unanswerable questions theta was fitted to, which M11 shows was optimistic — with theta
re-calibrated per score scale (0.31, `results/embeddings.md`). The remaining open requirement is **FR-11**: with a strong
dense side, hybrid 0.92 still trails dense alone 1.00, and the ablation shows the hand-tuned
rerank blend — not fusion — is what demotes correct chunks. That is the next layer's job.

M8 answered that with a **trained reranker**: weights fitted on 12 documents and judged on the
6 never seen. Pointwise and pairwise fits both scored **0.90 held-out against dense-only 1.00**,
so nothing was adopted — the weights file is committed and marked unadopted, and the loader
refuses to use it. FR-11 stays open with its evidence (`results/rerank.md`) instead of a claim.

M9 added the safety layer and measured it through the live server: **40/40 injection attacks
refused** (98% by the guard alone, the rest by the gate), **0 cross-tenant leaks** across 12
probes against a tenant holding a byte-identical copy of a campus document, **0 raw personal
values** in 133 captured log lines, and **3/3 degraded answers** with generation failing on
purpose (`results/safety.md`).

M10 closed the operations layer without a container: a **latency curve** at 1/10/50 users
(**NFR-01 PASS in a burst**: p95 43.25 ms at 10 users, 0 failures, 359 rps at 50) and a
30-minute soak that **misses the same target** — p95 58.40 ms with 0 failures over 628,983
requests — because sustained saturation leaves a queue that a few-second burst never builds.
Both readings are committed; the stricter one is the one quoted next to the target. A third
run answers the requirement as written: the same ten users with 100 ms of think time between
questions hold **p95 19.56 ms for 15 minutes** at 91 rps, 0 failures
(`results/soak-interactive.md`) - so NFR-01 passes for user traffic and fails at
saturation, and the dashboard shows both. a
**dashboard generated from the committed reports** (`dashboard.html`), **six decision records**
with their rejected alternatives (`docs/adr/`), a request **waterfall** that caught a negative
`serialize_ms` shipping since M5, and a **demonstrated CI-gate failure** so the quality gate is
a control rather than a claim (`results/ci_gate.md`). The **ablation finally has a control arm**
(`results/ablation.md`): five configurations × two encoders, one change per row, each rate with
n=24 and a 95% Wilson interval — which is what turns "the reranker is the bottleneck" from an
inference into a measurement, and shows the blend only *helps* while the encoder is the hashed
stand-in.

M11 asked the obvious question about all of the above: do the numbers survive a question set the
design never saw? `eval/golden_set_v2.jsonl` appends 12 answerable questions (each asking a fact
v1 does not ask) and 6 unanswerable ones, with the rule written down before the run — **fit on
v1, decide on v2** (`results/holdout.md`). Retrieval survives: every configuration reaches
recall@10 1.0000 on v2, so fusion misses nothing, though that also means v2 cannot rank the
rankers. The **refusal gate does not survive**: accuracy **1.0000 on v1, 0.1667 on v2**, because
the two classes overlap on the only feature it uses - the weakest answerable v2 question scores
0.279 and the strongest unanswerable one 0.434. No theta separates them; the best reachable v2
refusal accuracy is 0.50, and it costs half the answerable questions. Theta is deliberately *not*
moved, because tuning on the holdout is what makes a holdout worthless. The same run also shows
the fusion weights are inert (all six settings score identically), so they stay at 1.0/1.0.

M13 then asked whether v2 was unlucky. `eval/golden_set_v3.jsonl` appends a third set - 12 fresh
answerable questions and 6 unanswerable ones drawn from topics the corpus does not cover, half of
them deliberately close to what it does cover - and scores it for the first time
(`results/holdout.md`, decisions now read off v3). Retrieval saturates again (recall@10 1.0000 for
all five configurations), so it still cannot rank rankers. **The gate replicates its failure:**
refusal accuracy 1.0000 on v1, 0.1667 on v2, **0.5000 on v3**, with the weakest answerable v3
question at 0.322 against the strongest unanswerable one at 0.497 - overlapping, not separated.
The best refusal accuracy any theta can reach on v3 is 0.83, and it costs answerable questions.
So the v1 figure was in-sample, and the fix has to be a second signal rather than a threshold.

M14 built that second signal. Confidence only ever inspects the passage it already chose; the
new signal asks a different question - **does the tenant's corpus contain these words at all?**
A request is refused when at least 50% of its content terms occur nowhere in the corpus and at
least two of them do, with the floor fitted on v1 (the highest novelty among its answerable
questions is 0.40) and the decision read off v3 (`results/support.md`). It moved refusal accuracy
0.5000 → 0.6667 on v3 and 0.1667 → 0.3333 on v2 while refusing **no answerable question on any
set**. That is one question on each six-question set: an improvement, not a repair. The two
remaining failures have different causes and are named in the report - one is dilution by known
words, the other is a question whose every word the corpus uses ("sports scholarship"), which no
vocabulary check can refute. FR-16 therefore stays open, and the refusal now says which of the two
reasons applied (`refusal_reason`, `unseen`).

M15 looked at what the answer *said*, rather than whether it was retrieved or refused. Reading the
UI showed a failure no aggregate metric had caught: every policy document opens with a list of its
own sections ("Limits on the number of attempts for a failed course, carry-forward rules and load
restrictions for students with backlogs"), and because that line names every topic in the document
it covers more query words than the sentence holding the rule. The fix is structural rather than
fitted: a sentence of three or more items with no digit and no finite verb is a heading echo, and it
is disqualified only when another sentence in the passage also matches a query term
(`src/atlas/select.py`). Heading-echo answers went **5 → 0** across the three frozen sets, and all
five replacements carry a number or a finite verb (`results/answer_selection.md`). The same report
keeps the other half of the finding separate: the top-1 passage comes from the labelled document
for only 18 of v1's 24 questions, 10 of 12 on v2 and 11 of 12 on v3 - a ranking defect, i.e. FR-11,
which no sentence-scoring rule can reach.

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
| **An escalation signal** when confidence is low | A refusal carries `confidence` and `trace_id`, so a UI or queue can route it to a person; there is no ticket-system integration, and this line says so rather than implying one |
| **Strict tenant separation** | One organisation's documents can never surface in another's answers |

## What this project is actually about

The chatbot is the demo. The point is that its behaviour is **measured, explainable and
reproducible**:

- a hand-labeled question set with known correct documents, so retrieval quality is a number, not an opinion;
- an ablation table showing what each architectural choice (hybrid retrieval, reranking) actually bought;
- per-stage timings, so a latency regression has an address instead of a vague feeling;
- a committed report file for every claim, stating the machine, corpus and commit that produced it.

A design decision without a measurement attached is treated as unfinished work.

## Architecture

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
| Behaviour | refusal accuracy on unanswerable questions | unanswerable subset — 1.00 on v1, **0.17 on the appended v2 set** (M11) |
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
safety-first (theta 0.13, zero false accepts, refusal accuracy 1.00 on v1 — M11 measures
0.17 on questions the threshold was not fitted to) — the answer rate recovers
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
├── retrieval/{embedder,trained}.py  encoder seam · pretrained static encoder + disk cache
├── retrieval/learned.py             trained reranker + adoption gate (M8)
├── guard.py · breaker.py · obs.py   input guard · circuit breaker · log redaction (M9)
├── answer.py                        gate → extract → cite, or refuse (M4)
├── support.py                       second refusal signal: vocabulary novelty (M14)
├── select.py                        sentence selection + heading-echo guard (M15)
├── server.py                        /v1/ask JSON API, stdlib only (M5)
└── cli.py                           ingest · ask · stats · serve
tests/                                unit, contract and integration (pytest)
web/demo.html                         the one-page demo served at /
bench/load_test.py                    NFR-01 concurrent load test
eval/embeddings.py                    stage-2 encoder delta harness (M7)
eval/rerank_train.py                  document-held-out reranker training (M8)
eval/safety.py                        injection, tenancy, log and degraded suite (M9)
eval/answer_selection.py              heading-echo guard, measured on all three frozen sets (M15)
bench/sweep.py                        latency curve at 1/10/50 users, plus a soak (M10)
scripts/dashboard.py                  results/*.json -> dashboard.html (M10)
scripts/trace_sample.py               one request's stage waterfall (M10)
scripts/ci_gate_demo.py               proves the quality gate fails when it should (M10)
results/                              committed evidence: eval_report, calibration,
                                      fr11_diagnosis, ablation, latency, loadtest,
                                      robustness, embeddings, rerank, safety, bench,
                                      soak, trace, ci_gate, handover, holdout, support,
                                      answer_selection
dashboard.html                        the dashboard: opens from disk, no server needed
docs/
├── … 12 design documents (01–12) …
├── 13-handover-runbook.md           how to run, prove, and extend (M6)
├── 14-request-trace.md              the life of one request, with measured stages (M10)
├── adr/                             nine decision records, each with what it rejected (M10, M14, M15)
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
# the trained encoder is what the calibrated gate was measured on:
ATLAS_EMBEDDER=potion-base-8M python -m atlas.cli serve   # default port 8070
# with auth:  ATLAS_API_TOKEN=mytoken python -m atlas.cli serve
curl "http://127.0.0.1:8070/v1/ask?q=What%20is%20the%20minimum%20attendance" \
     -H "Authorization: Bearer mytoken"
# or open http://127.0.0.1:8070/ for the page
```

Every answer is a verbatim span with its citation or an explicit refusal - below `theta`, or for
a topic whose vocabulary the corpus does not carry (`refusal_reason` says which, and `unseen`
names the words); wrong-token requests get `401 AUTH_REQUIRED`; empty/stopword-only queries get
`400 INPUT_INVALID` (FR-19). The concurrent load test: start the server, then run
`python -m bench.load_test --token mytoken` (results committed in `results/loadtest.md`).

The page (`web/demo.html`, no build step, no external assets) is the product surface: a question
box, the answer as a verbatim span, **the confidence drawn against the refusal line the running
process actually uses** (read from `GET /v1/healthz`, so a hashed process shows 0.13 and a trained
one 0.31), then the source document and text, then the stage timings and the trace id. A refusal
is a red card that says so, with the same bar showing why it refused - and when the reason is
unknown vocabulary rather than a low score, it says that instead of blaming the line. Screenshots:
`docs/ui-answer.png`, `docs/ui-refusal.png`.

Two limits the page cannot hide. There are no CORS headers, so the page has to be served by the
same process (it is, at `GET /`). And a page served by the API cannot hold a secret, so with
`ATLAS_API_TOKEN` set the browser gets `401 AUTH_REQUIRED` and the page explains why - real browser
auth needs a session layer, which is not built.

## Reproduce every number

Every claim in this README comes from a target that rewrites a file in `results/`:

| Command | Produces | Headline |
|---|---|---|
| `make eval` | `results/eval_report.md` | recall@10 sparse 0.96 · hybrid 0.88 · dense 0.75 (frozen set) |
| `make embed` | `results/embeddings.md` | encoder swap: dense recall@10 0.75 → 1.00, answer rate 0.29 → 0.96 |
| `make ablation` | `results/ablation.md` | five configurations × two encoders, control arm, 95% Wilson intervals |
| `make holdout` | `results/holdout.md` | two out-of-sample sets: recall holds at 1.0000, refusal accuracy 1.00 → 0.17 (v2) → 0.50 (v3) |
| `make support` | `results/support.md` | second refusal signal: v3 refusal 0.50 → 0.67, v2 0.17 → 0.33, zero answers lost on any set |
| `make answer-selection` | `results/answer_selection.md` | topic-list answers 5 → 0 on three sets; top-1 passage from the right document 18/24 · 10/12 · 11/12 |
| `python -m eval.rerank_train` | `results/rerank.md` | trained reranker 0.90 held-out vs dense 1.00 → not adopted |
| `make safety` | `results/safety.md` | 40/40 attacks refused, 0 tenant leaks, 0 PII in logs, 3/3 degraded |
| `make bench` | `results/bench.md` | NFR-01 burst PASS: p95 43.25 ms at 10 users, 359 rps at 50 |
| `make soak` | `results/soak.md` | 30 minutes at 10 users: 0 failures, but p95 58.40 ms — NFR-01 missed under sustained load |
| `make soak-interactive` | `results/soak-interactive.md` | 15 minutes at 10 users with 100 ms think time: p95 19.56 ms, 0 failures — NFR-01 met for user traffic |
| `make trace` | `results/trace.md` | per-stage waterfall: retrieval is ~87% of a request |
| `make dashboard` | `dashboard.html` | all of the above on one page, generated from the JSON |
| `make gate-demo` | `results/ci_gate.md` | the CI gate failing on purpose, exit code 1 |
| `make ci` | terminal | lint → 200-line ceiling → tests → corpus → eval gate |

## Roadmap

**MVP** — six steps, each ending in something measurable:

1. Corpus + hand-labeled question set (the measuring instrument)
2. Ingest + hybrid index (sparse + dense, fused)
3. Answer path: citations, and refusal when evidence is weak
4. Eval harness → recall@10, precision@5, refusal accuracy
5. One HTTP endpoint + one page (demonstrable in 60 seconds)
6. README with the measured baseline

**After the MVP** — each layer reported as a delta against that baseline:

- ~~real embedding model~~ **done (M7):** dense recall@10 0.75 → 1.00, answer rate 0.29 → 0.96
  (`results/embeddings.md`) — and trained reranker (retrieval quality), still open (FR-11)
- LLM generation + claim-level grounding verifier (faithfulness, cost)
- explicit workflow states: route → rewrite → retrieve → rerank → verify → answer/refuse/escalate
- ~~safety~~ **done (M9):** injection suite, tenancy probes, log redaction, degraded mode
  (`results/safety.md`) — roles and PII masking on stored text remain open
- ~~performance~~ **done (M9–M10):** circuit breaker, load curve, soak, request trace
  (`results/bench.md`, `results/trace.md`) — batching and a response cache remain open
- ~~operations~~ **done (M10):** dashboard, a quality gate demonstrated to fail, runbook,
  decision records

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
| 13 | [Handover Runbook](docs/13-handover-runbook.md) | how to run it, prove it, and extend it |
| 14 | [Request Trace](docs/14-request-trace.md) | the life of one request, stage by stage |
| — | [Decision records](docs/adr/) | six decisions, each with the alternative it rejected and the report behind it |

## Status

Design (M0), the measuring instrument (M1), the index layer (M2), the measured baseline (M3),
the calibrated answer path (M4), the HTTP API with its load test (M5) and the handover proof
(M6) are complete; every number lives in `results/`. The FR-28 proof is re-runnable by anyone:
`python scripts/repro_clone.py` materialises a clean HEAD clone in a fresh venv, re-ingests,
re-evaluates and demos the live API, then compares against the committed baseline —
latest receipt: recall@10 0.8750 = 0.8750, refusal accuracy 1.0000 = 1.0000, **PASS**
(`results/handover.md`).

Stage 2 has started: M7 swaps the encoder behind the existing seam — one config value — and
reports the delta instead of asserting it (`results/embeddings.md`, regenerate with
`python -m eval.embeddings`). Selecting it is deliberate, because the hashed stand-in is what
keeps the default offline (C-3, NFR-17): `ATLAS_EMBEDDER=potion-base-8M python -m atlas.cli ask …`,
and every embedded text is cached on disk so a warm run needs no network. The runbook
(`docs/13-handover-runbook.md`) states the limitations openly: single node, single process, not
deployed, FR-11 still unmet, and a 0.011 gate margin measured on six unanswerable questions.

Stage 2 is now closed except for that one requirement. What the four stages changed, in one
line each: the encoder made the gate usable (M7), the trained reranker was built, measured and
**not shipped** because it lost out of sample (M8), the safety layer turned into numbers instead
of intentions (M9), and the operations layer became a curve, a soak, a dashboard and a gate that
provably fails (M10). FR-11's evidence is `results/rerank.md` and `results/fr11_diagnosis.md`:
the hand-tuned rerank blend, not fusion, is what demotes correct chunks — replacing it with a
learned model did not beat dense-only on held-out documents, so the honest state is *open with a
measured cause*, not *done*.
