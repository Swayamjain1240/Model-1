# Atlas — Engineering Design Document (EDD)

**Document ID:** ATL-EDD-001 · **Version:** 1.1 · **Status:** design (pre-implementation)
**Related:** [Software Design](05-software-design.md) · [Project Plan](09-project-plan.md)

How the thing is **built, tested, released and operated** — the engineering practice around the
code. This is the document that makes "it runs on my machine" stop being an answer.

---

## 1. Environments

| Environment | Purpose | Data | Configuration |
|---|---|---|---|
| local (dev) | write code, run tests | generated corpus, throwaway DB | `.env` (gitignored) |
| local (demo) | show the working system | generated corpus, real DB | `.env` |
| CI | prove the commit is sound | generated corpus, temp DB | env vars in workflow |

There is no staging or production environment in v1, and the docs say so rather than implying one.
A third environment with no users is theatre.

---

## 2. Bootstrap (the one path that must always work)

```bash
make setup      # create .venv, install pinned deps
make corpus     # generate corpus/campus/*.md
make ingest     # chunk + index into data/atlas.db
make eval       # write results/eval_report.md
make serve      # http://127.0.0.1:8000
```

Rules:

- **`make setup` is idempotent.** Running it twice must not break anything.
- **No global installs.** Everything inside `.venv`.
- **No manual steps.** If a README instruction says "now open a file and edit X", that instruction
  is a bug in the automation.

---

## 3. Configuration and secrets

Precedence: environment variable → `.env` → default in `config.py`.

| Variable | Purpose | Committed? |
|---|---|---|
| `ATLAS_DB` | database path | no (default in code) |
| `ATLAS_TENANT` | default tenant for CLI demos | no |
| `ATLAS_CHUNK_TOKENS`, `ATLAS_DIM` | tuning knobs | no |
| `ATLAS_REFUSE_THRESHOLD` | refusal gate | no |
| `ATLAS_LLM_API_KEY` *(stage 2)* | provider credential | **never** |

Policy:

- `.env.example` lists **names only**, never values.
- `.env` is gitignored by the first commit (already true).
- Startup validates required values and fails fast with a message naming the missing variable.
- Logs redact any key-like string (`sk-…`, 32+ hex chars) via a logging filter.

---

## 4. Dependency policy

- ≤ 8 runtime dependencies (NFR-20); each must justify itself in one line in the README.
- Pinned minor versions; no unpinned `>=` in the deployed path without a lockfile.
- No dependency for something the standard library does adequately.
- Adding a dependency is a design decision: recorded in the PR, and reversible.

---

## 5. Code structure and size ceilings

**Hard rule: no file under `src/` may exceed 200 lines. Enforced by CI from M1** — a
`scripts/check_limits.py` step fails the build on any violation. The fix for an oversized file is
splitting a responsibility, never compressing logic or stripping docstrings. A file that is too big
because it does two jobs is a design finding, not a formatting issue.

Target ceilings (the plan the file-splitting follows):

| File | Lines (≤) | Responsibility |
|---|---|---|
| `config.py` | 80 | every tunable number + validation |
| `interfaces.py` | 80 | Protocols + shared dataclasses |
| `text/tokenize.py` | 120 | tokens, bigrams, stopwords |
| `text/chunk.py` | 140 | chunking, section tracking |
| `retrieval/sparse.py` | 140 | BM25 scoring + inverted index |
| `retrieval/dense.py` | 120 | hashed vectors, cosine |
| `retrieval/fuse.py` | 60 | RRF |
| `retrieval/rerank.py` | 80 | coverage blend |
| `store.py` | 160 | SQLite, tenancy, idempotent ingest |
| `generate.py` | 120 | extractive answers + citations |
| `pipeline.py` | 150 | confidence, refusal, orchestration |
| `api.py` | 150 | HTTP, validation, error mapping |
| `metrics.py` | 60 | registry only |
| `cli.py` | 120 | operator commands |

Formatting is not a taste matter either: `ruff format` + `ruff check` (line length 100, rules
`E,F,I,UP,B,SIM`) run in CI, so "maintain code structure and format" is enforced by the gate, not by
memory.

