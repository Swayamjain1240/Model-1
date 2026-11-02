# Atlas — Build Plan: Workflow, Design, Architecture, Folder Structure

**Status:** plan (nothing built yet) · **Read after:** [01](01-problem-and-solution.md) · [02](02-deliverables-and-resume-output.md)

This is the "how do we actually build it" document. It is written so that each section can be
read on its own: the plain-language version first, then the detail.

Three constraints shape everything below:

1. **No Docker, no Kubernetes.** One process, one port, one command. The operations story comes
   from metrics, an eval gate and a runbook — not from containers.
2. **Every stage must produce a number.** If a piece of code doesn't move a metric or make the
   demo work, it doesn't go in the MVP.
3. **The upgrade must not be a rewrite.** The MVP is built with three swappable seams, so stage 2
   replaces *implementations*, not the pipeline.

---

## 1. Design principles (the five rules)

These are the rules to hold in your head. Everything else is detail.

| # | Rule | What it means in practice |
|---|---|---|
| 1 | **Build the ruler before the thing** | Corpus + golden set first. Without it, every later decision is taste. |
| 2 | **Freeze the measuring instrument** | Once the golden set exists, it doesn't change casually. When you tune the system, the ruler must not move with it — otherwise the "improvement" is fiction. |
| 3 | **One number at a time** | Each stage ends with exactly one headline number (recall@10, then faithfulness, then p95). Not six at once. |
| 4 | **Failure is a designed state, not an exception** | "Refuse", "degrade", "escalate" are normal outcomes with their own code paths — not `try/except: return 500`. |
| 5 | **Boring tech, sharp seams** | SQLite, FastAPI, numpy, one HTML page. The intelligence lives in *where the boundaries are*, not in exotic dependencies. |

Rule 5 is what makes a project look industrial. Interviewers are not impressed by a stack; they
are impressed by code where changing the embedding model touches exactly one file.

---

## 2. Architecture

### 2.1 System context — two separate paths

The single most important structural decision: **ingest and query are different paths that share a
store, and neither one does the other's job.**

```
                    ┌─────────────────────────── OFFLINE (CLI) ──────────────────────────┐
  corpus/*.md  ──▶  │  cli ingest → parse → chunk → write rows → rebuild in-memory index │
                    └───────────────────────────────┬───────────────────────────────────┘
                                                    │ writes
                                                    ▼
                                           ┌──────────────────┐
                                           │  SQLite          │  documents · chunks
                                           │  data/atlas.db   │  (tenant_id on every row)
                                           └────────┬─────────┘
                                                    │ reads (tenant-filtered)
                    ┌───────────────────────────────▼─────────────── ONLINE (HTTP) ──────┐
  user ──▶ POST /v1/ask ──▶ api.py ──▶ pipeline.py ──▶ retrieval.py ──▶ generate ──▶ JSON │
                    └────────────────────────────────────────────────────────────────────┘
```

Why this matters: the query path is **read-only**, so it can be reasoned about for latency and
safety in isolation. Ingest can be slow; answering cannot. Mixing them is the classic reason a
"simple RAG app" can't hit a latency target later.

### 2.2 Request lifecycle — nine steps, each timed

```
 1. validate        length, empty query, tenant resolved        ~0.2 ms
 2. embed query     hashed vector (stage 2: real embedding)     ~1–3 ms
 3. sparse search   BM25 over postings → top 50                 ~1–4 ms
 4. dense search    cosine over matrix → top 50                 ~1–3 ms
 5. fuse            Reciprocal Rank Fusion (rank-based)         <0.5 ms
 6. rerank          MVP: coverage blend. stage 2: real model    ~1 ms / ~30 ms
 7. confidence gate top score + coverage → answer or refuse     <0.5 ms
 8. generate        extractive sentences + citations            ~1–2 ms
 9. respond         answer, citations, confidence, timings      <1 ms
```

Two reasons to write it down this way:

- **You know where the time goes before you optimize.** When p95 is bad in stage 2, the answer is
  "step 8 is 700 ms because it's an LLM call", not "the system is slow".
- **The confidence gate is a real component, not an `if` at the end.** It's the difference between
  a system that refuses and a system that hallucinates.

