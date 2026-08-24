"""Opt-in model assistance for the claim and evidence-review workflow.

The deterministic rule evaluator remains the source of the persisted verdict.
This module produces bounded, structured suggestions after an explicit user
action.  A separate bulk evidence-review contract can recommend ``approved``
or ``rejected``; the UI only applies those recommendations after an explicit
trust confirmation and the storage workflow still enforces project boundaries.
It uses an OpenAI-compatible chat-completions endpoint so the provider can be
changed through environment variables without changing the product logic.

Only approved, confirmed evidence-card fields are placed in the request.  The
fields are redacted once more at this boundary and raw material paths or raw
material text are never included.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .claims import detect_rule_flags
from .config import LLMSettings, llm_settings
from .models import ClaimEvaluation, ConsentStatus, EvidenceType, ReviewStatus
from .privacy import redact_text
from .retrieval import evidence_candidate_from_mapping, rank_evidence_with_explanations


class LLMError(RuntimeError):
    """Base error for model-assistance failures shown to the user."""


class LLMConfigurationError(LLMError):
    """The feature was requested without complete opt-in configuration."""


class LLMRequestError(LLMError):
    """The provider could not be reached or returned an HTTP error."""


class LLMResponseError(LLMError):
    """The provider response did not satisfy the safe JSON contract."""


@dataclass(frozen=True)
class LLMAdvice:
    """Structured, non-authoritative advice returned by the model."""

    summary: str
    safe_rewrite: str
    follow_up_suggestions: tuple[str, ...]
    uncertainties: tuple[str, ...]
    cited_evidence_ids: tuple[int, ...]
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "safe_rewrite": self.safe_rewrite,
            "follow_up_suggestions": list(self.follow_up_suggestions),
            "uncertainties": list(self.uncertainties),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "model": self.model,
        }


@dataclass(frozen=True)
class EvidenceAdvice:
    """A model draft for one evidence card; it is never an approval decision."""

    title: str
    summary: str
    evidence_type: str
    uncertainties: tuple[str, ...]
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "evidence_type": self.evidence_type,
            "uncertainties": list(self.uncertainties),
            "model": self.model,
        }


@dataclass(frozen=True)
class EvidenceReviewAdvice:
    """A bounded model recommendation for one evidence-card review."""

    review_status: str
    review_reason: str
    uncertainties: tuple[str, ...]
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "review_status": self.review_status,
            "review_reason": self.review_reason,
            "uncertainties": list(self.uncertainties),
            "model": self.model,
        }


@dataclass(frozen=True)
class EvidenceReviewBatchAdvice:
    """Model recommendations for a bounded batch of evidence cards."""

    reviews: tuple[tuple[int, EvidenceReviewAdvice], ...]
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "reviews": [
                {"evidence_id": evidence_id, **advice.as_dict()}
                for evidence_id, advice in self.reviews
            ],
        }


@dataclass(frozen=True)
class ClaimEvidenceReviewItem:
    """One model-labelled relation between a claim and an eligible card."""

    evidence_id: int
    relation: str
    rationale: str


@dataclass(frozen=True)
class ClaimEvidenceReviewAdvice:
    """Bounded model review of which cards directly support or conflict."""

    reviews: tuple[ClaimEvidenceReviewItem, ...]
    uncertainties: tuple[str, ...]
    model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "reviews": [
                {
                    "evidence_id": item.evidence_id,
                    "relation": item.relation,
                    "rationale": item.rationale,
                }
                for item in self.reviews
            ],
            "uncertainties": list(self.uncertainties),
        }


_MAX_CLAIM_CHARS = 500
_MAX_FIELD_CHARS = 1200
_MAX_LIST_ITEMS = 8
_CLAIM_EVIDENCE_REVIEW_MAX_CARDS = 24


def _status(value: Any) -> str:
    return getattr(value, "value", value) if value is not None else ""


def _clean_text(value: Any, *, limit: int = _MAX_FIELD_CHARS) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # A second boundary redaction protects against PII introduced while a
    # human edited a title or summary after the material was imported.
    text = redact_text(text).redacted_text.strip()
    return text[:limit]


def _eligible_evidence(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if _status(row.get("review_status")) != ReviewStatus.APPROVED.value:
            continue
        if _status(row.get("consent_status")) != ConsentStatus.CONFIRMED.value:
            continue
        try:
            evidence_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        eligible.append(
            {
                "evidence_id": evidence_id,
                "title": _clean_text(row.get("title")),
                "quote": _clean_text(row.get("quote")),
                "summary": _clean_text(row.get("summary")),
                "evidence_type": _clean_text(row.get("evidence_type"), limit=100),
                "source_locator": _clean_text(row.get("source_locator"), limit=200),
            }
        )
    return eligible


def _safe_evaluation_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the evaluation summary bounded and redact any user-derived text."""

    def safe_list(value: Any, limit: int = _MAX_LIST_ITEMS) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [
            cleaned
            for item in list(value)[:limit]
            if (cleaned := _clean_text(item, limit=300))
        ]

    safe_ids: list[int] = []
    for raw_id in data.get("supporting_evidence_ids") or []:
        try:
            safe_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return {
        "verdict": _clean_text(data.get("verdict"), limit=80),
        "reason": _clean_text(data.get("reason"), limit=500),
        "supporting_evidence_ids": safe_ids[:20],
        "missing_evidence": safe_list(data.get("missing_evidence")),
        "safe_rewrite": _clean_text(data.get("safe_rewrite"), limit=500),
        "rule_flags": safe_list(data.get("rule_flags")),
    }


