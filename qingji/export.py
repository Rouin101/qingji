"""Trusted Markdown export with explicit claim-to-evidence traceability."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any


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


def render_project_markdown(
    project: Any,
    claims: Iterable[Any],
    evidence_cards: Iterable[Any],
    links: Iterable[Any] = (),
    tasks: Iterable[Any] = (),
) -> str:
    """Render already-fetched rows while excluding unsafe evidence cards."""

    project_data = _row_dict(project)
    safe_evidence: dict[int, dict[str, Any]] = {}
    for row in evidence_cards:
        data = _row_dict(row)
        review = _enum_value(data.get("review_status"))
        consent = _enum_value(data.get("consent_status", "confirmed"))
        if review != "approved" or consent != "confirmed":
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
    lines = [
        f"# 青迹可信证据导出｜{project_data.get('name', '未命名项目')}",
        "",
        "> 本文档仅说明当前项目材料对表述的支持程度，不构成对现实事实的权威认证。",
        "> 仅包含已授权且经人工批准的脱敏证据；使用前仍需项目成员复核。",
        "",
    ]
    description = str(project_data.get("description", "")).strip()
    if description:
        lines.extend(("## 项目说明", "", description, ""))

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
        lines.extend(("暂无可导出的已批准证据。", ""))
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

    lines.extend(("## 未解决的补证任务", ""))
    open_tasks = [
        task for task in task_rows if _enum_value(task.get("status")) == "open"
    ]
    if not open_tasks:
        lines.extend(("暂无未解决的补证任务。", ""))
    for task in open_tasks:
        lines.extend(
            (
                f"- **{task.get('title') or '补充材料'}**（对应 C{task.get('claim_id', '—')}）",
                f"  - 建议行动：{task.get('recommended_action') or '未记录'}",
            )
        )
    lines.extend(
        (
            "",
            "---",
            "",
            "由青迹 v0.8 本地可信证据链流程生成。",
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
    return render_project_markdown(project, claims, evidence_cards, links, tasks)