### 2.3 Stage 2 shape (what changes, and what doesn't)

```
MVP:      query ─▶ retrieve ─▶ (rerank-lite) ─▶ gate ─▶ extractive ─▶ answer

Stage 2:  query ─▶ GUARD ─▶ CACHE? ─▶ ROUTE ─▶ REWRITE ─▶ retrieve ─▶ RERANK
                                                              │
                                                              ▼
                                                        GENERATE (LLM)
                                                              │
                                                              ▼
                                                        VERIFY ──fail──▶ retry once
                                                              │              │
                                                            pass             ▼
                                                              ▼        REFUSE / ESCALATE
                                                           answer
```

The MVP pipeline becomes the `RETRIEVE → RERANK → GENERATE` segment verbatim. The new work is
the states around it. That's why the MVP is not throwaway code.

---

## 3. The three seams (how to build this "industrially")

Interfaces you design on day one, because they are what stage 2 replaces:

```python
# atlas/interfaces.py — the only places stage 2 is allowed to swap behaviour

class Embedder(Protocol):
    name: str
    dim: int
    def embed(self, texts: list[str]) -> np.ndarray: ...      # MVP: hashed TF-IDF
                                                              # stage 2: bge/e5 + batch API

class Generator(Protocol):
    name: str
    def generate(self, query: str, passages: list[Passage]) -> tuple[str, list[Citation]]: ...
                                                              # MVP: extractive
                                                              # stage 2: LLM + prompt template

class Retriever(Protocol):
    def search(self, query: str, *, tenant_id: str, k: int) -> list[Hit]: ...
                                                              # MVP: HybridIndex (in-memory)
                                                              # stage 2: vector store + BM25 service
```

Three rules about seams:

- **`tenant_id` is a required keyword argument on every `search`.** No default, ever. A caller
  physically cannot forget it — which is how tenancy stays a security property instead of a
  convention.
- **No module imports a concrete implementation from another module.** `pipeline.py` receives an
  `Embedder`/`Generator`, it doesn't construct one. That is what makes stage 2 a swap.
- **Every implementation exposes `name`.** It gets written into the eval report, so every number
  is traceable to the exact code path that produced it.

---

## 4. Folder structure

Annotated. `[MVP]` ships in stage 1, `[S2]` is added in stage 2 and must not appear earlier.

