# Evaluation Set — Atlas (campus tenant)

**Frozen rule.** From the moment of commit, this directory is the project's measuring instrument:
labels, doc-id lists and the unanswerable split do **not** change between the MVP and the stage-2
upgrades. Stage 2 is judged as a delta on exactly these queries. Widen the set later by *appending*
new ids (`a0NN`, `u0NN`) and recording an explicitly new baseline — an edit in place is a baseline
change, not a fix (Project Plan §12).

## Schema

| Field | Meaning |
|---|---|
| `id` | stable question id (`a*` = answerable, `u*` = unanswerable) |
| `query` | the natural-language question, exactly as a user would type it |
| `answerable` | true when the corpus contains the answer |
| `relevant_doc_ids` | documents containing the supporting information; empty for `u*` |
| `note` | authoring comment — paraphrase / keyword-mismatch / multi-doc |

## Composition (v1, frozen)

- 24 answerable queries across all 18 corpus documents
- 6 out-of-corpus queries (menu, bus routes, personnel names, wifi, gym, rankings)
- 7 deliberately keyword-mismatched or paraphrased so BM25 alone cannot pass the whole set
- three queries label **two** documents, which penalises retrieval that collapses overlaps

## Authoring-bias disclosure (stated, not hidden)

Labels are single-author (project owner). Real user questions will include phrasings outside this
set; "recall@10 >= 0.90 here" does not imply it everywhere. Adding questions logged from real users
is the sanctioned way to widen the set (Solution Design §10, P1 pilot).

## Targets this set supports (measured in M3; targets per docs/07)

| Metric | Target |
|---|---|
| recall@10 | >= 0.90 |
| precision@5 (capped) | >= 0.80 |
| nDCG@10 | reported |
| refusal accuracy (u-set) | >= 0.95 |

## M3 clarification, recorded (not a silent edit)

The first measured baseline exposed an ambiguity in the frozen table above:
`precision@5` was written without specifying the denominator. With document-level
binary labels (1 relevant document per query), the slot-denominator variant has a
deliberate ceiling of |relevant| / 5 = **0.20**, which no retriever can beat — so a
>= 0.80 target could only ever be met by passing through luck. Clarification:

- `precision@5 (slots)` — the frozen variant, hits / 5, ceiling 0.20. Kept as
  measured in the report for continuity.
- `precision@5 (capped)` — hits / min(5, |relevant|). This is the variant the
  >= 0.80 target refers to; it is computed per query and averaged.

Both definitions and both columns are printed from M3 onward. Labels, doc-id
lists and the unanswerable split remain untouched (they were never ambiguous).

The M3 report also shows the theta sweep saturating (answer rate 0.00 at every
candidate threshold): the hashed TF-IDF stand-in's raw confidence sits far below
the canonical 0.20–0.40 range. Product-side calibrated theta is M4 work, placed
where the gate actually runs inside the answering path.

## v2, appended (M11) — and the rule that keeps it usable

`golden_set_v2.jsonl` is the sanctioned widening: 12 new answerable questions (`v2-0NN`), each
asking a *fact v1 does not ask*, and 6 new unanswerable ones (`v2-uNN`). v1 was not edited, and
the v1 baseline in `results/baseline.json` still describes exactly the 24+6 set it always did.

The rule for a holdout, written here before the numbers were produced:

- **Fit on v1, decide on v2.** Weights, thresholds, rankers and prompts are chosen using v1 only.
- **v2 is read once per decision.** The theta sweep is printed for both sets in
  `results/holdout.md`, but theta is *not* moved to the value that happens to score best on v2 —
  that would consume the set and leave the next claim untested.
- **A v2 pass only counts if v2 can discriminate.** Recall on v2 saturates at 1.0000 for four of
  five configurations, so v2 supports "no relevant document is missed on easy questions" and
  nothing stronger about which ranker wins.

What v2 has already changed: the refusal gate's accuracy was **1.0000 on v1** and **0.1667 on
v2**. That is reported in `README.md` and `results/holdout.md` as a failed generalisation, not
tuned away.

## v3, appended (M13) — because v2 has now been read

`golden_set_v3.jsonl` appends 12 new answerable questions (`v3-0NN`) and 6 unanswerable ones
(`v3-0NN`, ids 013-018). The reason is in the previous paragraph: v2's refusal failure is public,
so tuning against v2 would be tuning against a set whose answers we already know. v3 was written
from the corpus after that result was recorded, and its six unanswerable questions were chosen
from topics the corpus does *not* cover (network passwords, parking, gym, canteen pricing,
duplicate ID cards, sports scholarship) rather than from the failure mode we had just seen. Three
of them are deliberately adjacent to covered ground, because an unanswerable question that shares
no vocabulary with the corpus tests nothing.

The rule extends, it does not change:

- **Fit on v1, decide on v3.** v1 remains the only set anything is tuned on.
- **v3 is read once per decision.** `results/holdout.md` prints every theta for all three sets;
  the threshold still does not move, because moving it now would spend v3 and leave the next
  claim untested.
- **A v2 pass and a v3 pass must agree before anything is adopted.** Two sets that fail the same
  way agree about the failure, which is what makes the M14 work targeted instead of exploratory.

What v3 changed on its first read: refusal accuracy **0.5000** at the shipped theta (v1 1.0000,
v2 0.1667), with answerable and unanswerable confidences still overlapping (0.322 vs 0.497). The
failure replicates. That is the baseline M14 has to beat, and it was measured before any fix was
designed.
