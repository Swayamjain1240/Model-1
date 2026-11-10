# ADR-0008 — Two refusal signals, one fitted on v1 and judged on v3

**Status:** accepted · **Date:** M14 · **Evidence:** `results/support.md`, `results/holdout.md`

## Context

M11 and M13 measured the same failure twice. The refusal gate is a single threshold on one
number, `confidence = 0.65·cosine + 0.35·idf_coverage`, and that number's two classes overlap:

| set | answerable confidence (min–max) | unanswerable (min–max) | refusal @ θ=0.31 |
|---|---|---|---|
| v1 | 0.306–0.555 | 0.218–0.299 | 1.0000 |
| v2 | 0.279–0.622 | 0.259–0.434 | 0.1667 |
| v3 | 0.322–0.602 | 0.223–0.497 | 0.5000 |

On v1 a gap existed, because the six unanswerable questions happened to score low. On the two
appended sets there is no gap, so **no value of θ** separates the classes; v1's 1.0000 was
in-sample. Raising θ trades answers for refusals at roughly 1:1 and was rejected in ADR-0007.

## Decision

Add a second, independent signal: **vocabulary novelty** — the share of a question's *content*
terms that occurs nowhere in the tenant's corpus (`src/atlas/support.py`). A request is refused
when confidence is below θ, **or** when at least 50% of its content terms are unknown to the
corpus **and** at least two of them are.

Independence matters more than cleverness. Confidence only ever inspects the passage it already
chose; novelty inspects the whole corpus and never looks at the passage. It also fixes a modelling
asymmetry: the reranker treats an unseen term as `idf = 1.0`, the *least* important weight, so a
word the corpus has never contained was being scored as if it hardly mattered.

## Rules, fixed before the run

1. **Fit on v1.** The floor is the smallest grid value strictly above the highest novelty among
   v1's answerable questions (0.40 → floor 0.50). θ does not move.
2. **Decide on v3**, with v2 reported as a replication.
3. **Adopt only if** v3 refusal improves, v3 answer rate does not fall, v2 answer rate does not
   fall, and v1 answer rate stays 1.0000.
4. Two unseen content terms minimum: a single unused modifier ("shortest", "resolved") is not a
   missing topic.

Those rules were written down before the measurement, including the correction that followed the
first (broken) version of the signal: it had counted "what", "how" and "i" as unknown vocabulary,
making the score partly a count of pronouns. The defect and its fix are in the module docstring
and the report, not silently absorbed.

## Consequences

- v3 refusal accuracy 0.5000 → 0.6667 and v2 0.1667 → 0.3333, with **no answerable question
  refused on any set**. On six-question sets that is one question each way; it is an improvement,
  not a repair.
- The gate stays **open as FR-16**. Two failures survive, for different reasons: v3-014 fails on
  dilution (three unknown words beside four known ones scores 0.429), and v3-018 uses only words
  the corpus contains ("sports", "scholarship", "attendance") and scores 0.000 novelty at 0.497
  confidence, above θ. Vocabulary cannot refute a question whose words all exist; that needs a
  semantic check, which this project does not have.
- The floor is calibrated for 18 documents / 1,027 terms. A tenant with far fewer documents has
  almost no vocabulary and must re-fit; the test fixture refuses everything at 0.50 for exactly
  that reason, which is why the answer-path tests disable the signal explicitly.
- API consumers get `refusal_reason` and `unseen`, so a UI can say *why* instead of blaming the
  threshold. The page uses both.

## Alternatives rejected

- **Move θ.** Costs answerable questions 1:1 and consumes a holdout (ADR-0007).
- **Cover the question with the passage (`idf_coverage`) as a second signal.** It is already 35%
  of confidence; a floor on it is a second view of the same number, not a second signal.
- **Rank margin between top-1 and top-2.** Independent in principle, but on this corpus the top
  two passages are frequently two chunks of the same document, so the margin measures chunking,
  not uncertainty. Not measured, therefore not adopted.
- **Retrain the blend/reranker to separate the classes.** M8 already showed a learned ranker loses
  out of sample; re-tuning it on v2/v3 would consume both sets.
