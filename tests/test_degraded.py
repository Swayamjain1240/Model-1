"""Circuit breaker and degraded-mode tests (NFR-16, FR-13).

The breaker's job is to stop a failing dependency from being paid for twice; the
answer path's job is to keep answering from retrieved evidence and label it. Both are
pinned here, including the cooldown, which is tested by moving an injected clock rather
than sleeping for it.
"""

from __future__ import annotations

import dataclasses

import pytest

from atlas.answer import answer_query
from atlas.breaker import CircuitBreaker, CircuitOpen
from atlas.config import SETTINGS


def test_breaker_opens_after_the_threshold_and_closes_after_cooldown():
    now = [0.0]
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=10.0, clock=lambda: now[0])

    def boom():
        raise RuntimeError("provider down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call(boom)
    assert breaker.state == "open"
    with pytest.raises(CircuitOpen):
        breaker.call(lambda: "never runs")

    now[0] = 11.0  # cooldown elapsed: one trial is allowed again
    assert breaker.state == "half_open"
    assert breaker.call(lambda: "recovered") == "recovered"
    assert breaker.state == "closed"


def test_a_success_resets_the_failure_count():
    breaker = CircuitBreaker(threshold=3, clock=lambda: 0.0)

    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        breaker.call(boom)
    breaker.call(lambda: "ok")
    assert breaker.failures == 0
    assert breaker.state == "closed"


def test_generation_failure_degrades_to_a_verbatim_passage(mini_index, monkeypatch):
    import atlas.answer as answer_module

    answer_module._GENERATOR_BREAKER.reset()
    monkeypatch.setenv("ATLAS_FAULT", "generator")
    query = "What is the attendance requirement?"
    tenant = SETTINGS.default_tenant
    # the mini corpus is three documents, so the gate would refuse before generation;
    # this test is about the breaker, so the threshold is pinned out of the way
    forced = dataclasses.replace(SETTINGS, confidence_theta=0.0)
    first = answer_query(mini_index, query, tenant_id=tenant, settings=forced)
    second = answer_query(mini_index, query, tenant_id=tenant, settings=forced)
    degraded = answer_query(mini_index, query, tenant_id=tenant, settings=forced)
    state = answer_module._GENERATOR_BREAKER.state
    monkeypatch.delenv("ATLAS_FAULT")
    answer_module._GENERATOR_BREAKER.reset()

    # every failing request still answers - degraded, never a 500 the caller cannot read
    assert first.refused is False and second.refused is False
    assert first.degraded is True and second.degraded is True and degraded.degraded is True
    # ...and after the threshold the call is skipped rather than retried
    assert state == "open"

    passage = mini_index.diagnostics(query, tenant_id=tenant)[0]
    assert degraded.text in passage.text  # FR-13 survives the degraded path
    assert degraded.citations[0].chunk_id == passage.chunk_id
