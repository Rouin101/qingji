"""Deterministic outcome-and-gap report outlines for verified projects."""
from __future__ import annotations
import json
from collections.abc import Iterable, Mapping
from typing import Any

VERDICT_LABELS = {"supported": "已有支持", "partially_supported": "部分支持", "unsupported": "暂无支持", "contradicted": "存在冲突"}

def _row(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else dict(getattr(value, "__dict__", {}))

def _list(value: Any) -> list[str]:
    if not value: return []
    if isinstance(value, (list, tuple)): return [str(item) for item in value]
    try: value = json.loads(str(value))
    except (TypeError, json.JSONDecodeError): return [str(value)]
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]

def build_outcome_outline(project: Mapping[str, Any] | Any, claims: Iterable[Mapping[str, Any] | Any], tasks: Iterable[Mapping[str, Any] | Any]) -> dict[str, Any]:
    project_data, claim_rows, task_rows = _row(project), [_row(item) for item in claims], [_row(item) for item in tasks]
    groups = {key: [] for key in VERDICT_LABELS}
    for claim in claim_rows: groups.setdefault(str(claim.get("verdict") or "unsupported"), []).append(claim)
    return {"title": f"{project_data.get('name') or '未命名项目'}成果与缺口报告大纲", "description": str(project_data.get("description") or "").strip(), "verdict_counts": {key: len(groups.get(key, [])) for key in VERDICT_LABELS}, "supported_findings": groups["supported"], "partial_findings": groups["partially_supported"], "conflicts": groups["contradicted"], "unsupported": groups["unsupported"], "open_tasks": [item for item in task_rows if item.get("status") == "open"]}

def render_outcome_outline_markdown(outline: Mapping[str, Any]) -> str:
    counts = outline.get("verdict_counts") or {}
    lines = [f"## 成果与缺口报告大纲｜{outline.get('title', '未命名项目')}", "", "### 一、核验概览", ""]
    lines.extend(f"- {VERDICT_LABELS[key]}：{counts.get(key, 0)} 条" for key in VERDICT_LABELS)
    lines.extend(("", "### 二、已获支持的发现", ""))
    findings = list(outline.get("supported_findings") or []) + list(outline.get("partial_findings") or [])
    lines.extend(f"- C{item.get('id', '—')}（{VERDICT_LABELS.get(str(item.get('verdict')), '待核验')}）：{item.get('safe_rewrite') or item.get('claim_text') or '未命名结论'}" for item in findings) or lines.append("- 暂无可纳入的支持性发现。")
    lines.extend(("", "### 三、冲突与需谨慎呈现的发现", ""))
    conflicts = outline.get("conflicts") or []
    lines.extend(f"- C{item.get('id', '—')}：{item.get('claim_text') or '未命名结论'}" for item in conflicts) or lines.append("- 当前未发现相互冲突的已核验结论。")
    lines.extend(("", "### 四、研究缺口与后续补证", ""))
    for item in outline.get("unsupported") or []: lines.append(f"- C{item.get('id', '—')}：{'；'.join(_list(item.get('missing_evidence_json'))) or '需要补充可追溯材料'}")
    for item in outline.get("open_tasks") or []: lines.append(f"- T{item.get('id', '—')}：{item.get('recommended_action') or item.get('title') or '补充材料'}")
    if not outline.get("unsupported") and not outline.get("open_tasks"): lines.append("- 当前没有待补证任务；正式使用前仍应复核材料边界。")
    lines.extend(("", "> 本大纲只汇总当前项目核验状态，不构成对现实事实的权威认证。", ""))
    return "\n".join(lines)