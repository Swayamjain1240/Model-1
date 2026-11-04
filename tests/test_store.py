"""Store tests: idempotent ingest, no orphans, tenancy enforced (FR-01..03, FR-06, FR-08)."""

from __future__ import annotations

import pytest
from conftest import MINI_CORPUS

from atlas.interfaces import TenantError
from atlas.store import Store


def test_ingest_reports_at_least_one_chunk_per_document(mini_store):
    counts = mini_store.stats(tenant_id="campus")
    assert counts["documents"] == 2
    assert counts["chunks"] >= counts["documents"]  # FR-01: at least one chunk per document


def test_double_ingest_is_a_no_op(tmp_path):
    """FR-02: the same content twice must not change any count."""
    doc = tmp_path / "doc.md"
    doc.write_text(MINI_CORPUS["attendance-policy.md"], encoding="utf-8")
    store = Store(tmp_path / "db.sqlite")
    first = store.upsert_document(tenant_id="campus", path=doc)
    counts_after_first = store.stats(tenant_id="campus")
    second = store.upsert_document(tenant_id="campus", path=doc)
    assert first > 0
    assert second == 0
    assert store.stats(tenant_id="campus") == counts_after_first
    store.close()


def test_edited_document_leaves_no_orphan_chunks(tmp_path):
    """FR-03: a changed document replaces all of its chunks; none of the old text survives."""
    doc = tmp_path / "doc.md"
    doc.write_text(MINI_CORPUS["attendance-policy.md"], encoding="utf-8")
    store = Store(tmp_path / "db.sqlite")
    store.upsert_document(tenant_id="campus", path=doc)
    changed = MINI_CORPUS["attendance-policy.md"].replace(
        "Condonation applies only between", "Dismissal applies only between"
    ).replace("## Detention", "## Dismissal Section Zed")
    doc.write_text(changed, encoding="utf-8")
    returned = store.upsert_document(tenant_id="campus", path=doc)
    assert returned > 0
    stored = store.list_chunks(tenant_id="campus")
    joined = "\n".join(chunk.text for chunk in stored)
    assert "Dismissal applies only between" in joined  # the new paragraph is stored
    assert all("Condonation applies only between" not in text for text in joined.split("\n"))
    assert all(chunk.section != "Detention" for chunk in stored)  # the old heading is gone
    # every stored *paragraph* must be reachable from the new document text (no orphans);
    # a chunk may legitimately span a heading boundary, so check paragraph by paragraph
    for chunk in stored:
        for paragraph in chunk.text.split("\n\n"):
            assert paragraph in changed
    store.close()


def test_ingest_rejects_empty_tenant(tmp_path):
    """FR-06: ingest without a tenant writes nothing and raises."""
    doc = tmp_path / "doc.md"
    doc.write_text("Some text.\n\nMore text.\n", encoding="utf-8")
    store = Store(tmp_path / "db.sqlite")
    with pytest.raises(TenantError):
        store.upsert_document(tenant_id="", path=doc)
    assert store.stats(tenant_id="campus") == {"documents": 0, "chunks": 0}
    store.close()


def test_tenants_are_isolated(mini_store):
    """FR-08: reads under tenant 'campus' can never surface 'other' rows."""
    campus_titles = {chunk.title for chunk in mini_store.list_chunks(tenant_id="campus")}
    other_titles = {chunk.title for chunk in mini_store.list_chunks(tenant_id="other")}
    assert campus_titles == {"Attendance Policy", "Grading System"}
    assert other_titles == {"Hostel Rules"}


def test_chunk_ids_stay_stable_when_a_document_changes(tmp_path):
    """Stable ids mean a rebuild cannot silently invalidate old citations."""
    doc = tmp_path / "doc.md"
    doc.write_text(MINI_CORPUS["grading-system.md"], encoding="utf-8")
    store = Store(tmp_path / "db.sqlite")
    store.upsert_document(tenant_id="campus", path=doc)
    ids_first = [chunk.chunk_id for chunk in store.list_chunks(tenant_id="campus")]
    doc.write_text(MINI_CORPUS["grading-system.md"] + "\n\nExtra paragraph.\n", encoding="utf-8")
    store.upsert_document(tenant_id="campus", path=doc)
    ids_second = [chunk.chunk_id for chunk in store.list_chunks(tenant_id="campus")]
    assert ids_first == ids_second[: len(ids_first)]  # a prefix of stable ids survives the edit
    store.close()
