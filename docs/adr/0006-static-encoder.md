# ADR-0006 — A distilled static encoder instead of a transformer stack

**Status:** accepted · **Date:** M7 · **Evidence:** `results/embeddings.md`

## Context
The MVP's dense side was hashed TF-IDF: deterministic, offline, and semantically blind
(paraphrase cosine ≈ 0). Stage 2 needed real meaning without breaking the offline default
(C-3, NFR-17) or the CPU-only constraint (C-2).

## Decision
Use `potion-base-8M` through `model2vec`: a pretrained, distilled static embedding table with
numpy-only inference, 256 dims. It is opt-in by configuration, and every embedded text is
cached on disk so warm runs need no network.

## Alternatives rejected
- **sentence-transformers / a cross-encoder.** Rejected: torch is a ~2 GB dependency for a
  corpus of 34 chunks, and the clean-clone proof would have to fetch it.
- **Keeping hashed TF-IDF and tuning theta.** Rejected: it optimises the ruler. The measured
  dense recall@10 went 0.75 → 1.00 and the answer rate 0.29 → 0.96 with no gate trickery.

## Consequences
Recall improves and the gate becomes usable, but the encoder is not fine-tuned on this domain,
and the 0.011 gate margin is measured on six unanswerable questions. Both are stated in
`results/embeddings.md` as the limits of the claim.
