# Atlas — Solution Design Document (SoDD)

**Document ID:** ATL-SoDD-001 · **Version:** 1.0 · **Status:** design (pre-implementation)
**Related:** [Problem & Solution](01-problem-and-solution.md) · [SRS](07-software-requirements.md) · [Architecture](08-architecture.md)

The other documents describe a *system*. This one describes a **solution to a problem**: who it is
for, what changes for them, what it costs, how success is judged, and how it is introduced. If a
stakeholder reads only one document, it is this one.

---

## 1. The situation today

A college office answers the same questions every term — scholarship cut-offs, backlog attempts,
withdrawal windows, placement eligibility. The answers exist in handbooks and circulars. Retrieving
them depends on finding the right PDF and reading the right clause.

Consequences, measured in the ordinary way:

| Cost | Where it lands |
|---|---|
| Repeated questions | staff hours, every intake cycle |
| Inconsistent answers between staff | student decisions made on wrong information |
| Advice given from memory | disputes that cannot be traced to a document |
| Nobody knows which policy is stale | an error that persists for years |

---

## 2. The solution in one paragraph

A question-answering service over the institution's **own** documents, which answers only from those
documents, shows the exact passage behind every sentence, refuses when the corpus does not contain the
answer, and escalates to a human when confidence is low. It runs on a laptop, needs no external
service, and its accuracy is measured against a hand-labeled question set rather than asserted.

---

## 3. Capability map

| Capability | What it replaces | Evidence it works |
|---|---|---|
| Natural-language retrieval over the corpus | keyword search, "ask a senior" | recall@10 on the golden set |
| Answer with passage-level citations | advice from memory | 100% citation coverage |
| Refusal on unsupported questions | confident guessing | refusal accuracy on unanswerable set |
| Escalation handoff | "go ask the office" with no context | escalation packet contains question + evidence |
| Tenant separation | one shared index for everyone | 0 leaks in automated probes |
| Measured quality, continuously | quarterly complaints | CI gate blocks quality regressions |

---

## 4. User journeys

### J1 — Answerable question

```
Student: "What CGPA do I need to keep the merit scholarship?"
System:  "A CGPA of at least 8.5 with 85% attendance is required for renewal [1]."
         [1] Merit Scholarship — Renewal Criteria (doc: merit-scholarship)
Value:   answered in ~50 ms, checkable in one click, no staff involved.
```

### J2 — Unanswerable question

```
Student: "What is the hostel mess menu for next week?"
System:  "I could not find this in the available documents, so I am not going to guess.
          You can rephrase the question, or escalate it to the office that owns this policy."
Value:   no invented answer, and the corpus gap becomes visible to the owner.
```

### J3 — Low-confidence / escalated

```
Student: "Can I carry forward a backlog into the next academic year after a medical break?"
System:  retrieves two partially relevant policies, confidence below threshold
         → returns the evidence it found, marked "needs human review", with a handoff packet.
Value:   the staff member starts from the two relevant clauses instead of from zero.
```

### J4 — Owner adds a document

```
Owner:   drops `scholarship-2027.md` into the corpus, runs `make ingest`
System:  chunks it, indexes it, invalidates the tenant index
Value:   new policy is answerable immediately; the same question is re-tested in eval.
```

---

## 5. Solution components mapped to requirements

| Solution element | Serves | Requirement IDs |
|---|---|---|
| Ingest + chunking | corpus lifecycle | FR-01…FR-06 |
| Hybrid index | finding the right passage | FR-07…FR-12 |
| Confidence gate | refusing safely | FR-16, FR-17 |
| Cited generation | verifiable answers | FR-13…FR-15 |
| API + page | access | FR-20…FR-23 |
| Eval harness | proving quality | FR-24…FR-27 |
| One-command run | handover | FR-28 |

---

## 6. Non-functional response

