"""Trusted Markdown export with explicit claim-to-evidence traceability."""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from .evidence import is_retrievable_evidence
from .report import build_outcome_outline, render_outcome_outline_markdown


_VERDICT_LABELS = {
    "supported": "已有支持",
    "partially_supported": "部分支持",
    "unsupported": "暂无支持",
    "contradicted": "存在冲突",
}

_EVIDENCE_LABELS = {
    "interview_statement": "受访者陈述",
    "staff_explanation": "工作人员说明",
    "field_observation": "团队现场观察",
    "formal_record": "文献或正式记录",
    "team_analysis": "团队分析",
}

_REVIEW_LABELS = {
    "draft": "待审核",
    "approved": "已批准",
    "rejected": "已拒绝",
}

_REVIEW_FIELD_LABELS = {
    "title": "标题",
    "summary": "摘要",
    "evidence_type": "证据类型",
    "review_status": "审核状态",
}

_TASK_STATUS_LABELS = {
    "open": "待补证",
    "done": "已完成",
    "cancelled": "已取消",
}


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if is_dataclass(row):
        return asdict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    values = getattr(row, "__dict__", None)
    return dict(values) if isinstance(values, dict) else {}


def _value(row: Any, key: str, default: Any = "") -> Any:
    return _row_dict(row).get(key, default)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return [str(value)]
    return parsed if isinstance(parsed, list) else [parsed]


def _quote_markdown(text: str) -> list[str]:
    lines = str(text or "（无摘录）").splitlines() or ["（无摘录）"]
    return [f"> {line}" for line in lines]


