"""Explainable local retrieval using keywords and Chinese character n-grams."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any, Mapping

from .models import (
    ConsentStatus,
    EvidenceCandidate,
    EvidenceType,
    ReviewStatus,
)


_SEMANTIC_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("线上便民平台", "线上办事平台"),
    ("线上平台", "线上办事平台"),
    ("网上", "线上"),
    ("在线", "线上"),
    ("办事系统", "办事平台"),
    ("服务系统", "服务平台"),
    ("遇到困难", "使用困难"),
    ("操作困难", "使用困难"),
    ("不会操作", "使用困难"),
    ("操作不便", "使用困难"),
    ("难以使用", "使用困难"),
    ("协助", "帮助"),
    ("年纪较大", "年长"),
    ("老年人", "年长者"),
    ("二维码", "扫码"),
    ("自助设备", "自助终端"),
    ("在线表格", "电子表单"),
    ("文件上传", "附件上传"),
    ("账户", "账号"),
    ("办理进展", "办理状态"),
    ("状态查询", "进度查询"),
    ("路标", "指示牌"),
    ("座位", "座椅"),
    ("大号字体", "大字版"),
    ("预约通知", "预约提醒"),
    ("准时", "按时"),
    ("流程讲解", "步骤说明"),
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


def chinese_ngrams(text: str, sizes: tuple[int, ...] = (2, 3, 4)) -> set[str]:
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
    # Project metadata such as "受访者" or one shared collection context is
    # repeated across many cards. Including it in lexical scoring creates false
    # independent support, so ranking uses only the card's evidentiary content.
    return " ".join(
        (
            candidate.title,
            candidate.quote,
            candidate.summary,
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

    prepared: list[
        tuple[EvidenceCandidate, str, set[str], set[str], set[str]]
    ] = []
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
        prepared.append(
            (
                candidate,
                candidate_normalized,
                candidate_ngrams,
                candidate_keywords,
                candidate_ascii,
            )
        )

    ngram_df: Counter[str] = Counter()
    keyword_df: Counter[str] = Counter()
    for _, _, candidate_ngrams, candidate_keywords, candidate_ascii in prepared:
        ngram_df.update(candidate_ngrams)
        keyword_df.update(candidate_keywords | candidate_ascii)
    corpus_size = max(1, len(prepared))

    def weight(term: str, frequencies: Counter[str]) -> float:
        return 1.0 + math.log((corpus_size + 1) / (frequencies[term] + 1))

    matches: list[RetrievalMatch] = []
    for (
        candidate,
        candidate_normalized,
        candidate_ngrams,
        candidate_keywords,
        candidate_ascii,
    ) in prepared:

        common_ngrams = query_ngrams & candidate_ngrams
        common_keywords = (query_keywords & candidate_keywords) | (
            query_ascii & candidate_ascii
        )
        query_ngram_weight = sum(weight(term, ngram_df) for term in query_ngrams)
        common_ngram_weight = sum(weight(term, ngram_df) for term in common_ngrams)
        union_ngram_weight = sum(
            weight(term, ngram_df) for term in query_ngrams | candidate_ngrams
        )
        query_keyword_terms = query_keywords | query_ascii
        query_keyword_weight = sum(
            weight(term, keyword_df) for term in query_keyword_terms
        )
        common_keyword_weight = sum(
            weight(term, keyword_df) for term in common_keywords
        )
        ngram_recall = common_ngram_weight / max(1.0, query_ngram_weight)
        ngram_jaccard = common_ngram_weight / max(1.0, union_ngram_weight)
        keyword_recall = common_keyword_weight / max(1.0, query_keyword_weight)
        direct_bonus = (
            0.08
            if query_normalized
            and (
                query_normalized in candidate_normalized
                or candidate_normalized in query_normalized
            )
            else 0.0
        )
        title_topic_overlap = query_ngrams & chinese_ngrams(
            candidate.title, sizes=(4,)
        )
        topic_bonus = min(0.36, 0.12 * len(title_topic_overlap))
        context_topic_overlap = query_ngrams & chinese_ngrams(
            candidate.context, sizes=(4,)
        )
        context_bonus = min(0.18, 0.09 * len(context_topic_overlap))
        coverage_bonus = min(0.08, math.log1p(len(common_ngrams)) / 50)
        score = min(
            1.0,
            0.56 * ngram_recall
            + 0.18 * ngram_jaccard
            + 0.18 * keyword_recall
            + direct_bonus
            + topic_bonus
            + context_bonus
            + coverage_bonus,
        )
        if not common_ngrams and not common_keywords:
            score = 0.0
        distinctive_ngrams = {
            term
            for term in common_ngrams
            if ngram_df[term] <= max(1, corpus_size // 4)
        }
        distinctive_keywords = {
            term
            for term in common_keywords
            if keyword_df[term] <= max(1, corpus_size // 4)
        }
        if (
            not distinctive_ngrams
            and not distinctive_keywords
            and not direct_bonus
            and not title_topic_overlap
            and not context_topic_overlap
        ):
            score = min(score, 0.06)

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
