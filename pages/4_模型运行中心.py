"""Project-local model run history and safe recovery actions."""

from __future__ import annotations

import streamlit as st

from qingji.config import llm_settings
from qingji.ui import (
    configure_page,
    empty_state,
    format_datetime,
    get_demo_context,
    render_page_intro,
    render_sidebar_note,
)
from qingji.workflow import retry_failed_model_run, retry_material_model_processing


RUN_TYPE_LABELS = {
    "llm_evidence_card_generation": "证据卡生成",
    "llm_evidence_card_full_coverage": "缺失证据卡补齐",
    "llm_material_claim_candidate_generation": "材料结论候选提取",
    "llm_evidence_review": "批量证据审核",
    "llm_evidence_assistance": "单卡草拟辅助",
    "llm_evidence_card_regeneration": "拒绝卡重新生成",
    "llm_claim_evidence_review": "结论—证据语义复核",
    "llm_claim_assistance": "结论改写与补证建议",
}
STATUS_LABELS = {"completed": "已完成", "failed": "失败", "running": "运行中"}
RETRYABLE_TYPES = {
    "llm_evidence_card_generation",
    "llm_evidence_card_full_coverage",
    "llm_material_claim_candidate_generation",
}


configure_page("模型运行中心", "🧭")
try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"读取项目失败：{exc}")
    st.stop()

render_sidebar_note(project, database=db, project_id=project_id)
render_page_intro("04 · MODEL OPERATIONS", "模型运行中心")
st.caption("查看当前项目的模型任务、失败原因与安全重试。这里不会展示 API Key 或未脱敏原文。")

runs = db.list_model_runs(project_id, limit=500)
completed_count = sum(item.get("status") == "completed" for item in runs)
failed_count = sum(item.get("status") == "failed" for item in runs)
metric_columns = st.columns(4)
metric_columns[0].metric("模型运行", len(runs))
metric_columns[1].metric("已完成", completed_count)
metric_columns[2].metric("失败", failed_count)
metric_columns[3].metric("模型配置", "可用" if llm_settings.configured else "未就绪")

if not llm_settings.configured:
    st.warning("当前模型配置未就绪。请更新本地 .env 并重启 Streamlit 后再执行恢复。")
else:
    st.info(f"当前 provider：{llm_settings.provider}；模型：{llm_settings.model}")

trust_retry = st.checkbox(
    "我确认仅对已授权、已脱敏材料执行模型恢复，并接受相应服务费用与数据政策",
    key=f"model_center_trust_{project_id}",
)

st.markdown("### 待恢复材料")
materials = db.list_materials(project_id)
cards = db.list_evidence_cards(project_id)
candidates = db.list_claim_candidates(project_id)
completed_candidate_material_ids = {
    int((run.get("input") or {}).get("material_id") or 0)
    for run in runs
    if run.get("run_type") == "llm_material_claim_candidate_generation"
    and run.get("status") == "completed"
}
incomplete_materials: list[dict] = []
for material in materials:
    if material.get("consent_status") != "confirmed":
        continue
    material_id = int(material["id"])
    segment_ids = {int(item["id"]) for item in db.list_segments(material_id)}
    covered_ids = {
        int(card["segment_id"])
        for card in cards
        if int(card.get("material_id") or 0) == material_id
    }
    has_candidates = any(
        int(item.get("material_id") or 0) == material_id for item in candidates
    )
    missing_count = len(segment_ids - covered_ids)
    candidate_pending = (
        not has_candidates
        and material_id not in completed_candidate_material_ids
    )
    if missing_count or candidate_pending:
        incomplete_materials.append(
            {
                **material,
                "missing_count": missing_count,
                "candidate_pending": candidate_pending,
            }
        )

if not incomplete_materials:
    st.success("当前没有需要断点恢复的已授权材料。")
