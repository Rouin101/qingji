"""Real-pilot summaries and portable tabular exports."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any, Mapping, Sequence


PILOT_STATUS_LABELS = {
    "planned": "待开始",
    "in_progress": "进行中",
    "completed": "已完成",
    "paused": "已暂停",
}


def summarize_pilot_sessions(
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Return conservative aggregate metrics for the pilot dashboard."""

    comparable = [
        item
        for item in sessions
        if item.get("status") == "completed"
        and item.get("manual_minutes") is not None
        and item.get("qingji_minutes") is not None
    ]
    return {
        "sessions": len(sessions),
        "completed": sum(item.get("status") == "completed" for item in sessions),
        "comparable": len(comparable),
        "manual_minutes": sum(int(item["manual_minutes"]) for item in comparable),
        "qingji_minutes": sum(int(item["qingji_minutes"]) for item in comparable),
        "overclaim_alerts": sum(int(item.get("overclaim_alerts") or 0) for item in sessions),
        "adopted_alerts": sum(int(item.get("adopted_alerts") or 0) for item in sessions),
        "false_positives": sum(int(item.get("false_positives") or 0) for item in sessions),
        "false_negatives": sum(int(item.get("false_negatives") or 0) for item in sessions),
        "completed_followups": sum(
            int(item.get("completed_followups") or 0) for item in sessions
        ),
    }


def export_pilot_sessions_csv(sessions: Sequence[Mapping[str, Any]]) -> bytes:
    """Export pilot rows as an Excel-friendly UTF-8 CSV."""

    columns = (
        ("session_code", "会话编号"),
        ("session_date", "试用日期"),
        ("operator_alias", "操作者代号"),
        ("status", "状态"),
        ("manual_minutes", "原流程耗时_分钟"),
        ("qingji_minutes", "青迹耗时_分钟"),
        ("overclaim_alerts", "越界提醒数"),
        ("adopted_alerts", "采纳提醒数"),
        ("false_positives", "误报数"),
        ("false_negatives", "漏报数"),
        ("completed_followups", "完成补证数"),
        ("confusion_notes", "困惑点"),
        ("next_action", "下一步动作"),
        ("created_at", "创建时间"),
        ("updated_at", "更新时间"),
    )
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in columns])
    for item in sessions:
        writer.writerow(
            [
                PILOT_STATUS_LABELS.get(str(item.get(key)), item.get(key, ""))
                if key == "status"
                else item.get(key, "")
                for key, _ in columns
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def export_pilot_baseline_markdown(
    project_name: str, sessions: Sequence[Mapping[str, Any]]
) -> bytes:
    """Summarize recorded observations without treating missing data as zero."""

    completed = [item for item in sessions if item.get("status") == "completed"]
    comparable = [
        item
        for item in completed
        if item.get("manual_minutes") is not None
        and item.get("qingji_minutes") is not None
    ]
    missing_duration = [
        item
        for item in completed
        if item.get("manual_minutes") is None
        or item.get("qingji_minutes") is None
    ]
    lines = [
        f"# {project_name.strip()} 真实试用基线摘要",
        "",
        "本摘要仅汇总当前项目内人工登记的试用记录。耗时只比较状态为“已完成”且两项耗时均已填写的会话。",
        "",
        "## 样本与耗时",
        "",
        f"- 已登记会话：{len(sessions)}；已完成：{len(completed)}；耗时可比：{len(comparable)}。",
    ]
    if comparable:
        manual_total = sum(int(item["manual_minutes"]) for item in comparable)
        qingji_total = sum(int(item["qingji_minutes"]) for item in comparable)
        lines.extend(
            [
                f"- 可比会话原流程合计：{manual_total} 分钟；青迹流程合计：{qingji_total} 分钟。",
                f"- 可比会话净差：{manual_total - qingji_total:+d} 分钟（原流程减青迹流程；正数表示青迹用时较少）。",
            ]
        )
    else:
        lines.append("- 暂无可比耗时，不计算节省时间。")

    lines.extend(["", "## 已完成会话的人工记录", ""])
    if completed:
        for key, label in (
            ("overclaim_alerts", "越界提醒"),
            ("adopted_alerts", "采纳提醒"),
            ("false_positives", "误报"),
            ("false_negatives", "漏报"),
            ("completed_followups", "完成补证"),
        ):
            count = sum(int(item.get(key) or 0) for item in completed)
            lines.append(f"- {label}：{count}。")
        noted = sum(bool(str(item.get("confusion_notes") or "").strip()) for item in completed)
        lines.append(f"- 记录了困惑点的已完成会话：{noted}。")
    else:
        lines.append("- 尚无已完成会话，质量计数不汇总。")

    lines.extend(["", "## 数据缺口与解释边界", ""])
    lines.append(f"- 已完成但缺少至少一项耗时：{len(missing_duration)}。")
    lines.append(
        f"- 未完成或已暂停会话：{len(sessions) - len(completed)}；其耗时和质量计数未纳入上述比较。"
    )
    lines.append(
        "- 误报和漏报属于人工登记结果；本摘要未核验独立标注、授权状态或原始材料。"
    )
    lines.append(
        "- 这些数字仅描述当前项目的已记录试用，不能据此宣称真实场景准确率或因果性效果。"
    )
    return ("\n".join(lines) + "\n").encode("utf-8")
