"""Material import and evidence review page."""

from __future__ import annotations

from datetime import date

import streamlit as st

from qingji.models import ConsentStatus
from qingji.ui import (
    CONSENT_LABELS,
    EVIDENCE_TYPE_LABELS,
    REVIEW_STATUS_LABELS,
    configure_page,
    empty_state,
    evidence_card_html,
    format_datetime,
    get_demo_context,
    is_demo_project,
    render_demo_banner,
    render_page_intro,
    render_sidebar_note,
)
from qingji.workflow import import_text_material, review_evidence_card


configure_page("材料与证据", "🗂️")

try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"读取项目失败：{exc}")
    st.stop()

render_sidebar_note(project)
render_page_intro(
    "01 · MATERIALS & EVIDENCE",
    "材料与证据",
    "先说明材料从哪里来、是否获得授权，再让系统生成待人工审核的证据卡。",
)
render_demo_banner(project)
demo_mode = is_demo_project(project)

tab_import, tab_review, tab_materials = st.tabs(
    ["导入文字材料", "审核证据卡", "材料清单"]
)

with tab_import:
    if demo_mode:
        st.markdown("### 导入新的测试材料")
        st.caption(
            "可粘贴文字，或上传 UTF-8 编码的 .txt/.md 文件。"
            "当前是内置演示项目，请只使用虚构测试内容。"
        )
    else:
        st.markdown("### 导入新的文字材料")
        st.caption(
            "可粘贴文字，或上传 UTF-8 编码的 .txt/.md 文件。"
            "请如实填写材料属性和授权状态；未确认授权的材料不会进入核验。"
        )

    uploaded = st.file_uploader(
        "上传文字文件（可选）",
        type=["txt", "md"],
        help="文件内容会先在本地读取，不会自动发送到云端。",
    )
    uploaded_text = ""
    uploaded_error = ""
    if uploaded is not None:
        try:
            uploaded_text = uploaded.getvalue().decode("utf-8-sig")
        except UnicodeDecodeError:
            uploaded_error = "文件不是 UTF-8 编码，请转换编码后重试。"
            st.error(uploaded_error)

    with st.form("material_import_form", clear_on_submit=True):
        if demo_mode:
            is_fictional = True
        else:
            material_nature = st.radio(
                "材料属性",
                options=["real", "fictional"],
                format_func=lambda item: (
                    "真实材料" if item == "real" else "虚构测试数据"
                ),
                horizontal=True,
                help="真实材料必须有权记录和使用；虚构材料必须明确标注。",
            )
            is_fictional = material_nature == "fictional"
        initial_text = uploaded_text or st.session_state.get(
            "material_draft_text", ""
        )
        text = st.text_area(
            "材料正文",
            value=initial_text,
            height=220,
            placeholder=(
                "示例（虚构）：模拟受访者D表示，第一次进入平台时没有找到"
                "验证码输入位置，经志愿者提示后完成了操作……"
            ),
        )
        metadata_left, metadata_right = st.columns(2)
        with metadata_left:
            filename = st.text_input(
                "材料名称",
                value=(
                    uploaded.name
                    if uploaded is not None
                    else (
                        "手工录入_虚构测试笔记.txt"
                        if is_fictional
                        else "手工录入_经授权记录.txt"
                    )
                ),
            )
            source_options = (
                [
                    "模拟受访者（虚构）",
                    "模拟工作人员（虚构）",
                    "模拟调研团队观察员",
                    "虚构正式记录",
                    "团队分析",
                ]
                if is_fictional
                else ["受访者", "工作人员", "调研团队观察员", "正式记录", "团队分析"]
            )
            source_role = st.selectbox(
                "来源角色",
                source_options,
                help="来源角色会影响默认的证据类型，但仍需人工审核。",
            )
            captured_at = st.date_input("采集日期", value=date.today())
        with metadata_right:
            context = st.text_input(
                "采集场景",
                value=(
                    "虚构的便民服务体验访谈，仅用于青迹功能测试"
                    if is_fictional
                    else ""
                ),
                placeholder="说明材料获取的时间、地点或活动场景",
            )
            consent_choice = st.radio(
                "记录与使用授权",
                options=["confirmed", "unknown", "denied"],
                format_func=lambda item: CONSENT_LABELS[item],
                horizontal=True,
                help="未确认或被拒绝授权的材料不会成为可引用证据。",
            )
            custom_terms_text = st.text_input(
                "自定义敏感词（可选）",
                placeholder="用逗号分隔，例如：虚构姓名, 虚构详细地址",
                help="适合标记姓名、精确住址或本项目特有身份信息。",
            )

        material_confirmed = st.checkbox(
            (
                "我确认本次提交的是虚构测试数据，不对应真实个人或真实调研结论。"
                if is_fictional
                else "我确认已如实填写授权状态，并会在引用或导出前复核脱敏文本。"
            ),
            value=False,
        )
        submitted = st.form_submit_button(
            "本地检查并生成证据卡",
            type="primary",
            width="stretch",
        )

    if submitted:
        if uploaded_error:
            st.error("请先解决文件编码问题。")
        elif not text.strip():
            st.error("材料正文不能为空。")
        elif not filename.strip():
            st.error("请填写材料名称，便于后续追溯。")
        elif not context.strip():
            st.error("请填写采集场景。")
        elif not material_confirmed:
            st.error("请先确认材料属性、授权状态和脱敏复核责任。")
        else:
            custom_terms = [
                item.strip()
                for item in custom_terms_text.replace("，", ",").split(",")
                if item.strip()
            ]
            try:
                with st.spinner("正在本地检查隐私并生成证据卡……"):
                    result = import_text_material(
                        db,
                        project_id,
                        text,
                        original_filename=filename.strip(),
                        source_role=source_role,
                        context=context.strip(),
                        captured_at=captured_at.isoformat(),
                        consent_status=ConsentStatus(consent_choice),
                        custom_sensitive_terms=custom_terms,
                        is_fictional=is_fictional,
                    )
            except Exception as exc:
                st.error(f"材料导入失败：{exc}")
            else:
                st.session_state["last_import_result"] = result
                st.success(
                    f"材料 M{result.material_id} 已保存，生成 "
                    f"{len(result.evidence_card_ids)} 张待审核证据卡。"
                )
                if result.warnings:
                    for warning in result.warnings:
                        st.warning(warning)
                st.markdown("**确认后的脱敏文本**")
                st.code(result.redacted_text, language=None)
                if consent_choice != "confirmed":
                    st.info("这份材料已保存，但在授权确认前不会进入结论核验。")

