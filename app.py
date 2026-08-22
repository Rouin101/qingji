"""青迹 Streamlit entry page."""

from __future__ import annotations

import hashlib

import streamlit as st

from qingji.backup import (
    export_project_backup,
    inspect_project_backup,
    restore_project_backup,
)
from qingji.demo import DEMO_PROJECT_NAME
from qingji.projects import (
    activate_project,
    archive_project_workspace,
    create_project_workspace,
    delete_project_workspace,
    rename_project_workspace,
    restore_project_workspace,
)
from qingji.ui import (
    VERDICT_LABELS,
    configure_page,
    empty_state,
    format_datetime,
    get_demo_context,
    is_demo_project,
    render_demo_banner,
    render_page_intro,
    render_sidebar_note,
    render_workflow_steps,
    verdict_box,
)


configure_page("项目概览", "🌱")

try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"应用初始化失败：{exc}")
    st.info("请确认当前目录可写，并重新运行应用。")
    st.stop()

render_sidebar_note(project, database=db, project_id=project_id)
render_page_intro(
    "QINGJI · 可信社会实践",
    "青迹",
    "把已授权的现场材料变成可回溯证据，检查每一句结论是否说过了头。",
)
render_demo_banner(project)
render_workflow_steps("overview")

with st.expander("第一次使用？按这 4 步完成一次完整体验"):
    st.markdown(
        """
        1. 先查看当前项目中的材料和结论，或新建一个自己的项目。
        2. 在“材料与证据”导入文字材料，填写来源、场景和授权状态。
        3. 人工审核证据卡后，到“结论核验”检查准备写入报告的一句话。
        4. 在“成果与缺口”查看证据对应关系、补证任务并导出 Markdown。

        推荐先完整走一遍当前项目流程，再继续录入其他经授权的材料。
        """
    )

st.markdown("### 项目工作区")
projects = db.list_projects()
project_by_id = {int(item["id"]): item for item in projects}
project_ids = list(project_by_id)
selected_project_id = st.selectbox(
    "当前项目",
    options=project_ids,
    index=project_ids.index(project_id),
    format_func=lambda item: project_by_id[item]["name"],
    help="各项目的材料、证据、结论和补证任务相互隔离。",
)
if int(selected_project_id) != project_id:
    activate_project(st.session_state, int(selected_project_id))
    st.rerun()

with st.expander("新建项目"):
    with st.form("create_project_form", clear_on_submit=True):
        new_project_name = st.text_input(
            "项目名称",
            placeholder="例如：社区公共服务体验调研",
        )
        new_project_description = st.text_area(
            "项目说明（可选）",
            placeholder="简要说明调研对象、材料范围和预期成果。",
            height=100,
        )
        create_submitted = st.form_submit_button(
            "创建并进入项目", type="primary", width="stretch"
        )
    if create_submitted:
        try:
            created_project_id = create_project_workspace(
                db, new_project_name, new_project_description
            )
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"创建项目失败：{exc}")
        else:
            activate_project(st.session_state, created_project_id)
            st.success("项目已创建，正在进入新工作区。")
            st.rerun()

