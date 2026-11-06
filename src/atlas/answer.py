"""The answer path (FR-13..FR-19): gate on confidence, extract, cite, or refuse.

The MVP generator is deliberately extractive: every sentence in the answer is
taken verbatim from the top passage, so "answer contains only sourced text"
(FR-13) holds by construction, and citation accuracy is 1.0 because the only
citation IS the passage the text came from (FR-14, FR-15). Refusal is a
deliberate `Answer` with `refused=True` and no citations (FR-16), never an
exception: an empty tenant is "no documents", which the gate refuses safely.
FR-19: an empty or stopword-only query is an InputError (HTTP 400 upstream).
"""

from __future__ import annotations

import os
import time
import uuid

from .breaker import CircuitBreaker, CircuitOpen
from .config import SETTINGS, Settings
from .guard import scan
from .interfaces import Answer, Citation, DependencyError, InputError, Passage
from .retrieval import HybridIndex
from .text.tokenize import sentences, tokenize

# One breaker per process: generation is a shared dependency, not a per-request one.
_GENERATOR_BREAKER = CircuitBreaker(threshold=SETTINGS.breaker_threshold)


def answer_query(
    index: HybridIndex,
    query: str,
    *,
    tenant_id: str,
    settings: Settings = SETTINGS,
    mode: str = "hybrid",
) -> Answer:
    """One question in, one cited extractive answer or a refusal out (FR-13..FR-17)."""
    trace_id = uuid.uuid4().hex[:16]
    total_start = time.perf_counter()
    if not tokenize(query):
        raise InputError("empty or stopword-only query")  # FR-19, maps to 400
    verdict = scan(query)  # NFR-10: refuse injection-shaped input before retrieval
    if verdict.blocked:
        return Answer(
            query=query,
            text="",
            citations=(),
            confidence=0.0,
            refused=True,
            mode="blocked",
            degraded=False,
            timings_ms={
                "retrieve_ms": 0.0,
                "gate_ms": _ms(time.perf_counter() - total_start),
                "extract_ms": 0.0,
                "total_ms": _ms(time.perf_counter() - total_start),
            },
            trace_id=trace_id,
        )

    retrieve_start = time.perf_counter()
    report = index.diagnostics(query, tenant_id=tenant_id, mode=mode)
    retrieve_ms = (time.perf_counter() - retrieve_start) * 1000.0
    gate_start = time.perf_counter()

    if report is not None:
        passage, parts = report
        confidence = round(parts["confidence"], 4)
        # theta follows the embedder's score scale (settings.theta), never a global
        gate_passes = confidence >= settings.theta
    else:
        passage, confidence, gate_passes = None, 0.0, False
    gate_ms = (time.perf_counter() - gate_start) * 1000.0
    timings = {
        "retrieve_ms": _ms(retrieve_ms),
        "gate_ms": _ms(gate_ms),
        "extract_ms": 0.0,
        "total_ms": _ms((time.perf_counter() - total_start) * 1000.0),
    }
    if not gate_passes:
        return Answer(  # refusal is deliberate, never an exception (FR-16, FR-17)
            query=query,
            text="",
            citations=(),
            confidence=confidence,
            refused=True,
            mode=mode,
            degraded=False,
            timings_ms=timings,
            trace_id=trace_id,
        )

    extract_start = time.perf_counter()
    degraded = False
    try:
        text = _GENERATOR_BREAKER.call(
            lambda: _extract(query, passage, max_sentences=settings.max_answer_sentences)
        )
    except (CircuitOpen, DependencyError, TimeoutError):
        # NFR-16 degraded mode: generation failed or was skipped, so answer from the
        # retrieved passage verbatim and SAY SO (degraded=True). The breaker's job is to
        # stop paying the failure twice: after the threshold, the call is not attempted
        # at all, which is the difference between a degraded answer and a slow one.
        text = passage.text[: settings.citation_snippet_chars]
        degraded = True
    timings["extract_ms"] = _ms((time.perf_counter() - extract_start) * 1000.0)
    timings["total_ms"] = _ms((time.perf_counter() - total_start) * 1000.0)
    citations = (
        Citation(
            chunk_id=passage.chunk_id,
            doc_id=passage.doc_id,
            title=passage.title,
            section=passage.section,
            snippet=text[: settings.citation_snippet_chars],
        ),
    )
    return Answer(
        query=query,
        text=text,
        citations=citations,
        confidence=confidence,
        refused=False,
        mode=mode,
        degraded=degraded,
        timings_ms=timings,
        trace_id=trace_id,
    )


def _extract(query: str, passage: Passage, *, max_sentences: int) -> str:
    """The generator. `_failing()` is the fault injection the degraded path is measured with."""
    if _failing():
        raise DependencyError("simulated generator failure")
    """The best sentence run from ONE passage, verbatim, bounded (FR-13, FR-18).

    Sentences are scored by how many unseen query tokens they cover; ties are
    broken by document order, and the join is back in document order, so the
    output is deterministic and reads naturally.
    """
    wanted = set(tokenize(query))
    split = sentences(passage.text)
    if not split:
        return ""
    split_tokens = [set(tokenize(sentence)) for sentence in split]
    covered: set[str] = set()
    chosen: list[int] = []
    while len(chosen) < max_sentences:
        best_idx, best_gain = -1, 0
        for idx, tokens in enumerate(split_tokens):
            if idx in chosen:
                continue
            gain = len((wanted - covered) & tokens)
            if gain > best_gain:
                best_idx, best_gain = idx, gain
        if best_idx < 0:
            break
        chosen.append(best_idx)
        covered |= split_tokens[best_idx]
    if not chosen:
        chosen = [0]  # query words absent from every sentence: the first-sentence fallback
    return " ".join(split[idx] for idx in sorted(chosen))


def _ms(seconds: float) -> float:
    return round(seconds, 3)


def _failing() -> bool:
    """Fault injection for the degraded-mode evidence (ATLAS_FAULT=generator)."""
    return os.environ.get("ATLAS_FAULT", "") == "generator"
