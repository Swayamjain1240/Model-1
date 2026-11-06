"""Log hygiene (NFR-11): what must never reach a log file, redacted at the boundary.

The service logs request lines, and a request line contains the user's question. Student
questions legitimately contain roll numbers, phone numbers and email addresses, so the log
is a place where personal data arrives by default - which makes redaction a property of the
logger, not a rule someone has to remember.

Patterns are deliberately conservative (a false redaction costs debugging detail, a missed
one costs a person), and this module imports nothing from the pipeline so it can never be
bypassed by a new call site that forgets it: callers import `redact` and that is the API.
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 13-19 digits with optional single separators: card-like, and long IDs generally.
LONG_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){13,18}\d(?!\d)")
# 10-12 digits, optionally with a country code: phone-like (India-first for this corpus).
PHONE = re.compile(r"(?<!\d)(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){9,11}\d(?!\d)")

PLACEHOLDERS = ((EMAIL, "[email]"), (LONG_NUMBER, "[number]"), (PHONE, "[phone]"))


def redact(text: str) -> str:
    """Return `text` with emails, long numbers and phone numbers replaced."""
    for pattern, placeholder in PLACEHOLDERS:
        text = pattern.sub(placeholder, text)
    return text


def contains_personal_data(text: str) -> bool:
    """True when `text` still holds something that looks personal: the audit predicate."""
    return any(pattern.search(text) is not None for pattern, _ in PLACEHOLDERS)