```
model 1/
├── README.md                     [MVP] number, machine, one reproduce command, demo screenshot
├── Makefile                      [MVP] setup · ingest · eval · serve · test  (the whole interface)
├── pyproject.toml                [MVP] deps + ruff/pytest config
├── .env.example                  [MVP] variable NAMES only — never values
├── .gitignore                    [MVP] .venv, data/, __pycache__, .env
│
├── corpus/                       [MVP] the input documents, versioned like code
│   └── campus/
│       ├── grading-and-cgpa.md
│       ├── attendance-policy.md
│       └── ... (~18 files)
│
├── src/atlas/
│   ├── __init__.py               [MVP]
│   ├── config.py                 [MVP] EVERY tunable value lives here (k, thresholds, budgets)
│   ├── interfaces.py             [MVP] the three Protocols from §3
│   ├── text.py                   [MVP] tokenise · sentences · structure-aware chunking
│   ├── store.py                  [MVP] SQLite; tenant-scoped reads; idempotent upsert
│   ├── retrieval.py              [MVP] BM25 + hashed dense + RRF + rerank-lite
│   ├── generate.py               [MVP] extractive generator (grounded by construction)
│   ├── pipeline.py               [MVP] guard → retrieve → gate → generate → respond
│   ├── metrics.py                [MVP] Prometheus counters/histograms
│   ├── api.py                    [MVP] /v1/ask · /v1/documents · /health · /metrics · /
│   ├── cli.py                    [MVP] ingest · ask · eval · serve · stats
│   ├── web/index.html            [MVP] one page: ask box, answer, citations, timings
│   ├── rerank.py                 [S2]  trained cross-encoder reranker
│   ├── fsm.py                    [S2]  explicit workflow states, budgets, retries
│   ├── guard.py                  [S2]  PII masking, injection detection, policy checks
│   ├── verify.py                 [S2]  claim-level grounding verifier
│   ├── cache.py                  [S2]  exact + semantic cache, tenant-namespaced, TTL
│   └── obs.py                    [S2]  span tracer, trace lookup, per-stage histograms
│
├── eval/
│   ├── golden_set.jsonl          [MVP] one JSON object per line (schema in §7)
│   ├── run_eval.py               [MVP] runs all modes, writes results/, prints the table
│   └── attacks.jsonl             [S2]  ~40 injection / exfiltration probes
│
├── results/                      [MVP] committed evidence — this directory IS the deliverable
│   ├── eval_report.md
│   └── eval_report.json
│
├── tests/
│   ├── test_text.py              [MVP] chunker never loses text; overlap behaves
│   ├── test_store.py             [MVP] idempotent ingest; tenant isolation
│   ├── test_retrieval.py         [MVP] known query → known document in top 3
│   ├── test_pipeline.py          [MVP] citations valid; refusal path; timing keys present
│   └── test_guard.py             [S2]  injection suite, PII, cross-tenant probes
│
├── scripts/
│   ├── make_corpus.py            [MVP] writes corpus/campus/*.md (deterministic)
│   └── run.ps1                   [MVP] one-command local server (replaces Docker)
│
├── bench/
│   └── load_test.py              [S2]  staged concurrency, percentiles, soak mode
│
├── docs/
│   ├── 01-problem-and-solution.md
│   ├── 02-deliverables-and-resume-output.md
│   ├── 03-build-plan.md          ← this file
│   ├── ARCHITECTURE.md           [MVP] diagrams + failure matrix (exported for interviews)
│   ├── EVALUATION.md             [MVP] metric definitions + labeling protocol
│   ├── RUNBOOK.md                [S2]  "slow / wrong / down" → what to check
│   └── adr/                      [S2]  one file per consequential decision
│
└── .github/workflows/ci.yml      [MVP] lint → tests → eval gate (fails on >2pt recall drop)
```

Two structural notes:

- **`results/` is committed, `data/` is not.** The database is a build artifact and gets rebuilt by
  `make ingest`; the reports are evidence and belong in git.
- **`config.py` holds every number.** If a `k=5` is typed inline somewhere, that's a bug, because
  the eval sweep can no longer find it.

**Current disk state:** 8 of these modules already exist as untested scaffolding
(`config, text, store, retrieval, llm, pipeline, metrics, __init__`) from an earlier attempt, plus
empty `eval/ scripts/ tests/ corpus/ data/ results/`. Treat them as a draft: review each against
this plan, rename `llm.py → generate.py`, add `interfaces.py`, and rewrite where the design
changed. Nothing has been run or verified.

---

## 5. Build workflow (the order of work, and why)

Six steps for the MVP. Each step ends with something you can see, and one thing you can measure.