def build_claim_assistance_prompt(
    claim_text: str,
    evaluation: ClaimEvaluation | Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    max_context_chars: int = 12000,
) -> tuple[str, set[int]]:
    """Build a provider prompt from the eligible, boundary-redacted context."""

    claim = _clean_text(claim_text, limit=_MAX_CLAIM_CHARS)
    if not claim:
        raise ValueError("claim_text must not be empty")

    raw_evaluation_data = (
        evaluation.as_dict()
        if isinstance(evaluation, ClaimEvaluation)
        else dict(evaluation)
    )
    evaluation_data = _safe_evaluation_data(raw_evaluation_data)
    rule_flags = evaluation_data.get("rule_flags") or detect_rule_flags(claim)
    eligible = _eligible_evidence(evidence_rows)
    allowed_ids = {int(item["evidence_id"]) for item in eligible}

    evidence_lines: list[str] = []
    used_chars = 0
    for item in eligible:
        line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if evidence_lines and used_chars + len(line) + 1 > max_context_chars:
            break
        evidence_lines.append(line)
        used_chars += len(line) + 1

    context = "\n".join(evidence_lines) or "（没有可供引用的已审核、已授权证据）"
    prompt = (
        "你是青迹的‘辅助建议’模块，不是事实裁判。只能根据给定材料提出保守建议，"
        "不得补造数字、人物、时间、地点或因果关系。四级核验结果由规则系统负责，"
        "不得改写为更高可信度。请只返回一个 JSON 对象，不要 Markdown 代码围栏。\n\n"
        "JSON 字段必须为：summary（不超过 160 字）、safe_rewrite（保守改写，"
        "不超过 240 字）、follow_up_suggestions（最多 8 条）、uncertainties（最多 8 条）、"
        "cited_evidence_ids（只能使用给定 evidence_id 的整数）。如果证据不足，"
        "明确写出不足，不要假设。\n\n"
        f"待核验结论：{claim}\n"
        f"规则判定：{json.dumps(evaluation_data, ensure_ascii=False)}\n"
        f"规则提醒：{json.dumps(list(rule_flags), ensure_ascii=False)}\n"
        "可引用证据（每行一个 JSON 对象）：\n"
        f"{context}"
    )
    return prompt, allowed_ids


