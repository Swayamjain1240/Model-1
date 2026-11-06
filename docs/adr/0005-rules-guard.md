# ADR-0005 — A deterministic guard, not a model, in front of retrieval

**Status:** accepted · **Date:** M9 · **Evidence:** `results/safety.md`

## Context
NFR-10 asks for a prompt-injection control. The MVP generator is extractive, so today an
injected instruction cannot change an answer — but that is a property of the generator, not
of the interface, and the generator is scheduled to change.

## Decision
Normalise the query, then match a fixed rule set (instruction override, prompt exfiltration,
role-play, bulk exfiltration, delimiter injection, credential probes, encodings). Blocked
queries are a deliberate refusal with no text, not an error. The suite is fixed at 40 strings
and is run twice: as shipped, and with the gate pinned open, so the guard's own rate is visible.

## Alternatives rejected
- **Prompt hardening only.** Rejected: an instruction in the prompt is not a control, and it
  cannot be tested against a fixed suite.
- **A learned classifier now.** Rejected: it would need its own held-out attack set to claim a
  rate, and with 40 examples that claim would be fiction.

## Consequences
The guard blocks 39/40 and misses leetspeak, which is recorded rather than chased with a
pattern per string. False positives are measured on the frozen questions (0 of 30), because a
guard that refuses real questions is a worse product than one that misses a puzzle.
