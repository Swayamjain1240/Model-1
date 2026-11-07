# ADR-0007 — An appended holdout, and a threshold that is not allowed to move

**Status:** accepted · **Date:** M11 · **Evidence:** `results/holdout.md`

## Context
Every number in the project - recall, answer rate, refusal accuracy 1.0000 - came from one
24+6 question set that was also the set used to choose theta, the rerank blend, and the
adoption rule for the trained reranker. A set that both fits and grades cannot tell you whether
anything generalises. M8 had already shown the cost of that in miniature: a reranker that looked
fine in-sample lost 0.10 recall on documents it had not seen.

## Decision
Append a second set (`eval/golden_set_v2.jsonl`, 12 answerable + 6 unanswerable) rather than
editing v1, and adopt one procedural rule: **fit on v1, decide on v2.** The v2 question that
matters is "does this generalise?", not "what is the best number?", so:

- Theta is **not** moved to the value that scores best on v2, even though v2 invites it
  (0.35 would lift v2 refusal accuracy from 0.17 to 0.50).
- Fusion weights are **not** adopted from a grid that ties on both sets.
- The v2 sweep is committed (`results/holdout.md`) exactly as measured, including the rows
  that make the system look worse.

## Alternatives rejected
- **Edit v1 in place to add the new questions.** Rejected: it changes the baseline every
  earlier report is a delta against, and the project rule forbids it.
- **Move theta to 0.35 using the v2 sweep.** Rejected: that consumes the holdout on the first
  use. The next claim would again be untested, which is the failure this exists to stop.
- **Report only the passing metrics from v2 (recall 1.0000).** Rejected: v2 saturates on
  retrieval, so its recall result is weak evidence and is labelled as such.

## Consequences
Two claims get weaker and are now stated as such: the refusal gate does not generalise
(1.0000 on v1, 0.1667 on v2, classes overlapping on the only feature the gate uses), and FR-11's
v2 pass is a weak one because every ranker ties at 1.0000. In exchange, the retrieval result is
now an out-of-sample result rather than a fit, and the honest answer to "how accurate is the
refusal?" has a number from a set the design never saw.

The remaining fix is a second, independent refusal signal - not a different threshold on the
same one. Until that exists, the API keeps returning `confidence` with every answer so a client
can present it instead of trusting a binary decision.
