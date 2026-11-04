"""Retrieval tests: contract, determinism, labeled-document smoke (FR-07..FR-09, FR-12)."""

from __future__ import annotations

import pytest
from conftest import MINI_CORPUS

from atlas.interfaces import InputError, Passage
from atlas.retrieval import HybridIndex


def test_supports_all_three_modes(mini_index):
    """FR-07: mode= accepts sparse, dense and hybrid and returns ranked passages."""
    for mode in ("sparse", "dense", "hybrid"):
        passages = mini_index.search("attendance detention", tenant_id="campus", k=5, mode=mode)
        assert passages, f"mode={mode} returned nothing"
        assert all(isinstance(item, Passage) for item in passages)
        assert [item.rank for item in passages] == list(range(len(passages)))


def test_results_are_at_most_k_and_sorted_descending(mini_index):
    """FR-09: len <= k and scores are non-increasing."""
    passages = mini_index.search("academic probation review", tenant_id="campus", k=3)
    assert 0 < len(passages) <= 3
    scores = [item.score for item in passages]
    assert scores == sorted(scores, reverse=True)


def test_search_scope_never_leaves_the_tenant(mini_index):
    """FR-08 at the retrieval contract level: 'Hostel Rules' lives only in tenant 'other'."""
    for query in ("curfew hostel", "visitor lounge"):
        passages = mini_index.search(query, tenant_id="campus", k=10)
        assert all(passage.title != "Hostel Rules" for passage in passages)


def test_cross_tenant_query_finds_hostel_only_for_other(mini_index):
    """The same query against both tenants: each sees only its own rows."""
    campus = mini_index.search("conduct review committee", tenant_id="campus", k=10)
    other = mini_index.search("conduct review committee", tenant_id="other", k=10)
    assert campus and other
    assert any(passage.title == "Hostel Rules" for passage in other)
    assert all(passage.title != "Hostel Rules" for passage in campus)


def test_labeled_query_returns_the_right_document(mini_index):
    """FR-10 spot check on the mini corpus: 'attendance' questions must hit Attendance Policy."""
    passages = mini_index.search("minimum attendance condonation", tenant_id="campus", k=3)
    assert passages[0].title == "Attendance Policy"


def test_identical_queries_are_deterministic_across_instances(tmp_path):
    """FR-12: fresh view (same corpus) has the same ranking order across instances."""
    scores = []
    for _ in range(2):
        store = _fresh_store(tmp_path)
        index = HybridIndex(store)
        try:
            result = [
                (p.chunk_id, p.rank, round(p.score, 6))
                for p in index.search("condonation denied", tenant_id="campus", k=5)
            ]
        finally:
            store.close()
        scores.append(result)
    assert scores[0] == scores[1]


def test_ties_break_by_storage_order(tmp_path):
    """Identical chunks stay in storage order; RRF ranks them by list position."""
    store = _fresh_store(tmp_path, add_duplicate=True)
    index = HybridIndex(store)
    try:
        storage_order = [
            chunk.chunk_id for chunk in store.list_chunks(tenant_id="campus")
        ]
        passages = index.search(
            "students must keep attendance for the course", tenant_id="campus", k=10
        )
        first, second = passages[0], passages[1]
        # RRF cannot rank twins equally: the later twin sits one rank lower in every
        # pool, so it is deterministically penalised, never arbitrarily swapped
        assert first.score >= second.score
        assert storage_order.index(first.chunk_id) < storage_order.index(second.chunk_id)
    finally:
        store.close()


def test_diagnostics_expose_confidence_components(mini_index):
    """The M3 harness needs cosine/coverage/confidence; the seam returns exactly those."""
    report = mini_index.diagnostics("condonation ten percent", tenant_id="campus")
    assert report is not None
    passage, parts = report
    assert set(parts) == {"cosine", "coverage", "confidence"}
    assert 0.0 <= parts["confidence"] <= 1.0
    assert passage.text  # some real passage came back with its components


def test_empty_tenant_returns_empty_list(mini_index):
    assert mini_index.search("anything", tenant_id="ghost", k=5) == []


def test_search_rejects_bad_input(mini_index):
    with pytest.raises(InputError):
        mini_index.search("", tenant_id="campus", k=5)
    with pytest.raises(InputError):
        mini_index.search("x", tenant_id="campus", k=0)


def test_invalidate_picks_up_ingest_changes(tmp_path):
    """Integration: ingest → search → replace content → invalidate → search sees the new text."""
    store = _fresh_store(tmp_path)
    index = HybridIndex(store)
    doc = tmp_path / "grading-system.md"
    extra = MINI_CORPUS["grading-system.md"] + "\n\n## Shock clause\n\nWormholes reset the CGPA."
    doc.write_text(extra, encoding="utf-8")
    store.upsert_document(tenant_id="campus", path=doc)
    index.invalidate("campus")
    passages = index.search("wormholes reset the CGPA", tenant_id="campus", k=5)
    assert any("Wormholes reset the CGPA" in passage.text for passage in passages)
    store.close()


def _fresh_store(tmp_path, *, add_duplicate: bool = False):
    from atlas.store import Store

    store = Store(tmp_path / f"db-{int(add_duplicate)}.sqlite")
    for name, content in MINI_CORPUS.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        store.upsert_document(tenant_id="campus", path=path)
    if add_duplicate:
        dup = tmp_path / "dup.md"
        # the title token set matches the original so the title feature cannot break the tie
        dup.write_text(
            "# Attendance (Policy)\n\n" + MINI_CORPUS["attendance-policy.md"],
            encoding="utf-8",
        )
        store.upsert_document(tenant_id="campus", path=dup)
    return store
