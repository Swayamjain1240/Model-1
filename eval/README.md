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
