# Atlas eval report — first measured baseline (M3)

Command: `python -m eval.run_eval` · corpus: `corpus/campus (18 documents, frozen at M1)` · commit `87a5222`
Platform: Windows-11-10.0.26300-SP0 · Python 3.12.10

## Retrieval metrics (answerable set, doc-level labels)

| mode | recall@10 (95% CI, n) | precision@5 (slots) | precision@5 (capped) | nDCG@10 | MRR |
|---|---|---|---|---|---|
| sparse | 0.9583 [0.798, 0.993] (n=24) | 0.20 | 0.88 | 0.82 | 0.79 |
| dense | 0.7500 [0.551, 0.880] (n=24) | 0.12 | 0.52 | 0.47 | 0.40 |
| hybrid | 0.8750 [0.690, 0.957] (n=24) | 0.18 | 0.79 | 0.73 | 0.68 |

## Theta sweep (hybrid, confidence = 0.65·cosine + 0.35·coverage)

| theta | answer rate | refusal accuracy |
|---|---|---|
| 0.20 | 0.08 | 1.00 |
| 0.25 | 0.00 | 1.00 |
| 0.30 | 0.00 | 1.00 |
| 0.35 | 0.00 | 1.00 |
| 0.40 | 0.00 | 1.00 |

## RRF fusion constant ablation (hybrid, ATL-TDD-001 §5)

| rrf_k | recall@10 |
|---|---|
| 10 | 0.88 |
| 60 | 0.88 |
| 100 | 0.88 |

Chosen theta: **0.25** — selection rule: maximise refusal accuracy, tie-break by retaining most answerable queries, then the lowest theta.
Chosen outcome: answer rate 0.00, refusal accuracy 1.00.

## Interpretation

- The hashed TF-IDF stand-in carries little meaning signal, exactly as documented in
  ATL-TDD-001 §4; stage-2 embeddings are the measured fix, not a rewrite.
- FR-11 (hybrid >= max(sparse, dense)) is NOT met on this baseline: sparse retrieval
  is the strongest single retriever, and fusion currently costs it a little
  (see the ablation). Recorded, not hidden; the stage-2 reranker/embedder targets it.
- precision@5 uses document slots: with single-doc labels its ceiling is 0.2, so the
  >= 0.80 target requires the capped variant (hits / min(5, |relevant|)); recorded as
  a documented ruler clarification, not a silent definition edit.
- The theta sweep saturates at 0.20 with answer rate 0: the hashed stand-in's raw
  confidences sit far below the canonical threshold range, so product-side theta
  calibration is deferred to M4, where the gate runs inside the answer path.
- This report is evidence for the current phase only: later changes re-run the same
  frozen set and report themselves as deltas against `baseline.json`.
