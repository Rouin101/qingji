"""Deterministic retrieval regression cases for Qingji's demo corpus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .diagnostics import RELEVANCE_THRESHOLD, RETRIEVAL_DIAGNOSTIC_VERSION
from .retrieval import (
    evidence_candidate_from_mapping,
    rank_evidence_with_explanations,
)


@dataclass(frozen=True)
class RetrievalEvalCase:
    name: str
    category: str
    query: str
    expected_title_fragments: tuple[str, ...] = ()
    expected_evidence_ids: tuple[int, ...] = ()
    expect_no_relevant: bool = False


DEFAULT_RETRIEVAL_CASES = (
    RetrievalEvalCase(
        "验证码求助",
        "direct",
        "第一次使用平台时找不到验证码位置，需要志愿者帮助。",
        ("首次使用时需要协助",),
    ),
    RetrievalEvalCase(
        "小样本观察",
        "direct",
        "六名办事者中有人询问登录步骤，也有人独立完成流程。",
        ("6名模拟办事者中的求助情况",),
    ),
    RetrievalEvalCase(
        "工作人员咨询",
        "direct",
        "工作人员收到登录咨询，但还没有分类统计。",
        ("登录咨询存在但未形成分类统计",),
    ),
    RetrievalEvalCase(
        "同义改写求助",
        "paraphrase",
        "网上办事系统不太会用，需要人工协助才能完成申请。",
        ("首次使用时需要协助",),
    ),
    RetrievalEvalCase(
        "无关主题零命中",
        "zero_hit",
        "校园宿舍空调维修进度与夜间噪声情况。",
        expect_no_relevant=True,
    ),
    RetrievalEvalCase(
        "正反体验同时召回",
        "conflict",
        "线上平台有人操作时需要帮助，也有人使用顺利没有遇到困难。",
        (
            "首次使用时需要协助",
            "熟悉线上服务者可独立完成",
        ),
    ),
)


def evaluate_retrieval(
    db: Any,
    project_id: int,
    *,
    top_k: int = 3,
    cases: tuple[RetrievalEvalCase, ...] = DEFAULT_RETRIEVAL_CASES,
) -> dict[str, Any]:
    """Evaluate positive recall and explicit zero-hit behavior at top-k."""

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
        relevant_matches = [
            match for match in matches if match.score >= RELEVANCE_THRESHOLD
        ]
        relevant_titles = [
            match.candidate.title for match in relevant_matches
        ]
        relevant_ids = [int(match.candidate.id) for match in relevant_matches]
        expected_ranks = {
            fragment: next(
                (
                    index
                    for index, title in enumerate(relevant_titles, start=1)
                    if fragment in title
                ),
                None,
            )
            for fragment in case.expected_title_fragments
        }
        expected_id_ranks = {
            evidence_id: (
                relevant_ids.index(int(evidence_id)) + 1
                if int(evidence_id) in relevant_ids
                else None
            )
            for evidence_id in case.expected_evidence_ids
        }
        if case.expect_no_relevant:
            passed = not relevant_matches
        else:
            all_expected_ranks = [
                *expected_ranks.values(),
                *expected_id_ranks.values(),
            ]
            passed = bool(all_expected_ranks) and all(
                rank is not None for rank in all_expected_ranks
            )
        hit_ranks = [
            rank
            for rank in [*expected_ranks.values(), *expected_id_ranks.values()]
            if rank is not None
        ]
        results.append(
            {
                "name": case.name,
                "category": case.category,
                "query": case.query,
                "expected_title_fragments": list(
                    case.expected_title_fragments
                ),
                "expected_evidence_ids": list(case.expected_evidence_ids),
                "expect_no_relevant": case.expect_no_relevant,
                "passed": passed,
                "hit": passed,
                "hit_rank": min(hit_ranks) if hit_ranks else None,
                "expected_ranks": expected_ranks,
                "expected_id_ranks": {
                    str(key): value for key, value in expected_id_ranks.items()
                },
                "relevant_count": len(relevant_matches),
                "relevant_evidence_ids": relevant_ids,
                "relevant_titles": relevant_titles,
                "top_titles": [match.candidate.title for match in matches],
                "top_scores": [round(float(match.score), 4) for match in matches],
            }
        )

    categories: dict[str, dict[str, Any]] = {}
    for result in results:
        summary = categories.setdefault(
            result["category"], {"case_count": 0, "passed_count": 0}
        )
        summary["case_count"] += 1
        summary["passed_count"] += int(result["passed"])
    for summary in categories.values():
        summary["pass_rate"] = (
            summary["passed_count"] / summary["case_count"]
        )

    passed_count = sum(bool(item["passed"]) for item in results)
    return {
        "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
        "top_k": top_k,
        "relevance_threshold": RELEVANCE_THRESHOLD,
        "case_count": len(results),
        "passed_count": passed_count,
        "pass_rate": passed_count / len(results) if results else 0.0,
        "hit_count": passed_count,
        "hit_rate": passed_count / len(results) if results else 0.0,
        "categories": categories,
        "results": results,
    }