def build_claim_evidence_review_prompt(
    claim_text: str,
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    max_context_chars: int = 12000,
    max_cards: int = _CLAIM_EVIDENCE_REVIEW_MAX_CARDS,
) -> tuple[str, set[int]]:
    """Build a bounded prompt for model-assisted claim/evidence relations.

    Local retrieval only limits the context size; it does not decide the
    relation.  The model must label every card included in the prompt so an
    accidental lexical match can be demoted to context.
    """

    claim = _clean_text(claim_text, limit=_MAX_CLAIM_CHARS)
    if not claim:
        raise ValueError("claim_text must not be empty")
    if isinstance(max_cards, bool) or not isinstance(max_cards, int) or max_cards <= 0:
        raise ValueError("max_cards must be a positive integer")

    eligible = _eligible_evidence(evidence_rows)
    candidates = [
        evidence_candidate_from_mapping(
            {
                **row,
                "id": row["evidence_id"],
                "material_id": row.get("material_id", row["evidence_id"]),
                "segment_id": row.get("segment_id", row["evidence_id"]),
                "source_role": row.get("source_role", ""),
                "context": row.get("context", ""),
                "review_status": "approved",
                "consent_status": "confirmed",
            }
        )
        for row in eligible
    ]
    ranked = rank_evidence_with_explanations(claim, candidates, limit=max_cards)
    by_id = {int(row["evidence_id"]): row for row in eligible}
    selected = [by_id[int(match.candidate.id)] for match in ranked]
    if not selected:
        selected = eligible[:max_cards]

    evidence_lines: list[str] = []
    used_chars = 0
    context_limit = max(800, max_context_chars - 1200)
    for item in selected:
        line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if evidence_lines and used_chars + len(line) + 1 > context_limit:
            break
        evidence_lines.append(line)
        used_chars += len(line) + 1
    allowed_ids = {
        int(json.loads(line)["evidence_id"]) for line in evidence_lines
    }
    context = "\n".join(evidence_lines) or "（没有可供复核的已审核、已授权证据）"
    prompt = (
        "你是青迹的证据关联复核模块，不是事实裁判。请只判断给定的、已经人工批准且"
        "已确认授权的证据卡，是否直接支持、直接反驳当前结论，或只能作为背景。"
        "不要因为共享一个关键词就判为支持；要检查对象、行为、范围、时间、场景和"
        "语气是否真正对应。团队分析不能单独证明受访者事实。四级核验结果仍由本地"
        "规则系统计算。请对每个给定 evidence_id 各返回一项；无法直接对应时返回 context。"
        "只返回一个 JSON 对象，不要 Markdown 代码围栏。\n\n"
        "JSON 字段必须为：evidence_reviews（数组，每项包含 evidence_id、relation、"
        "rationale；relation 只能是 support、contradict、context）、uncertainties（最多 8 条）。\n\n"
        f"待核验结论：{claim}\n"
        "候选证据（每行一个 JSON 对象）：\n"
        f"{context}"
    )
    return prompt, allowed_ids


