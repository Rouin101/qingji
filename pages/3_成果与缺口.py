"""Reviewed claims, evidence gaps and trustworthy export page."""

from __future__ import annotations

import streamlit as st

from qingji.export import export_project_markdown
from qingji.ui import (
    TASK_STATUS_LABELS,
    VERDICT_ICONS,
    VERDICT_LABELS,
    configure_page,
    empty_state,
    format_datetime,
    get_demo_context,
    render_demo_banner,
    render_page_intro,
    render_sidebar_note,
)


configure_page("成果与缺口", "📄")

try:
    db, project_id, project = get_demo_context()
    claims = db.list_claims(project_id)
    tasks = db.list_followup_tasks(project_id=project_id)
    stats = db.get_project_stats(project_id)
except Exception as exc:
    st.error(f"读取成果数据失败：{exc}")
    st.stop()

render_sidebar_note(project)
render_page_intro(
    "03 · OUTPUT & GAPS",
    "成果与缺口",
    "把已经核验的表述、结论—证据关系和未解决任务放在一起，导出时继续保留来源定位。",
)
render_demo_banner(project)

summary_columns = st.columns(4)
summary_columns[0].metric("核验记录", len(claims))
summary_columns[1].metric(
    "可引用证据", stats.get("approved_evidence_cards", 0)
)
summary_columns[2].metric(
    "待补证", sum(task.get("status") == "open" for task in tasks)
)
summary_columns[3].metric(
    "已完成补证", sum(task.get("status") == "done" for task in tasks)
)

tab_claims, tab_tasks, tab_mapping, tab_export = st.tabs(
    ["已核验结论", "补证任务", "证据对应表", "可信导出"]
)

with tab_claims:
    st.markdown("### 已核验结论")
    claim_filter_col, claim_search_col = st.columns([2, 3])
    with claim_filter_col:
        claim_verdict_filter = st.segmented_control(
            "核验状态",
            options=[
                "all",
                "supported",
                "partially_supported",
                "unsupported",
                "contradicted",
            ],
            default="all",
            format_func=lambda item: (
                "全部" if item == "all" else VERDICT_LABELS[item]
            ),
            key=f"output_claim_verdict_{project_id}",
        )
    with claim_search_col:
        claim_query = st.text_input(
            "搜索结论",
            placeholder="输入结论中的关键词",
            key=f"output_claim_query_{project_id}",
        )
    filtered_claims = db.list_claims(
        project_id,
        verdict=(
            None if claim_verdict_filter == "all" else claim_verdict_filter
        ),
        query=claim_query,
    )
    st.caption(f"当前显示 {len(filtered_claims)} / {len(claims)} 条核验记录。")
    if not filtered_claims:
        empty_state(
            "当前筛选条件下没有核验记录。"
            if claims
            else "尚无核验结果。请先到“结论核验”页面检查一句话。"
        )
    for claim in filtered_claims:
        verdict = claim.get("verdict", "unsupported")
        with st.expander(
            f"C{claim['id']} · {VERDICT_ICONS.get(verdict, '🔎')} "
            f"{VERDICT_LABELS.get(verdict, verdict)} · "
            f"{claim.get('claim_text', '未命名结论')}",
            expanded=claim is filtered_claims[0],
        ):
            st.markdown(f"**判断理由：** {claim.get('reason') or '—'}")
            st.markdown(
                f"**稳妥改写：** {claim.get('safe_rewrite') or '暂不建议写入成果'}"
            )
            st.caption(f"核验时间：{format_datetime(claim.get('checked_at'))}")
            missing = claim.get("missing_evidence") or []
            if missing:
                st.markdown("**未解决缺口**")
                for item in missing:
                    st.markdown(f"- {item}")
            if st.button(
                "在结论核验中打开",
                key=f"open_claim_{claim['id']}",
            ):
                st.session_state["active_claim_id"] = int(claim["id"])
                st.session_state["claim_draft"] = claim.get("claim_text", "")
                st.switch_page("pages/2_结论核验.py")

with tab_tasks:
    st.markdown("### 补证任务")
    status_filter = st.segmented_control(
        "任务状态",
        options=["all", "open", "done", "cancelled"],
        default="all",
        format_func=lambda item: (
            "全部" if item == "all" else TASK_STATUS_LABELS[item]
        ),
    )
    filtered_tasks = [
        task
        for task in tasks
        if status_filter == "all" or task.get("status") == status_filter
    ]
    if not filtered_tasks:
        empty_state("当前筛选条件下没有补证任务。")
    for task in filtered_tasks:
        status = TASK_STATUS_LABELS.get(task.get("status"), "未知")
        st.markdown(
            f"""
            <div class="qj-card">
              <div class="qj-card-label">T{task['id']} · {status}</div>
              <strong>{task.get('title') or '补证任务'}</strong>
              <div class="qj-meta">{task.get('recommended_action') or '—'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if task.get("completion_material_filename"):
            st.caption(
                f"完成材料：{task['completion_material_filename']}"
            )

with tab_mapping:
    st.markdown("### 结论—证据对应表")
    rows: list[dict[str, str]] = []
    for claim_summary in claims:
        claim = db.get_claim(int(claim_summary["id"])) or claim_summary
        links = claim.get("evidence_links") or []
        if not links:
            rows.append(
                {
                    "结论编号": f"C{claim['id']}",
                    "结论": claim.get("claim_text", ""),
                    "关系": "暂无可引用证据",
                    "证据编号": "—",
                    "证据": "—",
                    "来源定位": "—",
                }
            )
        for link in links:
            relation = {
                "support": "支持",
                "contradict": "冲突",
                "context": "背景",
            }.get(link.get("relation"), "未知")
            rows.append(
                {
                    "结论编号": f"C{claim['id']}",
                    "结论": claim.get("claim_text", ""),
                    "关系": relation,
                    "证据编号": f"E{link.get('evidence_card_id', '—')}",
                    "证据": link.get("evidence_title", ""),
                    "来源定位": link.get("source_locator", ""),
                }
            )
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        empty_state("尚无结论—证据关系。")

with tab_export:
    st.markdown("### 导出可信 Markdown")
    st.caption(
        "导出仅包含已脱敏、已授权、已审核的证据引用，并明确保留虚构测试声明和未解决缺口。"
    )
    try:
        markdown_output = export_project_markdown(db, project_id)
    except Exception as exc:
        st.error(f"生成导出内容失败：{exc}")
        markdown_output = ""

    if markdown_output:
        st.download_button(
            "下载 Markdown",
            data=markdown_output.encode("utf-8"),
            file_name="青迹_虚构测试项目_可信导出.md",
            mime="text/markdown",
            type="primary",
            width="stretch",
        )
        with st.expander("预览导出内容"):
            st.code(markdown_output, language="markdown")
    else:
        empty_state("当前没有可导出的内容。")

    st.warning(
        "导出不是事实认证。正式使用前仍需项目成员回看原材料、授权记录和来源定位。"
    )
