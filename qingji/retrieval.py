"""Explainable local retrieval using keywords and Chinese character n-grams."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

from .models import (
    ConsentStatus,
    EvidenceCandidate,
    EvidenceType,
    ReviewStatus,
)


_SEMANTIC_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("网上", "线上"),
    ("在线", "线上"),
    ("办事系统", "办事平台"),
    ("服务系统", "服务平台"),
    ("遇到困难", "使用困难"),
    ("操作困难", "使用困难"),
    ("不会操作", "使用困难"),
    ("操作不便", "使用困难"),
    ("难以使用", "使用困难"),
    ("年纪较大", "年长"),
    ("老年人", "年长者"),
)

_KEYWORD_CANONICAL: tuple[str, ...] = (
    "线上",
    "线下",
    "办事",
    "平台",
    "服务",
    "使用",
    "操作",
    "困难",
    "问题",
    "顺利",
    "顺畅",
    "方便",
    "人工",
    "帮助",
    "协助",
    "居民",
    "受访者",
    "学生",
    "工作人员",
    "年长",
    "安全",
    "满意",
    "不满",
    "等待",
    "效率",
    "流程",
)

_RISK_WORDS = {
    "普遍",
    "所有",
    "全部",
    "大多数",
    "显著",
    "导致",
    "证明",
    "认为",
}


@dataclass(frozen=True)
class RetrievalMatch:
    candidate: EvidenceCandidate
    score: float
    matched_keywords: tuple[str, ...]
    matched_ngrams: tuple[str, ...]

    @property
    def explanation(self) -> str:
        parts: list[str] = []
        if self.matched_keywords:
            parts.append("关键词：" + "、".join(self.matched_keywords))
        if self.matched_ngrams:
            parts.append("字词片段：" + "、".join(self.matched_ngrams[:8]))
        return "；".join(parts) or "未发现直接词面重合"


def normalize_semantics(text: str) -> str:
    normalized = (text or "").lower()
    for source, target in _SEMANTIC_REPLACEMENTS:
        normalized = normalized.replace(source, target)
    return re.sub(r"[\s\u3000，。！？；：、,.!?;:'\"“”‘’（）()\[\]【】\-_/]+", "", normalized)


def chinese_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> set[str]:
    normalized = normalize_semantics(text)
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    output: set[str] = set()
    for run in cjk_runs:
        for size in sizes:
            output.update(
                run[index : index + size]
                for index in range(max(0, len(run) - size + 1))
            )
    return output


def extract_keywords(text: str) -> set[str]:
    normalized = normalize_semantics(text)
    keywords = {
        keyword
        for keyword in _KEYWORD_CANONICAL
        if keyword in normalized and keyword not in _RISK_WORDS
    }
    keywords.update(
        token
        for token in re.findall(r"[a-z][a-z0-9]{1,}|[0-9]+(?:\.[0-9]+)?%?", normalized)
        if len(token) > 1
    )
    return keywords


def _status_value(value: object) -> str:
    return getattr(value, "value", value) if value is not None else ""


def evidence_candidate_from_mapping(
    row: Mapping[str, Any],
) -> EvidenceCandidate:
    """Convert one enriched evidence row into the shared retrieval type."""

    return EvidenceCandidate(
        id=int(row["id"]),
        material_id=int(row["material_id"]),
        segment_id=int(row["segment_id"]),
        title=str(row.get("title", "")),
        quote=str(row.get("quote", "")),
        summary=str(row.get("summary", "")),
        evidence_type=(
            EvidenceType(row["evidence_type"])
            if row.get("evidence_type")
            else EvidenceType.TEAM_ANALYSIS
        ),
        source_role=str(row.get("source_role", "")),
        context=str(row.get("context", "")),
        source_locator=str(
            row.get("source_locator") or row.get("segment_locator") or ""
        ),
        review_status=(
            ReviewStatus(row["review_status"])
            if row.get("review_status")
            else ReviewStatus.DRAFT
        ),
        consent_status=(
            ConsentStatus(row["consent_status"])
            if row.get("consent_status")
            else ConsentStatus.UNKNOWN
        ),
    )


def is_retrievable(candidate: EvidenceCandidate) -> bool:
    return (
        _status_value(candidate.review_status) == ReviewStatus.APPROVED.value
        and _status_value(candidate.consent_status) == ConsentStatus.CONFIRMED.value
    )


def _candidate_text(candidate: EvidenceCandidate) -> str:
    return " ".join(
        (
            candidate.title,
            candidate.quote,
            candidate.summary,
            candidate.context,
            candidate.source_role,
        )
    )


def rank_evidence_with_explanations(
    query: str,
    candidates: list[EvidenceCandidate],
    limit: int = 8,
) -> list[RetrievalMatch]:
    """Rank approved, authorized evidence and retain an explanation per score."""

    if limit <= 0:
        return []
    query_normalized = normalize_semantics(query)
    query_ngrams = chinese_ngrams(query)
    query_keywords = extract_keywords(query)
    query_ascii = set(re.findall(r"[a-z][a-z0-9]{1,}", query_normalized))

    matches: list[RetrievalMatch] = []
    for candidate in candidates:
        if not is_retrievable(candidate):
            continue
        candidate_text = _candidate_text(candidate)
        candidate_normalized = normalize_semantics(candidate_text)
        candidate_ngrams = chinese_ngrams(candidate_text)
        candidate_keywords = extract_keywords(candidate_text)
        candidate_ascii = set(
            re.findall(r"[a-z][a-z0-9]{1,}", candidate_normalized)
        )

        common_ngrams = query_ngrams & candidate_ngrams
        common_keywords = (query_keywords & candidate_keywords) | (
            query_ascii & candidate_ascii
        )
        ngram_recall = len(common_ngrams) / max(1, len(query_ngrams))
        ngram_jaccard = len(common_ngrams) / max(
            1, len(query_ngrams | candidate_ngrams)
        )
        keyword_recall = len(common_keywords) / max(1, len(query_keywords | query_ascii))
        direct_bonus = (
            0.08
            if query_normalized
            and (
                query_normalized in candidate_normalized
                or candidate_normalized in query_normalized
            )
            else 0.0
        )
        coverage_bonus = min(0.08, math.log1p(len(common_ngrams)) / 50)
        score = min(
            1.0,
            0.52 * ngram_recall
            + 0.20 * ngram_jaccard
            + 0.20 * keyword_recall
            + direct_bonus
            + coverage_bonus,
        )
        if not common_ngrams and not common_keywords:
            score = 0.0

        scored_candidate = replace(candidate, relevance=round(score, 6))
        matches.append(
            RetrievalMatch(
                candidate=scored_candidate,
                score=scored_candidate.relevance,
                matched_keywords=tuple(sorted(common_keywords)),
                matched_ngrams=tuple(sorted(common_ngrams)),
            )
        )

    matches.sort(
        key=lambda match: (
            -match.score,
            -len(match.matched_keywords),
            -len(match.matched_ngrams),
            match.candidate.id,
        )
    )
    return matches[:limit]


def rank_evidence(
    query: str,
    candidates: list[EvidenceCandidate],
    limit: int = 8,
) -> list[EvidenceCandidate]:
    """Convenience form returning candidates with their relevance populated."""

    return [
        match.candidate
        for match in rank_evidence_with_explanations(query, candidates, limit)
    ]