else:
    selected_material_id = st.selectbox(
        "选择材料",
        options=[int(item["id"]) for item in incomplete_materials],
        format_func=lambda item: next(
            (
                f"M{item} · {row.get('original_filename') or '未命名材料'}"
                f" · 缺卡 {row['missing_count']} · "
                f"候选{'待恢复' if row['candidate_pending'] else '已完成'}"
                for row in incomplete_materials
                if int(row["id"]) == item
            ),
            f"M{item}",
        ),
        key=f"model_center_material_{project_id}",
    )
    if st.button(
        "恢复所选材料的模型处理",
        type="primary",
        disabled=not llm_settings.configured or not trust_retry,
        key=f"model_center_resume_material_{project_id}",
    ):
        selected = next(
            item for item in incomplete_materials if int(item["id"]) == selected_material_id
        )
        with st.spinner("正在从已保存的脱敏片段恢复处理……"):
            result = retry_material_model_processing(
                db,
                project_id,
                selected_material_id,
                retry_evidence=bool(selected["missing_count"]),
                retry_claim_candidates=bool(selected["candidate_pending"]),
            )
        if result.errors:
            for error in result.errors:
                st.error(error)
        if result.evidence_card_ids or result.claim_candidate_ids:
            st.success(
                f"恢复完成：新增证据卡 {len(result.evidence_card_ids)} 张，"
                f"新增结论候选 {len(result.claim_candidate_ids)} 条。"
            )
            st.rerun()

st.divider()
st.markdown("### 运行历史")
run_types = sorted({str(item.get("run_type") or "") for item in runs})
filter_columns = st.columns(2)
with filter_columns[0]:
    status_filter = st.selectbox(
        "运行状态",
        options=["all", "failed", "completed", "running"],
        format_func=lambda item: "全部" if item == "all" else STATUS_LABELS.get(item, item),
        key=f"model_center_status_{project_id}",
    )
with filter_columns[1]:
    type_filter = st.selectbox(
        "任务类型",
        options=["all", *run_types],
        format_func=lambda item: "全部" if item == "all" else RUN_TYPE_LABELS.get(item, item),
        key=f"model_center_type_{project_id}",
    )

filtered_runs = [
    run
    for run in runs
    if (status_filter == "all" or run.get("status") == status_filter)
    and (type_filter == "all" or run.get("run_type") == type_filter)
]
if not filtered_runs:
    empty_state("当前筛选条件下没有模型运行记录。")
for run in filtered_runs:
    run_id = int(run["id"])
    run_type = str(run.get("run_type") or "")
    status = str(run.get("status") or "")
    run_input = run.get("input") or {}
    material_id = int(run_input.get("material_id") or 0)
    title = (
        f"R{run_id} · {STATUS_LABELS.get(status, status)} · "
        f"{RUN_TYPE_LABELS.get(run_type, run_type)}"
    )
    with st.expander(title, expanded=status == "failed"):
        st.caption(
            f"创建：{format_datetime(run.get('created_at'))}"
            + (f" · 完成：{format_datetime(run.get('finished_at'))}" if run.get("finished_at") else "")
        )
        summary = {
            "材料": f"M{material_id}" if material_id else "—",
            "证据卡数": run_input.get("card_count") or run_input.get("segment_count") or "—",
            "模型": run_input.get("model") or (run.get("output") or {}).get("model") or "—",
            "恢复自": f"R{run_input['retry_of_run_id']}" if run_input.get("retry_of_run_id") else "—",
        }
        st.dataframe([summary], width="stretch", hide_index=True)
        if run.get("error_message"):
            st.error(str(run["error_message"]))
        can_retry = status == "failed" and run_type in RETRYABLE_TYPES and material_id > 0
        if can_retry and st.button(
            "从该失败点重试",
            disabled=not llm_settings.configured or not trust_retry,
            key=f"retry_model_run_{project_id}_{run_id}",
        ):
            with st.spinner("正在从已保存的脱敏片段重试……"):
                result = retry_failed_model_run(db, project_id, run_id)
            if result.errors:
                for error in result.errors:
                    st.error(error)
            else:
                st.success(
                    f"重试完成：新增证据卡 {len(result.evidence_card_ids)} 张，"
                    f"新增结论候选 {len(result.claim_candidate_ids)} 条。"
                )
                st.rerun()
        elif status == "failed":
            st.caption("该任务缺少可安全重建的材料输入，保留记录供人工诊断。")
