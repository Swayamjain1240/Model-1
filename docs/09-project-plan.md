# Atlas — Project Plan

**Document ID:** ATL-PLAN-001 · **Version:** 1.1 · **Status:** active (design complete, build starting)
**Owner:** Swayam Jain · **Related:** [Build Plan](03-build-plan.md) · [SRS](07-software-requirements.md)

---

## 1. Objective

Deliver a working, measured, reproducible multi-tenant document question-answering service in two
stages — an MVP that establishes a quality baseline, then an upgrade judged as a delta against that
baseline — with every reported number traceable to a committed report.

**Success is not "it works".** Success is: a stranger clones the repository, runs one command, and
reproduces the numbers in the README.

---

## 2. Scope

| In scope (MVP) | In scope (upgrade) | Out of scope (permanently) |
|---|---|---|
| corpus + golden set | real embeddings + reranker | model training |
| ingest + hybrid index | LLM generation + verifier | multi-modal input |
| cited answers + refusal | workflow states + escalation | writing actions on user's behalf |
| eval harness + report | guardrails + safety suite | billing, public SaaS |
| one endpoint + one page | cache + circuit breaker + load tests | containers / orchestration |
| README with baseline | metrics dashboard + CI gate + runbook | multi-region deployment |

The right-hand column is not a wish list for later; it is what this project will never claim.

---

## 3. Deliverables

| # | Deliverable | Path | Acceptance |
|---|---|---|---|
| D1 | Design set (12 documents) | `docs/` | reviewed, consistent, no unlabelled numbers |
| D2 | Corpus | `corpus/campus/*.md` | ≥18 documents, deterministic generator |
| D3 | Golden set | `eval/golden_set.jsonl` | ≥30 questions, ≥6 unanswerable, hand-labeled |
| D4 | Service | `src/atlas/` | serves `/v1/ask` with citations and timings |
| D5 | Eval harness | `eval/run_eval.py` | writes all three modes to `results/` |
| D6 | Baseline report | `results/eval_report.md` | provenance header + ablation table |
| D7 | Demo page | `src/atlas/web/index.html` | ask → answer → citations |
| D8 | CI pipeline | `.github/workflows/ci.yml` | lint + tests + eval gate |
| D9 | README | `README.md` | number, machine, one command |

---

## 4. Work breakdown (MVP)

| WP | Work package | Effort (focused h) | Depends on |
|---|---|---|---|
| WP1 | Corpus authoring (18 docs) | 6 | — |
| WP2 | Golden set (30 queries + labels) | 5 | WP1 |
| WP3 | Tokeniser + chunker + tests | 4 | — |
| WP4 | Store + idempotent ingest + tenancy test | 4 | WP3 |
| WP5 | BM25 + dense + RRF | 8 | WP4 |
| WP6 | Eval harness + metrics | 6 | WP2, WP5 |
| WP7 | Confidence gate + extractive generator | 5 | WP5 |
| WP8 | API + web page | 5 | WP7 |
| WP9 | CI + eval gate + README | 4 | WP6, WP8 |
| **Total** | | **≈47 h** | ≈ 10–12 focused sessions |

Upgrade stage (indicative): embeddings 6 h · reranker 8 h · LLM + verifier 12 h · FSM 10 h ·
guardrails 12 h · performance 10 h · ops 8 h ≈ **66 h**.

---

## 5. Milestones

| ID | Milestone | Exit criterion (must be demonstrable) |
|---|---|---|
| M0 | Design frozen | 12 docs committed; no implementation code |
| M1 | Ruler exists | golden set committed; retrieval target defined |
| M2 | Index works | `ingest` → ≥1 chunk/doc; `ask` returns passages |
| M3 | **Baseline measured** | `results/eval_report.md` with three modes |
| M4 | Product works | cited answer in browser; refusal on unanswerable |
| M5 | Handover | clean clone → one command → same numbers |
| M6 | Upgrade layer 1 | recall@10 delta reported vs. M3 |

M3 is the milestone that matters. Everything before it is preparation; everything after it is
improvement. If time runs out, stopping at M3 still leaves a credible project.

---

## 6. Schedule (part-time, 3–4 h/day)

| Week | Focus | Milestone |
|---|---|---|
| 1 | corpus, golden set, chunker, store | M0, M1, M2 |
| 2 | retrieval, eval harness, first baseline | M3 |
| 3 | pipeline, API, page, CI, README | M4, M5 |
| 4–6 | upgrade layers 1–2 (embeddings, reranker, LLM + verifier) | M6 |

Buffer rule: one week of slack is assumed, not hoped for. Slippage is absorbed by cutting upgrade
layers, never by cutting the eval harness.

---

## 7. Roles

| Role | Who | Responsibility |
|---|---|---|
| Owner / implementer | Swayam | design, code, evaluation, docs |
| Reviewer (self, adversarial) | Swayam, different session | attack the numbers, then the code |
| User proxy | classmates | ask real questions; report wrong answers |

The reviewer role is scheduled deliberately: 30 minutes at each milestone spent trying to *break* the
previous week's claims. This is cheaper than discovering the flaw in an interview.

---

## 8. Risk register

