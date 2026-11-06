# Stage-2 reranker — trained on documents, judged on held-out documents (M8)

Command: `python -m eval.rerank_train` · commit `87a5222` · platform: Windows-11-10.0.26300-SP0

Split: 12 documents to train on, 6 held out (`backlog-and-attempts, course-withdrawal, grading-system, library-rules, placement-policy, supplementary-exams`). Questions with evidence in the held-out documents: **10** of 24; 14 train the weights, 0 span both sides and are excluded.

## Held-out retrieval (the honest number)

| configuration | recall@10 | p@5 capped | n |
|---|---|---|---|
| dense only | 1.0000 | 0.9000 | 10 |
| sparse only | 0.9000 | 0.8000 | 10 |
| blend (MVP) | 0.9000 | 0.9000 | 10 |
| learned pointwise | 0.9000 | 0.9000 | 10 |
| learned pairwise | 0.9000 | 0.9000 | 10 |

## In-sample reference (same 24 queries, context only — not evidence)

| configuration | recall@10 |
|---|---|
| blend (MVP) | 0.9167 |
| learned pairwise | 0.9167 |

## Learned weights

| feature | pointwise | pairwise |
|---|---|---|
| cosine | +4.0040 | +1.4554 |
| bm25 | +4.2115 | +2.1984 |
| rrf | -2.3612 | +1.1949 |
| coverage | +1.6332 | +0.7959 |
| bigram | +1.0453 | +0.2054 |
| title | +4.6262 | +0.9473 |
| section | +1.1426 | +0.2460 |
| length | -2.7380 | -0.6683 |

Decision: **not adopted**. no learned variant beat both the blend (0.9000) and the best single retriever (1.0000) on held-out documents; the MVP blend stays and FR-11 remains open.

Cost: mean search 0.81 ms (blend) vs 0.71 ms (learned pairwise), warm views, one process.

## Interpretation

- Held-out: blend 0.9000, pointwise 0.9000, pairwise 0.9000, best single retriever 1.0000.
- Questions missed by the blend: a009; by the learned pairwise: a009.
- The pointwise model put its largest weight on title overlap, which is a document
  identity prior: on training documents the title shares words with the question, and on
  unseen documents that shortcut is worth nothing. Its held-out score is the price of the
  shortcut, which is exactly what a document-held-out split is for.
- The pairwise model optimises ordering instead of relevance, and reports its own cost.
  Only one of these is adopted, and only if the frozen set says so; both stay in the
  table so the rejected one cannot quietly disappear.
- n=10 held-out questions: one question is worth 0.10 recall@10, so treat this as a direction, not an estimate. results/rerank.json carries the per-question rows.
- Training pairs come from `candidate_set`, the same function the server calls, so there
  is no feature drift between fitting and serving.