def _default_post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout: float,
) -> Mapping[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - URL is explicit config
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMRequestError(f"模型服务返回 HTTP {exc.code}：{detail}") from exc
    except URLError as exc:
        raise LLMRequestError(f"无法连接模型服务：{exc.reason}") from exc
    except TimeoutError as exc:
        raise LLMRequestError("模型服务请求超时，请稍后重试。") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("模型服务返回的不是有效 JSON。") from exc
    if not isinstance(parsed, Mapping):
        raise LLMResponseError("模型服务返回格式不正确。")
    return parsed


def _call_chat_completion(
    prompt: str,
    *,
    config: LLMSettings,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ],
) -> Mapping[str, Any]:
    payload = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "你只提供保守、可追溯、非权威的辅助建议。",
            },
            {"role": "user", "content": prompt},
        ],
    }
    return post_json(
        config.base_url.rstrip("/") + "/chat/completions",
        {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        payload,
        config.timeout_seconds,
    )


def _extract_json_object(content: str) -> Mapping[str, Any]:
    cleaned = str(content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise LLMResponseError("模型没有返回约定的 JSON 建议。")
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMResponseError("模型返回的建议 JSON 无法解析。") from exc
    if not isinstance(parsed, Mapping):
        raise LLMResponseError("模型建议必须是 JSON 对象。")
    return parsed


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise LLMResponseError(f"模型字段 {field} 必须是数组。")
    result: list[str] = []
    for item in value[:_MAX_LIST_ITEMS]:
        text = _clean_text(item, limit=300)
        if text:
            result.append(text)
    return tuple(result)


def _parse_advice(
    response: Mapping[str, Any],
    *,
    allowed_ids: set[int],
    model: str,
) -> LLMAdvice:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("模型响应缺少 choices 内容。")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMResponseError("模型响应内容格式不正确。")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseError("模型响应缺少 message 内容。")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMResponseError("模型响应缺少文本内容。")
    data = _extract_json_object(content)
    summary = _clean_text(data.get("summary"), limit=160)
    safe_rewrite = _clean_text(data.get("safe_rewrite"), limit=240)
    if not summary or not safe_rewrite:
        raise LLMResponseError("模型建议缺少 summary 或 safe_rewrite。")
    raw_ids = data.get("cited_evidence_ids") or []
    if not isinstance(raw_ids, list):
        raise LLMResponseError("模型字段 cited_evidence_ids 必须是数组。")
    cited_ids: list[int] = []
    for raw_id in raw_ids[:20]:
        try:
            evidence_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise LLMResponseError("模型引用了非整数证据编号。") from exc
        if evidence_id not in allowed_ids:
            raise LLMResponseError(
                f"模型引用了本次上下文之外的证据 E{evidence_id}。"
            )
        if evidence_id not in cited_ids:
            cited_ids.append(evidence_id)
    return LLMAdvice(
        summary=summary,
        safe_rewrite=safe_rewrite,
        follow_up_suggestions=_string_list(
            data.get("follow_up_suggestions"), field="follow_up_suggestions"
        ),
        uncertainties=_string_list(data.get("uncertainties"), field="uncertainties"),
        cited_evidence_ids=tuple(cited_ids),
        model=model,
    )


def _response_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("模型响应缺少 choices 内容。")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMResponseError("模型响应内容格式不正确。")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseError("模型响应缺少 message 内容。")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMResponseError("模型响应缺少文本内容。")
    return content


def _parse_claim_evidence_review(
    response: Mapping[str, Any],
    *,
    allowed_ids: set[int],
    model: str,
) -> ClaimEvidenceReviewAdvice:
    data = _extract_json_object(_response_content(response))
    raw_reviews = data.get("evidence_reviews")
    if not isinstance(raw_reviews, list):
        raise LLMResponseError("模型字段 evidence_reviews 必须是数组。")
    relation_values = {"support", "contradict", "context"}
    parsed: dict[int, ClaimEvidenceReviewItem] = {}
    for raw_item in raw_reviews:
        if not isinstance(raw_item, Mapping):
            raise LLMResponseError("模型证据关联项格式不正确。")
        try:
            evidence_id = int(raw_item.get("evidence_id"))
        except (TypeError, ValueError) as exc:
            raise LLMResponseError("模型引用了非整数证据编号。") from exc
        if evidence_id not in allowed_ids:
            raise LLMResponseError(
                f"模型引用了本次上下文之外的证据 E{evidence_id}。"
            )
        if evidence_id in parsed:
            raise LLMResponseError(f"模型重复返回证据 E{evidence_id}。")
        relation = _clean_text(raw_item.get("relation"), limit=30)
        if relation not in relation_values:
            raise LLMResponseError(
                "模型证据关联关系必须是 support、contradict 或 context。"
            )
        rationale = _clean_text(raw_item.get("rationale"), limit=240)
        parsed[evidence_id] = ClaimEvidenceReviewItem(
            evidence_id=evidence_id,
            relation=relation,
            rationale=rationale,
        )
    # Omitted cards are deliberately demoted to context rather than allowing
    # the old lexical relation to survive a user-confirmed model review.
    for evidence_id in sorted(allowed_ids):
        parsed.setdefault(
            evidence_id,
            ClaimEvidenceReviewItem(
                evidence_id=evidence_id,
                relation="context",
                rationale="模型未将该卡片识别为直接支持或冲突证据。",
            ),
        )
    return ClaimEvidenceReviewAdvice(
        reviews=tuple(parsed[evidence_id] for evidence_id in sorted(parsed)),
        uncertainties=_string_list(data.get("uncertainties"), field="uncertainties"),
        model=model,
    )


def request_claim_evidence_review(
    claim_text: str,
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    config: LLMSettings | None = None,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ]
    | None = None,
) -> ClaimEvidenceReviewAdvice:
    """Ask the model to classify direct claim/evidence relations."""

    current = config or llm_settings
    if not current.configured:
        raise LLMConfigurationError(
            "尚未启用大模型证据关联复核。请配置 QINGJI_LLM_ENABLED、"
            "QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
        )
    prompt, allowed_ids = build_claim_evidence_review_prompt(
        claim_text,
        evidence_rows,
        max_context_chars=current.max_context_chars,
    )
    if not allowed_ids:
        raise LLMResponseError("当前没有可供模型复核的已审核、已授权证据。")
    response = _call_chat_completion(
        prompt,
        config=current,
        post_json=post_json or _default_post_json,
    )
    return _parse_claim_evidence_review(
        response,
        allowed_ids=allowed_ids,
        model=current.model,
    )


def request_claim_assistance(
    claim_text: str,
    evaluation: ClaimEvaluation | Mapping[str, Any],
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    config: LLMSettings | None = None,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ] | None = None,
) -> LLMAdvice:
    """Request advisory claim assistance after an explicit user action."""

    current = config or llm_settings
    if not current.configured:
        raise LLMConfigurationError(
            "尚未启用大模型辅助。请配置 QINGJI_LLM_ENABLED、"
            "QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
        )
    prompt, allowed_ids = build_claim_assistance_prompt(
        claim_text,
        evaluation,
        evidence_rows,
        max_context_chars=current.max_context_chars,
    )
    post = post_json or _default_post_json
    response = _call_chat_completion(
        prompt,
        config=current,
        post_json=post,
    )
    return _parse_advice(response, allowed_ids=allowed_ids, model=current.model)


