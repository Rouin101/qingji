"""Selectable, presentation-ready report exports built from verified project data."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .artifacts import EXPORT_FORMATS, project_output_root, render_markdown_to_docx, render_markdown_to_pdf
from .evidence import is_retrievable_evidence
from .export import export_project_markdown


EXPORT_PROFILE_LABELS = {
    "report": "成果报告版",
    "audit": "完整审计版",
}

_VERDICT_LABELS = {
    "supported": "已有支持",
    "partially_supported": "部分支持",
    "unsupported": "暂无支持",
    "contradicted": "存在冲突",
}


def _selected_ids(values: Iterable[int] | None) -> set[int] | None:
    return None if values is None else {int(value) for value in values}


def _text(value: Any, default: str = "未记录") -> str:
    value = str(value or "").strip()
    return value or default


def _selected_rows(rows: Iterable[dict[str, Any]], ids: set[int] | None) -> list[dict[str, Any]]:
    return [dict(item) for item in rows if ids is None or int(item["id"]) in ids]


def render_outcome_report_markdown(
    project: dict[str, Any],
    claims: Iterable[dict[str, Any]],
    tasks: Iterable[dict[str, Any]],
    materials: Iterable[dict[str, Any]],
    evidence_cards: Iterable[dict[str, Any]],
    links: Iterable[dict[str, Any]],
    *,
    title: str = "",
    team_name: str = "",
    author: str = "",
    report_date: str = "",
) -> str:
    """Render selected findings as a report while retaining evidence IDs."""

    claim_rows = list(claims)
    task_rows = list(tasks)
    safe_evidence = {
        int(item["id"]): item
        for item in evidence_cards
        if item.get("id") is not None and is_retrievable_evidence(item)
    }
    grouped_links: dict[int, dict[str, list[int]]] = {}
    for link in links:
        claim_id = int(link.get("claim_id", 0) or 0)
        evidence_id = int(link.get("evidence_card_id", 0) or 0)
        if evidence_id not in safe_evidence:
            continue
        relation = str(link.get("relation") or "context")
        grouped_links.setdefault(claim_id, {"support": [], "contradict": [], "context": []})
        grouped_links[claim_id].setdefault(relation, []).append(evidence_id)

    report_title = _text(title, f"{_text(project.get('name'))}成果报告")
    lines = [
        f"# {report_title}",
        "",
        "> 本报告仅说明当前项目材料对相关表述的支持程度，不构成对现实事实的权威认证。",
        "",
    ]
    for label, value in (("项目", project.get("name")), ("团队", team_name), ("作者", author), ("日期", report_date)):
        if str(value or "").strip():
            lines.append(f"- {label}：{_text(value)}")
    description = str(project.get("description") or "").strip()
    if description:
        lines.extend(("", "## 项目说明", "", description))

    lines.extend(("", "## 核验概览", ""))
    for verdict, label in _VERDICT_LABELS.items():
        lines.append(f"- {label}：{sum(item.get('verdict') == verdict for item in claim_rows)} 条")

    lines.extend(("", "## 材料时间线", ""))
    timeline = sorted(materials, key=lambda item: str(item.get("captured_at") or item.get("created_at") or ""))
    if not timeline:
        lines.append("- 尚无可展示的材料记录。")
    for item in timeline:
        timestamp = _text(item.get("captured_at") or item.get("created_at"), "未记录日期")
        lines.append(f"- {timestamp}｜{_text(item.get('original_filename'), '未命名材料')}｜{_text(item.get('source_role'))}")

    findings = [item for item in claim_rows if item.get("verdict") in {"supported", "partially_supported"}]
    lines.extend(("", "## 可呈现的成果", ""))
    if not findings:
        lines.append("- 当前未选中具有支持性结论的成果。")
    for item in findings:
        claim_id = int(item["id"])
        relations = grouped_links.get(claim_id, {"support": [], "contradict": [], "context": []})
        lines.extend((
            f"### C{claim_id}｜{_text(item.get('safe_rewrite') or item.get('claim_text'))}",
            "",
            f"- 核验状态：{_VERDICT_LABELS.get(item.get('verdict'), '待核验')}",
            f"- 判断理由：{_text(item.get('reason'))}",
            "- 支持证据：" + ("、".join(f"E{value}" for value in relations["support"]) or "无"),
            "",
        ))

    cautions = [item for item in claim_rows if item.get("verdict") in {"unsupported", "contradicted"}]
    lines.extend(("## 需谨慎呈现的发现", ""))
    if not cautions:
        lines.append("- 当前没有选中需谨慎呈现的结论。")
    for item in cautions:
        lines.append(f"- **C{item.get('id', '—')}｜{_VERDICT_LABELS.get(item.get('verdict'), '待核验')}**：{_text(item.get('safe_rewrite') or item.get('claim_text'))}")

    lines.extend(("", "## 后续补证", ""))
    open_tasks = [item for item in task_rows if item.get("status") == "open"]
    if not open_tasks:
        lines.append("- 当前未选中待补证任务。")
    for item in open_tasks:
        lines.append(f"- **T{item.get('id', '—')}｜{_text(item.get('title'), '补充材料')}**：{_text(item.get('recommended_action'))}")

    cited_ids = sorted({evidence_id for relations in grouped_links.values() for values in relations.values() for evidence_id in values})
    lines.extend(("", "## 参考证据附录", ""))
    if not cited_ids:
        lines.append("- 当前选中结论没有可引用证据。")
    for evidence_id in cited_ids:
        evidence = safe_evidence[evidence_id]
        lines.extend((
            f"### E{evidence_id}｜{_text(evidence.get('title'), '证据卡')}",
            "",
            f"- 来源角色：{_text(evidence.get('source_role'))}",
            f"- 来源定位：{_text(evidence.get('source_locator') or evidence.get('locator'))}",
            f"> {_text(evidence.get('quote'), '（无摘录）')}",
            "",
        ))
    lines.extend(("---", "", "由青迹本地可信证据链流程生成。", ""))
    return "\n".join(lines)


def export_project_report_files(
    db: Any,
    project_id: int,
    formats: Iterable[str],
    *,
    profile: str,
    title: str = "",
    team_name: str = "",
    author: str = "",
    report_date: str = "",
    claim_ids: Iterable[int] | None = None,
    task_ids: Iterable[int] | None = None,
    output_root: str | Path | None = None,
) -> dict[str, Path]:
    """Write a selectable report or the complete audit record to ``output``."""

    selected_formats = tuple(dict.fromkeys(str(item) for item in formats))
    if not selected_formats:
        raise ValueError("请至少选择一种导出格式。")
    invalid = set(selected_formats).difference(EXPORT_FORMATS)
    if invalid:
        raise ValueError(f"不支持的导出格式：{'、'.join(sorted(invalid))}")
    if profile not in EXPORT_PROFILE_LABELS:
        raise ValueError("不支持的导出版本。")

    root = Path(output_root) if output_root is not None else project_output_root()
    if profile == "audit":
        markdown = export_project_markdown(db, project_id)
        stem = f"青迹_项目{int(project_id)}_可信证据导出"
    else:
        project = dict(db.get_project(project_id) or {})
        selected_claims = _selected_rows(db.list_claims(project_id), _selected_ids(claim_ids))
        selected_tasks = _selected_rows(db.list_followup_tasks(project_id=project_id), _selected_ids(task_ids))
        evidence_cards = [dict(item) for item in db.list_evidence_cards(project_id)]
        links: list[dict[str, Any]] = []
        for claim in selected_claims:
            links.extend(dict(item) for item in db.list_claim_evidence_links(int(claim["id"])))
        markdown = render_outcome_report_markdown(
            project,
            selected_claims,
            selected_tasks,
            [dict(item) for item in db.list_materials(project_id)],
            evidence_cards,
            links,
            title=title,
            team_name=team_name,
            author=author,
            report_date=report_date,
        )
        stem = f"青迹_项目{int(project_id)}_成果报告"

    files: dict[str, Path] = {}
    for export_format in selected_formats:
        extension = {"markdown": ".md", "docx": ".docx", "pdf": ".pdf"}[export_format]
        destination = root / export_format / f"{stem}{extension}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if export_format == "markdown":
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(markdown, encoding="utf-8", newline="\n")
            temporary.replace(destination)
        elif export_format == "docx":
            render_markdown_to_docx(markdown, destination)
        else:
            render_markdown_to_pdf(markdown, destination)
        files[export_format] = destination
    return files