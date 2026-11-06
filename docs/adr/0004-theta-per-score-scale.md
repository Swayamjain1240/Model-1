# ADR-0004 — Refusal threshold is safety-first and owned by each score scale

**Status:** accepted · **Date:** M4, extended in M7 · **Evidence:** `results/calibration.md`, `results/embeddings.md`

## Context
Confidence is `0.65·cosine + 0.35·coverage`. A threshold is a policy decision about which
error is worse: answering with a wrong citation, or refusing a question that had an answer.

## Decision
Choose the lowest theta with zero false accepts on the unanswerable set, and require a
declared margin above the hardest unanswerable query. Each embedder carries its own theta,
because cosine values are not comparable across encoders.

## Alternatives rejected
- **Balanced knee (theta 0.09).** Rejected: it let unanswerable questions through as answers
  in the live demo. A refusal is a safe failure; a confident wrong citation is not.
- **One global theta.** Rejected: re-using 0.13 after the M7 encoder swap would have refused
  almost everything while looking like a retrieval failure.

## Consequences
The hashed MVP shipped with an answer rate of 0.08 — measured, reported, and uncomfortable.
M7 recovered it to 0.96 at the same refusal accuracy, which is what made the threshold
decision defensible rather than permanent.
