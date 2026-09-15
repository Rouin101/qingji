"""Rule-based claim evaluation for the offline MVP."""

from __future__ import annotations

import re

from collections.abc import Mapping

from .models import ClaimEvaluation, EvidenceCandidate, EvidenceType, Verdict
from .retrieval import RetrievalMatch, normalize_semantics, rank_evidence_with_explanations

CLAIM_RULE_VERSION = "conservative_boundaries_v3"
_QUANTITY = re.compile(r"(?<!第)(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+)\s*(?:%|％|成|倍|人|份|次(?!说明|告知)|个|元|天|小时|分钟)")
_NEGATION = re.compile(r"(?:并非|没有|禁止|取消|不|未)(?=不|在|开放|提供|增加|减少|延长|完成|参加|支持|允许|开展|通过|改善|解决|存在|需要|使用|收到|找到|帮助|提升|降低|保留|认可|同意|满意|成功)")
_EXISTENTIAL = re.compile(r"(?:一名|一位|一个|有些|部分|个别|有)(?:模拟)?(?:受访者|居民|用户|学生|访客|参与者)")


def _boundary_relation(
    claim: str,
    quote: str,
    relation: str,
    *,
    semantic_support: bool = False,
) -> tuple[str, str]:
    """Veto unsafe relations, including model advice, using the source quote.

    Only identical propositions with a changed number/negation are treated as
    direct contradictions. Ambiguous scope or alignment stays context.
    """
    query = normalize_semantics(claim)
    source = normalize_semantics(quote)
    if not source:
        return "context", "补充能够回溯到原文的直接证据"
    if relation == "support" and re.search(r"不能证明|尚未确认|未能证实|不确定|可能|据说|推测|计划|预计", quote):
        return "context", "原文含有推测、计划或未确认表述，不能直接当作已发生的事实"
    for pattern in (r"受访者([甲乙丙丁ABCD])", r"周[一二三四五六日天末]", r"\d{4}年(?:\d{1,2}月)?(?:\d{1,2}日)?"):
        left, right = set(re.findall(pattern, claim)), set(re.findall(pattern, quote))
        if left and right and left.isdisjoint(right):
            return "context", "核对材料与结论的对象、时间是否一致"
    if _EXISTENTIAL.search(claim) and relation == "contradict":
        return "context", "不同参与者的体验可以并存，不能据此否定个例的存在"

    quantities = set(_QUANTITY.findall(claim))
    # A single person in an existential statement is a scope marker, not an
    # aggregate statistic. Other quantities still require literal alignment.
    if _EXISTENTIAL.search(claim):
        quantities.discard("一个")
    quantities = {re.sub(r"\s", "", value).replace("％", "%") for value in quantities}
    source_quantities = {re.sub(r"\s", "", value).replace("％", "%") for value in _QUANTITY.findall(quote)}
    if quantities:
        if not quantities.issubset(source_quantities):
            same_statement = _QUANTITY.sub("#", query) == _QUANTITY.sub("#", source)
            return ("contradict" if same_statement else "context"), "核对原文中的具体数量、单位与统计口径"
        if query not in source and not semantic_support:
            return "context", "数量相同不等于统计对象相同，请核对数量对应的完整表述"
        if (
            query not in source
            and semantic_support
            and re.search(r"(?:实际|实到|最终|仅有|只有)", source)
            and len(source_quantities) > len(quantities)
        ):
            return "context", "原文含有实际值或限制值，请核对数量对应的完整表述"

    query_negations = _NEGATION.findall(query)
    source_negations = _NEGATION.findall(source)
    if max(len(query_negations), len(source_negations)) > 1:
        return "context", "原文或结论含有多重否定，需要人工核对语义"
    query_negative = bool(query_negations)
    source_negative = bool(source_negations)
    if query_negative != source_negative:
        if _NEGATION.sub("", query) == _NEGATION.sub("", source):
            return "contradict", "原文与结论的肯定、否定方向相反"
        if relation == "support" and not semantic_support:
            return "context", "原文含有不同的否定表达，需要核对完整语义"
    return relation, ""


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
    "需要协助",
    "寻求协助",
    "需要人工帮助",
    "需要工作人员帮助",
    "需要现场人员帮助",
    "存在困难",
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
    if _QUANTITY.search(_EXISTENTIAL.sub("参与者", claim_text)):
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
        count = len({candidate.material_id for candidate in supporting})
        return (
            f"当前有{count}份可引用材料涉及该现象，但材料份数不代表独立样本数，"
            "尚不能据此作群体性或绝对化结论。"
        )
    if "precise_quantity" in flags or "causal_language" in flags or "strong_intensity" in flags:
        if verdict != Verdict.SUPPORTED:
            return "现有材料涉及相关现象，但尚不足以确认该表述中的数量、影响程度或因果关系。"
    return (
        f"现有可引用材料中出现与“{rewritten}”一致的表述，"
        "其适用范围仍限于已收集材料。"
    )


