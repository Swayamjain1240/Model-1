# RFC-0001 — Hybrid retrieval with an explicit refusal gate for the Atlas MVP

| Field | Value |
|---|---|
| RFC number | 0001 |
| Title | Hybrid retrieval with an explicit refusal gate for the Atlas MVP |
| Status | **Proposed** |
| Author | Swayam Jain |
| Created | 2026-11-02 |
| Deciders | project owner (solo project) |
| Affects | `retrieval/`, `pipeline.py`, `eval/`, SRS FR-07…FR-17 |
| Supersedes | — |

---

## 1. Summary

Adopt a two-retriever architecture (BM25 + hashed dense vectors) fused with Reciprocal Rank Fusion,
followed by a cheap reranker and a numeric confidence gate that can refuse to answer — as the
foundation of the Atlas MVP, rather than a single dense retriever with prompt-level instructions to
say "I don't know".

---

## 2. Motivation

A document question-answering service that cannot say "not in the corpus" is not usable for policy
questions, where a confident wrong answer is worse than no answer. Two forces drive this proposal:

1. **Recall on paraphrases.** Keyword search misses "can I drop a subject after the deadline" when the
   document says "withdrawal window". A single lexical retriever under-serves exactly the questions
   real users ask.
2. **Refusal needs a signal.** Without a numeric confidence derived from retrieval, "refuse when
   unsure" is implemented as a prompt instruction — untestable, unmeasurable, and silently ignored by
   the model. Refusal must be a decision the system makes, not one it hopes the model makes.

The MVP must establish a baseline for both, because stage 2 (real embeddings, LLM) can only be
evaluated as a delta against it.

---

## 3. Guide-level explanation

A user asks: *"how many attempts do I get for a backlog paper?"*

1. The query goes to two retrievers at once: a keyword scorer and a vector scorer.
2. Each returns its top 50 passages.
3. The two lists are merged by rank (RRF) — not by raw score, because their scales differ.
4. The merged top 20 are re-scored on how much of the question they actually contain.
5. The best 5 go to the answer generator, which composes sentences drawn from those passages and
   labels each with `[1]`, `[2]`.
6. Before that, a confidence number is computed from the top passage. If it falls below the threshold,
   the system returns a refusal instead of an answer.

What a reviewer will observe: answers cite specific documents and sections; questions outside the
corpus produce a refusal; and the eval report shows recall for keyword-only, vector-only, and hybrid
side by side, so the fusion has to justify itself.

What this RFC deliberately does not do: it does not introduce a trained embedding model or an LLM.
Those are the next RFC's subject, and introducing them now would make the baseline unmeasurable.

---

## 4. Reference-level explanation

### 4.1 Components

| Component | Implementation | Interface |
|---|---|---|
| Sparse scorer | BM25 (k1=1.5, b=0.75) over an inverted index | `Retriever.search(mode="sparse")` |
| Dense scorer | hashed TF-IDF, D=1024, L2-normalised, bigrams included | `Embedder.embed()` |
| Fusion | RRF, k=60 | `retrieval/fuse.py` |
| Reranker | weighted blend: 0.40 fusion + 0.40 coverage + 0.15 bigram + 0.05 title | `retrieval/rerank.py` |
| Confidence | `0.65·cosine + 0.35·idf_coverage`, threshold θ swept in eval | `pipeline.confidence()` |
| Refusal | returned as an outcome field, not an exception | `Answer.refused` |

### 4.2 Data flow

```
query → tokens (+ bigrams)
      → BM25   → ranked list A (≤50)
      → cosine → ranked list B (≤50)
      → RRF    → 50 candidates
      → rerank → 20 → top 5
      → confidence → (answer + citations) | (refusal)
```

### 4.3 Parameters and where they live

All in `config.py`: `bm25_k1`, `bm25_b`, `rrf_k`, `dim`, `retrieve_k=50`, `rerank_pool=20`,
`top_k=5`, `refuse_threshold`. No parameter is typed inline anywhere — the Engineering Design
Document (§15) bans magic numbers, and the build will respect that ban from the first commit.

### 4.4 Determinism

Hashing uses BLAKE2b over UTF-8, not Python's salted `hash()`, so the index is identical across
processes. Ties break by chunk index. Therefore `make eval` twice produces identical reports modulo
timestamps — a requirement (NFR-15), and a precondition for trusting an ablation.

