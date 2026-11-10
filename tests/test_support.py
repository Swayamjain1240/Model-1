"""The second refusal signal's own tests (M14, FR-16).

Three properties have to hold for this signal to be worth shipping: it must ignore the words
that ask the question (or every question looks novel), it must need more than one unseen word
(or a single unused adjective refuses an answerable question), and the floor must be a real off
switch. The behaviour on real questions is measured in `results/support.md`.
"""

from __future__ import annotations

from atlas.support import MIN_UNSEEN, content_terms, novelty, refuses, unseen_terms


def test_question_words_are_not_topics() -> None:
    """A question word is not evidence about the corpus, so it is not counted."""
    assert content_terms("what time is the curfew") == ("curfew", "time")


def test_novelty_ignores_question_wording() -> None:
    """The two phrasings ask the same thing; only the unused topic word may differ."""
    vocabulary = {"hostel", "curfew"}
    assert novelty("what is the hostel curfew", vocabulary) == 0.0
    assert novelty("when is the curfew at the hostel", vocabulary) == 0.0


def test_novelty_is_the_share_of_unseen_content_terms() -> None:
    """One unseen topic word out of two, then out of four: the score is the share, not a flag."""
    vocabulary = {"fee", "hostel", "refund"}
    assert novelty("parking fee", vocabulary) == 0.5
    assert novelty("parking permit fee hostel", vocabulary) == 0.5
    assert novelty("parking permit", vocabulary) == 1.0


def test_unseen_terms_lists_only_content_terms() -> None:
    vocabulary = {"fee"}
    assert unseen_terms("what is the parking permit fee", vocabulary) == ("parking", "permit")


def test_confidence_below_theta_always_refuses() -> None:
    """The original gate keeps its authority: the second signal only ever adds refusals."""
    assert refuses(confidence=0.30, theta=0.31, novel=0.0, unseen=0, floor=0.50)


def test_one_unseen_word_is_not_a_missing_topic() -> None:
    """MIN_UNSEEN exists because 'shortest' and 'resolved' are unused words, not absent topics."""
    assert MIN_UNSEEN == 2
    assert not refuses(confidence=0.90, theta=0.31, novel=1.0, unseen=1, floor=0.50)


def test_two_unseen_words_above_the_floor_refuse() -> None:
    assert refuses(confidence=0.90, theta=0.31, novel=0.667, unseen=2, floor=0.50)


def test_floor_is_a_real_off_switch() -> None:
    """0.0 disables the signal even when every content word is unknown."""
    assert not refuses(confidence=0.90, theta=0.31, novel=1.0, unseen=4, floor=0.0)
