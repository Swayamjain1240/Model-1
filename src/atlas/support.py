"""The second refusal signal (FR-16, M14): does the corpus know the question's words?

The confidence gate answers one question - "how well does the best passage match this query on
the embedder's scale" - and two holdout sets showed that one question is not enough: refusal
accuracy 1.0000 on v1 (where theta was fitted) against 0.1667 and 0.5000 on v2 and v3. The
classes overlap on confidence, so *no* theta separates them (`results/holdout.md`).

This module adds a signal that is not a function of the retrieved passage or of the embedding:
whether each of the question's terms occurs **anywhere in the tenant's corpus at all**. A question
about canteen prices cannot be answered from a corpus that never says "canteen", however similar
the wording looks to a fee document, and a similarity score cannot see that - it only ever looks
at the one passage it chose.

Two details that make this independent rather than a second view of the same number:

- the vocabulary is corpus-level (the sparse index's idf keys), not passage-level;
- it counts only absence, so it is invisible to a passage that happens to score high on cosine.

The known bias is deliberate: policy prose reuses its own vocabulary, so an answerable question
phrased in words the corpus never uses will look novel. That is why the floor is fitted on v1 and
decided on v3, and why the adoption rule requires that not one answerable question is refused.

Two corrections came from reading the first measurement rather than from a theory of it:

- **Question words were being counted as unknown vocabulary.** The tokeniser's stopword list is
  deliberately short (function words only), so "what", "how", "much" and "i" were absent from
  the corpus and inflated every question's novelty by a fixed amount. `QUESTION_WORDS` removes
  them: they cannot name a policy topic, so their absence says nothing about answerability.
- **One unseen word is weak evidence.** A modifier the corpus happens not to use ("shortest",
  "resolved") leaves an answerable question as novel as "gym membership", which is a topic the
  corpus does not carry at all. So the rule needs at least two unseen content terms before it
  refuses, and the count is measured, not assumed.
"""

from __future__ import annotations

from collections.abc import Collection

from .text.tokenize import tokenize

# Interrogatives, auxiliaries, pronouns and a few generic verbs: words that ask about a topic
# rather than naming one. Fixed in code and never learned, so two processes score a question
# identically. Deliberately kept separate from STOPWORDS, which feeds retrieval - widening that
# list would change every committed retrieval number for a reason that has nothing to do with it.
QUESTION_WORDS = frozenset(
    {
        "how", "what", "when", "where", "which", "who", "whom", "whose", "why",
        "is", "are", "am", "was", "were", "be", "been", "being", "do", "does", "did",
        "can", "could", "shall", "should", "will", "would", "may", "might", "must",
        "i", "me", "my", "we", "our", "us", "you", "your", "he", "she", "it", "its",
        "they", "them", "their", "there", "this", "that", "these", "those", "if",
        "much", "many", "some", "any", "all", "more", "most", "other", "also", "than",
        "get", "got", "take", "taken", "happen", "happens", "done", "make", "made",
        "need", "needed", "want", "like", "because", "please", "tell",
    }
)


def content_terms(query: str) -> tuple[str, ...]:
    """The question's distinct terms that could name a policy topic, sorted."""
    return tuple(sorted(set(tokenize(query)) - QUESTION_WORDS))


def unseen_terms(query: str, vocabulary: Collection[str]) -> tuple[str, ...]:
    """The question's content terms the corpus has never contained, sorted.

    `vocabulary` is the sparse index's key set, so a term is "seen" when some chunk in the
    tenant's corpus tokenises to it - after stopword removal and plural folding, the same
    transform both the index and the query go through.
    """
    return tuple(term for term in content_terms(query) if term not in vocabulary)


def novelty(query: str, vocabulary: Collection[str]) -> float:
    """Share of the question's content terms the corpus has never contained, in [0, 1].

    0.0 means every content word is attested somewhere in the corpus (which does not mean the
    question is answerable - see v3's sports-scholarship question); 1.0 means none are.
    """
    terms = content_terms(query)
    if not terms:
        return 0.0
    return round(sum(1 for term in terms if term not in vocabulary) / len(terms), 4)


# Two unseen content terms, not one: a single unused modifier is not a topic the corpus lacks.
MIN_UNSEEN = 2


def refuses(
    *, confidence: float, theta: float, novel: float, unseen: int, floor: float
) -> bool:
    """The combined decision: below the confidence gate, or a topic the corpus does not carry.

    `floor` of 0.0 disables the second signal entirely, which is the shipped default until a
    floor is adopted on committed evidence (`results/support.md`).
    """
    if confidence < theta:
        return True
    return floor > 0.0 and unseen >= MIN_UNSEEN and novel >= floor
