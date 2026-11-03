# Atlas — Technical Design Document (TDD)

**Document ID:** ATL-TDD-001 · **Version:** 1.0 · **Status:** design (pre-implementation)
**Related:** [Software Design](05-software-design.md) · [SRS](07-software-requirements.md)

Algorithms, formulas, parameters and complexity. If the Software Design Document says *where the
code lives*, this says *what the code computes and why those formulas*.

---

## 1. Retrieval pipeline at a glance

```
query
  ├─ tokenise ────────────────► q_terms (unigrams) + q_bigrams
  ├─ sparse:  BM25(q, chunk)  ─► ranked list A (top 50)
  ├─ dense:   cos(v(q), v(c)) ─► ranked list B (top 50)
  ├─ fusion:  RRF(list A, list B) ─► 50 fused candidates
  ├─ rerank:  coverage + bigram + title blend ─► 20 → top 5
  └─ confidence gate → answer | refuse
```

Everything is deterministic: no sampling, no random seeds, no clock-dependent behaviour. Two runs on
the same corpus and query produce byte-identical rankings, which is a precondition for the ablation
table to mean anything.

---

## 2. Chunking

**Goal:** passages small enough to cite precisely, large enough to be self-contained.

```text
split document into (section, paragraph) pairs by markdown headings and blank lines
current = []
for section, paragraph in pairs:
    if tokens(current) + tokens(paragraph) > 180:
        emit current                     # one chunk
        current = last 1 paragraph       # overlap, carries context across the boundary
    current.append((section, paragraph))
emit current
```

| Parameter | Value | Rationale |
|---|---|---|
| `chunk_tokens` | 180 | fits ~3 passages in a prompt with room for the question; keeps citations precise |
| `overlap_paragraphs` | 1 | a policy split across a boundary stays retrievable from both sides |
| split unit | paragraph | sentence splitting produces fragments that lose the subject of a policy |
| section | stored per chunk | citations read as "Attendance §Condonation", which a human can verify |

Complexity: **O(n_tokens)** per document, single pass, no re-reading.

Failure modes handled: empty document (no chunks emitted), document shorter than the budget (one
chunk), heading-only document (section label kept, no text chunk).

---

## 3. Sparse scoring — BM25

For query `Q` and chunk `D`:

```
score(Q,D) = Σ_{t ∈ Q} IDF(t) · (tf(t,D) · (k1+1)) / (tf(t,D) + k1 · (1 − b + b · |D| / avgdl))

IDF(t)  = ln( (N + 1) / (df(t) + 0.5) )
k1 = 1.5     b = 0.75     N = number of chunks
```

| Choice | Value | Why |
|---|---|---|
| `k1` | 1.5 | term-frequency saturation: a chunk repeating a word 20 times is not 20× more relevant |
| `b` | 0.75 | length normalisation, slightly under the classic 1.0 because our chunks are already length-normalised by construction |
| IDF floor | `ln(N+1)` | unseen query terms contribute nothing rather than raising an error |

Implementation: inverted index `term → [(chunk_idx, tf)]`, precomputed `doc_len` array. Query cost
is proportional to the number of postings for the query's terms — **O(Σ df(t))**, not O(corpus).

---

## 4. Dense scoring — hashed TF-IDF projection (MVP)

This is **not** a trained embedding model. It is a deterministic, offline stand-in that occupies the
same interface, so the engineering (fusion, reranking, evaluation) can be built and measured before
a model is introduced.

```
for each term t in (unigrams ∪ bigrams) of a text:
    slot, sign = hash64(t) → (value mod D, ±1)
    weight(t)  = (1 + ln tf(t)) · IDF_all(t)
    v[slot]   += sign · weight(t)
v ← v / ‖v‖₂          (unit norm ⇒ dot product = cosine)
```

| Parameter | Value | Why |
|---|---|---|
| `D` (dim) | 1024 | collisions stay rare at corpus scale; memory is 4 KB/chunk |
| weighting | `1 + ln tf` | sublinear, matches BM25's saturation intent |
| bigrams | included | recovers some phrase sensitivity that unigrams lose ("withdrawal window") |
| normalisation | L2 | makes cosine a dot product, so the whole corpus is one matrix multiply |

**Honest limitation, stated up front:** this captures lexical co-occurrence, not synonymy. "Drop a
course" will not match "withdrawal window" unless they share a token. That is exactly the gap the
stage-2 real embedder closes — and the ablation table is what proves it closed.

---

## 5. Fusion — Reciprocal Rank Fusion

```
score(chunk) = Σ_{r ∈ retrievers} 1 / (k + rank_r(chunk) + 1)      k = 60
```

Why RRF rather than weighted score fusion:

- BM25 scores are unbounded and corpus-dependent; cosine is in [−1, 1]. Weighted fusion needs
  per-corpus normalisation, which silently breaks when the corpus changes.
- RRF uses only ranks, so a retriever that is systematically over-confident cannot dominate.
- It is one line of arithmetic per candidate, which keeps the latency budget honest.

Chosen `k = 60` (the standard value from the original TREC work). The eval harness sweeps
`k ∈ {10, 60, 100}` in the ablation phase; if 60 is not best, the report says so and the config changes.

