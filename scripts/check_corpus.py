"""Validate the campus corpus (M1 gate).

The corpus is authored by hand and committed; this script is the machine check
that runs locally and in CI before any ingest (policy: ATL-EDD-001 s.5 and s.7).

Checks:
- exactly the 18 expected documents exist in corpus/campus/
- each document has an H1 title, a minimum of 4 sections (H2) and enough words to answer queries

Exit code 1 on any violation; prints a per-document summary table.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus" / "campus"

EXPECTED_IDS = [
    "admission-policy",
    "attendance-policy",
    "backlog-and-attempts",
    "branch-transfer",
    "code-of-conduct-discipline",
    "course-withdrawal",
    "examination-rules",
    "fee-payment-and-refund",
    "grading-system",
    "hostel-rules",
    "internship-guidelines",
    "library-rules",
    "medical-and-counseling",
    "minor-and-honors",
    "placement-policy",
    "scholarship-merit",
    "scholarship-need-based",
    "supplementary-exams",
]

MIN_SECTIONS = 4
MIN_WORDS = 250


def check_document(path: Path) -> tuple[list[str], int, int]:
    """Return (problems, section_count, word_count) for one document."""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip()
    if not title.startswith("# "):
        problems.append("missing H1 title")
    sections = len(re.findall(r"^## ", text, flags=re.M))
    if sections < MIN_SECTIONS:
        problems.append(f"only {sections} sections (needs {MIN_SECTIONS})")
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    if words < MIN_WORDS:
        problems.append(f"only {words} words (needs {MIN_WORDS})")
    return problems, sections, words


def main() -> int:
    found_paths = sorted(CORPUS.glob("*.md"))
    found_ids = {p.stem for p in found_paths}
    problems: list[str] = []

    for doc_id in sorted(set(EXPECTED_IDS) - found_ids):
        problems.append(f"missing document: {doc_id}")
    for doc_id in sorted(found_ids - set(EXPECTED_IDS)):
        problems.append(f"unexpected document: {doc_id}")

    print(f"{'document':34} {'sections':>8} {'words':>8}")
    total_words = 0
    for path in found_paths:
        doc_problems, sections, words = check_document(path)
        total_words += words
        state = "ok" if not doc_problems else "; ".join(doc_problems)
        print(f"{path.stem:34} {sections:>8} {words:>8}   {state}")
        problems.extend(f"{path.stem}: {item}" for item in doc_problems)

    print(f"\n{len(found_paths)} documents, {total_words} words total")
    if problems:
        print("\nFAILED:")
        for item in sorted(problems):
            print(f"  - {item}")
        return 1
    print("corpus ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
