"""Rule-based claim evaluation for the offline MVP."""

from __future__ import annotations

import re

from .models import ClaimEvaluation, EvidenceCandidate, EvidenceType, Verdict
from .retrieval import RetrievalMatch, rank_evidence_with_explanations


_GROUP_TERMS = ("普遍", "大多数", "多数", "广泛", "整体上", "居民都", "大家都")
_ABSOLUTE_TERMS = ("所有", "全部", "均", "无一例外", "从不", "一定", "必然")
_INTENSITY_TERMS = ("显著", "极大", "严重", "完全", "大幅", "明显提升", "明显下降")
_CAUSAL_TERMS = ("导致", "造成", "引发", "证明", "使得", "因此造成", "必然引起")

_DIFFICULTY_NEGATIONS = (
    "没有遇到困难",
    "未遇到困难",
    "没有困难",
    "不困难",
    "没有遇到问题",
    "未遇到问题",
    "操作顺利",
    "使用顺利",
    "操作顺畅",
    "使用顺畅",
    "很方便",
    "较方便",
    "容易操作",
)
_DIFFICULTY_POSITIVES = (
    "遇到困难",
    "使用困难",
    "操作困难",
    "不会操作",
    "不太会操作",
    "操作不便",
    "使用不便",
    "难以使用",
    "不好用",
    "遇到问题",
    "寻求帮助",
    "需要帮助",
)


def detect_rule_flags(claim_text: str) -> list[str]:
    flags: list[str] = []
    if any(term in claim_text for term in _GROUP_TERMS):
        flags.append("group_generalization")
    if any(term in claim_text for term in _ABSOLUTE_TERMS):
        flags.append("absolute_quantifier")
    if any(term in claim_text for term in _INTENSITY_TERMS):
        flags.append("strong_intensity")
    if any(term in claim_text for term in _CAUSAL_TERMS):
        flags.append("causal_language")
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|％|成|倍|人|份)", claim_text):
        flags.append("precise_quantity")
    return flags