| Step | Build | You can now… | Produces |
|---|---|---|---|
| **1** | `corpus/` + `eval/golden_set.jsonl` | read the questions your system must answer | 18 docs, ~30 labeled queries, 6 unanswerable |
| **2** | `text.py` + `store.py` + `cli ingest` | put documents in and see chunks come out | chunk count, avg tokens/chunk |
| **3** | `retrieval.py` + `eval/run_eval.py` | run 30 questions and get recall@10 per mode | **the baseline number** (the MVP's reason to exist) |
| **4** | `generate.py` + `pipeline.py` | get a cited answer, or an honest refusal | citation coverage, refusal accuracy |
| **5** | `api.py` + `web/index.html` | type a question in a browser and see the answer | demo works end to end |
| **6** | `README.md` + CI + `Makefile` | hand the repo to a stranger | reproduce command, eval gate |

Why this order and not "build the API first":

- Step 3 before step 4 means retrieval quality is measured **without** generation quality muddling
  it. If you build generation first, you cannot tell whether a bad answer came from bad retrieval
  or bad writing — and that ambiguity is what makes people tune the wrong thing for a week.
- Step 5 last means the UI never becomes a place where logic hides.

### The daily loop

```
1. write a failing test for one behaviour      (5 min)
2. implement until it passes                   (bulk of time)
3. run `make eval` and compare to the last run (1 min)
4. commit only if the numbers didn't regress   (1 min)
```

Step 4 is the discipline that produces the resume. A commit that drops recall@10 without a stated
reason gets reverted, not explained away.

### Git workflow

- One branch per stage: `stage-1-corpus`, `stage-2-index`, `stage-3-eval`…
- Commit messages in the imperative, one concern each: `add structure-aware chunker with 1-paragraph overlap`.
- Tag the MVP: `v0.1-mvp`. Tag each stage-2 layer: `v0.2-embeddings`, `v0.3-workflow`…
- `main` only ever contains a state where `make eval` passes.

---

## 6. Data model

```
documents
  doc_id       PK        stable id (filename stem) — citations point here
  tenant_id    NOT NULL  enforced on every read path
  title        NOT NULL  shown in citations
  checksum     NOT NULL  makes re-ingest idempotent
  ingested_at
  version                soft-delete / supersede support later

chunks
  chunk_id     PK        f"{doc_id}::{ordinal}" — citable, stable per version
  doc_id       FK
  tenant_id    NOT NULL  duplicated on purpose: filtering never requires a join
  section      NOT NULL  heading path → makes citations readable ("Attendance §Condonation")
  ordinal      NOT NULL  preserves document order for overlap logic
  text, n_tokens
```

Four decisions embedded here, each defensible in an interview:

- **`tenant_id` is duplicated on `chunks`.** Denormalised on purpose: tenant filtering is on the
  hot path, and a join there is both slower and easier to forget.
- **`checksum` makes ingest idempotent.** Running `make ingest` twice changes nothing. Without this,
  every rebuild silently duplicates chunks and your eval numbers drift for no visible reason.
- **`doc_id` is the citation unit, `chunk_id` the evidence unit.** Users read documents; the
  verifier checks passages.
- **`section` is stored, not inferred.** "According to Placement Eligibility §Backlogs" is a
  citation a human can check; chunk-47 is not.

---

## 7. Contracts (what the API and the eval file look like)

### `POST /v1/ask`

```jsonc
// request
{ "query": "how many attempts do I get for a backlog paper?", "tenant_id": "campus" }

// response
{
  "trace_id": "a1b2c3d4e5f6",
  "answer": "A student may attempt a supplementary examination ... [1]",
  "citations": [
    { "chunk_id": "backlog-and-reappear::0", "doc_id": "backlog-and-reappear",
      "title": "Backlog and Reappear Policy", "section": "Attempts",
      "snippet": "..." }
  ],
  "confidence": 0.61,
  "refused": false,
  "retrieval_mode": "hybrid_rerank",
  "generator": "offline-extractive-v1",
  "timings_ms": { "retrieve": 3.1, "score": 0.2, "generate": 1.4, "total": 5.9 }
}
```

The `timings_ms` object and `trace_id` are not decoration — they are the contract that makes the
next stage debuggable, and they cost nothing to add now.

### `eval/golden_set.jsonl`

```jsonc
{"id": "q01", "query": "what CGPA keeps my merit scholarship?", "relevant": ["merit-scholarship"], "answerable": true, "reference": "8.5 CGPA with 85% attendance"}
{"id": "q25", "query": "what is the hostel mess menu next week?", "relevant": [], "answerable": false, "reference": null}
{"id": "q30", "query": "what is the wifi password for the library?", "relevant": [], "answerable": false, "reference": null}
```

Rules that keep the evaluation honest:

- **Label documents, not vibes.** `relevant` is a list of `doc_id`s, so recall is computable without
  a human in the loop.
- **Include paraphrases with zero shared keywords** ("can I drop a subject after the deadline" vs a
  document about a "withdrawal window"). These are the queries that prove hybrid retrieval earns
  its complexity — and the ones a keyword-only system fails.
- **Include unanswerable questions.** Without them, refusal accuracy is undefined, and refusal is
  half the product.
- **Never label a query after seeing what the system returned.** That's how eval sets become
  self-fulfilling.

---

## 8. Testing strategy (four levels, and what not to test)

| Level | What it checks | Example | Where |
|---|---|---|---|
| Unit | pure functions, no I/O | chunker never drops a sentence; overlap is respected | `tests/test_text.py` |
| Contract | the seams behave as promised | `search()` returns ≤k hits, all for one tenant; citations reference retrieved chunks | `tests/test_retrieval.py`, `test_pipeline.py` |
| Integration | ingest → ask, end to end, on a temp DB | a question about a known doc returns that doc's chunk id | `tests/test_pipeline.py` |
| Evaluation | quality on the golden set | recall@10 ≥ threshold; CI fails otherwise | `make eval` in CI |

What **not** to test: LLM phrasing, exact answer strings, latency thresholds on a shared machine
(flaky and meaningless), or the HTML page's markup.

The eval gate is the only "test" that matters for quality, and it is also the thing almost nobody
builds. That's why it's in the MVP and not the upgrade.

---

## 9. Failure matrix (designed behaviour, not exceptions)

| Situation | Behaviour | User sees |
|---|---|---|
| Empty / stopword-only query | 400 before touching the index | "Please ask a question with more detail." |
| Tenant has no documents | 409 with a clear code | "This workspace has no documents yet." |
| Best match below confidence threshold | normal response, `refused: true` | "I couldn't find this in the documents." |
| Query longer than limit | truncated at `max_query_chars`, logged | normal answer + truncation flag |
| Index not built yet | lazy build on first request | slightly slower first request only |
| SQLite locked (concurrent write) | retry once with backoff, then 503 | "Try again in a moment." |
| LLM timeout *(stage 2)* | circuit opens → extractive fallback | answer labelled `degraded: true` |
| Injection detected *(stage 2)* | request refused, spans recorded | "This request was blocked." |

Every row here is a code path you can point at. "It has no error handling" is the fastest way to
lose an interview; this table is the answer.

---

## 10. Configuration and secrets

- One `Settings` object, constructed once, injected everywhere. No `os.environ` calls outside
  `config.py`.
- Variable *names* documented in `.env.example`; values never committed.
- `.env` is gitignored from the first commit — not after the first mistake.
- Model/provider keys (stage 2) are read at startup, never logged, never echoed in error messages.

---

## 11. Definition of done for the MVP

- [ ] `make setup && make ingest && make eval` works from a clean clone
- [ ] `results/eval_report.md` states corpus size, golden-set size, machine and timestamp
- [ ] Eval reports all three modes (keyword-only, vector-only, hybrid) side by side
- [ ] Refusal accuracy reported separately on the unanswerable subset
- [ ] Every answer carries at least one valid citation, or `refused: true`
- [ ] Tenant isolation covered by a test that must fail loudly if broken
- [ ] `/v1/ask` returns `timings_ms` and `trace_id`
- [ ] One page loads, asks a question, renders answer + citations
- [ ] README opens with the measured number and the reproduce command
- [ ] `make test` and `make lint` are green, and CI runs all three

Ten boxes. When all ten are ticked, the MVP is finished and the upgrade has a baseline to beat.

---

## 12. Document map

| Read | When |
|---|---|
| `01-problem-and-solution.md` | to remember *why* any of this exists |
| `02-deliverables-and-resume-output.md` | when filling in resume numbers, or rehearsing interviews |
| `03-build-plan.md` (this) | while writing code |
| `ARCHITECTURE.md` | when someone asks how the pieces fit (and to show in interviews) |
| `EVALUATION.md` | before touching the golden set — it defines what the numbers mean |
| `RUNBOOK.md` | stage 2, when you need to diagnose something under time pressure |

---

## 13. What happens at the boundary (MVP → upgrade)

The upgrade begins with these five moves, in this order:

1. Freeze the MVP: tag `v0.1-mvp`, record `results/eval_report.md` as the baseline.
2. Swap `Embedder` for a real model (one file, one config value). Re-run eval. **Report the delta.**
3. Swap `Generator` for an LLM, add `verify.py` because generative output needs it. Report
   faithfulness and tokens/query.
4. Replace `pipeline.py` internals with `fsm.py`. The retrieve→rerank→generate segment is copied,
   not rewritten.
5. Add `guard.py`, `cache.py`, `bench/`, `docs/RUNBOOK.md` — each with its own number.

If any of those five turns into "and now I rewrite everything", the seams in §3 were wrong, and that
is worth knowing at step 2 rather than step 5.
