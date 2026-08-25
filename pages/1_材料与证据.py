"""Material import and evidence review page."""

from __future__ import annotations

from datetime import date
import hashlib

import streamlit as st

from qingji.config import llm_settings
from qingji.document import DocumentImportError, extract_uploaded_text
from qingji.llm import (
    LLMError,
    request_evidence_assistance,
    request_evidence_review_batch,
)
from qingji.metadata import infer_material_metadata
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
    render_page_intro,
    render_sidebar_note,
)
from qingji.workflow import (
    import_text_material,
    regenerate_rejected_evidence_card,
    review_evidence_card,
    review_evidence_cards,
)


_REVIEW_FIELD_LABELS = {
    "title": "标题",
    "summary": "摘要",
    "evidence_type": "证据类型",
    "review_status": "审核状态",
}

_SOURCE_ROLE_OPTIONS = [
    "受访者",
    "工作人员",
    "调研团队观察员",
    "正式记录",
    "团队分析",
]
_SINGLE_SOURCE_ROLE_OPTIONS = ["请选择", *_SOURCE_ROLE_OPTIONS]

_MATERIAL_IMPORT_PROJECT_KEY = "material_import_project_id"
_MATERIAL_IMPORT_STATE_DEFAULTS = {
    "material_draft_text": "",
    "material_filename": "手工录入_项目记录.txt",
    "material_source_role": "请选择",
    "material_context": "",
    "material_captured_at": None,
    "material_consent_choice": "confirmed",
    "material_custom_terms": "",
    "material_confirmed": False,
}
_MATERIAL_IMPORT_RESET_KEYS = (
    "single_material_upload_lock",
    "single_material_file",
    "material_metadata_fingerprint",
    "material_metadata_notice",
    *_MATERIAL_IMPORT_STATE_DEFAULTS,
)


def reset_material_import_state_for_project(project_id: int) -> None:
    """Keep the unfinished import form scoped to the current project."""

    previous_project_id = st.session_state.get(_MATERIAL_IMPORT_PROJECT_KEY)
    if previous_project_id is not None and previous_project_id != project_id:
        for key in _MATERIAL_IMPORT_RESET_KEYS:
            st.session_state.pop(key, None)
    st.session_state[_MATERIAL_IMPORT_PROJECT_KEY] = project_id
    for key, default in _MATERIAL_IMPORT_STATE_DEFAULTS.items():
        st.session_state.setdefault(key, default)


def render_review_history(db, project_id: int, evidence_card_id: int) -> None:
    """Render the append-only human review history for one evidence card."""

    events = db.list_evidence_review_events(
        project_id,
        evidence_card_id=evidence_card_id,
        limit=100,
    )
    st.markdown(f"#### 审核历史（{len(events)}）")
    if not events:
        st.caption("暂无审核记录。旧数据和系统初始化状态不会伪造人工审核历史。")
        return
    for event in events:
        before = event.get("before") or {}
        after = event.get("after") or {}
        old_status = REVIEW_STATUS_LABELS.get(
            before.get("review_status"), "未知"
        )
        new_status = REVIEW_STATUS_LABELS.get(
            after.get("review_status"), "未知"
        )
        changed_fields = [
            field
            for field in _REVIEW_FIELD_LABELS
            if before.get(field) != after.get(field)
        ]
        with st.container(border=True):
            st.markdown(
                f"**审核记录 H{event['id']} · {old_status} → {new_status}**"
            )
            st.caption(format_datetime(event.get("created_at")))
            st.write("审核说明：", event.get("change_reason") or "未记录")
            st.write(
                "变更字段：",
                "、".join(_REVIEW_FIELD_LABELS[field] for field in changed_fields)
                or "无",
            )
            if "title" in changed_fields:
                st.write(
                    "标题变化：",
                    f"{before.get('title') or '—'} → {after.get('title') or '—'}",
                )
            if "summary" in changed_fields:
                st.write(
                    "摘要变化：",
                    f"{before.get('summary') or '—'} → {after.get('summary') or '—'}",
                )
            rechecked_ids = event.get("rechecked_claim_ids") or []
            st.caption(
                "触发重新核验："
                + ("、".join(f"C{item}" for item in rechecked_ids) or "无")
            )