| Concern | How the solution answers it | Residual risk |
|---|---|---|
| Latency | in-process index, <10 ms retrieval, no network in the loop | grows with corpus size; ANN needed beyond ~10k chunks |
| Accuracy | measured recall/precision, ablation table | golden set is authored by one person; limited coverage |
| Safety | refusal by default when evidence is thin; tenancy in the data layer | prompt-injection defence is stage 2 |
| Cost | ₹0 per query offline; no provider dependency | stage 2 introduces per-query cost, tracked then |
| Operability | single process, structured logs, metrics endpoint | no alerting in v1; a failure is noticed when a user reports it |
| Portability | Python + SQLite, no containers | manual setup on a new machine until `make setup` is verified |

---

## 7. Measurement plan (how we will know it solved the problem)

| Question | Metric | Baseline | Target | Artefact |
|---|---|---|---|---|
| Does it find the right policy? | recall@10 | dense-only | ≥ 0.90, beating both single retrievers | `results/eval_report.md` |
| Does it rank precisely? | precision@5 | dense-only | ≥ 0.80 | same |
| Does it refuse instead of guessing? | refusal accuracy | none | ≥ 0.95 | same |
| Is it fast enough to use? | p95 latency | — | ≤ 50 ms | `results/bench_report.md` |
| Can anyone verify a claim? | citation coverage | none | 100% of non-refused answers | contract test |
| Does it stay inside a tenant? | leak count | — | 0 | probe suite |
| Is quality maintained over time? | CI gate | — | blocks >2-pt regression | CI log |

**Anti-goal, stated explicitly:** this solution does not try to maximise answer *volume*. A refusal
on a question outside the corpus is a success, not a miss — and the metric that proves the system is
working is refusal accuracy, not answer rate.

---

## 8. Cost model

| Item | MVP | Stage 2 |
|---|---|---|
| Compute | existing laptop, CPU only | same + optional embedding calls |
| Storage | <50 MB (corpus + SQLite) | + vector store, ~100–500 MB |
| Per-query cost | ₹0 | tokens × provider price, measured |
| Build effort | ≈47 h (Project Plan §4) | ≈66 h |

No infrastructure spend is required for v1. That is a design goal, not a budget accident: it keeps
the project reproducible by any reviewer on any machine.

---

## 9. Assumptions and dependencies

| # | Assumption | If false |
|---|---|---|
| A-1 | Policies are in text/markdown with stable headings | PDF parsing and layout handling become a component |
| A-2 | Users ask single, self-contained questions | multi-turn conversation state required |
| A-3 | One person can label 30–150 questions | eval set shrinks, metrics get noisier |
| A-4 | The institution accepts citations as sufficient provenance | needs an approval workflow, out of scope |
| A-5 | Document set is small enough for memory | needs ANN storage and a different index |

---

## 10. Rollout

| Phase | Audience | Gate to proceed |
|---|---|---|
| P0 internal | author only | baseline report exists |
| P1 pilot | 5–10 classmates, 2 weeks | ≥20 real questions logged, wrong answers triaged |
| P2 department | one office, read-only demo | refusal accuracy holds on real questions |
| P3 (optional) | production use | authentication, PII handling, backup — all stage 2+ |

Rollout is deliberately slow at P1: real questions are the only source of the *next* golden set, and
the wrong answers found there are worth more than any synthetic test.

---

## 11. Acceptance

The solution is accepted when:

- [ ] All items in [Project Plan §14](09-project-plan.md#14-definition-of-done-mvp) are complete
- [ ] A stakeholder can ask three questions from their own domain and get cited answers or refusals
- [ ] Each claim in §7 has a row in `results/`
- [ ] The README's numbers match the reports byte for byte
- [ ] A second person reproduces the run on a different machine

---

## 12. What this solution explicitly is not

- Not a replacement for the office that owns the policy; it routes to them, with evidence.
- Not an authoritative legal interpretation of regulations.
- Not a general-purpose assistant; outside the corpus it declines.
- Not a claim of production readiness; it is a measured prototype with documented limits.
