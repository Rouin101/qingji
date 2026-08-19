"""Small, deterministic retrieval regression set for Qingji's demo corpus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .retrieval import (
    evidence_candidate_from_mapping,
    rank_evidence_with_explanations,
)


@dataclass(frozen=True)
class RetrievalEvalCase:
    name: str
    query: str
    expected_title_fragment: str


DEFAULT_RETRIEVAL_CASES = (
    RetrievalEvalCase(
        "验证码求助",
        "第一次使用平台时找不到验证码位置，需要志愿者帮助。",
        "首次使用时需要协助",
    ),
    RetrievalEvalCase(
        "小样本观察",
        "六名办事者中有人询问登录步骤，也有人独立完成流程。",
        "6名模拟办事者中的求助情况",
    ),
    RetrievalEvalCase(
        "工作人员咨询",
        "工作人员收到登录咨询，但还没有分类统计。",
        "登录咨询存在但未形成分类统计",
    ),
)


def evaluate_retrieval(
    db: Any,
    project_id: int,
    *,
    top_k: int = 3,
    cases: tuple[RetrievalEvalCase, ...] = DEFAULT_RETRIEVAL_CASES,
) -> dict[str, Any]:
    """Measure whether each expected demo card appears within the top-k."""

    if top_k <= 0:
        raise ValueError("top_k 必须为正整数。")
    candidates = [
        evidence_candidate_from_mapping(row)
        for row in db.list_evidence_cards(project_id, review_status="approved")
        if row.get("consent_status") == "confirmed"
    ]
    results: list[dict[str, Any]] = []
    for case in cases:
        matches = rank_evidence_with_explanations(
            case.query, candidates, limit=top_k
        )
        matched_titles = [match.candidate.title for match in matches]
        hit_rank = next(
            (
                index
                for index, title in enumerate(matched_titles, start=1)
                if case.expected_title_fragment in title
            ),
            None,
        )
        results.append(
            {
                "name": case.name,
                "query": case.query,
                "expected_title_fragment": case.expected_title_fragment,
                "hit": hit_rank is not None,
                "hit_rank": hit_rank,
                "top_titles": matched_titles,
            }
        )
    hit_count = sum(bool(item["hit"]) for item in results)
    return {
        "top_k": top_k,
        "case_count": len(results),
        "hit_count": hit_count,
        "hit_rate": hit_count / len(results) if results else 0.0,
        "results": results,
    }
