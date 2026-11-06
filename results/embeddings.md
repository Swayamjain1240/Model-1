# Stage-2 embeddings — measured delta against the frozen baseline (M7)

Command: `python -m eval.embeddings` · commit `87a5222` · platform: Windows-11-10.0.26300-SP0
Corpus: `corpus/campus (18 documents, frozen at M1)` · golden set unchanged: 24 answerable + 6 unanswerable (labels, doc ids and split are the M1 originals)

## Retrieval, same ruler (mean over the 24 answerable queries)

| encoder | dim | recall@10 | p@5 capped | nDCG@10 | MRR |
|---|---|---|---|---|---|
| hashed TF-IDF (MVP) · sparse | 1024 | 0.9583 | 0.8750 | 0.8216 | 0.7876 |
| hashed TF-IDF (MVP) · dense | 1024 | 0.7500 | 0.5208 | 0.4709 | 0.4016 |
| hashed TF-IDF (MVP) · hybrid | 1024 | 0.8750 | 0.7917 | 0.7271 | 0.6802 |
| potion-base-8M (stage 2) · sparse | 256 | 0.9583 | 0.8750 | 0.8216 | 0.7876 |
| potion-base-8M (stage 2) · dense | 256 | 1.0000 | 0.9167 | 0.8779 | 0.8451 |
| potion-base-8M (stage 2) · hybrid | 256 | 0.9167 | 0.9167 | 0.8494 | 0.8229 |

## The refusal gate, re-calibrated per score scale

| encoder | theta shipped | answer rate @shipped | refusal @shipped | theta by rule | answer rate @rule | refusal @rule | margin @rule |
|---|---|---|---|---|---|---|---|
| hashed | 0.13 | 0.2917 | 0.6667 | 0.20 | 0.0833 | 1.0000 | +0.0292 |
| trained | 0.31 | 0.9583 | 1.0000 | 0.31 | 0.9583 | 1.0000 | +0.0106 |

Theta is not shared between encoders: confidence is `0.65·cosine + 0.35·coverage`, and a trained encoder's cosines sit on a different scale, so re-using 0.13 would have refused almost everything while looking like a retrieval failure.

## Where the change lands, query by query (hybrid recall@10)

| query | hashed | trained | delta |
|---|---|---|---|
| a001 | 0.00 | 1.00 | +1.00 |
| a002 | 1.00 | 1.00 | +0.00 |
| a003 | 1.00 | 1.00 | +0.00 |
| a004 | 1.00 | 1.00 | +0.00 |
| a005 | 1.00 | 1.00 | +0.00 |
| a006 | 1.00 | 1.00 | +0.00 |
| a007 | 1.00 | 1.00 | +0.00 |
| a008 | 1.00 | 1.00 | +0.00 |
| a009 | 1.00 | 0.00 | -1.00 |
| a010 | 1.00 | 1.00 | +0.00 |
| a011 | 1.00 | 1.00 | +0.00 |
| a012 | 1.00 | 1.00 | +0.00 |
| a013 | 1.00 | 1.00 | +0.00 |
| a014 | 1.00 | 1.00 | +0.00 |
| a015 | 1.00 | 1.00 | +0.00 |
| a016 | 1.00 | 1.00 | +0.00 |
| a017 | 1.00 | 1.00 | +0.00 |
| a018 | 1.00 | 1.00 | +0.00 |
| a019 | 1.00 | 1.00 | +0.00 |
| a020 | 1.00 | 1.00 | +0.00 |
| a021 | 0.00 | 0.00 | +0.00 |
| a022 | 1.00 | 1.00 | +0.00 |
| a023 | 1.00 | 1.00 | +0.00 |
| a024 | 0.00 | 1.00 | +1.00 |

Queries whose hybrid recall changed: 3/24.

## Fusion ablation under the strong dense side (FR-11)

| sparse weight | dense weight | rerank pool | hybrid recall@10 |
|---|---|---|---|
| 1 | 1 | 20 | 0.9167 |
| 1 | 1 | 40 | 0.9167 |
| 1 | 2 | 20 | 0.9167 |
| 1 | 2 | 40 | 0.9167 |
| 1 | 3 | 20 | 0.9167 |
| 1 | 3 | 40 | 0.9167 |
| 2 | 1 | 20 | 0.9167 |
| 2 | 1 | 40 | 0.9167 |

## Rerank blend ablation, fusion held fixed (isolates the true bottleneck)

| fuse | coverage | bigram | title | hybrid recall@10 | p@5 capped | decision |
|---|---|---|---|---|---|
| 0.40 | 0.40 | 0.15 | 0.05 | 0.9167 | 0.9167 | recorded, not shipped |
| 1.00 | 0.00 | 0.00 | 0.00 | 0.9583 | 0.9167 | recorded, not shipped |
| 0.15 | 0.75 | 0.10 | 0.00 | 0.9167 | 0.8750 | recorded, not shipped |

## Cost of the swap

| encoder | cold view build (ms) | diagnostics mean (ms) | diagnostics p95 (ms) | vectors (MB) |
|---|---|---|---|---|
| hashed | 48.84 | 1.76 | 3.12 | 0.139 |
| trained | 40.28 | 1.56 | 3.53 | 0.035 |

## Interpretation

- Dense recall@10 moved 0.7500 -> 1.0000 (+0.2500) with every label,
  metric and query untouched: the ruler did not move, the encoder did.
- Answer rate at the gate moved 0.29 -> 0.96 (+0.67) with refusal accuracy 1.00 on the 6 unanswerable queries. This is the
  limitation M4 recorded honestly (answer rate 0.08) closing for a measured reason:
  confidence = 0.65*cosine + 0.35*coverage, and hashed cosine for a paraphrase is ~0,
  so the gate could not tell 'reworded but present' from 'absent'.
- The gate margin is thin: theta sits +0.0106 above the hardest
  unanswerable query, and n=6. That is a real risk, not a footnote - one reworded
  unanswerable question could flip it, which is exactly what a widened v2 set tests.
- FR-11 (hybrid >= max single retriever) is still NOT met: hybrid 0.9167 vs single-retriever 1.0000. The dense side is now the strongest retriever and the fusion+rerank
  stage is the bottleneck, not the encoder.
- Best fusion row here is sparse 1 : dense 1 with rerank pool 20 at 0.9167, i.e. +0.0000 against the
  committed setting. Selection was made on the same frozen set it is reported on, so it
  is in-sample and stated as such; it is a hypothesis for a trained reranker (M8), not a
  shipped claim, unless the table says otherwise.
- The rerank ablation names the real culprit: fusion weights move nothing (every row 0.9167), while the blend at best reaches 0.9583 against dense-only 1.0000. A hand-tuned  coverage/bigram blend was a proxy for semantics; once the encoder supplies semantics,  the proxy double-counts and demotes correct chunks.
- That best blend is recorded and NOT shipped: choosing it here would be in-sample  selection on the very set that scores it. Replacing the blend with a trained scorer  is the next phase, evaluated on a document-held-out split.
- Cost: the trained encoder is still CPU-only and its vectors are cached on disk, so a
  warm run needs no network (NFR-17); the hashed stand-in stays the default (C-3).

