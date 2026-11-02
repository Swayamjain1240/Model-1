# Atlas — Final Output, System Design & Resume Pack

**Status:** design (pre-implementation) · **Companion to:** [01-problem-and-solution.md](01-problem-and-solution.md) · **Version:** 0.1

This document answers one question: **when this project is finished, what is the output — and how
does it appear on a resume and in an interview?**

The chatbot is the demo. The **output of this project is a system whose behaviour is measured,
explained and reproducible.** That is deliberate: model output is not a deliverable you can put on
a resume, because every candidate has a chatbot. An ablation table, a latency curve, a threat
suite result and a design log are deliverables, because they prove engineering judgement.

---

## 1. The framing: what "output" means here

| | Not the output | The output |
|---|---|---|
| Object | A model that answers questions | A **service** with defined SLOs, failure modes and boundaries |
| Proof | "It worked when I tried it" | A **report file** produced by a script, reproducible by a stranger |
| Skill shown | Prompting | Retrieval design, evaluation methodology, concurrency, security, ops |
| Interview value | 30 seconds | 20 minutes of follow-up questions |

So the project has **four classes of output**, and all four go into the repo:

1. **A running system** — code, deployable, with documented interfaces.
2. **An evidence ledger** — `results/` files, each stamped with the command, machine and date that
   produced it. Every resume number cites one of these files.
3. **A decision log** — architecture docs and ADRs recording what was chosen, what was rejected
   and why. This is what separates "I followed a tutorial" from "I made engineering tradeoffs".
4. **A narrative** — README, demo, and the two-minute verbal version. Optimised for a reviewer
   with 90 seconds.

---

## 2. Artifact inventory (the definition of "done")

This is the actual file tree at project completion. If a file is missing, the project is not done.

```
atlas/
├── README.md                      ← 90-second proof: problem, result table, one-command run
├── Makefile                       ← setup · ingest · eval · bench · serve · escalate
├── pyproject.toml
├── src/atlas/
│   ├── config.py                  ← all limits in one place (budgets, thresholds, k, timeouts)
│   ├── ingest/                    ← parse → chunk → embed → index, idempotent by checksum
│   ├── retrieval/                 ← bm25.py · dense.py · fusion.py (RRF) · rerank.py · mmr.py
│   ├── agent/                     ← fsm.py (states, budgets, retries) · tools.py · handoff.py
│   ├── guard/                     ← pii.py · injection.py · grounding.py · policy.py
│   ├── store/                     ← sqlite or pg adapter; tenant filter is a required argument
│   ├── cache/                     ← exact + semantic (cosine ≥ θ), tenant-namespaced, TTL-busted
│   ├── obs/                       ← spans, metrics registry, structured logging, redaction
│   └── api.py                     ← /v1/ask, /v1/ask/stream, /v1/documents, /v1/traces, /metrics
├── eval/
│   ├── golden_set.jsonl           ← ~150 labeled queries (answerable + unanswerable)
│   ├── attacks.jsonl              ← ~40 injection / exfiltration / role-play probes
│   ├── tenant_probes.jsonl        ← cross-tenant leak attempts
│   └── run_eval.py                ← emits results/eval_report.{json,md} + ablation table
├── bench/
│   ├── load_test.py               ← staged concurrency, percentiles, degradation checks
│   └── soak.py                    ← 30-minute run, memory/leak drift
├── results/                       ← ★ THE EVIDENCE LEDGER — committed, timestamped
│   ├── eval_report.md             ← recall/precision/nDCG/faithfulness per config, with CI
│   ├── ablation.md                ← dense · sparse · hybrid · +rerank · +cache
│   ├── safety_report.md           ← injection pass/fail table, tenant probes, PII findings
│   ├── bench_report.md            ← p50/p95/p99 per concurrency level, RPS, error rate
│   └── soak_report.md
├── docs/
│   ├── 01-problem-and-solution.md
│   ├── 02-deliverables-and-resume-output.md   ← this file
│   ├── ARCHITECTURE.md            ← diagrams + data flow + failure modes
│   ├── EVALUATION.md              ← metric definitions, labeling protocol, known biases
│   ├── RUNBOOK.md                 ← "it's slow / it's wrong / it's down" → what to check
│   └── adr/                       ← 0001-hybrid-retrieval.md, 0002-refusal-threshold.md, ...
├── deploy/
│   ├── Dockerfile                 ← multi-stage, non-root, healthcheck
│   ├── docker-compose.yml         ← api + prometheus + grafana (provisioned dashboard)
│   └── grafana/                   ← dashboard JSON committed as code
├── .github/workflows/ci.yml       ← lint → types → unit → integration → eval gate → image
└── tests/                         ← unit + integration + the adversarial suites as pytest
```

