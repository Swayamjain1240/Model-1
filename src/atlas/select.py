"""Sentence selection for the extractive answer (FR-13, FR-18; M15).

The answer is one or two sentences from the retrieved passage, chosen by how much of the query
they cover. That rule has one failure mode that reading the UI found and no aggregate metric did:
every policy document opens with a line that lists its own sections -

    "Limits on the number of attempts for a failed course, carry-forward rules and load
     restrictions for students with backlogs."

- and because that line names every topic in the document, it covers more query words than the
sentence that actually answers. So a question about the number of attempts was answered with the
table of contents (v1 a007, v3-003, v2-006 and three more; `results/answer_selection.md`).

The guard is structural, not fitted: a sentence is a *heading echo* when it is a list of three or
more items, contains no digit, and contains no finite verb - the shape of a topic list rather than
a statement of policy. An echo is disqualified as an answer **only when another sentence in the
passage also matches a query term**, so a document whose only match is its intro still answers
with it rather than returning nothing. Nothing here is tuned: there is no threshold to fit and no
holdout to spend, which is why the measurement is a before/after count on all three question sets
rather than a fitted score.
"""

from __future__ import annotations

import re

from .interfaces import Passage
from .text.tokenize import sentences, tokenize

# A topic list has no finite verb. These are the markers policy prose uses in a statement:
# "must", "is", "requires". A sentence with none of them is describing a topic, not a rule.
_FINITE_VERB = re.compile(
    r"\b(is|are|was|were|be|must|may|can|cannot|will|shall|should|requires?|required|"
    r"applies?|applied|counts?|counted|carries|carried|grants?|granted|pays?|paid|"
    r"allows?|allowed|permits?|permitted|leads?|results?|remains?|stays?)\b",
    re.IGNORECASE,
)


def heading_echo(sentence: str) -> bool:
    """True when the sentence is the document's own topic list, not a statement of policy."""
    stripped = sentence.strip()
    if not stripped or re.search(r"\d", stripped):
        return False  # a number means it is already carrying a fact
    if _FINITE_VERB.search(stripped):
        return False
    items = [part for part in re.split(r",|;|\band\b", stripped) if part.strip()]
    return len(items) >= 3


def is_statement(sentence: str) -> bool:
    """True when the sentence carries a fact: a number or a finite verb.

    Used to check that a replacement sentence is still an answer, rather than another topic list
    (M15's second adoption criterion, `results/answer_selection.md`).
    """
    return bool(re.search(r"\d", sentence)) or bool(_FINITE_VERB.search(sentence))


def select(query: str, passage: Passage, *, max_sentences: int) -> str:
    """The best sentence run from ONE passage, verbatim, bounded, in document order.

    Sentences are scored by how many unseen query tokens they cover; ties fall to document order
    and the join is back in document order, so the output is deterministic and reads naturally.
    """
    wanted = set(tokenize(query))
    split = sentences(passage.text)
    if not split:
        return ""
    split_tokens = [set(tokenize(sentence)) for sentence in split]
    if len(split) > 1 and heading_echo(split[0]) and wanted & set().union(*split_tokens[1:]):
        # The echo may still be joined back for readability, but it can no longer be *chosen*:
        # it answers a question about the document, not the question that was asked.
        split_tokens[0] = set()
    covered: set[str] = set()
    chosen: list[int] = []
    while len(chosen) < max_sentences:
        best_idx, best_gain = -1, 0
        for idx, tokens in enumerate(split_tokens):
            if idx in chosen:
                continue
            gain = len((wanted - covered) & tokens)
            if gain > best_gain:
                best_idx, best_gain = idx, gain
        if best_idx < 0:
            break
        chosen.append(best_idx)
        covered |= split_tokens[best_idx]
    if not chosen:
        chosen = [0]  # query words absent from every sentence: the first-sentence fallback
    return " ".join(split[idx] for idx in sorted(chosen))
