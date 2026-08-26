"""Text segmentation and deterministic evidence-card drafting."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import ConsentStatus, EvidenceDraft, EvidenceType, ReviewStatus


@dataclass(frozen=True)
class TextChunk:
    sequence_no: int
    text: str
    locator: str


_ROLE_RULES: tuple[tuple[tuple[str, ...], EvidenceType], ...] = (
    (
        ("受访", "访谈对象", "居民", "村民", "学生", "respondent", "interviewee"),
        EvidenceType.INTERVIEW_STATEMENT,
    ),
    (
        ("工作人", "教师", "辅导员", "负责人", "干部", "staff", "official"),
        EvidenceType.STAFF_EXPLANATION,
    ),
    (
        ("正式记录", "公开资料", "文件", "统计表", "文献", "record", "document"),
        EvidenceType.FORMAL_RECORD,
    ),
    (
        ("现场观察", "观察员", "团队成员", "队员", "observer", "field"),
        EvidenceType.FIELD_OBSERVATION,
    ),
    (
        ("团队分析", "研究者", "分析", "推测", "analysis", "researcher", "team"),
        EvidenceType.TEAM_ANALYSIS,
    ),
)

_TYPE_LABELS = {
    EvidenceType.INTERVIEW_STATEMENT: "受访者陈述",
    EvidenceType.STAFF_EXPLANATION: "工作人员说明",
    EvidenceType.FIELD_OBSERVATION: "现场观察",
    EvidenceType.FORMAL_RECORD: "正式记录",
    EvidenceType.TEAM_ANALYSIS: "团队分析",
}


def evidence_type_for_role(source_role: str) -> EvidenceType:
    """Map a user-provided source role to a conservative evidence type."""

    normalized = (source_role or "").strip().lower()
    for hints, evidence_type in _ROLE_RULES:
        if any(hint in normalized for hint in hints):
            return evidence_type
    # An unknown source should not silently become primary factual evidence.
    return EvidenceType.TEAM_ANALYSIS


def is_retrievable_evidence(row: Mapping[str, Any]) -> bool:
    """Return whether an authorized card remains in the project evidence set."""

    review_status = getattr(
        row.get("review_status"), "value", row.get("review_status")
    )
    consent_status = getattr(
        row.get("consent_status"), "value", row.get("consent_status")
    )
    return (
        review_status != ReviewStatus.REJECTED.value
        and consent_status == ConsentStatus.CONFIRMED.value
    )



def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    pieces = [
        part.strip()
        for part in re.split(r"(?<=[，,、：:])", sentence)
        if part.strip()
    ]
    if len(pieces) == 1:
        return [
            sentence[index : index + max_chars].strip()
            for index in range(0, len(sentence), max_chars)
            if sentence[index : index + max_chars].strip()
        ]

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks


def split_text(text: str, max_chars: int = 320) -> list[TextChunk]:
    """Split text by non-empty paragraph and then sentence boundaries."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if max_chars < 40:
        raise ValueError("max_chars must be at least 40")

    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"(?:\r?\n)\s*(?:\r?\n)*", text)
        if paragraph.strip()
    ]
    chunks: list[TextChunk] = []
    sequence_no = 1
    for paragraph_no, paragraph in enumerate(paragraphs, start=1):
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？!?；;])\s*", paragraph)
            if sentence.strip()
        ]
        if not sentences:
            sentences = [paragraph]
        sentence_no = 1
        for sentence in sentences:
            for piece in _split_long_sentence(sentence, max_chars):
                chunks.append(
                    TextChunk(
                        sequence_no=sequence_no,
                        text=piece,
                        locator=f"第{paragraph_no}段第{sentence_no}句",
                    )
                )
                sequence_no += 1
                sentence_no += 1
    return chunks


def _read_value(record: object, names: Sequence[str], default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return default
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _shorten(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def generate_evidence_drafts(
    material_id: int,
    segments: Sequence[object],
    source_role: str,
    *,
    max_cards: int = 40,
    target_chars: int = 720,
) -> list[EvidenceDraft]:
    """Create bounded, conservative evidence-card drafts from persisted segments.

    A segment may be a mapping or object exposing ``id``/``segment_id``,
    ``redacted_text``/``text``, and optionally ``locator``.

    Segments remain fine-grained in storage for traceability and retrieval, but
    adjacent short segments are merged into a single review card.  This keeps a
    long transcript from producing hundreds of nearly identical review forms
    while preserving the complete redacted quote in the generated cards.
    """

    if isinstance(max_cards, bool) or not isinstance(max_cards, int) or max_cards <= 0:
        raise ValueError("max_cards must be a positive integer")
    if isinstance(target_chars, bool) or not isinstance(target_chars, int) or target_chars < 80:
        raise ValueError("target_chars must be at least 80")

    evidence_type = evidence_type_for_role(source_role)
    label = _TYPE_LABELS[evidence_type]
    normalized_segments: list[tuple[int, str, str]] = []
    for index, segment in enumerate(segments, start=1):
        segment_id = _read_value(segment, ("segment_id", "id"))
        if segment_id is None:
            raise ValueError("every persisted segment must have an id")
        quote = str(
            _read_value(segment, ("redacted_text", "text", "quote"), "")
        ).strip()
        if not quote:
            continue
        locator = str(
            _read_value(segment, ("locator", "source_locator"), f"第{index}段")
        )
        normalized_segments.append((int(segment_id), quote, locator))

    if not normalized_segments:
        return []

    groups: list[list[tuple[int, str, str]]] = []
    current: list[tuple[int, str, str]] = []
    current_chars = 0
    for item in normalized_segments:
        item_chars = len(item[1])
        if current and current_chars + item_chars + 1 > target_chars:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars + (1 if current_chars else 0)
    if current:
        groups.append(current)

    # If natural grouping still creates too many cards, merge adjacent groups
    # evenly.  No segment is dropped; only the review granularity changes.
    if len(groups) > max_cards:
        merged: list[list[tuple[int, str, str]]] = []
        for index in range(max_cards):
            start = index * len(groups) // max_cards
            end = (index + 1) * len(groups) // max_cards
            combined = [item for group in groups[start:end] for item in group]
            if combined:
                merged.append(combined)
        groups = merged

    drafts: list[EvidenceDraft] = []
    for group in groups:
        segment_id = group[0][0]
        quote = " ".join(item[1] for item in group).strip()
        first_locator = group[0][2]
        last_locator = group[-1][2]
        locator = (
            first_locator
            if first_locator == last_locator
            else f"{first_locator}–{last_locator}"
        )
        drafts.append(
            EvidenceDraft(
                material_id=int(material_id),
                segment_id=int(segment_id),
                evidence_type=evidence_type,
                title=f"{label}｜{_shorten(quote, 22)}",
                quote=quote,
                summary=_shorten(quote, 140),
                source_locator=locator,
            )
        )
    return drafts
