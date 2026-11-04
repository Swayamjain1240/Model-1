"""Deterministic tokenisation: no learned vocabulary, no randomness (ATL-SwDD-001 s.2).

Folds only regular English plurals; irregular forms are left alone. That is a
documented limitation, not a bug: the corpus is policy text where the regular
cases dominate, and stage 2's real embedder is what closes the rest of the gap.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Function words carry almost no retrieval signal here but they do lengthen every
# posting list; the list is fixed in code, never learned from the corpus.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "into", "is", "it", "its", "of", "on", "onto", "or", "per",
        "the", "to", "under", "up", "with", "within", "without",
    }
)


def fold_plural(word: str) -> str:
    """Fold regular plurals; 'ss' endings are protected so 'class' and 'express' survive."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ss") or len(word) <= 3:
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stopword-filtered, plural-folded, in text order."""
    raw = _TOKEN_RE.findall(text.lower())
    return [fold_plural(word) for word in raw if fold_plural(word) not in STOPWORDS]


def bigrams(tokens: list[str]) -> list[str]:
    """Adjacent token pairs, space-joined ('withdrawal window'); empty for len < 2."""
    if len(tokens) < 2:
        return []
    return [f"{left} {right}" for left, right in zip(tokens, tokens[1:], strict=False)]


def sentences(text: str) -> list[str]:
    """Split on sentence-final punctuation while keeping the punctuation attached."""
    if not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]
