"""The v2 set and the theta table (M11).

These tests guard the two cheap failure modes of a holdout: a label file that drifts from its
own rules, and a theta table that silently stops being monotone (which would let a "sweep"
report a threshold that answers more questions the higher it is set).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from eval.holdout import V2_PATH, load_v2, theta_table  # noqa: E402

GRID = (0.20, 0.25, 0.30, 0.31, 0.35, 0.40)


def test_v2_set_keeps_its_shape() -> None:
    """12 answerable and 6 unanswerable, appended - v1 is untouched by construction."""
    answerable, unanswerable = load_v2()
    assert len(answerable) == 12
    assert len(unanswerable) == 6
    assert all(row["id"].startswith("v2-") for row in answerable + unanswerable)
    assert all(row["answerable"] for row in answerable)
    assert not any(row["answerable"] for row in unanswerable)


def test_v2_labels_name_documents_that_exist() -> None:
    """A label pointing at a missing document would mark every configuration wrong."""
    corpus = {path.stem for path in (ROOT / "corpus" / "campus").glob("*.md")}
    answerable, _ = load_v2()
    for row in answerable:
        unknown = set(row["relevant_doc_ids"]) - corpus
        assert not unknown, f"{row['id']} labels unknown documents: {sorted(unknown)}"


def test_v2_questions_are_not_duplicates_of_v1() -> None:
    """v2 must be new questions, not paraphrases of the set the design was fitted to."""
    import json

    v1 = [
        json.loads(line)
        for line in (ROOT / "eval" / "golden_set.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    v1_queries = {row["query"].strip().lower() for row in v1}
    rows = [
        json.loads(line)
        for line in V2_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        assert row["query"].strip().lower() not in v1_queries, row["id"]


def test_theta_table_is_monotone() -> None:
    """Raising theta can never answer more questions or refuse fewer."""
    profile = {
        "v1": {
            "answerable": [0.55, 0.44, 0.33, 0.31, 0.29],
            "unanswerable": [0.30, 0.28, 0.22],
        },
        "v2": {
            "answerable": [0.62, 0.41, 0.279],
            "unanswerable": [0.434, 0.33, 0.259],
        },
    }
    table = theta_table(profile, GRID)
    assert [row["theta"] for row in table] == list(GRID)
    for label in ("v1", "v2"):
        answers = [row[label]["answer_rate"] for row in table]
        refusals = [row[label]["refusal_accuracy"] for row in table]
        assert answers == sorted(answers, reverse=True), label
        assert refusals == sorted(refusals), label
