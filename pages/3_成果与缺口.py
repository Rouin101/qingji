"""Reviewed claims, evidence gaps and trustworthy export page."""

from __future__ import annotations

import streamlit as st

from qingji.evaluation import (
    build_eval_history_rows,
    build_eval_template,
    export_eval_run_csv,
    export_eval_run_markdown,
    parse_eval_csv,
    run_project_retrieval_eval,
)
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
    render_next_action,
    render_page_intro,
    render_sidebar_note,
    render_workflow_steps,
)


EVAL_CATEGORY_LABELS = {
    "direct": "直接匹配",
    "paraphrase": "同义改写",
    "zero_hit": "零命中",
    "conflict": "冲突召回",
    "custom": "自定义",
}


def render_eval_report(report: dict, *, title: str = "评测结果") -> None:
    st.markdown(f"#### {title}")
    summary_columns = st.columns(3)
    summary_columns[0].metric("用例数", report.get("case_count", 0))
    summary_columns[1].metric("通过数", report.get("passed_count", 0))
    summary_columns[2].metric(
        "通过率", f"{float(report.get('pass_rate', 0)):.0%}"
    )
    categories = report.get("categories") or {}
    if categories:
        category_columns = st.columns(len(categories))
        for column, (name, summary) in zip(
            category_columns, categories.items()
        ):
            column.metric(
                EVAL_CATEGORY_LABELS.get(name, name),
                f"{summary.get('passed_count', 0)}/"
                f"{summary.get('case_count', 0)}",
            )
    result_rows = []
    for result in report.get("results") or []:
        expected_ids = result.get("expected_evidence_ids") or []
        ranks = result.get("expected_id_ranks") or {}
        result_rows.append(
            {
                "结果": "通过" if result.get("passed") else "未通过",
                "用例": result.get("name", ""),
                "类别": EVAL_CATEGORY_LABELS.get(
                    result.get("category"), result.get("category", "")
                ),
                "目标证据": (
                    "、".join(f"E{item}" for item in expected_ids)
                    if expected_ids
                    else "要求零命中"
                ),
                "目标排名": (
                    "、".join(
                        f"E{key}: {value if value is not None else '未召回'}"
                        for key, value in ranks.items()
                    )
                    if ranks
                    else "—"
                ),
                "相关候选数": result.get("relevant_count", 0),
            }
        )
    if result_rows:
        st.dataframe(result_rows, width="stretch", hide_index=True)


configure_page("成果与缺口", "📄")

try:
    db, project_id, project = get_demo_context()
    claims = db.list_claims(project_id)
    tasks = db.list_followup_tasks(project_id=project_id)
    stats = db.get_project_stats(project_id)
except Exception as exc:
    st.error(f"读取成果数据失败：{exc}")
    st.stop()

render_sidebar_note(project, database=db, project_id=project_id)
render_page_intro(
    "03 · OUTPUT & GAPS",
    "成果与缺口",
    "把已经核验的表述、结论—证据关系和未解决任务放在一起，导出时继续保留来源定位。",
)
render_demo_banner(project)
render_workflow_steps("output")
render_next_action(
    db.get_project_stats(project_id),
    heading="成果处理进度",
    current_step="output",
)

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

