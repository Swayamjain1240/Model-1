# The second refusal signal — does the corpus know the question's words? (M14)

Encoder `potion-base-8M`, theta fixed at 0.31, vocabulary 1027 terms. Baseline is the confidence gate alone; `floor` adds one rule:
refuse when at least that share of the question's content terms occurs nowhere in the
corpus *and* at least 2 such terms exist. Confidence and novelty are measured
once per question, so every grid row below
is the same measurement re-bucketed - there is no second chance to make the signal look
good by re-running something.

## What the signal sees that confidence cannot

| set | class | novelty min | max | mean |
|---|---|---|---|---|
| v1 | answerable | 0.00 | 0.40 | 0.1302 |
| v1 | unanswerable | 0.17 | 0.67 | 0.3778 |
| v2 | answerable | 0.00 | 0.17 | 0.0315 |
| v2 | unanswerable | 0.00 | 0.50 | 0.2532 |
| v3 | answerable | 0.00 | 0.17 | 0.0432 |
| v3 | unanswerable | 0.00 | 0.60 | 0.3798 |

## Before and after the fitted floor

Fitted floor: **0.50** - smallest grid floor strictly above the highest novelty among v1 answerables, and the worst v1 answerable
question has novelty 0.4000. theta does not move.

| set | baseline answer | baseline refusal | + floor answer | + floor refusal |
|---|---|---|---|---|
| v1 | 0.9583 | 1.0000 | 0.9583 | 1.0000 |
| v2 | 0.9167 | 0.1667 | 0.9167 | 0.3333 |
| v3 | 1.0000 | 0.5000 | 1.0000 | 0.6667 |

## Every floor, all three sets

| floor | v1 answer | v1 refusal | v2 answer | v2 refusal | v3 answer | v3 refusal |
|---|---|---|---|---|---|---|
| 0.33 | 0.8750 | 1.0000 | 0.9167 | 0.5000 | 1.0000 | 0.8333 |
| 0.40 | 0.9167 | 1.0000 | 0.9167 | 0.3333 | 1.0000 | 0.8333 |
| 0.50 (fitted) | 0.9583 | 1.0000 | 0.9167 | 0.3333 | 1.0000 | 0.6667 |
| 0.60 | 0.9583 | 1.0000 | 0.9167 | 0.1667 | 1.0000 | 0.5000 |
| 0.67 | 0.9583 | 1.0000 | 0.9167 | 0.1667 | 1.0000 | 0.5000 |
| 0.75 | 0.9583 | 1.0000 | 0.9167 | 0.1667 | 1.0000 | 0.5000 |
| 1.00 | 0.9583 | 1.0000 | 0.9167 | 0.1667 | 1.0000 | 0.5000 |

## Decision

- **Adopted** at floor 0.50: v3 refusal 0.5000 → 0.6667 while the answer rate stays at 1.0000 on v3 and does not fall on v1 or v2.

## Every unanswerable question, before and after

This is the whole evidence for the numbers above - six questions per appended set, so one
row is worth 0.1667 of refusal accuracy. Read it that way.

| set | id | confidence | novelty | unseen terms | refused before | refused after |
|---|---|---|---|---|---|---|
| v1 | u001 | 0.281 | 0.200 | menu | yes | yes |
| v1 | u002 | 0.273 | 0.167 | bus | yes | yes |
| v1 | u003 | 0.281 | 0.400 | head, now | yes | yes |
| v1 | u004 | 0.218 | 0.667 | password, wifi | yes | yes |
| v1 | u005 | 0.299 | 0.333 | gym | yes | yes |
| v1 | u006 | 0.237 | 0.500 | national, ranking | yes | yes |
| v2 | v2-u01 | 0.434 | 0.000 | - | no | no |
| v2 | v2-u02 | 0.334 | 0.000 | - | no | no |
| v2 | v2-u03 | 0.328 | 0.286 | professor, structure | no | no |
| v2 | v2-u04 | 0.259 | 0.400 | accreditation, naac | yes | yes |
| v2 | v2-u05 | 0.406 | 0.500 | degree, duplicate, graduating | no | yes |
| v2 | v2-u06 | 0.424 | 0.333 | cleaning, submitting | no | no |
| v3 | v3-013 | 0.223 | 0.600 | fi, password, wi | yes | yes |
| v3 | v3-014 | 0.340 | 0.429 | car, parking, permit | no | no |
| v3 | v3-015 | 0.290 | 0.500 | gym, membership | yes | yes |
| v3 | v3-016 | 0.305 | 0.250 | canteen | yes | yes |
| v3 | v3-017 | 0.313 | 0.500 | duplicate, identity | no | yes |
| v3 | v3-018 | 0.496 | 0.000 | - | no | no |

## What this signal still cannot see

- **Dilution.** v3-014 fails because three unknown words sit beside four known ones:
  0.429 is below the floor, so a question about parking is answered from hostel rules;
  A share cannot tell a missing topic from a wordy question; only a weighting could.
- **All-attested topics.** v3-018 asks about a sports scholarship using words the corpus
  does use ("sports", "scholarship", "attendance") and scores 0.000 novelty with
  confidence
  0.497. Vocabulary cannot refute a question whose words all exist; that needs meaning.
- **Corpus size.** The floor was fitted on 18 documents and 1027 terms. A tenant with
  far fewer documents has almost no vocabulary, so the floor must be re-fitted per
  corpus - the mini test fixture refuses everything at 0.50 for exactly this reason.

## Questions the signal cannot see

- v2: `v2-006` (weekly), `v2-007` (split), `v2-011` (money), `v2-u03` (professor, structure), `v2-u04` (accreditation, naac), `v2-u05` (degree, duplicate, graduating), `v2-u06` (cleaning, submitting)
- v3: `v3-003` (allowed), `v3-005` (shortest), `v3-007` (wrong), `v3-012` (resolved), `v3-013` (fi, password, wi), `v3-014` (car, parking, permit), `v3-015` (gym, membership), `v3-016` (canteen), `v3-017` (duplicate, identity)
