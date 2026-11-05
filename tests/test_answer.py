"""Answer-path tests (FR-13..FR-18): extraction stays inside the passage, the gate refuses."""

from __future__ import annotations

import dataclasses

from atlas.answer import answer_query
from atlas.config import SETTINGS
from atlas.interfaces import Answer

OPEN = dataclasses.replace(SETTINGS, confidence_theta=0.0)  # accept tests: gate wide open
SHUT = dataclasses.replace(SETTINGS, confidence_theta=1.0)  # refuse tests: gate shut

# the mini corpus' strongest topic, phrased like the golden set does
CURFEW_QUERY = "what time at night must hostel residents be inside"


def test_accepted_query_is_extractive_and_cited(mini_index):
    result = answer_query(mini_index, CURFEW_QUERY, tenant_id="campus", settings=OPEN)
    assert not result.refused
    assert len(result.citations) == 1  # FR-14: >= 1 citation
    citation = result.citations[0]
    passage = mini_index.search(CURFEW_QUERY, tenant_id="campus", k=1)[0]
    sentences = [s for s in result.text.split(". ") if s]  # FR-13: verbatim sourcing
    assert sentences
    for sentence in sentences:
        assert sentence in passage.text
    assert citation.doc_id == passage.doc_id  # FR-15: citation references the evidence
    assert len(sentences) <= SETTINGS.max_answer_sentences  # FR-18


def test_unanswerable_query_refuses_with_no_citations(mini_index):
    result = answer_query(mini_index, "what is on the mess menu next week", tenant_id="campus")
    assert result.refused
    assert result.citations == ()  # FR-16


def test_gate_boundary_is_respected(mini_index):
    shut = answer_query(mini_index, CURFEW_QUERY, tenant_id="campus", settings=SHUT)
    assert shut.refused
    open_ = answer_query(mini_index, CURFEW_QUERY, tenant_id="campus", settings=OPEN)
    assert not open_.refused


def test_empty_tenant_refuses_instead_of_raising(mini_index):
    result = answer_query(mini_index, CURFEW_QUERY, tenant_id="ghost", settings=OPEN)
    assert result.refused and result.confidence == 0.0 and result.citations == ()


def test_answer_carries_trace_and_timings(mini_index):
    result = answer_query(mini_index, CURFEW_QUERY, tenant_id="campus", settings=OPEN)
    assert result.trace_id and "total_ms" in result.timings_ms
    assert isinstance(result, Answer)
