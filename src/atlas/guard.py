"""Input guard: deterministic detection of injection-shaped queries (NFR-10).

Why a rules layer at all, when the MVP generator is extractive and cannot follow
instructions? Because "it cannot happen here" is an argument about today's generator,
not about the interface. The guard sits in front of retrieval, so it keeps holding when
generation is swapped for an LLM - and it is testable now, against a fixed suite, in a
way that a promise is not.

Deliberate bias: this layer is allowed to be strict, because a blocked attack costs a
retry while a successful one costs data. The false-positive check is part of the suite
(`eval/safety.py` asserts every golden-set question still passes), so strictness is
measured rather than assumed.

Patterns are plain regexes on the normalised query: no model, no network, no latency
budget of its own, and the same verdict on every machine (FR-12).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# (category, compiled pattern). Order matters only for the reported label: the first
# match explains the block, which is what an operator needs in a log line.
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b[^.]{0,30}?"
            r"\b(previous|prior|above|earlier|all|any|your)\b[^.]{0,20}?"
            r"\b(instruction|instructions|rules|prompt|prompts|guidelines|policy)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction_override",
        re.compile(
            r"\b(new|updated|real)\s+(instructions?|rules?|system prompt)\s*[:\-]",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"\b(repeat|print|show|reveal|output|display|leak|tell me)\b[^.]{0,25}?"
            r"\b(system prompt|hidden (prompt|instructions|rules)"
            r"|(the|your|its) (instructions|prompt|prompts|rules|guidelines))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_play",
        re.compile(
            r"\b(you are now|from now on you are|act as (an? )?(unrestricted|unfiltered|different)"
            r"|pretend (to be|you are)|jailbreak|do anything now|developer mode)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"\b(list|show|dump|export|reveal|give me|send me)\b[^.]{0,30}?"
            r"\b(all|every|any|other|entire|whole)\b[^.]{0,20}?"
            r"\b(tenants?|organi[sz]ations?|databases?|documents?|users?|records?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"\b(dump|export|exfiltrate)\b[^.]{0,25}?\b(database|corpus|everything you have)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cross_tenant_probe",
        re.compile(
            r"\b(another|other|different)\s+(tenant|organisation|organisations|company)"
            r"\b|\btenant\s*(id|_id)\s*[:=]",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_injection",
        re.compile(
            r"(<\|[a-z_]+\|>)"
            r"|(\[/?INST\])"
            r"|(###\s*(system|instruction|assistant))"
            r"|(^\s*(system|assistant)\s*:)",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "citation_forgery",
        re.compile(
            r"\b(cite|reference|attribute)\b[^.]{0,20}?\b(fake|invented|made[- ]up|nonexistent)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_request",
        re.compile(
            r"\b(api[ _-]?key|password|secret|token|credentials?)\b[^.]{0,20}?"
            r"\b(show|print|reveal|give|list|dump|share)\b"
            r"|\b(show|print|reveal|give|list|dump|share)\b[^.]{0,20}?"
            r"\b(api[ _-]?key|password|secret|token|credentials?)\b",
            re.IGNORECASE,
        ),
    ),
)

# Attack strings that are not English sentences.
_SUSPICIOUS_CHARS = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200b\u200c\u200d\ufeff]")
_BASE64_BLOB = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class Verdict:
    """What the guard decided, and why - the reason goes to the log, never the user."""

    blocked: bool
    category: str = ""
    rule: str = ""


def normalise(query: str) -> str:
    """NFKC-fold and strip zero-width/bidi tricks before matching.

    Homoglyph and bidi padding is the cheapest way to defeat a regex, so the guard
    compares what a human reads, not the raw bytes.
    """
    folded = unicodedata.normalize("NFKC", query)
    return _SUSPICIOUS_CHARS.sub("", folded)


def scan(query: str) -> Verdict:
    """Deterministic verdict for one query; blocked means "do not retrieve, refuse"."""
    text = normalise(query)
    if _CONTROL.search(text):
        return Verdict(True, "encoding", "control_characters")
    if _BASE64_BLOB.search(text):
        return Verdict(True, "encoding", "encoded_payload")
    for category, pattern in RULES:
        match = pattern.search(text)
        if match is not None:
            return Verdict(True, category, match.group(0).strip()[:60])
    return Verdict(False)
