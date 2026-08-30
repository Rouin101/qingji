"""Explainable retrieval diagnostics for persisted claim checks."""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from .evidence import is_retrievable_evidence

from .models import ClaimEvaluation
from .retrieval import (
    chinese_ngrams,
    evidence_candidate_from_mapping,
    extract_keywords,
    rank_evidence_with_explanations,
)


RETRIEVAL_DIAGNOSTIC_VERSION = "local_weighted_ngram_v2"
RELEVANCE_THRESHOLD = 0.08
MAX_EVALUATION_CANDIDATES = 8


def build_retrieval_diagnostic(
    claim_text: str,
    evidence_rows: Sequence[Mapping[str, Any]],
    material_rows: Sequence[Mapping[str, Any]],
    evaluation: ClaimEvaluation,
) -> dict[str, Any]:
    """Describe eligibility, ranking, thresholding, and final citation use."""

    eligible_rows: list[Mapping[str, Any]] = []
    excluded_evidence: list[dict[str, Any]] = []
    for row in evidence_rows:
        reasons: list[str] = []
        if row.get("review_status") == "rejected":
            reasons.append("证据卡已被人工排除")
        if row.get("consent_status") != "confirmed":
            reasons.append("来源材料尚未确认授权")
        if reasons or not is_retrievable_evidence(row):
            excluded_evidence.append(
                {
                    "evidence_id": int(row["id"]),
                    "title": row.get("title") or f"证据 E{row['id']}",
                    "reasons": reasons or ["证据卡当前不可引用"],
                }
            )
        else:
            eligible_rows.append(row)

    candidates = [
        evidence_candidate_from_mapping(row) for row in eligible_rows
    ]
    ranked_matches = rank_evidence_with_explanations(
        claim_text,
        candidates,
        limit=max(1, len(candidates)),
    )
    relation_by_id = {
        **{
            int(item): "support"
            for item in evaluation.supporting_evidence_ids
        },
        **{
            int(item): "contradict"
            for item in evaluation.contradicting_evidence_ids
        },
        **{
            int(item): "context"
            for item in evaluation.context_evidence_ids
        },
    }

    ranked_candidates: list[dict[str, Any]] = []
    for position, match in enumerate(ranked_matches, start=1):
        evidence_id = int(match.candidate.id)
        if position > MAX_EVALUATION_CANDIDATES:
            decision = "outside_top_k"
        elif match.score < RELEVANCE_THRESHOLD:
            decision = "below_threshold"
        else:
            decision = relation_by_id.get(evidence_id, "not_cited")
        ranked_candidates.append(
            {
                "rank": position,
                "evidence_id": evidence_id,
                "title": match.candidate.title,
                "score": round(float(match.score), 4),
                "matched_keywords": list(match.matched_keywords),
                "matched_ngrams": list(match.matched_ngrams[:8]),
                "explanation": match.explanation,
                "decision": decision,
                "source_locator": match.candidate.source_locator,
            }
        )

    material_ids_with_cards = {
        int(row["material_id"]) for row in evidence_rows
    }
    excluded_materials: list[dict[str, Any]] = []
    for material in material_rows:
        material_id = int(material["id"])
        if material_id in material_ids_with_cards:
            continue
        consent = material.get("consent_status")
        if consent == "denied":
            reason = "记录或使用授权已被拒绝，未生成证据卡"
        elif consent != "confirmed":
            reason = "授权状态未确认，未生成可引用证据卡"
        else:
            reason = "当前材料没有可供检索的证据卡"
        excluded_materials.append(
            {
                "material_id": material_id,
                "name": material.get("original_filename") or f"材料 M{material_id}",
                "reason": reason,
            }
        )

    relevant_count = sum(
        item["rank"] <= MAX_EVALUATION_CANDIDATES
        and item["score"] >= RELEVANCE_THRESHOLD
        for item in ranked_candidates
    )
    cited_count = sum(
        item["decision"] in {"support", "contradict", "context"}
        for item in ranked_candidates
    )
    return {
        "version": RETRIEVAL_DIAGNOSTIC_VERSION,
        "query": claim_text,
        "query_keywords": sorted(extract_keywords(claim_text)),
        "query_ngrams": sorted(chinese_ngrams(claim_text))[:20],
        "relevance_threshold": RELEVANCE_THRESHOLD,
        "max_evaluation_candidates": MAX_EVALUATION_CANDIDATES,
        "total_evidence_cards": len(evidence_rows),
        "eligible_count": len(eligible_rows),
        "excluded_evidence_count": len(excluded_evidence),
        "excluded_material_count": len(excluded_materials),
        "relevant_count": relevant_count,
        "cited_count": cited_count,
        "ranked_candidates": ranked_candidates,
        "excluded_evidence": excluded_evidence,
        "excluded_materials": excluded_materials,
    }
