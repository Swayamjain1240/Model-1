"""Sentence selection and the heading-echo guard (M15, FR-13).

The guard exists because a document's table of contents out-covers the sentence that answers.
These tests pin the two directions that matter: a topic list is recognised and skipped when the
passage can answer, and a passage whose *only* match is its opening line still answers with that
line rather than returning nothing.
"""

from __future__ import annotations

from atlas.interfaces import Passage
from atlas.select import heading_echo, is_statement, select

ECHO = "Limits on the number of attempts for a failed course, carry-forward rules and load rules."
RULE = "A failed course may be attempted a maximum of 3 times in the regular end-term cycle."


def passage(text: str) -> Passage:
    return Passage(
        chunk_id="c1",
        doc_id="backlog-and-attempts",
        title="Backlog and Attempts",
        section="Attempt limits",
        text=text,
        score=1.0,
        rank=0,
    )


def test_a_topic_list_is_recognised() -> None:
    assert heading_echo(ECHO)


def test_a_policy_statement_is_not_a_topic_list() -> None:
    """A digit or a finite verb means it is carrying a fact, whatever its commas."""
    assert not heading_echo(RULE)
    assert not heading_echo("Students may borrow 4 books, 2 journals and 1 thesis.")
    assert not heading_echo("The mess closes during semester breaks.")


def test_two_item_phrases_are_left_alone() -> None:
    """The guard only fires on lists of three or more, so ordinary enumerations survive."""
    assert not heading_echo("Hostel and mess charges are paid with the tuition instalments.")


def test_statement_check_accepts_numbers_and_verbs() -> None:
    assert is_statement(RULE)
    assert is_statement("Rs 500 is charged per week.")
    assert is_statement("Fees are due on 20 August.")
    assert not is_statement(ECHO)


def test_the_echo_is_skipped_when_the_passage_can_answer() -> None:
    text = f"{ECHO} {RULE}"
    answer = select("how many attempts for a failed course", passage(text), max_sentences=1)
    assert answer == RULE


def test_the_echo_is_kept_when_it_is_the_only_match() -> None:
    """A document whose only query match is its opening line must still answer with it."""
    text = f"{ECHO} Fees are due on 20 August."
    answer = select("attempts failed course carry-forward", passage(text), max_sentences=1)
    assert answer.startswith("Limits on the number of attempts")


def test_selection_is_deterministic_and_in_document_order() -> None:
    text = f"{ECHO} {RULE} A student may carry forward a maximum of 4 pending courses."
    first = select("attempts courses carry forward", passage(text), max_sentences=2)
    second = select("attempts courses carry forward", passage(text), max_sentences=2)
    assert first == second
    assert text.index(first.split(". ")[0]) < len(text)