**The `results/` directory is the single most important output.** Everything else is machinery that
produces it. Each report header must state, in this shape:

```
Generated by : make eval            (commit 7f3c1a9)
Machine      : Windows 11, 12 threads, 16 GB RAM, CPU-only
Provider     : offline extractive generator (deterministic)
Corpus       : campus-handbook-v3, 412 documents → 6,318 chunks, 3 tenants
Golden set   : 150 queries (118 answerable, 32 unanswerable), hand-labeled
```

Without that header a number is a claim. With it, a number is a measurement.

---

## 3. The five things you actually show people

These are the artifacts that carry the project in front of a human. Not the code.

| # | Artifact | Who reads it | What it proves | Time to consume |
|---|---|---|---|---|
| 1 | **README top fold** — result table, one command, 3 screenshots | Recruiter / screener | This is real and finished | 90 s |
| 2 | **`results/ablation.md`** | Engineer | You measure instead of guessing | 2 min |
| 3 | **`results/bench_report.md`** — p95 curve across concurrency | Engineer / SRE | You understand load, not just latency | 2 min |
| 4 | **`results/safety_report.md`** — 40 attacks, per-attack verdict | Security-minded reviewer | You threat-modelled it | 2 min |
| 5 | **Grafana dashboard screenshot** + trace waterfall of one slow request | Anyone technical | You can operate what you built | 30 s |

Supporting but high-leverage: a **5-minute demo video** (one question answered with citation, one
refused, one escalated, one injected-and-blocked, one degraded-mode answer) and a **one-page
architecture PDF** exported from `docs/ARCHITECTURE.md`.

Note what is *absent* from that list: a model card, training curves, a benchmark leaderboard. This
project is not a model-training project, and pretending otherwise invites the wrong questions.

---

## 4. System design: the decisions you will be asked to defend

An interviewer's real question is "did you choose, or did you copy?" So the deliverable includes a
record of **eight decisions, each with the alternative you rejected.** Format: choice → why →
what it cost → what would change your mind.

| # | Decision | Rejected alternative | Cost you accepted | What would change your mind |
|---|---|---|---|---|
| 1 | **Hybrid retrieval (BM25 + dense) fused with RRF** | Dense-only (simpler, trendier) | Two indexes to keep consistent; slightly more ingest work | If dense-only recall approached hybrid on the golden set, delete BM25 and the complexity with it |
| 2 | **Hand-rolled FSM instead of a framework** | LangGraph / LlamaIndex agents | You write the state machine, retry and budget logic yourself | A framework would be right if the team needed many authors or dynamic graph shapes |
| 3 | **Two-stage retrieve-then-rerank** | Single-stage big-k retrieval | A reranker adds ~tens of ms of p95 | If the reranker's precision lift didn't pay for its latency |
| 4 | **Refusal as a first-class state** | Always answer, let the user judge | Some genuinely answerable questions get refused (false silence) | If refusal false-negative rate exceeded the hallucination it prevented |
| 5 | **Tenant filter inside the query, not in the prompt** | Prompt-level instruction "only use tenant X docs" | Harder storage layer; every query path must thread tenant_id | Nothing — prompt-level tenancy is not security, at any scale |
| 6 | **Semantic cache with a tenant-namespaced key** | No cache / exact-match cache only | Cache invalidation on every document change; a similarity threshold to tune | If cache hit rate stayed near zero on real traffic, the complexity isn't earned |
| 7 | **Designed degradation (circuit breaker → extractive fallback)** | Return 503 when the provider fails | A weaker answer path to build and test | Never — the failure path *is* the production behaviour under load |
| 8 | **Eval harness before retrieval tuning** | Tune by feel, evaluate at the end | ~2 extra days of labeling at the start | Nothing — without it, decisions 1–7 are unfalsifiable |