---

## 6. Reranking (MVP-lite)

Cheap, explainable, and replaceable by a trained cross-encoder in stage 2. For the top 20 fused
candidates:

```
combined = 0.40 · (fuse_score / max_fuse_score)      # keeps fusion's opinion
         + 0.40 · idf_coverage(query, chunk)         # did it actually contain the ask?
         + 0.15 · bigram_overlap(query, chunk)       # phrase sensitivity
         + 0.05 · title_match(query, chunk)          # a document about the topic beats a mention of it
```

```
idf_coverage(q, c) = Σ_{t ∈ q ∩ c} idf(t) / Σ_{t ∈ q} idf(t)
```

| Weight | Why it is that size |
|---|---|
| 0.40 fusion | a strong retriever's ranking should not be thrown away by the reranker |
| 0.40 coverage | the dominant failure mode is "returned a chunk that mentions the words in passing" |
| 0.15 bigrams | phrase match is a strong precision signal on policy text |
| 0.05 title | small, because titles are often generic ("Academic Regulations") |

Weights live in `config.py` so the sweep can move them and the report can show what each bought.

---

## 7. Confidence and the refusal decision

```
cosine    = max(0, cos(v(query), v(top_chunk)))
coverage  = idf_coverage(query, top_chunk)
confidence = 0.65 · cosine + 0.35 · coverage
refuse     = (confidence < θ) or (no candidates)
```

Why a blend rather than a raw similarity: similarity can be high for a chunk that shares vocabulary
but answers a different question, while coverage alone over-rewards keyword stuffing. Together they
approximate "the passage is about the ask and contains the ask".

**Threshold selection is measured, not chosen.** The harness sweeps
`θ ∈ {0.20, 0.25, 0.30, 0.35, 0.40}` and reports, for each value:

| θ | answer rate | refusal accuracy | false refusals | hallucinations let through |
|---|---|---|---|---|
| … | … | … | … | … |

The chosen value is the one on the knee of that table, and the table goes in `results/`. A threshold
without that table is a guess wearing a number.

---

## 8. Answer assembly (extractive, MVP)

```
for each of the top-k passages:
    pick ≤2 sentences maximising  overlap(sentence, query) / sqrt(len(query))
                                  − 0.01 · sentence_position
    attach citation (doc, section, snippet)
stop at max_sentences (4)
join: "<sentence> [1] <sentence> [2] …"
```

Properties:

- **Grounded by construction** — the generator cannot emit a sentence that is not in a retrieved
  passage. Faithfulness is 1.0 *for this generator only*; the moment an LLM is introduced, a verifier
  becomes mandatory (stage 2).
- Citation numbering follows answer order, so a reader can check every `[n]` mechanically.
- If no sentence contains a query term, return the refusal text rather than an off-topic quote.

---

## 9. Complexity and footprint

| Operation | Cost | At MVP scale (≈6k chunks, D=1024) |
|---|---|---|
| chunk a document | O(tokens) | <5 ms / doc |
| build index | O(chunks · D) | ≈2 s once, then cached |
| BM25 query | O(Σ df(t)) | ≈1–3 ms |
| dense query | O(chunks · D) | ≈1–3 ms (one matmul) |
| RRF fusion | O(pool · retrievers) | <0.5 ms |
| rerank | O(pool · terms) | ≈1 ms |
| memory | chunks · D · 4 B + text | ≈24 MB vectors + text |

These estimates exist so that a later "it's slow" report can be checked against a prediction instead
of investigated from scratch. If measured cost differs by more than 2× from this table, one of the
assumptions is wrong and that is worth finding.

---

## 10. Stage-2 substitutions (same interfaces, new maths)

| Component | MVP | Stage 2 | What must be re-measured |
|---|---|---|---|
| Embedder | hashed TF-IDF, D=1024 | hosted/local sentence encoder, D=384–1024, batched | recall@10, index build time, memory |
| Retrieval store | numpy matrix in RAM | vector store with on-disk ANN | recall@10 (ANN is approximate!), p95 |
| Reranker | weighted features | cross-encoder over (query, passage) | precision@5 vs. added p95 |
| Generator | extractive | LLM with numbered passages + citation contract | faithfulness, tokens/query, p95 |
| Verifier | none | claim extraction + support check | unsupported-claim rate |
| Fusion | RRF k=60 | tuned fusion, possibly weighted | ablation table |

Non-negotiable during substitution: **the golden set and the metric definitions do not change.**
Otherwise the comparison between MVP and stage 2 measures the ruler, not the system.

---

## 11. Numerical and determinism notes

- All vector maths in float32; accumulation in float32 is sufficient at D=1024, and float64 doubles
  memory for no measurable gain here.
- `np.argsort(-scores)` with stable ties broken by chunk index, so equal scores order deterministically.
- Hashing uses BLAKE2b over the UTF-8 term, not Python's `hash()`, because `hash()` is salted per
  process and would make the index differ between runs — a subtle bug that destroys reproducibility.
- Logs and reports round to 4 decimals; comparisons in tests use tolerances, never `==` on floats.