---

## 6. Testing strategy

| Level | Scope | Speed | Example |
|---|---|---|---|
| unit | pure functions | ms | chunker never drops a paragraph; tokeniser folds plurals |
| contract | interfaces | ms | `search` returns ≤k, all same tenant; citations reference retrieved chunks |
| integration | ingest → ask | ~1 s | known question returns the labeled document |
| evaluation | golden set | ~10 s | recall@10 ≥ threshold, refusal accuracy ≥ threshold |

Coverage expectation: **every FR-* in the SRS has at least one automated test.** Coverage percentage
is reported but never used as a target — 100% of trivial lines is a worse signal than 70% of
branching logic.

Fixtures: a `tmp_path` SQLite database and a 3-document mini-corpus. Tests never touch `data/`.

Flakiness policy: a test that fails intermittently is deleted or fixed the same day; a quarantined
test is a lie with a date on it.

---

## 7. CI pipeline

```
┌──────────┐   ┌──────────┐   ┌───────┐   ┌──────────┐   ┌──────────────┐   ┌───────────┐
│ checkout │──▶│  ruff    │──▶│ limit │──▶│pytest ut │──▶│pytest integ  │──▶│ eval gate │
└──────────┘   └──────────┘   └───────┘   └──────────┘   └──────────────┘   └───────────┘
                                                                                 │
                                              fail if recall@10 drops >2 pts vs baseline
```

| Stage | Timeout | Fails the build when |
|---|---|---|
| lint (ruff) | 2 min | any ruff error |
| limits (`check_limits.py`) | 1 min | any `src/*.py` > 200 lines |
| unit | 3 min | any failure |
| integration | 5 min | any failure |
| eval gate | 10 min | recall@10 < baseline − 2 pts, or refusal accuracy < 0.90 |

The gate compares against `results/baseline.json` (committed at M3). The comparison is intentionally
loose: a gate that trips on noise gets disabled within a week, and a disabled gate protects nothing.

**Legibility rule:** the CI log must print the metric table, not just pass/fail. A green tick with no
number is not evidence.

---

## 8. Code review checklist

Used on every PR to this repository, even when the author and reviewer are the same person in a
different session:

