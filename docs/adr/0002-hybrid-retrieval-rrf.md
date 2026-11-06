# ADR-0002 — Hybrid retrieval with reciprocal rank fusion

**Status:** accepted · **Date:** M2 · **Evidence:** `results/eval_report.md`, `results/fr11_diagnosis.md`

## Context
Policy questions mix exact terms (fee amounts, percentages, form names) with paraphrase.
Sparse retrieval wins on the first, dense on the second, and the corpus is small enough to
run both on every query.

## Decision
Retrieve top-50 from BM25 and top-50 from the vector side, fuse by RRF (k=60, swept in the
ablation), rerank the fused pool, return k.

## Alternatives rejected
- **Dense only.** Rejected at M2: hashed vectors scored recall@10 0.75 against sparse 0.96,
  so a dense-only MVP would have measured the stand-in, not the design.
- **Score blending (weighted sum of BM25 and cosine).** Rejected: the two scores have
  different, corpus-dependent scales, and normalising them per query hides that.

## Consequences
Fusion is rank-based and therefore insensitive to scale, which is why it survived the M7
encoder swap unchanged. It is also why the M7 ablation could not fix FR-11 by reweighting:
with equal-weight RRF every weight produced 0.9167.
