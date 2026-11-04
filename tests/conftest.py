"""Fixtures: a 3-document mini corpus on a tempfile DB (ATL-EDD-001 s.6).

Tests never touch data/; the real corpus is exercised by the M3 eval harness,
not by these unit-and-contract tests.
"""

from __future__ import annotations

import pytest

from atlas.retrieval import HybridIndex
from atlas.store import Store

# Each paragraph is repeated filler so real chunks split under the 180-token
# budget; the descriptive first sentences are what the retrieval tests query.
MINI_CORPUS = {
    "attendance-policy.md": (
        "# Attendance Policy\n\n"
        "## Condonation\n\n"
        "Students must keep seventy-five percent attendance for every course in a semester. "
        "Below the bar the student is detained and cannot sit the end-term examination. "
        "Condonation applies only between sixty-five and seventy-four percent, for medical "
        "reasons, and it cannot exceed ten percent of the course total.\n\n"
        "## Detention\n\n"
        "A detained course must be repeated by attending it again with the audit fee of five "
        "hundred rupees per course. The repeat audit fee is not waivable and does not "
        "guarantee a pass. Three or more detentions place the student on academic probation "
        "review with the committee."
    ),
    "grading-system.md": (
        "# Grading System\n\n"
        "## Scales\n\n"
        "Grades run AA AB BB BC CC CD DD F carrying ten to zero grade points. "
        "The SGPA is the credit-weighted mean of grade points over one semester. "
        "The CGPA is recomputed every semester and displayed with two decimals only.\n\n"
        "## Pass criteria\n\n"
        "A student passes a course with the DD grade at four points. "
        "An F grade contributes zero points and remains until the course is cleared. "
        "Rounding beyond two decimals never applies anywhere in the computation."
    ),
    "hostel-rules.md": (
        "# Hostel Rules\n\n"
        "## Curfew\n\n"
        "The hostel curfew is at half past ten at night on every day of the week. "
        "Late entries require advance permission from the warden before five in the evening. "
        "Three late entries in one semester lead to a conduct review with the warden.\n\n"
        "## Visitors\n\n"
        "Visitors are permitted on Saturday and Sunday between five and seven in the "
        "evening only. Visitors meet residents in the visitor lounge and never inside "
        "residential rooms. Every entry and exit of a resident is recorded for audit."
    ),
}


@pytest.fixture
def mini_store(tmp_path):
    """A Store with three documents in tenant 'campus' and one in tenant 'other'."""
    db = tmp_path / "atlas-test.db"
    store = Store(db)
    for name, content in MINI_CORPUS.items():
        doc = tmp_path / name
        doc.write_text(content, encoding="utf-8")
        if name == "hostel-rules.md":
            store.upsert_document(tenant_id="other", path=doc)
            continue
        store.upsert_document(tenant_id="campus", path=doc)
    yield store
    store.close()


@pytest.fixture
def mini_index(mini_store):
    """A HybridIndex over the mini corpus ('campus' tenant)."""
    return HybridIndex(mini_store)