def render_evidence_advice(advice_data: dict, *, persisted: bool = False) -> None:
    """Render model drafting suggestions without changing the evidence card."""

    with st.container(border=True):
        prefix = "已保存的模型草拟" if persisted else "模型草拟"
        st.caption(
            f"{prefix}（{advice_data.get('model') or '未标注'}）· 仅供人工审核"
        )
        st.markdown(f"**建议标题：** {advice_data.get('title') or '—'}")
        st.markdown(f"**建议摘要：** {advice_data.get('summary') or '—'}")
        suggested_type = advice_data.get("evidence_type")
        st.caption(
            "建议类型："
            + EVIDENCE_TYPE_LABELS.get(suggested_type, suggested_type or "—")
        )
        uncertainties = advice_data.get("uncertainties") or []
        if uncertainties:
            st.markdown("**模型标记的不确定性：**")
            for item in uncertainties:
                st.markdown(f"- {item}")


configure_page("材料与证据", "🗂️")

try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"读取项目失败：{exc}")
    st.stop()

render_sidebar_note(project, database=db, project_id=project_id)
render_page_intro(
    "01 · MATERIALS & EVIDENCE",
    "材料与证据",
)
saved_evidence_advice: dict[int, dict] = {}
for run in db.list_project_runs(
    project_id, "llm_evidence_assistance", limit=200
):
    if run.get("status") != "completed":
        continue
    evidence_id = (run.get("input") or {}).get("evidence_id")
    output = run.get("output") or {}
    try:
        evidence_id = int(evidence_id)
    except (TypeError, ValueError):
        continue
    if evidence_id not in saved_evidence_advice and output:
        saved_evidence_advice[evidence_id] = output

tab_import, tab_review, tab_materials = st.tabs(
    ["导入文字材料", "审核证据卡", "材料清单"]
)