def build_evidence_assistance_prompt(
    evidence_row: Mapping[str, Any],
    *,
    max_context_chars: int = 12000,
) -> str:
    """Build a redacted prompt for a consent-confirmed evidence card."""

    if _status(evidence_row.get("consent_status")) != ConsentStatus.CONFIRMED.value:
        raise ValueError("未确认授权的材料不能请求模型辅助。")
    quote = _clean_text(evidence_row.get("quote"), limit=1800)
    if not quote:
        raise ValueError("证据卡缺少可供摘要的脱敏原文片段。")
    source = {
        "current_title": _clean_text(evidence_row.get("title"), limit=300),
        "current_summary": _clean_text(evidence_row.get("summary"), limit=800),
        "quote": quote,
        "current_evidence_type": _clean_text(
            evidence_row.get("evidence_type"), limit=100
        ),
    }
    prompt = (
        "你是青迹的证据卡草拟助手。请根据给定的脱敏片段，提出便于人工审核的"
        "标题、摘要和证据类型建议。不得补造人物、数字、时间、地点或因果关系；"
        "不得把单个来源推广为群体事实；团队分析只能标记为 team_analysis。"
        "这只是草稿，不代表证据已批准。只返回一个 JSON 对象，不要 Markdown 围栏。\n\n"
        "JSON 字段必须为：title（不超过 80 字）、summary（不超过 240 字）、"
        "evidence_type（只能是 interview_statement、staff_explanation、"
        "field_observation、formal_record、team_analysis 之一）、"
        "uncertainties（最多 8 条）。\n\n"
        f"证据卡输入：{json.dumps(source, ensure_ascii=False)}"
    )
    return prompt[:max_context_chars]


def _parse_evidence_advice(
    response: Mapping[str, Any],
    *,
    model: str,
) -> EvidenceAdvice:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("模型响应缺少 choices 内容。")
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise LLMResponseError("模型响应缺少文本内容。")
    data = _extract_json_object(content)
    title = _clean_text(data.get("title"), limit=80)
    summary = _clean_text(data.get("summary"), limit=240)
    evidence_type = _clean_text(data.get("evidence_type"), limit=100)
    allowed_types = {item.value for item in EvidenceType}
    if not title or not summary:
        raise LLMResponseError("模型证据建议缺少 title 或 summary。")
    if evidence_type not in allowed_types:
        raise LLMResponseError("模型返回了不受支持的证据类型。")
    return EvidenceAdvice(
        title=title,
        summary=summary,
        evidence_type=evidence_type,
        uncertainties=_string_list(data.get("uncertainties"), field="uncertainties"),
        model=model,
    )


def request_evidence_assistance(
    evidence_row: Mapping[str, Any],
    *,
    config: LLMSettings | None = None,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ] | None = None,
) -> EvidenceAdvice:
    """Request a draft evidence card without changing its review status."""

    current = config or llm_settings
    if not current.configured:
        raise LLMConfigurationError(
            "尚未启用大模型辅助。请配置 QINGJI_LLM_ENABLED、"
            "QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
        )
    prompt = build_evidence_assistance_prompt(
        evidence_row,
        max_context_chars=current.max_context_chars,
    )
    post = post_json or _default_post_json
    response = _call_chat_completion(
        prompt,
        config=current,
        post_json=post,
    )
    return _parse_evidence_advice(response, model=current.model)