Those eight rows are the interview. Someone who can walk through rows 1, 3, 4 and 7 with their own
numbers attached is indistinguishable from a working ML/platform engineer in a 20-minute loop.

---

## 5. Two more design outputs worth more than the code

**a) The failure-mode table** (`docs/ARCHITECTURE.md`). For each of the eight problems in the
problem statement: the mechanism, the *residual* risk you did not eliminate, and how you'd detect
it in production. Admitting residual risk is a senior signal — every system has some.

**b) The SLO definition.** Written as an operator would write it:

```
Availability      : 99.5% of /v1/ask over a rolling 30 days
Latency           : p95 ≤ <measured budget> ms, p99 ≤ <measured>, at 20 concurrent users
Quality           : recall@10 ≥ 0.90, faithfulness ≥ 0.90 (evaluated on every release)
Safety            : 0 cross-tenant leaks; injection block rate ≥ 95%
Cost              : ≤ <measured> tokens/query at p95
Degradation       : provider failure → degrade to extractive, never 5xx
Error budget      : 3 failed evaluations in a release window → freeze feature work
```

You are not running this in production for 30 days. You are showing that you know an SLO is a
*contract with numbers*, and that the eval harness is how the quality clause is enforced.

---

## 6. From measurement to resume line

The rule: **every bullet is `action + mechanism + measured result + the artifact that proves it`.**
Numbers without a mechanism read as decoration; mechanisms without numbers read as a tutorial.

| Measured thing | Where it comes from | How it becomes a resume phrase |
|---|---|---|
| recall@10 per config | `results/ablation.md` | "lifted recall@10 from **X** to **Y** (+**Z** pts) over dense-only" |
| precision@5, nDCG@10, MRR | `results/eval_report.md` | "precision@5 **P**, nDCG@10 **N**, on a 150-query hand-labeled set" |
| bootstrap CI | `results/eval_report.md` | "…±**C** (95% CI)" — this single parenthetical kills doubt |
| faithfulness / refusal accuracy | `results/eval_report.md` | "faithfulness **F**; refusal accuracy **R** on 32 unanswerable queries" |
| injection pass rate | `results/safety_report.md` | "blocked **I**/40 adversarial prompts; 0 cross-tenant leaks across **T** tenants" |
| p50/p95/p99 per concurrency | `results/bench_report.md` | "p95 **L** ms at **VU** concurrent users; **R** RPS sustained; **E**% error rate" |
| cache hit rate, delta latency | `results/bench_report.md` | "semantic cache served **H**% of queries, cutting p95 by **D** ms" |
| tokens/query before-after | `results/eval_report.md` | "reduced tokens/query **A** → **B** (**P**%) via context compression" |
| eval gate | `.github/workflows/ci.yml` | "CI blocks merges on a >2-pt recall regression via an automated eval gate" |

**Fill the placeholders only from the files.** If a report doesn't contain a number, the bullet
doesn't contain that number. This is the discipline that makes the whole project credible, and it
takes one afternoon of restraint.

---

## 7. The resume pack

### 7.1 Project header line (one line, above the bullets)

> **Atlas — Multi-tenant RAG service with measured retrieval quality, guardrails and SLOs**
> `Python · FastAPI · hybrid BM25+dense · RRF · reranking · eval harness · Prometheus/Grafana · Docker · CI`

### 7.2 Full version — 6 bullets (for a 1-page resume with space)

