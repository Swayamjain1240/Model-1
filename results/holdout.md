# Holdout — the out-of-sample test (M11)

Encoder `potion-base-8M`. v1 is the frozen 24+6 set every earlier number used; v2 is an
appended 12+6 set written after the code was frozen, with its own ids. Nothing in v1
was edited, and no v2 question was used to choose a weight, a threshold or a ranker.
v3 is the second appended set (12+6, M13), written after the v2 refusal failure was
already known and scored here for the first time. **Decisions below are read off v3.**

## Retrieval, all three sets, same configurations

| configuration | v1 recall@10 (95% CI) | v2 recall@10 | v3 recall@10 | v3 p@5 capped | v3 MRR |
|---|---|---|---|---|---|
| sparse | 0.9583 [0.798, 0.993] | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| dense | 1.0000 [0.862, 1.000] | 1.0000 | 1.0000 | 1.0000 | 0.9583 |
| hybrid (fusion only) | 0.9583 [0.798, 0.993] | 1.0000 | 1.0000 | 1.0000 | 0.9583 |
| hybrid + blend (shipped) | 0.9167 [0.742, 0.977] | 1.0000 | 1.0000 | 1.0000 | 0.9583 |
| hybrid + learned | 0.9583 [0.798, 0.993] | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

5 of five configurations reach 1.0000 on
v2, 5 of five on v3, so both appended
sets
are saturated: they say only that no configuration misses a relevant document on
questions like these, which are short, factual and single-document - exactly the traffic
this corpus produces. Neither set can rank the rankers. Their teeth are in the gate, and
that is where both earn their place.

## The gate on the new set: answer rate and refusal accuracy

| set | theta | answer rate | refusal accuracy | n answerable | n unanswerable |
|---|---|---|---|---|---|
| v1 | 0.31 | 0.9583 | 1.0000 | 24 | 6 |
| v2 | 0.31 | 0.9167 | 0.1667 | 12 | 6 |
| v3 | 0.31 | 1.0000 | 0.5000 | 12 | 6 |

## Why it fails: the classes overlap on the only feature the gate uses

| set | class | confidence min | max | mean |
|---|---|---|---|---|
| v1 | answerable | 0.306 | 0.555 | 0.420 |
| v1 | unanswerable | 0.218 | 0.299 | 0.265 |
| v2 | answerable | 0.279 | 0.622 | 0.486 |
| v2 | unanswerable | 0.259 | 0.434 | 0.364 |
| v3 | answerable | 0.322 | 0.602 | 0.486 |
| v3 | unanswerable | 0.223 | 0.497 | 0.328 |

On v1 the six unanswerable questions all sit below the six weakest answerable ones,
which is why theta had a clean gap to land in. On v2 they do not: the lowest
answerable question scores 0.279 and the highest
unanswerable one scores 0.434. No theta separates
the two classes, and across the whole grid the best v2 refusal accuracy reachable is
0.5000 - at the cost of refusing questions the system can answer.

v3 repeats the pattern with different numbers, which is what makes it a replication and
not an anecdote: the weakest answerable question scores
0.322, the strongest unanswerable one
0.497, and the best refusal accuracy any theta can
reach is 0.8333. The classes overlap on confidence in all three sets;
the first set only looked separable because six questions happened to be easy to refuse.

| theta | v1 answer | v1 refusal | v2 answer | v2 refusal | v3 answer | v3 refusal |
|---|---|---|---|---|---|---|
| 0.20 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 |
| 0.25 | 1.0000 | 0.3333 | 1.0000 | 0.0000 | 1.0000 | 0.1667 |
| 0.28 | 1.0000 | 0.5000 | 0.9167 | 0.1667 | 1.0000 | 0.1667 |
| 0.30 | 1.0000 | 1.0000 | 0.9167 | 0.1667 | 1.0000 | 0.3333 |
| 0.31 (shipped) | 0.9583 | 1.0000 | 0.9167 | 0.1667 | 1.0000 | 0.5000 |
| 0.33 | 0.9167 | 1.0000 | 0.9167 | 0.3333 | 0.9167 | 0.6667 |
| 0.35 | 0.8750 | 1.0000 | 0.9167 | 0.5000 | 0.9167 | 0.8333 |
| 0.38 | 0.7500 | 1.0000 | 0.9167 | 0.5000 | 0.8333 | 0.8333 |
| 0.40 | 0.5417 | 1.0000 | 0.9167 | 0.5000 | 0.8333 | 0.8333 |

The shipped theta is **not** moved. Choosing the theta with the fewest v2 mistakes
would consume the holdout and leave the next claim untested, which is the failure mode
this set exists to prevent. The requirement stays open in `README.md` with these
numbers attached.

## Fusion weights: fitted on v1, judged on v3

| sparse weight | dense weight | v1 recall@10 | v2 recall@10 | v3 recall@10 |
|---|---|---|---|---|
| 1.0 | 1.0 | 0.9167 | 1.0000 | 1.0000 |
| 1.5 | 1.0 | 0.9167 | 1.0000 | 1.0000 |
| 2.0 | 1.0 | 0.9167 | 1.0000 | 1.0000 |
| 1.0 | 0.5 | 0.9167 | 1.0000 | 1.0000 |
| 1.0 | 1.5 | 0.9167 | 1.0000 | 1.0000 |
| 1.5 | 0.5 | 0.9167 | 1.0000 | 1.0000 |

## Decisions

- **Fusion weights:** all six settings score identically on all three sets (v1 0.9167, v2 1.0000, v3 1.0000), so this evaluation cannot identify a weight at all: fusion re-orders the same chunks whichever weight is used. **Nothing adopted.** The grid is kept as evidence that the knob is inert on a corpus this small, not as a tuned value.
- **FR-11 on the holdout:** fusion-only scores 1.0000 against dense 1.0000 and sparse 1.0000, a gap of +0.0000. The requirement is met on v2, but v2 saturates, so this is a weak pass: it shows fusion misses nothing on easy questions, not that it matches dense.
- **Refusal generalises:** no on v3 - refusal accuracy 1.0000 on v1, 0.1667 on v2, 0.5000 on v3. Two independent appended sets agree, so
the v1 figure was in-sample and the gate is the open requirement, not a rounding problem.
- **FR-11 on v3:** fusion-only 1.0000 against dense 1.0000 and sparse 1.0000 (+0.0000). Met on v3 as well, with the same saturation caveat.

## Misses, by set and configuration

**v2**

- sparse: none
- dense: none
- hybrid (fusion only): none
- hybrid + blend (shipped): none
- hybrid + learned: none

**v3**

- sparse: none
- dense: none
- hybrid (fusion only): none
- hybrid + blend (shipped): none
- hybrid + learned: none