with tab_review:
    st.markdown("### 人工审核证据卡")
    filter_columns = st.columns([1, 1, 2])
    with filter_columns[0]:
        review_filter = st.selectbox(
            "审核状态",
            ["all", "draft", "approved", "rejected"],
            format_func=lambda item: (
                "全部" if item == "all" else REVIEW_STATUS_LABELS[item]
            ),
        )
    with filter_columns[1]:
        type_filter = st.selectbox(
            "证据类型",
            ["all", *EVIDENCE_TYPE_LABELS],
            format_func=lambda item: (
                "全部" if item == "all" else EVIDENCE_TYPE_LABELS[item]
            ),
        )

    try:
        cards = db.list_evidence_cards(
            project_id,
            review_status=None if review_filter == "all" else review_filter,
            evidence_type=None if type_filter == "all" else type_filter,
        )
    except Exception as exc:
        st.error(f"读取证据卡失败：{exc}")
        cards = []

    if not cards:
        empty_state("当前筛选条件下没有证据卡。")
    for card in cards:
        card_id = int(card["id"])
        title = card.get("title") or f"证据 E{card_id}"
        with st.expander(
            f"E{card_id} · {title} · "
            f"{REVIEW_STATUS_LABELS.get(card.get('review_status'), '未知')}",
            expanded=card.get("review_status") == "draft",
        ):
            st.markdown(evidence_card_html(card), unsafe_allow_html=True)
            if card.get("consent_status") != "confirmed":
                st.warning("来源材料尚未确认授权。即使批准，仍不会进入可引用证据集。")

            with st.form(f"evidence_edit_{card_id}"):
                edited_title = st.text_input(
                    "证据标题", value=card.get("title", "")
                )
                edited_summary = st.text_area(
                    "证据摘要", value=card.get("summary", ""), height=80
                )
                edited_type = st.selectbox(
                    "证据类型",
                    list(EVIDENCE_TYPE_LABELS),
                    index=list(EVIDENCE_TYPE_LABELS).index(
                        card.get("evidence_type", "team_analysis")
                    ),
                    format_func=lambda item: EVIDENCE_TYPE_LABELS[item],
                    key=f"type_{card_id}",
                )
                decision = st.radio(
                    "审核结论",
                    ["draft", "approved", "rejected"],
                    index=["draft", "approved", "rejected"].index(
                        card.get("review_status", "draft")
                    ),
                    format_func=lambda item: REVIEW_STATUS_LABELS[item],
                    horizontal=True,
                    key=f"decision_{card_id}",
                )
                save_card = st.form_submit_button(
                    "保存审核结果", type="primary"
                )
            if save_card:
                if not edited_title.strip() or not edited_summary.strip():
                    st.error("证据标题和摘要不能为空。")
                else:
                    try:
                        review_result = review_evidence_card(
                            db,
                            card_id,
                            title=edited_title.strip(),
                            summary=edited_summary.strip(),
                            evidence_type=edited_type,
                            review_status=decision,
                        )
                    except Exception as exc:
                        st.error(f"保存审核结果失败：{exc}")
                    else:
                        refreshed_count = len(review_result.rechecked_claim_ids)
                        if refreshed_count:
                            st.success(
                                f"证据 E{card_id} 已更新，并已重新核验当前项目的 "
                                f"{refreshed_count} 条结论。"
                            )
                        else:
                            st.success(f"证据 E{card_id} 已更新。")
                        st.rerun()

with tab_materials:
    st.markdown("### 已保存材料")
    try:
        materials = db.list_materials(project_id)
    except Exception as exc:
        st.error(f"读取材料列表失败：{exc}")
        materials = []
    if not materials:
        empty_state("尚无材料。")
    for material in materials:
        fictional = "虚构测试" if material.get("is_fictional") else "用户导入"
        with st.expander(
            f"M{material['id']} · "
            f"{material.get('original_filename') or '未命名材料'} · {fictional}"
        ):
            detail_columns = st.columns(3)
            detail_columns[0].markdown(
                f"**来源角色**  \n{material.get('source_role') or '—'}"
            )
            detail_columns[1].markdown(
                f"**授权状态**  \n"
                f"{CONSENT_LABELS.get(material.get('consent_status'), '—')}"
            )
            detail_columns[2].markdown(
                f"**采集时间**  \n{format_datetime(material.get('captured_at'))}"
            )
            st.markdown(f"**场景：** {material.get('context') or '—'}")
            if material.get("notes"):
                st.caption(material["notes"])