def _strong_claim_is_proven(
    flags: list[str],
    supporting: list[EvidenceCandidate],
) -> bool:
    if not flags:
        return True
    formal = [
        candidate
        for candidate in supporting
        if candidate.evidence_type == EvidenceType.FORMAL_RECORD
    ]
    # Neither file counts nor a source-type label establish representativeness,
    # a causal design, or a quantitative effect. Keep these claims qualified.
    if set(flags) & {"absolute_quantifier", "group_generalization", "causal_language", "strong_intensity"}:
        return False
    if "precise_quantity" in flags and not formal:
        return False
    return True


def evaluate_claim(
    claim_text: str,
    candidates: list[EvidenceCandidate],
    max_candidates: int = 8,
    relation_overrides: Mapping[int, str] | None = None,
) -> ClaimEvaluation:
    """Evaluate support using only the supplied, eligible candidate IDs.

    ``relation_overrides`` is an optional, user-confirmed model review of the
    retrieved cards.  The model may correct a false lexical match, but the
    verdict, scope flags, and conservative rewrite remain computed here.
    """

    if not isinstance(claim_text, str) or not claim_text.strip():
        raise ValueError("claim_text must not be empty")

    allowed_ids = {candidate.id for candidate in candidates}
    matches = rank_evidence_with_explanations(
        claim_text.strip(), candidates, limit=max_candidates
    )
    # A small threshold removes cards that share only a generic character pair.
    relevant = [match for match in matches if match.score >= 0.08]
    claim_stance = _stance(claim_text)
    flags = detect_rule_flags(claim_text)
    # A copied conclusion or team synthesis can be lexically identical to the
    # claim while remaining context-only.  It must not raise the comparison
    # bar so high that the underlying interview or observation is discarded.
    strongest_score = max(
        (
            match.score
            for match in relevant
            if match.candidate.evidence_type != EvidenceType.TEAM_ANALYSIS
        ),
        default=0.0,
    )
    supporting: list[EvidenceCandidate] = []
    contradicting: list[EvidenceCandidate] = []
    context: list[EvidenceCandidate] = []
    boundary_notes: list[str] = []

    for match in relevant:
        candidate = match.candidate
        relation = (relation_overrides or {}).get(int(candidate.id))
        semantic_support = relation == "support"
        if relation not in {"support", "contradict", "context"}:
            relation = _relation(claim_stance, match)
            semantic_support = False
        if candidate.evidence_type == EvidenceType.TEAM_ANALYSIS:
            relation = "context"
        else:
            relation, note = _boundary_relation(
                claim_text,
                candidate.quote,
                relation,
                semantic_support=semantic_support,
            )
            if note:
                boundary_notes.append(note)
        # Strong scope/causal/quantity claims need evidence tied to the main
        # topic, not several weaker cards that only share generic vocabulary.
        if (
            relation == "support"
            and flags
            and match.score < strongest_score * 0.65
        ):
            relation = "context"
        if relation == "support":
            supporting.append(candidate)
        elif relation == "contradict":
            contradicting.append(candidate)
        else:
            context.append(candidate)

    missing: list[str] = list(dict.fromkeys(boundary_notes))
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
                f"当前找到{len(contradicting)}项与该表述方向相反的可引用材料。"
            )
        missing.append("核对相反材料的对象、时间和场景差异")
    elif supporting:
        if _strong_claim_is_proven(flags, supporting):
            verdict = Verdict.SUPPORTED
            reason = f"当前有{len(supporting)}项已授权、可引用材料支持该表述；待复核卡仍需人工确认。"
        else:
            verdict = Verdict.PARTIALLY_SUPPORTED
            reason = (
                f"当前有{len(supporting)}项材料支持核心现象，"
                "但结论的范围、强度、数量或因果表达超过了现有证据。"
            )
    else:
        verdict = Verdict.UNSUPPORTED
        reason = "当前候选材料中未找到能够直接支持该表述的可引用证据。"
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