def _stance(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    # Negative-difficulty phrases must be checked before the shorter positive
    # substring "遇到困难".
    if any(phrase in compact for phrase in _DIFFICULTY_NEGATIONS):
        return "smooth"
    if any(phrase in compact for phrase in _DIFFICULTY_POSITIVES):
        return "difficulty"
    return "neutral"


def _relation(
    claim_stance: str,
    match: RetrievalMatch,
) -> str:
    candidate_stance = _stance(
        " ".join(
            (
                match.candidate.quote,
                match.candidate.summary,
                match.candidate.title,
            )
        )
    )
    if claim_stance == "difficulty" and candidate_stance == "smooth":
        return "contradict"
    if claim_stance == "smooth" and candidate_stance == "difficulty":
        return "contradict"
    if claim_stance != "neutral" and candidate_stance == claim_stance:
        return "support"

    # For other claims, require meaningful lexical coverage.  A team analysis
    # remains context even when highly relevant.
    if match.score >= 0.19 and (
        len(match.matched_keywords) >= 1 or len(match.matched_ngrams) >= 2
    ):
        return "support"
    return "context"


def _remove_group_scope(claim_text: str) -> str:
    rewritten = claim_text.strip().rstrip("。；;")
    patterns = (
        r"^(?:当地|本地|受访的)?居民(?:们)?(?:普遍|大多数|多数|广泛|整体上)?认为[，,:：]?",
        r"^(?:所有|全部|大多数|多数)受访者(?:均|都)?(?:认为|表示)[，,:：]?",
        r"^大家都(?:认为|表示)?[，,:：]?",
    )
    for pattern in patterns:
        changed = re.sub(pattern, "", rewritten)
        if changed != rewritten:
            rewritten = changed
            break
    return rewritten or claim_text.strip().rstrip("。")


def _safe_rewrite(
    claim_text: str,
    verdict: Verdict,
    supporting: list[EvidenceCandidate],
) -> str:
    if verdict == Verdict.CONTRADICTED:
        return f"现有材料对“{claim_text.rstrip('。')}”存在不一致表述，暂不宜作统一结论。"
    if verdict == Verdict.UNSUPPORTED:
        return f"当前材料不足以支持“{claim_text.rstrip('。')}”。"

    flags = detect_rule_flags(claim_text)
    rewritten = claim_text.strip().rstrip("。")
    if "group_generalization" in flags or "absolute_quantifier" in flags:
        core = _remove_group_scope(claim_text)
        count = len({candidate.material_id for candidate in supporting})
        if count <= 1:
            rewritten = f"一份已审核材料提到，{core}"
        else:
            rewritten = f"现有{count}份独立材料提到，{core}"
    if "causal_language" in flags:
        rewritten = re.sub(r"导致|造成|引发|使得|因此造成|必然引起", "与", rewritten)
        rewritten += "相关，但现有材料不能单独确认因果关系"
    if "strong_intensity" in flags:
        rewritten = re.sub(r"显著|极大|严重|完全|大幅|明显", "", rewritten)
        rewritten += "；影响程度仍需进一步量化"
    return rewritten.rstrip("。；") + "。"


def _strong_claim_is_proven(
    flags: list[str],
    supporting: list[EvidenceCandidate],
) -> bool:
    if not flags:
        return True
    independent_sources = {candidate.material_id for candidate in supporting}
    formal = [
        candidate
        for candidate in supporting
        if candidate.evidence_type == EvidenceType.FORMAL_RECORD
    ]
    if "absolute_quantifier" in flags:
        return False
    if "group_generalization" in flags and len(independent_sources) < 3:
        return False
    if "causal_language" in flags and not formal:
        return False
    if "strong_intensity" in flags and not any(
        re.search(r"\d+(?:\.\d+)?\s*(?:%|％|倍|人|份)", item.quote)
        for item in formal
    ):
        return False
    if "precise_quantity" in flags and not formal:
        return False
    return True


def evaluate_claim(
    claim_text: str,
    candidates: list[EvidenceCandidate],
    max_candidates: int = 8,
) -> ClaimEvaluation:
    """Evaluate support using only the supplied, eligible candidate IDs."""

    if not isinstance(claim_text, str) or not claim_text.strip():
        raise ValueError("claim_text must not be empty")

    allowed_ids = {candidate.id for candidate in candidates}
    matches = rank_evidence_with_explanations(
        claim_text.strip(), candidates, limit=max_candidates
    )
    # A small threshold removes cards that share only a generic character pair.
    relevant = [match for match in matches if match.score >= 0.08]
    claim_stance = _stance(claim_text)
    supporting: list[EvidenceCandidate] = []
    contradicting: list[EvidenceCandidate] = []
    context: list[EvidenceCandidate] = []

    for match in relevant:
        relation = _relation(claim_stance, match)
        candidate = match.candidate
        if (
            relation == "support"
            and candidate.evidence_type == EvidenceType.TEAM_ANALYSIS
        ):
            relation = "context"
        if relation == "support":
            supporting.append(candidate)
        elif relation == "contradict":
            contradicting.append(candidate)
        else:
            context.append(candidate)

    flags = detect_rule_flags(claim_text)
    missing: list[str] = []
    if "group_generalization" in flags or "absolute_quantifier" in flags:
        missing.extend(
            (
                "补充不同背景参与者的独立材料",
                "明确样本数量、选择方式与结论适用范围",
            )
        )
    if "causal_language" in flags:
        missing.append("补充能够区分因果与相关关系的正式记录或专门设计")
    if "strong_intensity" in flags or "precise_quantity" in flags:
        missing.append("补充可核验的统计口径、样本量和量化记录")

    if contradicting:
        verdict = Verdict.CONTRADICTED
        if supporting:
            reason = (
                f"当前候选材料中有{len(supporting)}项支持核心现象，"
                f"同时有{len(contradicting)}项给出相反经历，不能合并为单一结论。"
            )
        else:
            reason = (
                f"当前找到{len(contradicting)}项与该表述方向相反的已审核材料。"
            )
        missing.append("核对相反材料的对象、时间和场景差异")
    elif supporting:
        if _strong_claim_is_proven(flags, supporting):
            verdict = Verdict.SUPPORTED
            reason = f"当前有{len(supporting)}项已审核、已授权材料直接支持该表述。"
        else:
            verdict = Verdict.PARTIALLY_SUPPORTED
            reason = (
                f"当前有{len(supporting)}项材料支持核心现象，"
                "但结论的范围、强度、数量或因果表达超过了现有证据。"
            )
    else:
        verdict = Verdict.UNSUPPORTED
        reason = "当前候选材料中未找到能够直接支持该表述的已审核证据。"
        missing.append("补充直接记录该现象的访谈、观察或正式资料")

    # Citation validation is deliberately final and explicit: even if future
    # relation logic changes, an ID outside this invocation can never escape.
    support_ids = list(
        dict.fromkeys(item.id for item in supporting if item.id in allowed_ids)
    )
    contradict_ids = list(
        dict.fromkeys(item.id for item in contradicting if item.id in allowed_ids)
    )
    context_ids = list(
        dict.fromkeys(item.id for item in context if item.id in allowed_ids)
    )
    missing = list(dict.fromkeys(missing))
    return ClaimEvaluation(
        verdict=verdict,
        reason=reason,
        supporting_evidence_ids=support_ids,
        contradicting_evidence_ids=contradict_ids,
        context_evidence_ids=context_ids,
        missing_evidence=missing,
        safe_rewrite=_safe_rewrite(claim_text, verdict, supporting),
        rule_flags=flags,
    )


def validate_citation_ids(
    evaluation: ClaimEvaluation,
    candidate_ids: set[int] | list[int] | tuple[int, ...],
) -> bool:
    """Return whether every cited ID belongs to the retrieval candidate set."""

    allowed = set(candidate_ids)
    cited = (
        evaluation.supporting_evidence_ids
        + evaluation.contradicting_evidence_ids
        + evaluation.context_evidence_ids
    )
    return all(evidence_id in allowed for evidence_id in cited)
