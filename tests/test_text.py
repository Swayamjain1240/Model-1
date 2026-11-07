"""Chunker tests: nothing is lost, overlap behaves, labels are traceable (FR-04, FR-05)."""

from __future__ import annotations

import dataclasses

from atlas.config import Settings
from atlas.text.chunk import chunk_document, parse_pairs
from atlas.text.tokenize import bigrams, sentences, tokenize

# line breaks built by name, so multi-paragraph fixtures cannot be mis-read as broken literals
NL = chr(10)
DD = NL + NL


def test_tokenizer_is_deterministic_and_folds_plurals():
    assert tokenize("Courses and classes sessions")[:3] == ["course", "class", "session"]
    assert tokenize("repeat repeat") == ["repeat", "repeat"]
    assert "and" not in tokenize("and without")


def test_bigrams_are_adjacent_pairs():
    tokens = tokenize("withdrawal window closes after three weeks")
    assert bigrams(tokens)[0] == "withdrawal window"
    assert bigrams(["solo"]) == []


def test_sentences_keep_their_punctuation():
    assert sentences("A first rule. A second rule? Final note") == [
        "A first rule.",
        "A second rule?",
        "Final note",
    ]


def test_parse_pairs_tracks_sections_and_title():
    title, pairs = parse_pairs(_TWO_SECTION)
    assert title == "Rulebook"
    assert [section for section, _ in pairs] == ["One", "Two"]


def test_parse_pairs_without_headings_root_is_the_label():
    _, pairs = parse_pairs("Only a paragraph here.")
    assert pairs == [("root", "Only a paragraph here.")]


def test_chunking_preserves_every_paragraph():
    """FR-04: concatenated chunk text must contain every source paragraph verbatim."""
    _, pairs = parse_pairs(_MULTI_SECTION_DOC)
    joined = "\n\n".join(chunk.text for chunk in chunk_document(_MULTI_SECTION_DOC))
    for _, paragraph in pairs:
        assert paragraph in joined


def test_overlap_carries_the_last_paragraph_forward():
    settings = dataclasses.replace(Settings(), chunk_tokens=30, overlap_paragraphs=1)
    chunks = chunk_document(_LONG_DOC, settings=settings)
    assert len(chunks) >= 2
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert later.text.startswith(earlier.text.split("\n\n")[-1])


def test_section_label_is_the_section_holding_most_of_the_chunk():
    """A merged chunk is labelled by its dominant section, never by its last paragraph."""
    doc = NL.join(["# Doc", "", "## Short", "", "Two words here.", "", "## Dominant", "",
                   " ".join(["policy"] * 40), "", "## Trailing", "", "Three more words."])
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].section == "Dominant"


def test_section_label_falls_back_deterministically_on_a_tie():
    doc = NL.join(["# Doc", "", "## First", "", "same size text", "", "## Second", "",
                   "also same size"])
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].section == "First"


def test_a_merged_chunk_still_covers_the_whole_document():
    chunks = chunk_document(_MULTI_SECTION_DOC)
    combined = " ".join(chunk.text for chunk in chunks)
    for paragraph in _MULTI_SECTION_DOC.split(DD):
        text = paragraph.strip()
        if text and not text.startswith("#"):
            assert text in combined


def test_short_or_empty_documents_edge_cases():
    assert chunk_document("") == []
    assert chunk_document("   \n\n  ") == []
    assert len(chunk_document("One short paragraph only.")) == 1
    # a heading-only document keeps its labels but emits no text chunk (ATL-TDD-001 s.2)
    assert chunk_document("# Title\n\n## A Section\n") == []


_TWO_SECTION = (
    "# Rulebook\n\n## One\n\nFirst filler paragraph here.\n\n"
    "## Two\n\nSecond filler paragraph here too."
)

_LONG_DOC = (
    "Paragraph one covers conductor details of the syllabus for this course.\n\n"
    "Paragraph two continues with more redundant text that adds tokens without facts.\n\n"
    "Paragraph three also provides filler so the budget forces a chunk boundary.\n\n"
    "Paragraph four keeps pushing the token count so the split is exercised.\n\n"
    "Paragraph five completes the synthetic document with still more filler."
)

_MULTI_SECTION_DOC = (
    "# Rulebook\n\n"
    "## One\n\n" + "Filler text alpha with enough words to count tokens. " * 6 +
    "## Two\n\n" + "Filler text beta with enough words to count tokens. " * 6 +
    "## Three\n\n" + "Filler text gamma with enough words to count tokens. " * 6
)
