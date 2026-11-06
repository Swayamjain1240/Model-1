# ADR-0001 — One process, SQLite, and an in-memory index

**Status:** accepted · **Date:** M2 · **Evidence:** `results/bench.md`, `results/handover.md`

## Context
The corpus is 18 documents (34 chunks) and the operator is one person. The system must be
demonstrable, measurable and reproducible from a clean clone on a laptop, with no network.

## Decision
One Python process serves HTTP; SQLite is the store; each tenant's vectors and BM25
postings live in memory, rebuilt lazily per tenant and invalidated as a whole on ingest.

## Alternatives rejected
- **A vector database (pgvector, Qdrant) in a container.** Rejected: it adds an operational
  surface the project then has to explain, and at 34 chunks it measures nothing that matters.
  The honest scaling answer is written down instead (`docs/13`), not improvised.
- **In-memory only, no database.** Rejected: ingest idempotency (FR-02) and content-hash
  replacement (FR-03) are requirements, and they need durable state.

## Consequences
Tenant views are O(corpus) to build, which is fine at this size and becomes the first thing
to change at millions of chunks. Cross-tenant isolation is enforced by SQL predicates, not by
a query planner's good behaviour.