with st.expander("项目备份与恢复"):
    st.caption(
        "备份包包含当前项目的数据库记录、审核历史、评测记录，以及青迹托管的原文和脱敏文件。"
    )
    st.warning("备份包可能含有未经脱敏的原始材料，请妥善保管，不要公开上传。")
    backup_col, restore_col = st.columns(2)
    with backup_col:
        st.markdown("#### 导出当前项目")
        if st.button(
            "生成完整备份包",
            key=f"generate_project_backup_{project_id}",
            width="stretch",
        ):
            try:
                backup = export_project_backup(db, project_id)
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"生成项目备份失败：{exc}")
            else:
                st.session_state["project_backup_payload"] = backup.content
                st.session_state["project_backup_filename"] = backup.filename
                st.session_state["project_backup_source_id"] = project_id
                st.success(
                    f"备份包已生成，包含 {backup.material_file_count} 个材料文件。"
                )
        backup_payload = st.session_state.get("project_backup_payload")
        backup_source_id = st.session_state.get("project_backup_source_id")
        if backup_payload and int(backup_source_id or 0) == project_id:
            st.download_button(
                "下载备份包",
                data=backup_payload,
                file_name=st.session_state.get("project_backup_filename")
                or "青迹_项目备份_v1.zip",
                mime="application/zip",
                key=f"download_project_backup_{project_id}",
                type="primary",
                width="stretch",
            )

    with restore_col:
        st.markdown("#### 恢复为新项目")
        uploaded_backup = st.file_uploader(
            "选择青迹 ZIP 备份包",
            type=["zip"],
            key="restore_project_backup_upload",
        )
        if uploaded_backup is not None:
            uploaded_content = uploaded_backup.getvalue()
            try:
                inspection = inspect_project_backup(uploaded_content)
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"读取项目备份失败：{exc}")
            else:
                st.success(f"备份校验通过：{inspection.source_project_name}")
                st.caption(
                    f"材料 {inspection.counts['materials']} · "
                    f"证据 {inspection.counts['evidence_cards']} · "
                    f"结论 {inspection.counts['claims']} · "
                    f"材料文件 {inspection.material_file_count}"
                )
                default_restore_name = inspection.source_project_name
                if db.get_project_by_name(default_restore_name) is not None:
                    default_restore_name += "（恢复）"
                upload_key = hashlib.sha256(uploaded_content).hexdigest()[:12]
                restored_project_name = st.text_input(
                    "恢复后的项目名称",
                    value=default_restore_name,
                    key=f"restored_project_name_{upload_key}",
                )
                restore_acknowledged = st.checkbox(
                    "我确认备份来源可信，并理解其中可能包含原始材料",
                    key=f"restore_ack_{upload_key}",
                )
                if st.button(
                    "校验并恢复",
                    disabled=not restore_acknowledged,
                    key=f"restore_project_backup_{upload_key}",
                    width="stretch",
                ):
                    try:
                        restored = restore_project_backup(
                            db, uploaded_content, restored_project_name
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"恢复项目失败：{exc}")
                    else:
                        activate_project(st.session_state, restored.project_id)
                        st.success(
                            f"项目“{restored.project_name}”已完整恢复，正在进入新工作区。"
                        )
                        st.rerun()

if not is_demo_project(project):
    with st.expander("管理当前项目"):
        st.caption("重命名会保留全部数据；归档后项目将从日常工作区列表隐藏。")
        with st.form(f"rename_project_{project_id}"):
            edited_project_name = st.text_input(
                "新的项目名称", value=project["name"]
            )
            edited_project_description = st.text_area(
                "项目说明",
                value=project.get("description") or "",
                height=100,
            )
            rename_submitted = st.form_submit_button("保存项目信息")
        if rename_submitted:
            try:
                rename_project_workspace(
                    db,
                    project_id,
                    edited_project_name,
                    edited_project_description,
                )
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"保存项目信息失败：{exc}")
            else:
                st.success("项目信息已更新。")
                st.rerun()

        st.markdown("**归档项目**")
        st.caption("归档不会删除任何材料，可随时从下方恢复。")
        archive_confirmed = st.checkbox(
            "我确认暂时归档当前项目",
            key=f"archive_confirmed_{project_id}",
        )
        if st.button(
            "归档当前项目",
            disabled=not archive_confirmed,
            key=f"archive_project_{project_id}",
        ):
            try:
                archive_project_workspace(db, project_id)
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"归档项目失败：{exc}")
            else:
                demo_project = db.get_project_by_name(
                    DEMO_PROJECT_NAME
                )
                if demo_project is None:
                    st.error("归档成功，但未找到可切换的内置项目。")
                else:
                    activate_project(st.session_state, int(demo_project["id"]))
                    st.success("项目已归档。")
                    st.rerun()

archived_projects = db.list_archived_projects()
if archived_projects:
    with st.expander(f"已归档项目（{len(archived_projects)}）"):
        st.caption("恢复后可继续编辑；永久删除要求输入完整项目名称，且不可撤销。")
        for archived_project in archived_projects:
            archived_id = int(archived_project["id"])
            st.markdown(f"#### {archived_project['name']}")
            st.caption(archived_project.get("description") or "尚未填写项目说明。")
            restore_col, delete_col = st.columns([1, 2])
            with restore_col:
                if st.button(
                    "恢复项目",
                    key=f"restore_project_{archived_id}",
                    width="stretch",
                ):
                    try:
                        restore_project_workspace(db, archived_id)
                    except ValueError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"恢复项目失败：{exc}")
                    else:
                        activate_project(st.session_state, archived_id)
                        st.success("项目已恢复。")
                        st.rerun()
            with delete_col:
                with st.form(f"delete_project_{archived_id}"):
                    delete_confirmation = st.text_input(
                        "输入完整项目名称以永久删除",
                        key=f"delete_name_{archived_id}",
                    )
                    delete_acknowledged = st.checkbox(
                        "我理解数据库记录和本地材料文件将被永久删除",
                        key=f"delete_ack_{archived_id}",
                    )
                    delete_submitted = st.form_submit_button(
                        "永久删除",
                    )
                if delete_submitted:
                    if not delete_acknowledged:
                        st.error("请先确认理解永久删除的影响。")
                    else:
                        try:
                            deletion = delete_project_workspace(
                                db, archived_id, delete_confirmation
                            )
                        except ValueError as exc:
                            st.error(str(exc))
                        except Exception as exc:
                            st.error(f"删除项目失败：{exc}")
                        else:
                            st.success(
                                f"项目已永久删除，同时移除 "
                                f"{deletion.removed_files} 个本地材料文件。"
                            )
                            for warning in deletion.warnings:
                                st.warning(warning)
                            st.rerun()
            st.divider()