| ID | Risk | P | I | Mitigation | Trigger |
|---|---|---|---|---|---|
| R1 | Corpus too small to be interesting | M | H | 18 docs, 6–10 sections each, real policy shapes | <30 chunks after ingest |
| R2 | Golden set biased toward easy questions | H | H | keyword-free paraphrases + 6 unanswerable | recall >0.95 — suspiciously good |
| R3 | Hashed embeddings weaken the MVP story | H | M | report the limitation and the stage-2 delta | reviewer asks "is this real ML?" |
| R4 | Scope creep (guardrails early) | H | H | SRS §6 non-goals; defer to upgrade | new file outside MVP tree |
| R5 | Latency target missed after reranking | M | M | measure at M3, tune pool sizes | p95 > 50 ms |
| R6 | Motivation loss after M3 | M | H | each upgrade layer ends in a number | 1 week without a commit |
| R7 | Numbers not reproducible on another machine | L | H | provenance header, determinism test | report differs on rerun |
| R8 | Files grow past the 200-line ceiling | M | M | CI check from M1; split responsibility, never compress | `check_limits.py` red |

---

## 9. Dependencies and assumptions

- Local Python 3.11+ environment and `pip`; no system services required.
- GitHub repository for CI and evidence publishing.
- No paid API dependency in the MVP; provider keys are optional and out of the critical path.
- Assumes single-operator maintenance (see SRS C-6).

---

## 10. Quality gates

| Gate | When | Blocks |
|---|---|---|
| G1 design review | M0 | any code |
| G2 golden-set review | M1 | retrieval work |
| G3 unit + integration green | every commit | merge |
| G4 eval within tolerance of baseline | every commit after M3 | merge |
| G5 baseline report complete | M3 | upgrade work |
| G6 clean-clone reproduction | M5 | declaring MVP done |

A gate that has never failed is a gate that does not work. G4 must be proven by deliberately
introducing a regression once and watching CI reject it.

---

## 11. Git and commit policy

**Rule: every phase ships exactly four valuable commits, pushed to `main` at phase close.**

A commit is *valuable* only if it has one intent, is independently green (lint + tests pass), and
leaves something checkable behind. Code alone does not count.

| # | Commit in a phase | Content | Value |
|---|---|---|---|
| 1 | the feature | smallest working slice of the phase's requirement | its test fails before it, passes after |
| 2 | the evidence | eval row / metric / report for that slice | a number, not a feeling |
| 3 | the docs | SRS/plan updated in the same phase | requirement ↔ test ↔ metric traceable |
| 4 | the gate | CI check, config default, runbook row | quality cannot silently regress next phase |

Message format:

```
<PHASE> · <REQ-ID> · <one-line what>

- what changed, bullet list
- metric impact (e.g. recall@10 unchanged: 0.874; or first measured value)
- evidence: test / report path
```

Example:

```
M3 · FR-08 · tenancy filter enforced in store.search

- required keyword-only tenant_id; TenantError on unknown tenant
- metric impact: recall@10 unchanged (0.874); 0 cross-tenant leaks in probe
- evidence: tests/test_retrieval.py::test_no_cross_tenant_leak
```

M0 itself follows the rule: commit 1 = system/software/technical design, commit 2 = SRS +
architecture, commit 3 = project plan + engineering design, commit 4 = RFC + solution design +
README index. All four are pulled/doc Tudor only, so lint/test gates are trivially green — the "value"
is that each commit is a reviewable, self-contained step of the design.

---

## 12. Change control

- A change to the golden set after M3 is a **new baseline**, not a fix. It must be a separate commit
  that regenerates the report and states why labels changed.
- A change to a metric definition is a design change: update SRS + TDD in the same PR as the code.
- A new dependency requires a one-line justification in the PR and must respect NFR-20 (≤8 runtime
  dependencies).

---

## 13. Tooling

| Purpose | Tool | Note |
|---|---|---|
| language | Python 3.11+ | typed, ruff-formatted |
| web | FastAPI + uvicorn | no framework beyond this |
| maths | numpy | no scipy/torch in MVP |
| storage | SQLite | file-based, zero ops |
| tests | pytest | unit/contract/integration |
| quality | ruff | lint + format in CI |
| size discipline | `scripts/check_limits.py` | any `src/*.py` > 200 lines fails CI |
| CI | GitHub Actions | lint → tests → limits → eval gate |

---

## 14. Definition of done (MVP)

All ten boxes in [Build Plan §11](03-build-plan.md#11-definition-of-done-for-the-mvp) plus:

- [ ] This plan's milestone table is accurate (M3 report exists, M5 verified on a clean clone)
- [ ] Risk register reviewed at M3; any triggered risk has a recorded decision
- [ ] README's claims map one-to-one to a file in `results/`
- [ ] No source file exceeds 200 lines at any point in history since M1

---

## 15. Reporting cadence

| When | Artefact | Purpose |
|---|---|---|
| per commit | git history (format per §11) | traceability |
| per phase | **phase report to the owner**, in four parts | decision & review record |
| per milestone | short note + updated docs | decision record |
| at M3 and each upgrade layer | `results/` report | the evidence ledger |

**Phase report format (fixed):**

1. **Is the project complete?** yes / no / not yet — one line, no spin.
2. **What remains** — the next phase's scope and anything left unfinished in the last one.
3. **GitHub commits** — the exactly-four hashes and messages for the phase.
4. **Summary** — what is now true that was not true at the phase start, with numbers where they exist.

---

## 16. Evidence to resume mapping

| Milestone | Artefact produced | Resume line it enables |
|---|---|---|
| M3 | `eval_report.md`, ablation | the recall/precision bullet |
| M4 | demo + refusal tests | the guardrails/behaviour bullet |
| M5 | CI log, clean clone | the reproducibility bullet |
| M6 | delta table | the "improved by X" bullet |

A bullet without its milestone is deleted, not softened.