- **Built Atlas**, a multi-tenant retrieval-augmented answer service (Python/FastAPI, async I/O,
  hybrid BM25 + dense retrieval with RRF fusion and cross-encoder-style reranking) serving cited
  answers over **[N]** documents / **[M]** chunks partitioned across **[T]** isolated tenants, with
  a refusal path and human-escalation handoff instead of ungrounded answers.
- **Raised retrieval recall@10 from [X] to [Y] (+[Z] pts, 95% CI ±[C])** and precision@5 to **[P]**
  on a hand-labeled 150-query golden set, by adding hybrid fusion and reranking; results and the
  full five-config ablation table are committed as reproducible reports (`make eval`).
- **Cut p95 latency [A] ms → [B] ms** with a tenant-namespaced semantic cache (**[H]%** hit rate),
  batched embeddings and bounded thread-pool offload; sustained **[R] RPS at p95 < [L] ms** under
  **[VU]** concurrent virtual users, **0 errors** in a 30-minute soak test.
- **Enforced grounding and safety**: a verifier vetoes unsupported claims (faithfulness **[F]**),
  refusal accuracy **[Rf]** on 32 held-out unanswerable queries, **[I]**/40 prompt-injection attacks
  blocked, **0 cross-tenant leaks** across **[T]** tenants verified by an automated CI probe suite.
- **Instrumented the pipeline end-to-end** with per-stage OpenTelemetry spans, Prometheus latency
  histograms and a provisioned Grafana dashboard, reducing diagnosis of latency regressions from
  ad-hoc debugging to a single trace lookup.
- **Automated quality gates in GitHub Actions** (lint → types → tests → eval regression gate →
  container build), so a recall regression >2 pts fails the build instead of shipping silently.

### 7.3 Compact version — 3 bullets (for a dense one-pager)

- Built **Atlas**, a multi-tenant RAG service (FastAPI, hybrid BM25+dense with RRF + reranking,
  citation-enforced answers, refusal/escalation states); improved recall@10 **[X] → [Y]** and
  precision@5 to **[P]** on a hand-labeled 150-query set, with a committed ablation report.
- Held **p95 at [L] ms under [VU] concurrent users ([R] RPS, 30-min soak, 0 errors)** via semantic
  caching, batched embeddings and designed degradation to an extractive fallback on provider failure.
- Hardened and operationalised it: **[I]**/40 injection attacks blocked, 0 cross-tenant leaks, plus
  Prometheus/Grafana observability and a CI eval gate that blocks quality regressions.

### 7.4 What NOT to write

- ✗ "Azure AI Search / Copilot Studio / Entra ID / AKS" — unless you literally use them. Write the
  honest equivalent: hybrid index, agent FSM, OIDC+RBAC, Docker/CI. Interviewers ask about names.
- ✗ "99.9% accuracy" — accuracy of *what task*? RAG has no single accuracy. Use recall@k,
  faithfulness, refusal accuracy.
- ✗ "10,000+ monthly users" — you have classmates, not 10k users. Say "tested at [VU] concurrent
  users, [R] RPS" and it is unassailable.
- ✗ "Reduced costs by $120K" — you have no employer baseline. Say "reduced tokens/query [A] → [B]".
- ✗ "Fine-tuned a multimodal LLM" — you didn't. Claiming it invites questions you can't survive.

---

## 8. Interview defence: the six questions you will get

Rehearse these until each answer is 45–60 seconds. They are the highest-probability follow-ups.

1. **"Why not just use LangChain/LlamaIndex?"**
   → "The interesting part of this system is the state machine and the failure paths — retries,
   budgets, circuit breaking, refusal. Those are exactly the parts a framework hides. I wrote the
   FSM explicitly so I could instrument every state transition and reason about spend. If the team
   needed many authors on it, a framework would be the right call."
2. **"Why RRF and not weighted score fusion?"**
   → "BM25 scores and cosine similarities aren't on a comparable scale, so weighted fusion needs
   per-corpus normalization tuning. RRF only uses ranks, which is scale-free and robust. I kept the
   ablation table so the choice is falsifiable rather than a preference."
