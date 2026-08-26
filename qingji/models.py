"""Shared domain types used by storage, workflows, and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class ConsentStatus(StrEnum):
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    DENIED = "denied"


class ProcessingStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    FAILED = "failed"


class EvidenceType(StrEnum):
    INTERVIEW_STATEMENT = "interview_statement"
    STAFF_EXPLANATION = "staff_explanation"
    FIELD_OBSERVATION = "field_observation"
    FORMAL_RECORD = "formal_record"
    TEAM_ANALYSIS = "team_analysis"


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class Verdict(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RedactionSpan:
    kind: str
    original: str
    replacement: str
    start: int
    end: int


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    spans: list[RedactionSpan] = field(default_factory=list)

    @property
    def found_sensitive_data(self) -> bool:
        return bool(self.spans)


@dataclass(frozen=True)
class EvidenceDraft:
    material_id: int
    segment_id: int
    evidence_type: EvidenceType
    title: str
    quote: str
    summary: str
    source_locator: str


@dataclass
class EvidenceCandidate:
    id: int
    material_id: int
    segment_id: int
    title: str
    quote: str
    summary: str
    evidence_type: EvidenceType
    source_role: str
    context: str
    source_locator: str
    review_status: ReviewStatus
    consent_status: ConsentStatus
    relevance: float = 0.0


@dataclass(frozen=True)
class ClaimEvaluation:
    verdict: Verdict
    reason: str
    supporting_evidence_ids: list[int] = field(default_factory=list)
    contradicting_evidence_ids: list[int] = field(default_factory=list)
    context_evidence_ids: list[int] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    safe_rewrite: str = ""
    rule_flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "contradicting_evidence_ids": self.contradicting_evidence_ids,
            "context_evidence_ids": self.context_evidence_ids,
            "missing_evidence": self.missing_evidence,
            "safe_rewrite": self.safe_rewrite,
            "rule_flags": self.rule_flags,
        }


@dataclass(frozen=True)
class MaterialImportResult:
    material_id: int
    redacted_text: str
    evidence_card_ids: list[int]
    claim_candidate_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