def _markdown_inline(value: Any) -> str:
    """Keep user-authored audit text on one safe Markdown line."""

    return (
        html.escape(str(value or "未记录"), quote=False)
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def render_project_markdown(
    project: Any,
    claims: Iterable[Any],
    evidence_cards: Iterable[Any],
    links: Iterable[Any] = (),
    tasks: Iterable[Any] = (),
    review_events: Iterable[Any] = (),
) -> str:
    """Render already-fetched rows while excluding unsafe evidence cards."""

    project_data = _row_dict(project)
    safe_evidence: dict[int, dict[str, Any]] = {}
    for row in evidence_cards:
        data = _row_dict(row)
        if not is_retrievable_evidence(data):
            continue
        try:
            evidence_id = int(data["id"])
        except (KeyError, TypeError, ValueError):
            continue
        safe_evidence[evidence_id] = data

    grouped_links: dict[int, dict[str, list[int]]] = {}
    for row in links:
        data = _row_dict(row)
        try:
            claim_id = int(data["claim_id"])
            evidence_id = int(
                data.get("evidence_card_id", data.get("evidence_id"))
            )
        except (KeyError, TypeError, ValueError):
            continue
        if evidence_id not in safe_evidence:
            continue
        relation = str(data.get("relation", "context"))
        grouped_links.setdefault(
            claim_id, {"support": [], "contradict": [], "context": []}
        ).setdefault(relation, []).append(evidence_id)

    claim_rows = [_row_dict(row) for row in claims]
    task_rows = [_row_dict(row) for row in tasks]
    review_rows = [_row_dict(row) for row in review_events]
    lines = [
        f"# 青迹可信证据导出｜{project_data.get('name', '未命名项目')}",
        "",
        "> 本文档仅说明当前项目材料对表述的支持程度，不构成对现实事实的权威认证。",
        "> 仅包含已授权且未被人工排除的脱敏证据；使用前仍需项目成员复核。",
        "",
    ]
    description = str(project_data.get("description", "")).strip()
    if description:
        lines.extend(("## 项目说明", "", description, ""))

    lines.extend(render_outcome_outline_markdown(
        build_outcome_outline(project_data, claim_rows, task_rows)
    ).splitlines())
    lines.append("")
    lines.extend(("## 已核验结论", ""))
    if not claim_rows:
        lines.extend(("暂无已核验结论。", ""))
    for claim in claim_rows:
        claim_id = int(claim.get("id", 0) or 0)
        verdict = _enum_value(claim.get("verdict"))
        relations = grouped_links.get(
            claim_id, {"support": [], "contradict": [], "context": []}
        )
        lines.extend(
            (
                f"### C{claim_id}｜{claim.get('claim_text', '未命名结论')}",
                "",
                f"- 核验结果：{_VERDICT_LABELS.get(verdict, verdict or '尚未核验')}",
                f"- 判断理由：{claim.get('reason') or '未记录'}",
                f"- 稳妥表述：{claim.get('safe_rewrite') or '未生成'}",
                "- 支持证据："
                + (
                    "、".join(f"E{item}" for item in relations["support"])
                    or "无"
                ),
                "- 冲突证据："
                + (
                    "、".join(f"E{item}" for item in relations["contradict"])
                    or "无"
                ),
                "- 背景证据："
                + (
                    "、".join(f"E{item}" for item in relations["context"])
                    or "无"
                ),
            )
        )
        missing = _json_list(claim.get("missing_evidence_json"))
        if missing:
            lines.append("- 尚缺材料：" + "；".join(str(item) for item in missing))
        lines.append("")

    lines.extend(("## 证据目录", ""))
    cited_ids = {
        evidence_id
        for relations in grouped_links.values()
        for evidence_ids in relations.values()
        for evidence_id in evidence_ids
    }
    if not cited_ids:
        lines.extend(("暂无可导出的可引用证据。", ""))
    for evidence_id in sorted(cited_ids):
        evidence = safe_evidence[evidence_id]
        evidence_type = _enum_value(evidence.get("evidence_type"))
        lines.extend(
            (
                f"### E{evidence_id}｜{evidence.get('title') or '证据卡'}",
                "",
                f"- 类型：{_EVIDENCE_LABELS.get(evidence_type, evidence_type)}",
                f"- 来源角色：{evidence.get('source_role') or '未记录'}",
                f"- 场景：{evidence.get('context') or '未记录'}",
                f"- 来源定位：{evidence.get('source_locator') or evidence.get('locator') or '未记录'}",
                "",
            )
        )
        lines.extend(_quote_markdown(str(evidence.get("quote", ""))))
        lines.append("")

    lines.extend(("## 证据审核变更日志", ""))
    if not review_rows:
        lines.extend(("暂无人工审核变更记录。", ""))
    for event in review_rows:
        before = _row_dict(event.get("before"))
        after = _row_dict(event.get("after"))
        old_status = _REVIEW_LABELS.get(
            _enum_value(before.get("review_status")), "未知"
        )
        new_status = _REVIEW_LABELS.get(
            _enum_value(after.get("review_status")), "未知"
        )
        changed_fields = [
            label
            for field, label in _REVIEW_FIELD_LABELS.items()
            if before.get(field) != after.get(field)
        ]
        rechecked_ids = _json_list(event.get("rechecked_claim_ids"))
        lines.extend(
            (
                f"### 审核记录 H{event.get('id', 0)}｜E{event.get('evidence_card_id', 0)}",
                "",
                f"- 时间：{event.get('created_at') or '未记录'}",
                f"- 审核状态：{old_status} → {new_status}",
                "- 变更字段：" + ("、".join(changed_fields) or "无"),
                f"- 审核说明：{_markdown_inline(event.get('change_reason'))}",
                "- 触发重新核验："
                + ("、".join(f"C{item}" for item in rechecked_ids) or "无"),
                "",
            )
        )

    lines.extend(("## 补证任务", ""))
    if not task_rows:
        lines.extend(("暂无补证任务。", ""))
    for task in task_rows:
        status = _enum_value(task.get("status"))
        status_label = _TASK_STATUS_LABELS.get(status, status or "未知")
        lines.extend(
            (
                f"- **{task.get('title') or '补充材料'}**（对应 C{task.get('claim_id', '—')} · {status_label}）",
                f"  - 建议行动：{task.get('recommended_action') or '未记录'}",
            )
        )
        if task.get("completion_material_filename"):
            lines.append(
                f"  - 完成材料：{_markdown_inline(task.get('completion_material_filename'))}"
            )
    open_tasks = [
        task for task in task_rows if _enum_value(task.get("status")) == "open"
    ]
    lines.append(
        f"当前未解决任务：{len(open_tasks)} 项。"
    )
    lines.extend(
        (
            "",
            "---",
            "",
            "由青迹 v1.0 本地可信证据链流程生成。",
            "",
        )
    )
    return "\n".join(lines)


def export_project_markdown(db: Any, project_id: int) -> str:
    """Fetch one project through the storage API and render Markdown."""

    project = db.get_project(project_id)
    claims = db.list_claims(project_id)
    evidence_cards = db.list_evidence_cards(project_id)
    links: list[dict[str, Any]] = []
    for claim in claims:
        links.extend(db.list_claim_evidence_links(int(claim["id"])))
    tasks = db.list_followup_tasks(project_id=project_id)
    review_events = db.list_evidence_review_events(project_id, limit=500)
    return render_project_markdown(
        project,
        claims,
        evidence_cards,
        links,
        tasks,
        review_events,
    )
