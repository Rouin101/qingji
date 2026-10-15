"""Project-local real-pilot session logging and baseline summaries."""

from __future__ import annotations

from datetime import date

import streamlit as st

from qingji.pilot import (
    PILOT_STATUS_LABELS,
    export_pilot_baseline_markdown,
    export_pilot_sessions_csv,
    summarize_pilot_sessions,
)
from qingji.ui import (
    configure_page,
    empty_state,
    format_datetime,
    get_demo_context,
    is_demo_project,
    render_compact_metrics,
    render_demo_notice,
    render_page_intro,
    render_sidebar_note,
)


def _optional_minutes(value: str, label: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if not text.isdigit():
        raise ValueError(f"{label}必须填写非负整数，或留空表示尚未记录。")
    return int(text)


def _status_index(status: str) -> int:
    statuses = list(PILOT_STATUS_LABELS)
    return statuses.index(status) if status in statuses else 0


configure_page("真实试用", "🧪")
try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"读取项目失败：{exc}")
    st.stop()

render_sidebar_note(project, database=db, project_id=project_id)
render_page_intro("05 · REAL PILOT", "真实试用记录")
render_demo_notice(project)
st.caption(
    "记录实际耗时与人工复核结果。误报、漏报必须由人工判定，不能由模型自评。"
)

sessions = db.list_pilot_sessions(project_id)
summary = summarize_pilot_sessions(sessions)
time_delta = summary["manual_minutes"] - summary["qingji_minutes"]
render_compact_metrics(
    (
        ("试用会话", summary["sessions"]),
        ("完成 / 可比", f"{summary['completed']} / {summary['comparable']}"),
        (
            "可比样本净节省",
            f"{time_delta} 分钟" if summary["comparable"] else "暂无",
        ),
        (
            "误报 / 漏报",
            f"{summary['false_positives']} / {summary['false_negatives']}",
        ),
    )
)

if summary["completed"] > summary["comparable"]:
    st.info(
        "部分已完成会话缺少一项耗时，因此未进入耗时对比；保留缺失值比用 0 代填更可靠。"
    )

record_tab, review_tab = st.tabs(["新增记录", "查看与修订"])
demo_locked = is_demo_project(project)

