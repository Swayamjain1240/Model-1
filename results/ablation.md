# Ablation — what each layer bought (M10)

Frozen set, 24 answerable questions, doc-level labels, k=10. One change per row;
`hybrid` is the control arm (fusion, no reranker). Intervals are 95% Wilson on n=24,
so a difference smaller than the overlap is not a finding.

The table runs twice on purpose. The stage-2 claim is an interaction — the hand-weighted
blend only double-counts once the dense side carries real meaning — and one encoder
would hide exactly the thing this table is for.

## hashed stand-in (default, offline)

| configuration | recall@10 (95% CI) | Δ recall | p@5 capped | nDCG@10 | MRR |
|---|---|---|---|---|---|
| sparse | 0.9583 [0.7976, 0.9926] | +0.1250 | 0.8750 | 0.8216 | 0.7876 |
| dense | 0.7500 [0.5510, 0.8800] | -0.0833 | 0.5208 | 0.4709 | 0.4016 |
| hybrid | 0.8333 [0.6415, 0.9332] | 0.0000 | 0.8333 | 0.6553 | 0.5965 |
| hybrid + blend | 0.8750 [0.6900, 0.9566] | +0.0417 | 0.7917 | 0.7271 | 0.6802 |
| hybrid + learned | 0.9167 [0.7415, 0.9768] | +0.0834 | 0.8750 | 0.8084 | 0.7782 |

Misses at k=10, by configuration:

- sparse: a009
- dense: a001, a002, a010, a012, a021, a024
- hybrid: a001, a009, a021, a024
- hybrid + blend: a001, a021, a024
- hybrid + learned: a009, a021

## trained encoder (potion-base-8M)

| configuration | recall@10 (95% CI) | Δ recall | p@5 capped | nDCG@10 | MRR |
|---|---|---|---|---|---|
| sparse | 0.9583 [0.7976, 0.9926] | 0.0000 | 0.8750 | 0.8216 | 0.7876 |
| dense | 1.0000 [0.8620, 1.0000] | +0.0417 | 0.9167 | 0.8779 | 0.8451 |
| hybrid | 0.9583 [0.7976, 0.9926] | 0.0000 | 0.9167 | 0.8868 | 0.8692 |
| hybrid + blend | 0.9167 [0.7415, 0.9768] | -0.0416 | 0.9167 | 0.8494 | 0.8229 |
| hybrid + learned | 0.9583 [0.7976, 0.9926] | 0.0000 | 0.9167 | 0.8566 | 0.8281 |

Misses at k=10, by configuration:

- sparse: a009
- dense: none
- hybrid: a009
- hybrid + blend: a009, a021
- hybrid + learned: a009

## What the two tables say together

**hashed stand-in (default, offline).** Fusion 0.8333 vs best single retriever 0.9583 (sparse 0.9583, dense 0.7500). The blend scores 0.8750 (+0.0417 vs control) and the learned weights 0.9167 (+0.0834). Here the blend *helps*, because with a hashed encoder it is the only semantic-ish signal left after fusion.

**trained encoder (potion-base-8M).** Fusion 0.9583 vs best single retriever 1.0000 (sparse 0.9583, dense 1.0000). The blend scores 0.9167 (-0.0416 vs control) and the learned weights 0.9583 (0.0000). Here the blend *costs* recall: with a real encoder it double-counts the lexical evidence and demotes correct chunks — the M7 diagnosis, measured by holding fusion fixed rather than inferred from fusion weights.

## Where the FR-11 gap actually comes from

- **hashed stand-in (default, offline).** Best single retriever 0.9583; fusion alone 0.8333 (-0.1250); best reranked configuration 0.9167 (-0.0416). Fusion alone already trails it, and reranking does not close the gap - so the shortfall is not the ranker's alone.
- **trained encoder (potion-base-8M).** Best single retriever 1.0000; fusion alone 0.9583 (-0.0417); best reranked configuration 0.9583 (-0.0417). Fusion alone already trails it, and reranking does not close the gap - so the shortfall is not the ranker's alone.

FR-11 stays open in the README for any row above where hybrid trails the best single
retriever. What this table adds is attribution: fusion and reranking are measured
separately instead of blamed together.
