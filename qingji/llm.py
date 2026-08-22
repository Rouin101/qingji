"""Opt-in model assistance for the claim-review workflow.

The deterministic rule evaluator remains the source of the persisted verdict.
This module only produces advisory wording after an explicit user action.  It
uses an OpenAI-compatible chat-completions endpoint so the provider can be
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


_MAX_CLAIM_CHARS = 500
_MAX_FIELD_CHARS = 1200
_MAX_LIST_ITEMS = 8


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