with record_tab:
    if demo_locked:
        st.caption("内置演示项目不写入试用记录；请在首页切换到实际项目。")
    default_code = f"TRIAL-{date.today():%Y%m%d}-{len(sessions) + 1:02d}"
    with st.form(f"pilot_create_{project_id}", clear_on_submit=False):
        top = st.columns(4)
        session_code = top[0].text_input("会话编号 *", value=default_code)
        session_date = top[1].date_input("试用日期 *", value=date.today())
        operator_alias = top[2].text_input(
            "操作者代号", help="建议使用组内代号，不填写姓名等不必要的个人信息。"
        )
        status = top[3].selectbox(
            "状态",
            options=list(PILOT_STATUS_LABELS),
            index=1,
            format_func=PILOT_STATUS_LABELS.get,
        )
        duration = st.columns(2)
        manual_minutes = duration[0].text_input(
            "原流程耗时（分钟）",
            placeholder="留空表示尚未记录",
        )
        qingji_minutes = duration[1].text_input(
            "青迹流程耗时（分钟）",
            placeholder="留空表示尚未记录",
        )
        with st.expander("质量与补证计数（可选）"):
            counts = st.columns(5)
            overclaim_alerts = counts[0].number_input(
                "越界提醒", min_value=0, step=1
            )
            adopted_alerts = counts[1].number_input(
                "采纳提醒", min_value=0, step=1
            )
            false_positives = counts[2].number_input("误报", min_value=0, step=1)
            false_negatives = counts[3].number_input("漏报", min_value=0, step=1)
            completed_followups = counts[4].number_input(
                "完成补证", min_value=0, step=1
            )
        note_columns = st.columns(2)
        confusion_notes = note_columns[0].text_area(
            "困惑点",
            placeholder="在哪一步犹豫、找不到入口或不理解提示？",
            max_chars=2000,
            height=80,
        )
        next_action = note_columns[1].text_area(
            "下一步动作",
            placeholder="写下可执行的修正、复核或补证动作。",
            max_chars=2000,
            height=80,
        )
        submitted = st.form_submit_button(
            "保存试用记录", type="primary", disabled=demo_locked
        )
    if submitted:
        try:
            db.create_pilot_session(
                project_id,
                session_code,
                session_date.isoformat(),
                operator_alias=operator_alias,
                manual_minutes=_optional_minutes(manual_minutes, "原流程耗时"),
                qingji_minutes=_optional_minutes(qingji_minutes, "青迹流程耗时"),
                overclaim_alerts=int(overclaim_alerts),
                adopted_alerts=int(adopted_alerts),
                false_positives=int(false_positives),
                false_negatives=int(false_negatives),
                completed_followups=int(completed_followups),
                confusion_notes=confusion_notes,
                next_action=next_action,
                status=status,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("试用记录已保存。")
            st.rerun()

with review_tab:
    if not sessions:
        empty_state("当前项目还没有试用记录。完成一次实际流程后，从“新增记录”开始登记。")
    else:
        table_rows = [
            {
                "会话编号": item["session_code"],
                "日期": item["session_date"],
                "状态": PILOT_STATUS_LABELS.get(item["status"], item["status"]),
                "操作者": item["operator_alias"] or "—",
                "原流程分钟": item["manual_minutes"],
                "青迹分钟": item["qingji_minutes"],
                "提醒 / 采纳": f"{item['overclaim_alerts']} / {item['adopted_alerts']}",
                "误报 / 漏报": f"{item['false_positives']} / {item['false_negatives']}",
                "完成补证": item["completed_followups"],
                "更新时间": format_datetime(item["updated_at"]),
            }
            for item in sessions
        ]
        st.dataframe(table_rows, width="stretch", hide_index=True)
        exports = st.columns(2)
        exports[0].download_button(
            "导出试用记录 CSV",
            data=export_pilot_sessions_csv(sessions),
            file_name=f"青迹_{project['name']}_真实试用记录.csv",
            mime="text/csv",
        )
        exports[1].download_button(
            "导出基线摘要",
            data=export_pilot_baseline_markdown(project["name"], sessions),
            file_name=f"青迹_{project['name']}_试用基线摘要.md",
            mime="text/markdown",
            help="汇总已完成会话及数据缺口；明细仍以 CSV 和人工标注记录为准。",
        )

        selected_id = st.selectbox(
            "选择要修订的记录",
            options=[int(item["id"]) for item in sessions],
            format_func=lambda item_id: next(
                f"{item['session_code']} · {item['session_date']}"
                for item in sessions
                if int(item["id"]) == item_id
            ),
        )
        selected = next(item for item in sessions if int(item["id"]) == selected_id)
        with st.form(f"pilot_update_{project_id}_{selected_id}"):
            edit_top = st.columns(4)
            edit_code = edit_top[0].text_input(
                "会话编号 *", value=selected["session_code"], key=f"edit_code_{selected_id}"
            )
            edit_date = edit_top[1].date_input(
                "试用日期 *",
                value=date.fromisoformat(selected["session_date"]),
                key=f"edit_date_{selected_id}",
            )
            edit_alias = edit_top[2].text_input(
                "操作者代号",
                value=selected["operator_alias"],
                key=f"edit_alias_{selected_id}",
            )
            edit_status = edit_top[3].selectbox(
                "状态",
                options=list(PILOT_STATUS_LABELS),
                index=_status_index(selected["status"]),
                format_func=PILOT_STATUS_LABELS.get,
                key=f"edit_status_{selected_id}",
            )
            edit_duration = st.columns(2)
            edit_manual = edit_duration[0].text_input(
                "原流程耗时（分钟）",
                value=(
                    ""
                    if selected["manual_minutes"] is None
                    else str(selected["manual_minutes"])
                ),
                key=f"edit_manual_{selected_id}",
            )
            edit_qingji = edit_duration[1].text_input(
                "青迹流程耗时（分钟）",
                value=(
                    ""
                    if selected["qingji_minutes"] is None
                    else str(selected["qingji_minutes"])
                ),
                key=f"edit_qingji_{selected_id}",
            )
            with st.expander("质量与补证计数（可选）"):
                edit_counts = st.columns(5)
                edit_overclaim = edit_counts[0].number_input(
                    "越界提醒",
                    min_value=0,
                    value=int(selected["overclaim_alerts"]),
                    step=1,
                )
                edit_adopted = edit_counts[1].number_input(
                    "采纳提醒",
                    min_value=0,
                    value=int(selected["adopted_alerts"]),
                    step=1,
                )
                edit_fp = edit_counts[2].number_input(
                    "误报",
                    min_value=0,
                    value=int(selected["false_positives"]),
                    step=1,
                )
                edit_fn = edit_counts[3].number_input(
                    "漏报",
                    min_value=0,
                    value=int(selected["false_negatives"]),
                    step=1,
                )
                edit_followups = edit_counts[4].number_input(
                    "完成补证",
                    min_value=0,
                    value=int(selected["completed_followups"]),
                    step=1,
                )
            edit_notes = st.columns(2)
            edit_confusion = edit_notes[0].text_area(
                "困惑点",
                value=selected["confusion_notes"],
                max_chars=2000,
                height=80,
            )
            edit_action = edit_notes[1].text_area(
                "下一步动作",
                value=selected["next_action"],
                max_chars=2000,
                height=80,
            )
            updated = st.form_submit_button(
                "保存修订", type="primary", disabled=demo_locked
            )
        if updated:
            try:
                db.update_pilot_session(
                    selected_id,
                    project_id,
                    session_code=edit_code,
                    session_date=edit_date.isoformat(),
                    operator_alias=edit_alias,
                    manual_minutes=_optional_minutes(edit_manual, "原流程耗时"),
                    qingji_minutes=_optional_minutes(edit_qingji, "青迹流程耗时"),
                    overclaim_alerts=int(edit_overclaim),
                    adopted_alerts=int(edit_adopted),
                    false_positives=int(edit_fp),
                    false_negatives=int(edit_fn),
                    completed_followups=int(edit_followups),
                    confusion_notes=edit_confusion,
                    next_action=edit_action,
                    status=edit_status,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("试用记录已更新。")
                st.rerun()