3. **"How do you know your eval set isn't biased?"**
   → "150 queries stratified by intent, held-out split, bootstrap confidence intervals, and I report
   per-intent recall instead of only the mean. The honest limitation: the set is mine, so it shares
   my blind spots; the per-intent breakdown is there so a reviewer can see where it's weak."
4. **"What happens when the model provider rate-limits you mid-load-test?"**
   → "A circuit breaker opens after consecutive failures and the request degrades to a
   retrieval-only extractive answer, labelled as degraded. I measured that path rather than
   assuming it — the alternative was unbounded queueing and 504s under the same load."
5. **"How do you guarantee tenant isolation?"**
   → "tenant_id comes from the session, never the request body, and it's a required argument on
   every index query, so a caller can't forget it. Prompt-level instructions are not a control. An
   automated probe suite tries to cross boundaries in CI; it must return zero hits."
6. **"Recall 0.9 — is that good?"**
   → "Good enough for this corpus and this budget, and I know exactly where it's weakest: the
   per-intent table shows it drops on multi-hop questions. The number means something because it's
   against a stated baseline (dense-only at [X]) and a confidence interval, not in isolation."

And one you must answer honestly: **"What's the weakest part of this system?"**
→ Name it. "The reranker is a hand-tuned feature scorer, not a trained cross-encoder; a trained one
would probably buy a few points of precision@5, at GPU cost. And my corpus is a few hundred
documents, so nothing here proves behaviour at millions of chunks — that needs a real vector store
with disk-based ANN."

Being able to say that is *worth more* than another feature, because it proves you know where your
own measurements stop being valid.

---

## 9. Delivery map: which phase produces which output

| Phase | Code output | Evidence output | Resume bullet unlocked |
|---|---|---|---|
| 0 | Golden set, metric definitions | `eval_report.md` skeleton | — (enables everything) |
| 1 | Ingest + hybrid index | Baseline recall@10 | Bullet 1 (system) |
| 2 | Fusion + reranking | `ablation.md` | **Bullet 2 (the headline number)** |
| 3 | FSM + guardrails | `safety_report.md` | Bullet 4 |
| 4 | Cache + serving + bench | `bench_report.md`, `soak_report.md` | Bullet 3 |
| 5 | Observability + CI | Grafana screenshot, CI gate log | Bullets 5, 6 |
| 6 | Docs, demo, README | Architecture PDF, demo video | The narrative |

Note the sequencing: bullets 2 and 3 — the two numbers a recruiter actually stops on — come out of
phases 2 and 4. Everything after that is polish that makes the numbers look operated rather than
generated.

---

## 10. Definition of done (tick every box)

- [ ] `make setup && make ingest && make eval && make bench` works from a clean clone
- [ ] `results/` contains all five reports, each with the provenance header from §2
- [ ] Ablation table has five configurations and shows the delta, not just the winner
- [ ] Every metric has n, mean and a confidence interval
- [ ] Refusal accuracy reported on a held-out unanswerable set (not zero-shot claims)
- [ ] 40-attack injection suite with per-attack verdicts; tenant probe suite at zero leaks
- [ ] Load test at ≥3 concurrency levels, plus a 30-minute soak
- [ ] Degraded mode demonstrated (provider failure simulated), not just coded
- [ ] Grafana dashboard committed as JSON and screenshotted with real traffic
- [ ] One trace waterfall of a slow request, annotated with where the time went
- [ ] CI eval gate demonstrated by a deliberate regression commit that fails the build
- [ ] `docs/adr/` has ≥5 decisions, each with a rejected alternative
- [ ] README opens with a result table and a single reproduce command
- [ ] 5-minute demo video: answer with citation → refusal → escalation → injection blocked → degraded
- [ ] Resume bullets contain **only** numbers traceable to a file in `results/`

When all fifteen are true, you are not describing a project you built. You are handing over a system
someone else can run, critique and extend — which is the actual thing a hiring manager is trying to
find out about you.