### 4.5 Measurement

| Metric | Definition | Target |
|---|---|---|
| recall@10 | relevant docs found in top 10 / relevant docs | ≥ 0.90 |
| precision@5 | relevant docs in top 5 / 5 | ≥ 0.80 |
| nDCG@10 | position-discounted gain, binary relevance | reported |
| refusal accuracy | correctly refused unanswerable / unanswerable | ≥ 0.95 |

Plus the ablation table: sparse-only, dense-only, hybrid, hybrid+rerank — same query set, same corpus.

---

## 5. Drawbacks

1. **Two indexes, twice the consistency surface.** Ingest must update both; a partial update is a
   silent quality bug. Mitigation: index rebuild is atomic per tenant.
2. **Hashed embeddings are not semantic.** They capture co-occurrence, not synonymy, so the MVP's
   ceiling is lower than a real embedding model. This is accepted *because* it makes the stage-2
   delta meaningful and keeps the MVP offline and free.
3. **Two knobs to tune (θ, rerank weights).** More surface for overfitting to the golden set.
   Mitigation: held-out split and a bootstrap CI in the report.
4. **Hybrid is more code than dense-only.** Roughly 200 extra lines across four small files. Accepted
   for the recall gain, and revertible if the ablation shows no gain.

---

## 6. Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Dense-only (hashed)** | Fails exact-token questions ("form 12B", "Section 4.2") that users ask constantly; ablated directly in the MVP report |
| **BM25-only** | Fails paraphrases — the failure mode that motivated the project |
| **Weighted score fusion** | Requires per-corpus normalisation of incomparable scales; breaks silently when the corpus changes |
| **Learned fusion (LTR)** | Needs training labels the project does not have; premature |
| **LLM-judge reranking** | Latency and cost blow the MVP budget; also makes the baseline dependent on a model |
| **Prompt-level "say I don't know"** | Not measurable, not enforceable, not a system property |
| **Cross-encoder reranker now** | Best precision, but 30–80 ms on CPU and a model dependency before the baseline exists |

---

## 7. Prior art

- Cormack, Clarke & Büttcher (2009) — Reciprocal Rank Fusion, the source of `k=60`.
- Robertson & Zaragoza (2009) — BM25 parameterisation (`k1`, `b`).
- The retrieval literature's consistent finding that hybrid sparse+dense beats either alone on
  heterogeneous queries; this RFC reproduces that finding on a domain corpus rather than assuming it.

---

## 8. Unresolved questions

1. Is `rrf_k = 60` right for a corpus this small (≈6k chunks)? The sweep will answer it; the RFC
   commits to reporting rather than guessing.
2. Should the reranker be applied to the top 20 or top 30? Latency budget suggests 20; the ablation
   will show the precision cost.
3. Do we need query rewriting (synonym expansion) before fusion, or does the dense side already cover
   it? Deferred to the stage-2 RFC, because it needs the baseline to be judgeable.
4. Is document-level relevance granular enough for precision@5, or do labels need to be chunk-level?
   Current choice: document-level, with chunk-level as a stage-2 refinement.

---

## 9. Rollout

| Step | Action | Reversible? |
|---|---|---|
| 1 | Land `retrieval/` with all three modes, no default fusion weights tuned | yes |
| 2 | Land eval harness; record baseline for each mode | yes |
| 3 | Enable hybrid as the default **only if** it beats both single modes on recall@10 | yes |
| 4 | Sweep θ; commit the knee value with the table | yes |
| 5 | Tag `v0.1-mvp` and freeze the golden set | baseline becomes the reference |

If step 3 fails — hybrid does not beat both — the honest outcome is to ship the better single
retriever and record the negative result. That is a valid RFC outcome and a stronger interview story
than unexamined complexity.

---

## 10. How we will know this worked

- `results/eval_report.md` shows hybrid ≥ each single mode on recall@10, with n and CI.
- Refusal accuracy ≥ 0.95 on the unanswerable subset, with θ's sweep table attached.
- Two consecutive `make eval` runs produce identical metrics (determinism holds).
- Stage 2 has a numeric baseline to beat, so its "improvement" claim is falsifiable.

If those four hold, this RFC achieved what it proposed. If hybrid does not win, the RFC's outcome is
documented as rejected-by-measurement, which is equally useful and considerably rarer.
