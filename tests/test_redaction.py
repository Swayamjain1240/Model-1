"""Log hygiene tests (NFR-11): personal data never reaches a log line.

The service logs request lines, and a request line is the user's question. These tests
pin that emails, phone numbers and long card-like numbers are replaced at the logger.
"""

from __future__ import annotations

import pytest

from atlas.obs import contains_personal_data, redact

PERSONAL = [
    "my email is ravi.kumar@example.com what is the attendance rule",
    "call me on 9876543210 about the hostel curfew",
    "card 4111 1111 1111 1111 was charged twice for the exam fee",
    "+91 9123456780 please confirm my condonation",
    "roll number 123456789012 attendance correction",
    "write to priya.sharma+exam@college.example.edu about detention",
]


@pytest.mark.parametrize("line", PERSONAL)
def test_personal_values_are_removed(line):
    cleaned = redact(line)
    assert contains_personal_data(cleaned) is False
    assert "example.com" not in cleaned
    assert "4111 1111 1111 1111" not in cleaned


def test_redaction_keeps_the_shape_of_the_log_line():
    cleaned = redact("GET /v1/ask?q=call+9876543210+about+the+curfew")
    assert cleaned.startswith("GET /v1/ask?q=call+")
    assert "curfew" in cleaned  # the useful part survives


def test_ordinary_policy_text_is_not_redacted():
    line = "[atlas] 127.0.0.1 GET /v1/ask?q=attendance+rule+for+semester+4 HTTP/1.1 200"
    assert redact(line) == line