def build_evidence_review_prompt(
    evidence_row: Mapping[str, Any],
    *,
    max_context_chars: int = 12000,
) -> str:
    """Build a redacted prompt for a model recommendation on one card."""

    if _status(evidence_row.get("consent_status")) != ConsentStatus.CONFIRMED.value:
        raise ValueError("未确认授权的材料不能请求模型审核。")
    quote = _clean_text(evidence_row.get("quote"), limit=1800)
    if not quote:
        raise ValueError("证据卡缺少可供审核的脱敏原文片段。")
    source = {
        "evidence_id": int(evidence_row["id"]),
        "title": _clean_text(evidence_row.get("title"), limit=300),
        "summary": _clean_text(evidence_row.get("summary"), limit=800),
        "quote": quote,
        "evidence_type": _clean_text(evidence_row.get("evidence_type"), limit=100),
        "source_role": _clean_text(evidence_row.get("source_role"), limit=100),
        "context": _clean_text(evidence_row.get("context"), limit=200),
    }
    prompt = (
        "你是青迹的证据卡审核模块。请只根据给定的脱敏证据卡判断它是否适合"
        "作为当前项目的可引用证据。不得补造人物、数字、时间、地点或因果关系；"
        "不能因为文字通顺就批准；团队分析不能单独证明事实；信息不足或存在"
        "明显问题时请选择 rejected。只返回一个 JSON 对象，不要 Markdown 围栏。\n\n"
        "JSON 字段必须为：review_status（只能是 approved 或 rejected）、"
        "review_reason（不超过 300 字）、uncertainties（最多 8 条）。\n\n"
        f"证据卡：{json.dumps(source, ensure_ascii=False)}"
    )
    return prompt[:max_context_chars]


def build_evidence_review_batch_prompt(
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    max_context_chars: int = 12000,
) -> tuple[str, set[int]]:
    """Build one bounded prompt for several draft-card review decisions."""

    eligible: list[dict[str, Any]] = []
    for row in evidence_rows:
        if _status(row.get("review_status")) != ReviewStatus.DRAFT.value:
            continue
        if _status(row.get("consent_status")) != ConsentStatus.CONFIRMED.value:
            continue
        try:
            evidence_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        eligible.append(
            {
                "evidence_id": evidence_id,
                "title": _clean_text(row.get("title"), limit=180),
                "summary": _clean_text(row.get("summary"), limit=360),
                "quote": _clean_text(row.get("quote"), limit=700),
                "evidence_type": _clean_text(row.get("evidence_type"), limit=100),
                "source_role": _clean_text(row.get("source_role"), limit=100),
                "context": _clean_text(row.get("context"), limit=200),
            }
        )
    if not eligible:
        raise ValueError("没有可供模型审核的已确认授权待审核卡片。")

    lines: list[str] = []
    used_chars = 0
    context_limit = max(800, max_context_chars - 900)
    for item in eligible:
        line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if lines and used_chars + len(line) + 1 > context_limit:
            break
        lines.append(line)
        used_chars += len(line) + 1
    allowed_ids = {
        int(json.loads(line)["evidence_id"]) for line in lines
    }
    prompt = (
        "你是青迹的批量证据卡审核模块。请逐张判断给定的、已确认授权的待审核证据卡"
        "是否适合作为当前项目的可引用证据。不能因为文字通顺或共享关键词就批准；"
        "信息不足、来源边界不清、把分析当事实或存在明显问题时请选择 rejected。"
        "不得补造人物、数字、时间、地点或因果关系。请对每个 evidence_id 各返回一项，"
        "只返回一个 JSON 对象，不要 Markdown 代码围栏。\n\n"
        "JSON 字段必须为 reviews（数组，每项包含 evidence_id、review_status、"
        "review_reason、uncertainties；review_status 只能是 approved 或 rejected）。\n\n"
        "证据卡（每行一个 JSON 对象）：\n"
        + "\n".join(lines)
    )
    return prompt, allowed_ids


def _parse_evidence_review_advice(
    response: Mapping[str, Any],
    *,
    model: str,
) -> EvidenceReviewAdvice:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("模型响应缺少 choices 内容。")
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise LLMResponseError("模型响应缺少文本内容。")
    data = _extract_json_object(content)
    review_status = _clean_text(data.get("review_status"), limit=30)
    if review_status not in {ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value}:
        raise LLMResponseError("模型审核状态必须是 approved 或 rejected。")
    return EvidenceReviewAdvice(
        review_status=review_status,
        review_reason=_clean_text(data.get("review_reason"), limit=300),
        uncertainties=_string_list(data.get("uncertainties"), field="uncertainties"),
        model=model,
    )