with tab_import:
    reset_material_import_state_for_project(project_id)
    st.markdown("### 导入新的文字材料")
    st.caption(
        "可粘贴文字，或上传 UTF-8 编码的 .txt/.md、未加密的 Word .docx 和可提取文本的 .pdf 文件。"
        "请如实填写来源、采集场景和授权状态；未确认授权的材料不会进入核验。"
    )

    upload_lock_key = "single_material_upload_lock"
    uploader_widget_key = "single_material_file"
    locked_upload = st.session_state.get(upload_lock_key)
    uploaded_name = ""
    uploaded_bytes = b""
    if isinstance(locked_upload, dict):
        uploaded_name = str(locked_upload.get("name") or "")
        uploaded_bytes = locked_upload.get("content") or b""
        if not isinstance(uploaded_bytes, bytes):
            uploaded_bytes = b""
        if not uploaded_name or not uploaded_bytes:
            st.session_state.pop(upload_lock_key, None)
    selected_upload = st.file_uploader(
        "上传文字文件（可选）",
        type=["txt", "md", "docx", "pdf"],
        key=uploader_widget_key,
        disabled=bool(uploaded_name),
        help="文字、Word 和 PDF 文件会先在本地读取，不会自动发送到云端。选中一个文件后将锁定，避免误覆盖。",
    )
    if not uploaded_name and selected_upload is not None:
        st.session_state[upload_lock_key] = {
            "name": selected_upload.name,
            "content": selected_upload.getvalue(),
        }
        st.rerun()

    uploaded_text = ""
    uploaded_error = ""
    if uploaded_name:
        try:
            uploaded_text = extract_uploaded_text(uploaded_name, uploaded_bytes)
        except DocumentImportError as exc:
            uploaded_error = str(exc)
            st.error(uploaded_error)

    # Prefer explicit local extraction for uploaded files.  A new file resets
    # only the metadata fields so a previous material's values are not reused.
    uploaded_metadata_suggestion = infer_material_metadata(
        uploaded_text,
        uploaded_name,
    )
    if uploaded_text and not uploaded_error:
        metadata_fingerprint = hashlib.sha256(
            f"{uploaded_name}\n{uploaded_text}".encode("utf-8")
        ).hexdigest()
        if st.session_state.get("material_metadata_fingerprint") != metadata_fingerprint:
            st.session_state["material_metadata_fingerprint"] = metadata_fingerprint
            st.session_state["material_draft_text"] = uploaded_text
            st.session_state["material_filename"] = uploaded_name
            st.session_state["material_source_role"] = (
                uploaded_metadata_suggestion.source_role or "请选择"
            )
            st.session_state["material_context"] = uploaded_metadata_suggestion.context
            st.session_state["material_captured_at"] = (
                uploaded_metadata_suggestion.captured_at
            )

    if uploaded_metadata_suggestion.has_suggestions:
        suggestion_parts = []
        if uploaded_metadata_suggestion.source_role:
            suggestion_parts.append(
                f"来源角色={uploaded_metadata_suggestion.source_role}"
            )
        if uploaded_metadata_suggestion.context:
            suggestion_parts.append(
                f"采集场景={uploaded_metadata_suggestion.context}"
            )
        if uploaded_metadata_suggestion.captured_at:
            suggestion_parts.append(
                f"采集日期={uploaded_metadata_suggestion.captured_at.isoformat()}"
            )
        st.caption(
            "已从材料正文或文件名提取元数据建议，请在提交前核对："
            + "；".join(suggestion_parts)
        )
    metadata_notice = st.session_state.pop("material_metadata_notice", "")
    if metadata_notice:
        st.info(metadata_notice)

    # Keep all fields after submission so validation errors never erase a
    # partially completed material entry. Successful imports also remain
    # visible until the user intentionally replaces them.
    with st.form("material_import_form", clear_on_submit=False):
        is_fictional = False
        text = st.text_area(
            "材料正文",
            height=220,
            key="material_draft_text",
            placeholder=(
                "例如：受访者D表示，第一次进入平台时没有找到"
                "验证码输入位置，经志愿者提示后完成了操作……"
            ),
        )
        metadata_left, metadata_right = st.columns(2)
        with metadata_left:
            filename = st.text_input(
                "材料名称",
                key="material_filename",
            )
            source_role = st.selectbox(
                "来源角色",
                _SINGLE_SOURCE_ROLE_OPTIONS,
                key="material_source_role",
                help="来源角色会影响默认的证据类型，但仍需人工审核。",
            )
            captured_at = st.date_input(
                "采集日期",
                value=st.session_state.get("material_captured_at"),
                key="material_captured_at",
                help="优先从材料正文或文件名识别；识别不到时请手动选择。",
            )
        with metadata_right:
            context = st.text_input(
                "采集场景",
                key="material_context",
                placeholder="说明材料获取的时间、地点或活动场景",
            )
            consent_choice = st.radio(
                "记录与使用授权",
                options=["confirmed", "unknown", "denied"],
                index=0,
                key="material_consent_choice",
                format_func=lambda item: CONSENT_LABELS[item],
                horizontal=True,
                help="未确认或被拒绝授权的材料不会成为可引用证据。",
            )
            custom_terms_text = st.text_input(
                "自定义敏感词（可选）",
                key="material_custom_terms",
                placeholder="用逗号分隔，例如：姓名, 详细地址",
                help="适合标记姓名、精确住址或本项目特有身份信息。",
            )

        material_confirmed = st.checkbox(
            "我确认已如实填写来源和授权状态，并会在引用或导出前复核脱敏文本。",
            key="material_confirmed",
        )
        submitted = st.form_submit_button(
            "本地检查并生成证据卡",
            type="primary",
            width="stretch",
        )
        autofill_submitted = st.form_submit_button(
            "自动识别并填充材料信息",
            help="优先使用本地规则读取正文和文件名；识别不到的字段仍需手动填写。",
        )

    if autofill_submitted:
        suggestion = infer_material_metadata(text, filename)
        if suggestion.source_role:
            st.session_state["material_source_role"] = suggestion.source_role
        if suggestion.context:
            st.session_state["material_context"] = suggestion.context
        if suggestion.captured_at:
            st.session_state["material_captured_at"] = suggestion.captured_at
        if suggestion.has_suggestions:
            st.session_state["material_metadata_notice"] = (
                "已填入可识别的材料信息，请核对后再生成证据卡。"
            )
        else:
            st.session_state["material_metadata_notice"] = (
                "未从材料中找到明确元数据，请手动填写采集场景、来源角色和采集日期。"
            )
        st.rerun()

    if submitted:
        submission_suggestion = infer_material_metadata(text, filename)
        effective_source_role = (
            source_role
            if source_role != "请选择"
            else (submission_suggestion.source_role or "")
        )
        effective_context = context.strip() or submission_suggestion.context
        effective_captured_at = captured_at or submission_suggestion.captured_at
        if uploaded_error:
            st.error("请先解决文件编码问题。")
        elif not text.strip():
            st.error("材料正文不能为空。")
        elif not filename.strip():
            st.error("请填写材料名称，便于后续追溯。")
        elif not material_confirmed:
            st.warning(
                "请先勾选“我确认已如实填写来源和授权状态”，"
                "确认后才能生成证据卡。"
            )
        elif not effective_source_role:
            st.error("未能从材料识别来源角色，请手动选择来源角色。")
        elif not effective_context:
            st.error("未能从材料识别采集场景，请手动填写采集场景。")
        elif effective_captured_at is None:
            st.error("未能从材料识别采集日期，请手动选择采集日期。")
        else:
            custom_terms = [
                item.strip()
                for item in custom_terms_text.replace("，", ",").split(",")
                if item.strip()
            ]
            try:
                import_progress = st.empty()

                def update_import_progress(message: str) -> None:
                    import_progress.info(message)

                import_kwargs = {
                    "original_filename": filename.strip(),
                    "source_role": effective_source_role,
                    "context": effective_context,
                    "captured_at": effective_captured_at.isoformat(),
                    "consent_status": ConsentStatus(consent_choice),
                    "custom_sensitive_terms": custom_terms,
                    "is_fictional": is_fictional,
                }
                try:
                    with st.spinner("正在检查隐私并生成证据卡……"):
                        try:
                            result = import_text_material(
                                db,
                                project_id,
                                text,
                                progress_callback=update_import_progress,
                                **import_kwargs,
                            )
                        except TypeError as exc:
                            # Streamlit may reload this page before a
                            # previously imported workflow module is reloaded.
                            if "progress_callback" not in str(exc):
                                raise
                            result = import_text_material(
                                db, project_id, text, **import_kwargs
                            )
                finally:
                    import_progress.empty()
            except Exception as exc:
                st.error(f"材料导入失败：{exc}")
            else:
                st.session_state["last_import_result"] = result
                if consent_choice != "confirmed":
                    st.warning(
                        f"材料 M{result.material_id} 已保存，但当前授权状态为“"
                        f"{CONSENT_LABELS[consent_choice]}”，所以没有生成待审核证据卡。"
                        "若已取得授权，请将状态改为“已确认授权”后重新提交。"
                    )
                elif not result.evidence_card_ids:
                    st.error(
                        "材料已保存，但没有生成证据卡。请不要继续引用这份材料，"
                        "并检查脱敏文本或重新导入。"
                    )
                else:
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
                    st.info(
                        "下一步：确认授权后，将授权状态改为“已确认授权”并重新提交；"
                        "未确认授权的材料不会进入结论核验。"
                    )
                else:
                    st.info(
                        "下一步：打开上方“审核证据卡”标签，确认标题、摘要、类型和审核状态。"
                    )

    st.divider()
    with st.expander("批量导入文字文件", expanded=False):
        st.caption(
            "一次选择多个 UTF-8 编码的 .txt/.md、未加密的 Word .docx 或可提取文本的 .pdf 文件。"
            "批量导入会对所有文件使用相同的来源角色、"
            "采集场景、授权状态和自定义敏感词；每个文件仍会单独生成材料和证据卡。"
        )
        with st.form("batch_material_import_form", clear_on_submit=False):
            batch_files = st.file_uploader(
                "选择多个文字文件",
                type=["txt", "md", "docx", "pdf"],
                accept_multiple_files=True,
                key="batch_material_files",
                help="文件内容只会在本地读取和处理，不会自动发送到云端。",
            )
            batch_left, batch_right = st.columns(2)
            with batch_left:
                batch_source_role = st.selectbox(
                    "批量来源角色",
                    _SOURCE_ROLE_OPTIONS,
                    key="batch_source_role",
                    help="所选角色会应用于本次批量导入的全部文件。",
                )
                batch_captured_at = st.date_input(
                    "批量采集日期",
                    value=date.today(),
                    key="batch_captured_at",
                )
            with batch_right:
                batch_context = st.text_input(
                    "批量采集场景",
                    value="",
                    key="batch_context",
                    placeholder="说明这批材料获取的时间、地点或活动场景",
                )
                batch_consent_choice = st.radio(
                    "批量记录与使用授权",
                    options=["confirmed", "unknown", "denied"],
                    index=0,
                    key="batch_consent_choice",
                    format_func=lambda item: CONSENT_LABELS[item],
                    horizontal=True,
                    help="未确认或被拒绝授权的材料不会成为可引用证据。",
                )
                batch_custom_terms_text = st.text_input(
                    "批量自定义敏感词（可选）",
                    key="batch_custom_terms",
                    placeholder="用逗号分隔，例如：姓名, 详细地址",
                )
            batch_confirmed = st.checkbox(
                "我确认已如实填写这批材料的来源和授权状态，并会在引用或导出前复核脱敏文本。",
                value=False,
                key="batch_material_confirmed",
            )
            batch_submitted = st.form_submit_button(
                "批量本地检查并生成证据卡",
                type="primary",
                width="stretch",
            )

        if batch_submitted:
            if not batch_files:
                st.error("请先选择至少一个文字文件。")
            elif not batch_confirmed:
                st.warning(
                    "请先勾选批量材料确认框，确认来源、授权状态和脱敏复核责任。"
                )
            elif not batch_context.strip():
                st.error("请填写批量采集场景。")
            else:
                custom_terms = [
                    item.strip()
                    for item in batch_custom_terms_text.replace("，", ",").split(",")
                    if item.strip()
                ]
                decoded_files: list[tuple[str, str]] = []
                decode_errors: list[str] = []
                for batch_file in batch_files:
                    try:
                        content = extract_uploaded_text(
                            batch_file.name, batch_file.getvalue()
                        )
                    except DocumentImportError as exc:
                        decode_errors.append(f"{batch_file.name}（{exc}）")
                        continue
                    if not content.strip():
                        decode_errors.append(f"{batch_file.name}（正文为空）")
                        continue
                    decoded_files.append((batch_file.name, content))

                if decode_errors:
                    st.error(
                        "以下文件未通过本地检查，本次批量导入未写入任何文件："
                        + "、".join(decode_errors)
                    )
                else:
                    results = []
                    failures: list[str] = []
                    with st.spinner(
                        f"正在本地检查并处理 {len(decoded_files)} 个文件……"
                    ):
                        for filename, content in decoded_files:
                            try:
                                result = import_text_material(
                                    db,
                                    project_id,
                                    content,
                                    original_filename=filename,
                                    source_role=batch_source_role,
                                    context=batch_context.strip(),
                                    captured_at=batch_captured_at.isoformat(),
                                    consent_status=ConsentStatus(batch_consent_choice),
                                    custom_sensitive_terms=custom_terms,
                                    is_fictional=False,
                                )
                            except Exception as exc:
                                failures.append(f"{filename}：{exc}")
                            else:
                                results.append(result)
                    if results:
                        st.success(
                            f"已处理 {len(results)} 个文件，共生成 "
                            f"{sum(len(item.evidence_card_ids) for item in results)} 张待审核证据卡。"
                        )
                        with st.expander("查看批量导入结果", expanded=True):
                            for result in results:
                                st.write(
                                    f"M{result.material_id}：已保存，生成 "
                                    f"{len(result.evidence_card_ids)} 张证据卡。"
                                )
                                for warning in result.warnings:
                                    st.caption(f"M{result.material_id}：{warning}")
                                if (
                                    batch_consent_choice == "confirmed"
                                    and not result.evidence_card_ids
                                ):
                                    st.error(
                                        f"M{result.material_id} 已确认授权，但没有生成证据卡，"
                                        "请检查该文件是否包含可提取文字。"
                                    )
                    if failures:
                        st.error("以下文件未能导入：" + "；".join(failures))