tab_claims, tab_tasks, tab_mapping, tab_export, tab_eval = st.tabs(
    ["已核验结论", "补证任务", "证据对应表", "可信导出", "检索评测"]
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
        if not claims:
            st.page_link(
                "pages/2_结论核验.py",
                label="去结论核验开始第一条检查",
                icon="🔎",
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
    completion_materials = db.list_materials(
        project_id, consent_status="confirmed"
    )
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
        task_id = int(task["id"])
        status = TASK_STATUS_LABELS.get(task.get("status"), "未知")
        with st.container(border=True):
            st.markdown(
                f"**T{task_id} · {status} · {task.get('title') or '补证任务'}**"
            )
            st.caption(
                f"对应结论：C{task.get('claim_id', '—')} · "
                f"{task.get('claim_text') or '—'}"
            )
            st.write(task.get("recommended_action") or "—")
            if task.get("completion_material_filename"):
                st.caption(
                    f"完成材料：{task['completion_material_filename']}"
                )

            if task.get("status") == "open":
                if completion_materials:
                    material_options = [int(item["id"]) for item in completion_materials]
                    material_by_id = {
                        int(item["id"]): item for item in completion_materials
                    }
                    with st.form(f"complete_task_{task_id}"):
                        selected_material_id = st.selectbox(
                            "选择完成任务的材料",
                            options=material_options,
                            format_func=lambda item: (
                                f"M{item} · "
                                f"{material_by_id[item].get('original_filename') or '未命名材料'}"
                            ),
                            key=f"completion_material_{task_id}",
                            help="只显示当前项目中已确认授权的材料。",
                        )
                        complete_submitted = st.form_submit_button(
                            "标记为已完成",
                            type="primary",
                        )
                    if complete_submitted:
                        try:
                            db.set_followup_task_status(
                                task_id,
                                "done",
                                completion_material_id=int(selected_material_id),
                            )
                        except Exception as exc:
                            st.error(f"更新补证任务失败：{exc}")
                        else:
                            st.success(f"补证任务 T{task_id} 已完成。")
                            st.rerun()
                else:
                    st.warning(
                        "当前项目还没有已确认授权的材料。请先导入并确认材料，再完成此任务。"
                    )
                    st.page_link(
                        "pages/1_材料与证据.py",
                        label="去材料与证据导入完成材料",
                        icon="🗂️",
                    )
                if st.button(
                    "取消任务",
                    key=f"cancel_task_{task_id}",
                ):
                    try:
                        db.set_followup_task_status(task_id, "cancelled")
                    except Exception as exc:
                        st.error(f"更新补证任务失败：{exc}")
                    else:
                        st.success(f"补证任务 T{task_id} 已取消。")
                        st.rerun()
            else:
                if st.button(
                    "重新打开任务",
                    key=f"reopen_task_{task_id}",
                ):
                    try:
                        db.update_followup_task(
                            task_id,
                            status="open",
                            completion_material_id=None,
                        )
                    except Exception as exc:
                        st.error(f"重新打开补证任务失败：{exc}")
                    else:
                        st.success(f"补证任务 T{task_id} 已重新打开。")
                        st.rerun()

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
        "导出仅包含已脱敏、已授权、已审核的证据引用，并保留来源边界和未解决缺口。"
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
            file_name=f"青迹_项目{project_id}_可信导出.md",
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

with tab_eval:
    st.markdown("### 自定义检索评测")
    st.caption(
        "评测只在本地运行并保存到当前项目。目标证据必须属于当前项目，"
        "且已确认授权、已人工批准。评测成绩不能替代真实项目上的人工检查。"
    )
    evidence_rows = db.list_evidence_cards(project_id)
    eligible_rows = [
        row
        for row in evidence_rows
        if row.get("review_status") == "approved"
        and row.get("consent_status") == "confirmed"
    ]
    st.metric("当前可作为评测目标的证据", len(eligible_rows))
    if eligible_rows:
        with st.expander("查看可用证据编号"):
            st.dataframe(
                [
                    {
                        "证据编号": f"E{row['id']}",
                        "标题": row.get("title", ""),
                        "来源定位": row.get("source_locator") or "—",
                    }
                    for row in eligible_rows
                ],
                width="stretch",
                hide_index=True,
            )
    else:
        empty_state("当前没有已授权、已批准的证据，暂时无法建立目标召回用例。")

    st.download_button(
        "下载当前项目的 CSV 模板",
        data=build_eval_template(evidence_rows),
        file_name=f"青迹_项目{project_id}_检索评测模板.csv",
        mime="text/csv",
        width="stretch",
    )
    uploaded_eval = st.file_uploader(
        "上传填写后的评测 CSV",
        type=["csv"],
        key=f"retrieval_eval_upload_{project_id}",
        help="文件必须为 UTF-8 编码、不超过 1 MiB，单次最多 100 个用例。",
        max_upload_size=1,
    )
    top_k = st.slider(
        "候选范围 Top-K",
        min_value=1,
        max_value=10,
        value=3,
        key=f"retrieval_eval_top_k_{project_id}",
    )
    parsed_cases = None
    if uploaded_eval is not None:
        try:
            parsed_cases = parse_eval_csv(uploaded_eval.getvalue())
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"已读取 {len(parsed_cases)} 个评测用例。")
            st.dataframe(
                [
                    {
                        "用例": case.name,
                        "类别": EVAL_CATEGORY_LABELS.get(
                            case.category, case.category
                        ),
                        "查询": case.query,
                        "目标证据": (
                            "、".join(
                                f"E{item}"
                                for item in case.expected_evidence_ids
                            )
                            if case.expected_evidence_ids
                            else "要求零命中"
                        ),
                    }
                    for case in parsed_cases
                ],
                width="stretch",
                hide_index=True,
            )

    if st.button(
        "运行自定义评测",
        type="primary",
        disabled=parsed_cases is None,
        key=f"run_retrieval_eval_{project_id}",
        width="stretch",
    ):
        try:
            with st.spinner("正在本地运行检索评测……"):
                report = run_project_retrieval_eval(
                    db, project_id, parsed_cases, top_k=top_k
                )
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"检索评测运行失败：{exc}")
        else:
            st.session_state[f"retrieval_eval_selection_{project_id}"] = int(
                report["run_id"]
            )
            st.success(
                f"评测完成：{report['passed_count']}/"
                f"{report['case_count']} 个用例通过。"
            )

    eval_runs = db.list_project_runs(project_id, "retrieval_eval", limit=50)
    if not eval_runs:
        empty_state("还没有检索评测记录。上传用例并运行后，结果会保存在当前项目。")
    else:
        st.markdown("#### 评测历史")
        st.caption(
            "通过率变化只在用例集、证据集、检索版本、Top-K 和相关阈值完全一致时比较；"
            "不同配置的成绩不直接作升降判断。"
        )
        history_rows = build_eval_history_rows(eval_runs)
        st.dataframe(
            [
                {
                    "运行": f"R{row['run_id']}",
                    "时间": format_datetime(row.get("created_at")),
                    "用例集": row.get("case_set_id", "未记录"),
                    "证据集": row.get("evidence_set_id", "未记录"),
                    "检索版本": row.get("retrieval_version", "未记录"),
                    "Top-K": row.get("top_k") or "—",
                    "结果": (
                        f"{row.get('passed_count', 0)}/"
                        f"{row.get('case_count', 0)} "
                        f"({float(row.get('pass_rate', 0)):.0%})"
                    ),
                    "分类": "；".join(
                        f"{EVAL_CATEGORY_LABELS.get(name, name)} "
                        f"{summary.get('passed_count', 0)}/"
                        f"{summary.get('case_count', 0)}"
                        for name, summary in row.get("categories", {}).items()
                    )
                    or "—",
                    "与上次可比运行变化": (
                        f"{float(row['pass_rate_delta']):+.0%}"
                        f"（对比 R{row['comparable_to_run_id']}）"
                        if row.get("pass_rate_delta") is not None
                        else "—"
                    ),
                    "可比性": row.get("comparison_status", "—"),
                }
                for row in history_rows
            ],
            width="stretch",
            hide_index=True,
        )

        run_ids = [int(run["id"]) for run in eval_runs]
        selection_key = f"retrieval_eval_selection_{project_id}"
        if st.session_state.get(selection_key) not in run_ids:
            st.session_state[selection_key] = run_ids[0]
        selected_run_id = st.selectbox(
            "查看一次评测",
            options=run_ids,
            format_func=lambda item: next(
                (
                    f"R{row['run_id']} · {format_datetime(row.get('created_at'))} · "
                    f"{row.get('passed_count', 0)}/{row.get('case_count', 0)} 通过"
                    for row in history_rows
                    if int(row["run_id"]) == int(item)
                ),
                f"R{item}",
            ),
            key=selection_key,
        )
        selected_run = next(
            run for run in eval_runs if int(run["id"]) == int(selected_run_id)
        )
        selected_output = selected_run.get("output") or {}
        render_eval_report(
            selected_output,
            title=f"评测运行 R{selected_run_id}",
        )
        selected_summary = next(
            row
            for row in history_rows
            if int(row["run_id"]) == int(selected_run_id)
        )
        threshold_label = selected_summary.get("relevance_threshold")
        if threshold_label is None:
            threshold_label = "未记录"
        st.caption(
            f"用例集 {selected_summary.get('case_set_id', '未记录')} · "
            f"证据集 {selected_summary.get('evidence_set_id', '未记录')} · "
            f"检索版本 {selected_summary.get('retrieval_version', '未记录')} · "
            f"Top-K {selected_summary.get('top_k') or '未记录'} · "
            f"相关阈值 {threshold_label}"
        )
        export_columns = st.columns(2)
        export_columns[0].download_button(
            "下载本次结果 CSV",
            data=export_eval_run_csv(selected_run),
            file_name=(
                f"青迹_项目{project_id}_检索评测_R{selected_run_id}.csv"
            ),
            mime="text/csv",
            width="stretch",
        )
        export_columns[1].download_button(
            "下载本次结果 Markdown",
            data=export_eval_run_markdown(
                selected_run, project.get("name", f"项目{project_id}")
            ).encode("utf-8"),
            file_name=(
                f"青迹_项目{project_id}_检索评测_R{selected_run_id}.md"
            ),
            mime="text/markdown",
            width="stretch",
        )
        st.warning(
            "检索评测通过率不是事实正确率，也不是外部基准成绩；"
            "它只反映当前项目中已授权、已审核证据集上的本地检索表现。"
        )