def _parse_evidence_review_batch(
    response: Mapping[str, Any],
    *,
    allowed_ids: set[int],
    model: str,
) -> EvidenceReviewBatchAdvice:
    data = _extract_json_object(_response_content(response))
    raw_reviews = data.get("reviews")
    if not isinstance(raw_reviews, list):
        raise LLMResponseError("模型字段 reviews 必须是数组。")
    parsed: dict[int, EvidenceReviewAdvice] = {}
    for raw_item in raw_reviews:
        if not isinstance(raw_item, Mapping):
            raise LLMResponseError("模型批量审核项格式不正确。")
        try:
            evidence_id = int(raw_item.get("evidence_id"))
        except (TypeError, ValueError) as exc:
            raise LLMResponseError("模型批量审核引用了非整数证据编号。") from exc
        if evidence_id not in allowed_ids:
            raise LLMResponseError(
                f"模型引用了本次批量上下文之外的证据 E{evidence_id}。"
            )
        if evidence_id in parsed:
            raise LLMResponseError(f"模型批量审核重复返回证据 E{evidence_id}。")
        status = _clean_text(raw_item.get("review_status"), limit=30)
        if status not in {ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value}:
            raise LLMResponseError(
                "模型批量审核状态必须是 approved 或 rejected。"
            )
        parsed[evidence_id] = EvidenceReviewAdvice(
            review_status=status,
            review_reason=_clean_text(raw_item.get("review_reason"), limit=300),
            uncertainties=_string_list(
                raw_item.get("uncertainties"), field="uncertainties"
            ),
            model=model,
        )
    missing = allowed_ids - set(parsed)
    if missing:
        missing_text = "、".join(f"E{item}" for item in sorted(missing))
        raise LLMResponseError(f"模型批量审核遗漏证据卡：{missing_text}。")
    return EvidenceReviewBatchAdvice(
        reviews=tuple((evidence_id, parsed[evidence_id]) for evidence_id in sorted(parsed)),
        model=model,
    )


def request_evidence_review_batch(
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    config: LLMSettings | None = None,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ]
    | None = None,
) -> EvidenceReviewBatchAdvice:
    """Review several cards in one provider request to reduce round trips."""

    current = config or llm_settings
    if not current.configured:
        raise LLMConfigurationError(
            "尚未启用大模型审核。请配置 QINGJI_LLM_ENABLED、"
            "QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
        )
    prompt, allowed_ids = build_evidence_review_batch_prompt(
        evidence_rows,
        max_context_chars=current.max_context_chars,
    )
    response = _call_chat_completion(
        prompt,
        config=current,
        post_json=post_json or _default_post_json,
    )
    return _parse_evidence_review_batch(
        response,
        allowed_ids=allowed_ids,
        model=current.model,
    )


def request_evidence_review(
    evidence_row: Mapping[str, Any],
    *,
    config: LLMSettings | None = None,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ] | None = None,
) -> EvidenceReviewAdvice:
    """Request one bounded model recommendation for an evidence-card review."""

    current = config or llm_settings
    if not current.configured:
        raise LLMConfigurationError(
            "尚未启用大模型审核。请配置 QINGJI_LLM_ENABLED、"
            "QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
        )
    prompt = build_evidence_review_prompt(
        evidence_row,
        max_context_chars=current.max_context_chars,
    )
    post = post_json or _default_post_json
    response = _call_chat_completion(
        prompt,
        config=current,
        post_json=post,
    )
    return _parse_evidence_review_advice(response, model=current.model)


def probe_llm_connection(
    *,
    config: LLMSettings | None = None,
    post_json: Callable[
        [str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]
    ] | None = None,
) -> str:
    """Verify provider credentials with a no-project-data JSON probe."""

    current = config or llm_settings
    if not current.configured:
        raise LLMConfigurationError(
            "尚未启用大模型辅助。请先配置 QINGJI_LLM_ENABLED、"
            "QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
        )
    post = post_json or _default_post_json
    response = _call_chat_completion(
        '只返回一个 JSON 对象：{"ok":true}。不要返回其他内容。',
        config=current,
        post_json=post,
    )
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str):
        raise LLMResponseError("模型探针响应缺少文本内容。")
    data = _extract_json_object(content)
    if data.get("ok") is not True:
        raise LLMResponseError("模型探针没有返回 ok=true。")
    return str(response.get("model") or current.model)