- [ ] Does it change behaviour? If yes, is there a test that would have failed before?
- [ ] Does it add a tunable number inline instead of `config.py`?
- [ ] Does a module import something it is not allowed to (layering rules, SwDD §1)?
- [ ] Is `tenant_id` optional anywhere it should be required?
- [ ] Do new log lines contain user text or secrets?
- [ ] Would this still work with the network disabled?
- [ ] If it claims a number, where is the report row?
- [ ] Did the file it touched go over 200 lines? (then split it, don't compress)

---

## 9. Logging standard

One JSON object per line, to stdout:

```json
{"ts":"2026-11-02T14:03:11Z","level":"info","event":"ask.completed","trace_id":"a1b2c3",
 "tenant":"campus","mode":"hybrid_rerank","confidence":0.61,"refused":false,
 "stage_ms":{"retrieve":3.1,"generate":1.4,"total":5.9}}
```

| Field | Required | Note |
|---|---|---|
| `ts`, `level`, `event` | yes | `event` is dotted and stable (`ask.completed`, `ingest.done`) |
| `trace_id` | yes for requests | correlates logs with the API response |
| `tenant` | yes | never a user identifier |
| `stage_ms` | when available | the fields that make latency diagnosable |
| `query` / `answer` | **no** | user text is not logged by default; if enabled, PII-masked |

Never logged: API keys, full documents, raw user queries in the default configuration.

---

## 10. Metrics catalogue

| Metric | Type | Labels | Question it answers |
|---|---|---|---|
| `atlas_requests_total` | counter | endpoint, status | traffic volume, error rate |
| `atlas_answers_total` | counter | outcome=answered\|refused | refusal rate drifting? |
| `atlas_answer_latency_seconds` | histogram | — | is the tail getting worse? |
| `atlas_retrieval_latency_seconds` | histogram | — | retrieval or generation? |
| `atlas_confidence` | histogram | — | are answers getting weaker over time? |
| `atlas_ingested_chunks_total` | counter | — | did ingest actually run? |
| `atlas_cache_hits_total` *(S2)* | counter | kind | is the cache earning its complexity? |
| `atlas_llm_tokens_total` *(S2)* | counter | kind | what does a query cost? |
| `atlas_degraded_total` *(S2)* | counter | reason | fallback path usage frequency? |

Every metric must be used by the dashboard or a CI check. Unused metrics are removed — they are
maintenance cost disguised as observability.

---

## 11. Performance test protocol

Fixed method, so runs are comparable:

1. Warm up: 30 requests, discarded from statistics.
2. Levels: 1, 5, 10, 20, 50 concurrent virtual users, 60 s each.
3. Report: p50, p95, p99, throughput, error rate, and stage breakdown.
4. Machine recorded in the report header (CPU, RAM, OS, Python version).
5. Soak: 30 minutes at the target level; watch RSS growth and latency drift.
6. Thresholds: MVP p95 ≤ 50 ms; stage 2 p95 ≤ 1.2 s. A miss is reported, never rounded away.

Anti-pattern explicitly forbidden: reporting latency from a single request, or from a machine whose
specs are not stated.

---

## 12. Release and versioning

| Version | Contents | Tag |
|---|---|---|
| 0.1.0 | MVP: ingest, hybrid retrieval, cited answers, refusal, eval | `v0.1-mvp` |
| 0.2.0 | real embeddings + reranker | `v0.2-retrieval` |
| 0.3.0 | LLM + verifier + FSM | `v0.3-workflow` |
| 0.4.0 | guardrails, cache, load tests, dashboards | `v0.4-ops` |

Rules: `main` is always releasable; a tag requires a green CI run and the matching `results/` report;
breaking API changes bump the minor version until 1.0.

Rollback: `git revert` + redeploy is sufficient at single-node scale. Documented here so it is not
improvised during a demo.

---

## 13. Runbook (skeleton, completed in stage 2)

| Symptom | First check | Likely cause | Action |
|---|---|---|---|
| `/v1/ask` 500s | log `event=ask.failed` + trace_id | store unavailable | check `data/atlas.db` exists and is writable |
| Answers ignore new document | `stats` document count | index not invalidated | restart or call invalidate |
| p95 rising with traffic | `retrieval_latency` histogram | CPU saturation / pool too small | raise pool, reduce `rerank_pool` |
| Many refusals | `confidence` histogram | threshold too high, or corpus gap | sweep θ in eval, inspect misses |
| Answers off-topic | golden-set recall per intent | retrieval regression | check last change to fusion/rerank weights |
| Provider errors *(S2)* | `degraded_total` by reason | rate limit or outage | confirm fallback active, then investigate |

Every row must map to a real observability field. If a symptom cannot be diagnosed from the fields in
§9–§10, the instrumentation is incomplete — not the operator.

---

## 14. Data lifecycle

| Item | Lifecycle |
|---|---|
| corpus | versioned in git; changing a document is a reviewable diff |
| database | rebuildable from corpus (`make ingest`); never committed |
| golden set | versioned; changes are baseline changes (Project Plan §12) |
| results | committed; never edited by hand, only regenerated |
| logs | stdout, ephemeral in v1; no retention obligation |

Backup story in v1: none needed, because everything durable is in git and everything else is
derivable. Stage 2 adds a database dump for user-generated documents, at which point "no backup" stops
being defensible.

---

## 15. Engineering anti-patterns banned in this repository

| Banned | Why |
|---|---|
| `try/except: pass` | hides the failure mode you were supposed to design for |
| inline magic numbers | the eval sweep cannot find them later |
| optional `tenant_id` | isolation becomes a convention, which is not a control |
| claiming a number without a `/results` row | the project's central discipline |
| mocking internal modules in tests | hides that a seam is missing |
| `print()` debugging left in code | unstructured, unscreenable |
| "temporary" scripts at repo root | becomes permanent, undocumented, unowned |
| a file over 200 lines | a responsibility boundary was never drawn; split it instead |
