# ADR-0003 — Extractive answers, not generative ones (for now)

**Status:** accepted for the MVP, revisited in stage 2 · **Evidence:** `results/eval_report.md`

## Context
Policy answers carry consequences. A fluent wrong sentence costs more than an awkward right
one, and the project's whole claim is that grounding is measurable.

## Decision
The answer is a bounded selection of sentences taken verbatim from the top passage, with that
passage cited. Grounding (FR-13) is then true by construction, and citation accuracy is 1.0
because there is exactly one citation: the passage the text came from.

## Alternatives rejected
- **LLM generation first.** Rejected for the MVP: without a verifier it makes FR-13 a promise,
  and a verifier without a measured baseline has nothing to be measured against.
- **Template synthesis across passages.** Rejected: multi-passage synthesis needs claim-level
  attribution, which is the verifier's job, not a template's.

## Consequences
Answers read less naturally and cannot summarise across documents. That is the honest cost,
and `docs/13` names the LLM + verifier as the next layer rather than pretending extraction is
the destination.
