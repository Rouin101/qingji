"""Local, deterministic redaction for the text-only MVP.

The module deliberately uses only the Python standard library.  Redaction is
performed against the original string first, then all non-overlapping spans
are replaced in one pass.  This keeps :class:`RedactionSpan` offsets stable and
prevents a phone-number pattern from matching a substring of an ID number.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .models import RedactionResult, RedactionSpan


_PATTERNS: tuple[tuple[str, re.Pattern[str], str, int], ...] = (
    (
        "id_card",
        re.compile(r"(?<![0-9A-Za-z])(?:\d{17}[\dXx]|\d{15})(?![0-9A-Za-z])"),
        "[身份证号]",
        100,
    ),
    (
        "email",
        re.compile(
            r"(?<![A-Za-z0-9._%+-])"
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
            r"(?![A-Za-z0-9._%+-])"
        ),
        "[邮箱]",
        90,
    ),
    (
        "phone",
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        "[手机号]",
        80,
    ),
)


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    kind: str
    original: str
    replacement: str
    priority: int


def _custom_replacements(
    custom_terms: Iterable[str] | Mapping[str, str] | None,
) -> list[tuple[str, str]]:
    if custom_terms is None:
        return []
    if isinstance(custom_terms, Mapping):
        pairs = [
            (str(term), str(replacement) or "[自定义信息]")
            for term, replacement in custom_terms.items()
        ]
    else:
        pairs = [(str(term), "[自定义信息]") for term in custom_terms]
    # Long terms win when one custom term contains another.
    return sorted(
        ((term, replacement) for term, replacement in pairs if term),
        key=lambda item: (-len(item[0]), item[0]),
    )


def _overlaps(left: _Match, right: _Match) -> bool:
    return left.start < right.end and right.start < left.end


def redact_text(
    text: str,
    custom_terms: Iterable[str] | Mapping[str, str] | None = None,
) -> RedactionResult:
    """Redact phone numbers, ID cards, email addresses, and explicit terms.

    ``custom_terms`` may be an iterable of literal strings or a mapping from a
    literal string to its desired replacement.  Literal matching is used so a
    name or address containing regular-expression characters is still safe.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    matches: list[_Match] = []
    for kind, pattern, replacement, priority in _PATTERNS:
        for found in pattern.finditer(text):
            matches.append(
                _Match(
                    start=found.start(),
                    end=found.end(),
                    kind=kind,
                    original=found.group(0),
                    replacement=replacement,
                    priority=priority,
                )
            )

    for term, replacement in _custom_replacements(custom_terms):
        for found in re.finditer(re.escape(term), text):
            matches.append(
                _Match(
                    start=found.start(),
                    end=found.end(),
                    kind="custom",
                    original=found.group(0),
                    replacement=replacement,
                    priority=70,
                )
            )

    # Resolve overlaps globally.  Earlier offsets are preferred; at the same
    # offset the higher-priority and then longer match wins.
    accepted: list[_Match] = []
    for candidate in sorted(
        matches,
        key=lambda item: (
            item.start,
            -item.priority,
            -(item.end - item.start),
            item.kind,
        ),
    ):
        if not any(_overlaps(candidate, existing) for existing in accepted):
            accepted.append(candidate)
    accepted.sort(key=lambda item: item.start)

    if not accepted:
        return RedactionResult(redacted_text=text)

    output: list[str] = []
    cursor = 0
    spans: list[RedactionSpan] = []
    for match in accepted:
        output.append(text[cursor : match.start])
        output.append(match.replacement)
        spans.append(
            RedactionSpan(
                kind=match.kind,
                original=match.original,
                replacement=match.replacement,
                start=match.start,
                end=match.end,
            )
        )
        cursor = match.end
    output.append(text[cursor:])
    return RedactionResult(redacted_text="".join(output), spans=spans)


def redact_sensitive_data(
    text: str,
    custom_terms: Iterable[str] | Mapping[str, str] | None = None,
) -> RedactionResult:
    """Backward-friendly alias for :func:`redact_text`."""

    return redact_text(text, custom_terms)


def detect_sensitive_data(
    text: str,
    custom_terms: Iterable[str] | Mapping[str, str] | None = None,
) -> list[RedactionSpan]:
    """Return detected spans without making callers parse the redacted text."""

    return redact_text(text, custom_terms).spans