st.markdown(f"### {project['name']}")
st.caption(project.get("description") or "尚未填写项目说明。")

try:
    stats = db.get_project_stats(project_id)
    verdict_stats = db.get_claim_verdict_stats(project_id)
    claims = db.list_claims(project_id)
except Exception as exc:
    st.error(f"读取项目数据失败：{exc}")
    st.stop()

metric_columns = st.columns(5)
metric_columns[0].metric("材料", stats.get("materials", 0))
metric_columns[1].metric("已审核证据", stats.get("approved_evidence_cards", 0))
metric_columns[2].metric("已核验结论", stats.get("claims", 0))
metric_columns[3].metric("待补证任务", stats.get("open_followup_tasks", 0))
metric_columns[4].metric(
    "证据可引用率",
    (
        f"{stats.get('approved_evidence_cards', 0) / stats.get('evidence_cards', 1):.0%}"
        if stats.get("evidence_cards", 0)
        else "—"
    ),
)

st.markdown("#### 结论状态分布")
verdict_columns = st.columns(4)
for column, verdict in zip(
    verdict_columns,
    ["supported", "partially_supported", "unsupported", "contradicted"],
):
    column.metric(VERDICT_LABELS[verdict], verdict_stats.get(verdict, 0))

st.markdown("### 从这里开始")
left, right = st.columns(2)
with left:
    st.markdown(
        """
        <div class="qj-card">
          <div class="qj-card-label">01 · 材料进入证据链</div>
          <strong>导入一份文字材料</strong>
          <div class="qj-meta">
          填写来源和授权信息，在本地发现敏感内容，再人工审核证据卡。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("前往材料与证据", type="primary", width="stretch"):
        st.switch_page("pages/1_材料与证据.py")

with right:
    st.markdown(
        """
        <div class="qj-card">
          <div class="qj-card-label">02 · 检查报告表述</div>
          <strong>核验一句准备写入报告的话</strong>
          <div class="qj-meta">
          查看四级判断、相关证据、稳妥改写，以及下一步应补什么材料。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("前往结论核验", type="primary", width="stretch"):
        st.switch_page("pages/2_结论核验.py")

st.markdown("### 最近一次核验")
if not claims:
    empty_state("尚无核验记录。输入一句结论，青迹会先检查它能否被当前材料支持。")
else:
    latest = claims[0]
    verdict_box(latest.get("verdict"), latest.get("reason", ""))
    info_columns = st.columns([3, 1])
    with info_columns[0]:
        st.markdown(f"**待核验表述：** {latest.get('claim_text', '—')}")
        if latest.get("safe_rewrite"):
            st.markdown(f"**稳妥改写：** {latest['safe_rewrite']}")
    with info_columns[1]:
        st.caption(
            f"状态：{VERDICT_LABELS.get(latest.get('verdict'), '尚未核验')}\n\n"
            f"时间：{format_datetime(latest.get('checked_at'))}"
        )

st.markdown("### 青迹如何守住边界")
boundary_columns = st.columns(3)
with boundary_columns[0]:
    st.markdown(
        """
        **先授权、再引用**

        未确认授权的材料可以保存，但不会进入核验候选或可信导出。
        """
    )
with boundary_columns[1]:
    st.markdown(
        """
        **先脱敏、再处理**

        联系方式与自定义敏感词在本地识别；公开成果只使用脱敏片段。
        """
    )
with boundary_columns[2]:
    st.markdown(
        """
        **先审核、再下结论**

        证据卡必须经人工批准；个人陈述不能自动推广成群体事实。
        """
    )

if is_demo_project(project):
    with st.expander("当前项目的使用路径"):
        st.markdown(
            """
            1. 在“材料与证据”查看已授权、已脱敏的项目材料。
            2. 核验“当地居民普遍认为线上办事平台使用困难”。
            3. 添加一份持不同观点的补充材料，重新核验。
            4. 在“成果与缺口”下载可追溯的 Markdown。
            """
        )
