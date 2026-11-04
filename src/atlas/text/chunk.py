"""Structure-aware chunking (ATL-TDD-001 s.2).

Markdown becomes (section, paragraph) pairs, paragraphs become chunks under a
token budget with one paragraph of overlap. The split unit is the paragraph, not
the sentence: sentence fragments lose the subject of a policy, and a policy split
across a boundary must stay retrievable from both sides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import SETTINGS, Settings
from .tokenize import tokenize

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Chunk:
    """One citable passage: the section it ends in, plus its concatenated text."""

    section: str
    text: str


def parse_pairs(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (title, [(section, paragraph), ...]) with title = first H1 (or fallback)."""
    title = ""
    section = "root"
    paragraphs: list[tuple[str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            paragraphs.append((section, " ".join(line.strip() for line in buffer).strip()))
            buffer.clear()

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            level, label = len(heading.group(1)), heading.group(2)
            if level == 1 and not title:
                title = label
            section = label
            continue
        if not line.strip():
            flush()
            continue
        buffer.append(line)
    flush()
    return title, paragraphs


def chunk_document(text: str, *, settings: Settings = SETTINGS) -> list[Chunk]:
    """Emit chunks of at most `chunk_tokens` tokens; overlap by `overlap_paragraphs`.

    The label of a chunk is the section its last paragraph belongs to: chunks
    trail into the next section across the boundary, and the label should name
    the ground the chunk's majority stands on (FR-05).
    """
    _, pairs = parse_pairs(text)
    chunks: list[Chunk] = []
    current: list[tuple[str, str]] = []
    current_tokens = 0

    for pair in pairs:
        pair_tokens = len(tokenize(pair[1]))
        if current and current_tokens + pair_tokens > settings.chunk_tokens:
            chunks.append(_emit(current))
            current = current[-settings.overlap_paragraphs :]
            current_tokens = sum(len(tokenize(item[1])) for item in current)
        current.append(pair)
        current_tokens += pair_tokens
    if current:
        chunks.append(_emit(current))
    return chunks


def _emit(paragraphs: list[tuple[str, str]]) -> Chunk:
    section = paragraphs[-1][0]
    text = "\n\n".join(item[1] for item in paragraphs)
    return Chunk(section=section, text=text)
