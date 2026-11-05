"""The answer path (FR-13..FR-18): gate on confidence, extract, cite, or refuse.

The MVP generator is deliberately extractive: every sentence in the answer is
taken verbatim from the top passage, so "answer contains only sourced text"
(FR-13) holds by construction, and citation accuracy is 1.0 because the only
citation IS the passage the text came from (FR-14, FR-15). Refusal is a
deliberate `Answer` with `refused=True` and no citations (FR-16), never an
exception: an empty tenant is "no documents", which the gate refuses safely.
"""

from __future__ import annotations

import re
import time
import uuid

from .config import SETTINGS, Settings
from .interfaces import Answer, Citation
from .retrieval import HybridIndex
from .text.tokenize import tokenize

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


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
    retrieve_start = total_start
    report = index.diagnostics(query, tenant_id=tenant_id, mode=mode)
    retrieve_ms = (time.perf_counter() - retrieve_start) * 1000.0

    if report is None:
        return Answer(  # no documents at all: refuse, never raise (FR-16)
            query=query,
            text="",
            citations=(),
            confidence=0.0,
            refused=True,
            mode=mode,
            degraded=False,
            timings_ms={"retrieve_ms": _ms(retrieve_ms), "total_ms": _ms(retrieve_ms)},
            trace_id=trace_id,
        )

    passage, parts = report
    confidence = round(parts["confidence"], 4)
    if confidence < settings.confidence_theta:
        return Answer(
            query=query,
            text="",
            citations=(),
            confidence=confidence,
            refused=True,
            mode=mode,
            degraded=False,
            timings_ms={"retrieve_ms": _ms(retrieve_ms), "total_ms": _ms(retrieve_ms)},
            trace_id=trace_id,
        )

    extract_start = time.perf_counter()
    text = _extract(query, passage, max_sentences=settings.max_answer_sentences)
    extract_ms = (time.perf_counter() - extract_start) * 1000.0
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
        degraded=False,
        timings_ms={
            "retrieve_ms": _ms(retrieve_ms),
            "extract_ms": _ms(extract_ms),
            "total_ms": _ms((time.perf_counter() - total_start) * 1000.0),
        },
        trace_id=trace_id,
    )


def _extract(query: str, passage, *, max_sentences: int) -> str:
    """The best sentence run from ONE passage, verbatim, bounded (FR-13, FR-18).

    Sentences are scored by how many unseen query tokens they cover; ties are
    broken by document order, and the join is back in document order, so the
    output is deterministic and reads naturally.
    """
    wanted = set(tokenize(query))
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(passage.text) if s.strip()]
    if not sentences:
        return ""
    sentence_tokens = [set(tokenize(sentence)) for sentence in sentences]
    covered: set[str] = set()
    chosen: list[int] = []
    while len(chosen) < max_sentences:
        best_idx, best_gain = -1, 0
        for idx, tokens in enumerate(sentence_tokens):
            if idx in chosen:
                continue
            gain = len((wanted - covered) & tokens)
            if gain > best_gain:
                best_idx, best_gain = idx, gain
        if best_idx < 0:
            break
        chosen.append(best_idx)
        covered |= sentence_tokens[best_idx]
    if not chosen:
        chosen = [0]  # query words absent from every sentence: the fallback opinion
    return " ".join(sentences[idx] for idx in sorted(chosen))


def _ms(seconds: float) -> float:
    return round(seconds, 3)
