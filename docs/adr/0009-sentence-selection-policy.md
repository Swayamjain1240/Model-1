# ADR-0009 — A structural guard for topic-list answers, and a corrected adoption rule

**Status:** accepted · **Date:** M15 · **Evidence:** `results/answer_selection.md`

## Context

The extractive answer is one or two sentences chosen by query-term coverage (FR-13). Reading the
answer in the UI showed a failure no aggregate metric had reported: the returned text was the
document's own table of contents —

> Minimum attendance requirements, condonation rules, medical leave and the consequences of
> falling below the attendance bar.

— rather than the sentence holding the 75% rule. The cause is not a bug in scoring. Every policy
document opens with a line listing its sections, and a list of the document's topics necessarily
names more of the question's words than any single statement can. Coverage, measured honestly,
prefers it.

M4 had already tried to fix this by discounting title words and **rejected** that fix
(ADR-0007): 6 of 24 answers changed, 2 became worse, because flattening title-word scores hands
the tie to document order. What M4 lacked was a way to tell a topic list from a statement.

## Decision

Disqualify a heading echo structurally, without fitting anything (`src/atlas/select.py`):

- A sentence is a heading echo when it has **three or more** comma/`and`-separated items, contains
  **no digit**, and contains **no finite verb**. That is the shape of a topic list; a policy
  statement carries a number or a verb ("must", "is", "requires").
- An echo is disqualified **only when another sentence in the same passage also matches a query
  term**, so the fallback for a document whose only match is its intro stays the intro instead of
  producing an empty answer.
- No threshold exists, so nothing is held out; the evidence is a before/after count over all three
  frozen sets (`results/answer_selection.md`).

## The adoption rule I wrote first, and why it was wrong

The pre-registered rule required (a) heading-echo answers fall to zero **and** (b) no answer loses
query-term coverage. (b) fired on `v3-003`, and (b) is the mis-specified half: a topic list covers
more query words *because* it lists them, so requiring the replacement to keep that coverage
requires keeping the defect. Amended before adoption, with both readings reported:

| rule | requirement | outcome |
|---|---|---|
| as pre-registered | echo → 0 **and** no coverage lost | fail |
| amended (decides) | echo → 0 **and** every replacement is a statement | pass |

The amended criterion asks the question that matters — is the new answer still a statement of
policy, or another list of headings? All five replacements carry a digit or a finite verb.

## Consequences

- Heading-echo answers **5 → 0** across v1/v2/v3; 5 answers changed in total, 4 strictly better
  and 1 (`v3-003`) losing only the echo's own words.
- The measured defect that remains is **ranking**, and the report states it in the same place: the
  top-1 passage comes from the labelled document for 18/24, 10/12 and 11/12 questions, with
  recall@10 at 1.0000. The right passage is retrieved and out-ranked, so FR-11 owns the remaining
  wrong answers and no sentence rule can reach them.
- The guard sees only the passage's **opening** sentence, because that is where a document's topic
  list lives. A mid-document summary inside a merged chunk is still eligible; the corpus produces
  none today, and this record does not claim otherwise.
- A verb list is a maintenance surface: a policy sentence phrased entirely with a verb outside
  `_FINITE_VERB` would be read as a topic list. It is guarded by tests on the corpus's real
  headings and on the five changed answers, not by an exhaustive English verb table.

## Alternatives rejected

- **Title-word discounting.** Measured in M4 and worse (ADR-0007).
- **Drop the first sentence of every passage.** Removes the echo but also the topic sentence of
  passages that have no echo, and changes answers the defect never touched.
- **Penalise sentences with many commas.** A list of fees or dates is exactly the kind of sentence
  the answer needs; commas alone do not distinguish a summary from a fact.
- **Fit a classifier on labelled good/bad sentences.** There are five labelled examples in the
  whole project, and M8 already showed what fitting on this corpus's scale does out of sample.