with tab_review:
    st.markdown("### 人工审核证据卡")
    try:
        all_cards = db.list_evidence_cards(project_id)
    except Exception:
        all_cards = []
    if all_cards:
        status_columns = st.columns(3)
        status_columns[0].metric(
            "待审核",
            sum(card.get("review_status") == "draft" for card in all_cards),
        )
        status_columns[1].metric(
            "已批准",
            sum(card.get("review_status") == "approved" for card in all_cards),
        )
        status_columns[2].metric(
            "授权待确认",
            sum(card.get("consent_status") != "confirmed" for card in all_cards),
        )
        st.caption("只有“已确认授权 + 已批准”的证据卡会进入结论核验。")

    authorized_draft_cards = [
        card
        for card in all_cards
        if card.get("review_status") == "draft"
        and card.get("consent_status") == "confirmed"
    ]
    unauthorized_draft_count = sum(
        card.get("review_status") == "draft"
        and card.get("consent_status") != "confirmed"
        for card in all_cards
    )
    with st.expander("批量审核工具", expanded=False):
        st.caption(
            f"当前有 {len(authorized_draft_cards)} 张已确认授权的待审核卡片。"
            "未确认授权的卡片不会进入可引用证据集，也不会发送给模型。"
        )
        manual_confirmation = st.checkbox(
            "我确认这些已授权卡片的来源和脱敏结果可以进入项目证据集。",
            key=f"bulk_review_confirm_{project_id}",
        )
        manual_bulk = st.button(
            "一键批准全部已授权待审核卡片",
            type="primary",
            disabled=not manual_confirmation or not authorized_draft_cards,
            key=f"bulk_approve_evidence_{project_id}",
        )
        if manual_bulk:
            failures: list[str] = []
            updated_count = 0
            rechecked_claim_ids: set[int] = set()
            try:
                results = review_evidence_cards(
                    db,
                    [
                        {
                            "evidence_card_id": int(card["id"]),
                            "title": str(card.get("title") or "").strip(),
                            "summary": str(card.get("summary") or "").strip(),
                            "evidence_type": card.get(
                                "evidence_type", "team_analysis"
                            ),
                            "review_status": "approved",
                            "change_reason": "",
                        }
                        for card in authorized_draft_cards
                    ],
                )
                updated_count = sum(
                    result.review_event_id is not None for result in results
                )
                for result in results:
                    rechecked_claim_ids.update(result.rechecked_claim_ids)
            except Exception as exc:
                failures.append(f"批量审核失败：{exc}")
            if updated_count:
                st.success(
                    f"已批准 {updated_count} 张证据卡。"
                    f"重新核验结论 {len(rechecked_claim_ids)} 条。"
                )
            if unauthorized_draft_count:
                st.warning(
                    f"另有 {unauthorized_draft_count} 张材料未确认授权，已跳过。"
                )
            if failures:
                st.error("以下卡片未能完成批量审核：" + "；".join(failures))
            st.rerun()

        if llm_settings.configured:
            st.divider()
            llm_review_notice_key = f"llm_review_notice_{project_id}"
            llm_review_notice = st.session_state.pop(llm_review_notice_key, None)
            if llm_review_notice:
                notice_level = llm_review_notice.get("level", "info")
                notice_message = llm_review_notice.get("message", "")
                getattr(st, notice_level, st.info)(notice_message)
            st.caption(
                "模型只会读取再次脱敏后的已授权证据卡，并返回批准或拒绝建议。"
                "勾选确认后，模型结果会直接写入审核状态。"
            )
            trust_model = st.checkbox(
                "我确认信任本次大模型审核结果，并允许其自动写入审核状态。",
                key=f"trust_llm_review_{project_id}",
            )
            model_bulk = st.button(
                "让大模型审核全部待审核卡片",
                type="primary",
                disabled=not trust_model or not authorized_draft_cards,
                key=f"llm_review_all_evidence_{project_id}",
            )
            if model_bulk:
                model_failures: list[str] = []
                approved_count = 0
                rejected_count = 0
                rechecked_claim_ids: set[int] = set()
                model_updates: list[dict] = []
                with st.spinner(
                    f"正在让模型审核全部 {len(authorized_draft_cards)} 张证据卡……"
                ):
                    remaining_cards = list(authorized_draft_cards)
                    while remaining_cards:
                        batch = remaining_cards
                        run_input = {
                            "evidence_ids": [int(card["id"]) for card in batch],
                            "model": llm_settings.model,
                            "review_source": "bulk_all",
                        }
                        try:
                            advice = request_evidence_review_batch(
                                batch,
                                config=llm_settings,
                            )
                            advice_data = advice.as_dict()
                            db.create_agent_run(
                                project_id,
                                "llm_evidence_review",
                                input_data=run_input,
                                output_data=advice_data,
                            )
                            card_by_id = {int(card["id"]): card for card in batch}
                            for evidence_id, item in advice.reviews:
                                card = card_by_id.get(int(evidence_id))
                                if card is None:
                                    raise ValueError(
                                        f"模型返回了当前批次之外的证据 E{evidence_id}。"
                                )
                                model_updates.append(
                                    {
                                        "evidence_card_id": int(evidence_id),
                                        "title": str(card.get("title") or "").strip(),
                                        "summary": str(card.get("summary") or "").strip(),
                                        "evidence_type": card.get(
                                            "evidence_type", "team_analysis"
                                        ),
                                        "review_status": item.review_status,
                                        "change_reason": item.review_reason,
                                    }
                                )
                            reviewed_ids = {
                                int(evidence_id)
                                for evidence_id, _ in advice.reviews
                            }
                            if not reviewed_ids:
                                raise ValueError("模型本次未返回任何证据卡审核结果。")
                            remaining_cards = [
                                card
                                for card in remaining_cards
                                if int(card["id"]) not in reviewed_ids
                            ]
                        except Exception as exc:
                            model_failures.append(
                                f"剩余 {len(batch)} 张证据卡：{exc}"
                            )
                            try:
                                db.create_agent_run(
                                    project_id,
                                    "llm_evidence_review",
                                    status="failed",
                                    input_data=run_input,
                                    error_message=str(exc)[:500],
                                )
                            except Exception:
                                pass
                            break
                if model_updates:
                    try:
                        results = review_evidence_cards(db, model_updates)
                    except Exception as exc:
                        model_failures.append(f"写入模型审核结果失败：{exc}")
                    else:
                        for update in model_updates:
                            if update["review_status"] == "approved":
                                approved_count += 1
                            else:
                                rejected_count += 1
                        for result in results:
                            rechecked_claim_ids.update(result.rechecked_claim_ids)
                completion_message = (
                    f"模型审核完成：批准 {approved_count} 张，"
                    f"拒绝 {rejected_count} 张，"
                    f"重新核验结论 {len(rechecked_claim_ids)} 条。"
                )
                if model_failures:
                    st.session_state[llm_review_notice_key] = {
                        "level": "error",
                        "message": (
                            completion_message
                            + " 以下卡片未完成模型审核："
                            + "；".join(model_failures)
                        ),
                    }
                else:
                    st.session_state[llm_review_notice_key] = {
                        "level": "success",
                        "message": completion_message,
                    }
                st.rerun()
        else:
            st.info(
                "尚未配置可用的大模型。配置 DeepSeek 后，这里会出现批量模型审核入口。"
            )
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
        empty_state(
            "当前筛选条件下没有证据卡。请先在“导入文字材料”标签提交材料，"
            "或调整上方筛选条件。"
        )
    for card in cards:
        card_id = int(card["id"])
        title = card.get("title") or f"证据 E{card_id}"
        with st.expander(
            f"E{card_id} · {title} · "
            f"{REVIEW_STATUS_LABELS.get(card.get('review_status'), '未知')}",
            expanded=False,
        ):
            st.markdown(evidence_card_html(card), unsafe_allow_html=True)
            if card.get("consent_status") != "confirmed":
                st.warning("来源材料尚未确认授权。即使批准，仍不会进入可引用证据集。")

            review_events = db.list_evidence_review_events(
                project_id, evidence_card_id=card_id, limit=100
            )
            rejection_event = next(
                (
                    event
                    for event in review_events
                    if (event.get("after") or {}).get("review_status") == "rejected"
                ),
                None,
            )
            if card.get("review_status") == "rejected":
                rejection_reason = str(
                    (rejection_event or {}).get("change_reason")
                    or "未记录具体拒绝理由，请人工复核。"
                )
                st.error(f"拒绝理由：{rejection_reason}")
                already_regenerated = any(
                    str(event.get("change_reason") or "").startswith(
                        "已根据拒绝理由生成替代卡"
                    )
                    for event in review_events
                )
                if llm_settings.configured and card.get("consent_status") == "confirmed":
                    if already_regenerated:
                        st.caption("已根据该拒绝理由生成替代卡，请审核新卡后再决定是否引用。")
                    elif st.button(
                        "根据拒绝理由重新生成待审核卡",
                        key=f"regenerate_rejected_evidence_{project_id}_{card_id}",
                    ):
                        try:
                            with st.spinner("正在根据拒绝理由重新生成证据卡……"):
                                regenerated = regenerate_rejected_evidence_card(
                                    db, card_id
                                )
                            db.create_agent_run(
                                project_id,
                                "llm_evidence_card_regeneration",
                                input_data={
                                    "source_evidence_id": card_id,
                                    "rejection_reason": regenerated.rejection_reason,
                                    "model": llm_settings.model,
                                },
                                output_data={
                                    "replacement_evidence_id": regenerated.replacement_evidence_card_id
                                },
                            )
                            st.success(
                                f"已生成替代卡 E{regenerated.replacement_evidence_card_id}，"
                                "它仍需重新审核。"
                            )
                            st.rerun()
                        except LLMError as exc:
                            st.error(f"重新生成失败：{exc}")
                        except Exception as exc:
                            st.error(f"无法重新生成替代卡：{exc}")

            evidence_advice_key = f"llm_evidence_advice_{project_id}_{card_id}"
            advice_data = st.session_state.get(evidence_advice_key)
            advice_persisted = False
            if advice_data is None:
                advice_data = saved_evidence_advice.get(card_id)
                advice_persisted = advice_data is not None
            if llm_settings.configured and card.get("consent_status") == "confirmed":
                st.caption(
                    "可请求模型草拟标题、摘要和证据类型；结果不会自动批准或保存。"
                )
                request_advice = st.button(
                    "请求大模型草拟证据卡",
                    key=f"request_evidence_llm_{project_id}_{card_id}",
                )
                if request_advice:
                    try:
                        with st.spinner("正在生成证据卡草拟建议……"):
                            advice = request_evidence_assistance(
                                card,
                                config=llm_settings,
                            )
                        advice_data = advice.as_dict()
                        st.session_state[evidence_advice_key] = advice_data
                        db.create_agent_run(
                            project_id,
                            "llm_evidence_assistance",
                            input_data={
                                "evidence_id": card_id,
                                "model": llm_settings.model,
                            },
                            output_data=advice_data,
                        )
                    except LLMError as exc:
                        st.error(f"证据卡辅助失败：{exc}")
                        db.create_agent_run(
                            project_id,
                            "llm_evidence_assistance",
                            status="failed",
                            input_data={
                                "evidence_id": card_id,
                                "model": llm_settings.model,
                            },
                            error_message=str(exc)[:500],
                        )
                if request_advice:
                    advice_data = st.session_state.get(evidence_advice_key)
                    advice_persisted = False

            if advice_data:
                render_evidence_advice(advice_data, persisted=advice_persisted)

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
                current_decision = card.get("review_status", "draft")
                if current_decision == "draft":
                    current_decision = "approved"
                decision = st.radio(
                    "审核结论",
                    ["draft", "approved", "rejected"],
                    index=["draft", "approved", "rejected"].index(
                        current_decision
                    ),
                    format_func=lambda item: REVIEW_STATUS_LABELS[item],
                    horizontal=True,
                    key=f"decision_{card_id}",
                )
                change_reason = st.text_area(
                    "本次审核说明（可选）",
                    placeholder="例如：已核对来源与授权，批准进入可引用证据集。",
                    max_chars=500,
                    key=f"review_reason_{card_id}",
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
                            change_reason=change_reason,
                        )
                    except Exception as exc:
                        st.error(f"保存审核结果失败：{exc}")
                    else:
                        refreshed_count = len(review_result.rechecked_claim_ids)
                        if review_result.review_event_id is None:
                            st.info("没有检测到实际变更，因此未新增审核记录。")
                        elif refreshed_count:
                            st.success(
                                f"证据 E{card_id} 已更新，并已重新核验当前项目的 "
                                f"{refreshed_count} 条结论。"
                            )
                        else:
                            st.success(f"证据 E{card_id} 已更新。")
                        if review_result.review_event_id is not None:
                            st.session_state.pop(evidence_advice_key, None)
                            st.rerun()
            try:
                render_review_history(db, project_id, card_id)
            except Exception as exc:
                st.error(f"读取证据审核历史失败：{exc}")

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
        with st.expander(
            f"M{material['id']} · "
            f"{material.get('original_filename') or '未命名材料'}"
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
