"""Claim checking and evidence-gap workflow page."""

from __future__ import annotations

import streamlit as st

from qingji.config import llm_settings
from qingji.demo import add_demo_supplement
from qingji.llm import (
    LLMConfigurationError,
    LLMError,
    request_claim_assistance,
    request_claim_candidates,
)
from qingji.ui import (
    TASK_STATUS_LABELS,
    VERDICT_ICONS,
    VERDICT_LABELS,
    configure_page,
    empty_state,
    evidence_card_html,
    format_datetime,
    get_demo_context,
    is_demo_project,
    render_page_intro,
    render_sidebar_note,
    verdict_box,
)
from qingji.workflow import (
    check_and_store_claim,
    recheck_claim,
    recheck_project_claims,
)


EXAMPLE_CLAIM = "当地居民普遍认为线上办事平台使用困难。"
RULE_FLAG_LABELS = {
    "group_generalization": "群体性概括",
    "absolute_quantifier": "绝对量词",
    "strong_intensity": "强程度表达",
    "causal_language": "因果表达",
    "precise_quantity": "精确数量",
}
RETRIEVAL_DECISION_LABELS = {
    "support": "用于支持",
    "contradict": "用于冲突",
    "context": "作为背景",
    "below_threshold": "低于相关阈值",
    "outside_top_k": "超出前 8 名",
    "not_cited": "相关但未引用",
}


def render_claim_advice(advice_data: dict, *, persisted: bool = False) -> None:
    """Render a stored model suggestion without treating it as a verdict."""

    with st.container(border=True):
        prefix = "已保存的模型建议" if persisted else "模型建议"
        st.caption(
            f"{prefix}（{advice_data.get('model') or '未标注'}）· 仅供人工复核"
        )
        st.markdown(f"**辅助摘要：** {advice_data.get('summary') or '—'}")
        st.markdown(
            f"**辅助改写：** {advice_data.get('safe_rewrite') or '—'}"
        )
        cited_ids = advice_data.get("cited_evidence_ids") or []
        st.caption(
            "引用证据："
            + ("、".join(f"E{item}" for item in cited_ids) if cited_ids else "无")
        )
        suggestions = advice_data.get("follow_up_suggestions") or []
        if suggestions:
            st.markdown("**辅助补证建议：**")
            for item in suggestions:
                st.markdown(f"- {item}")
        uncertainties = advice_data.get("uncertainties") or []
        if uncertainties:
            st.markdown("**模型主动标记的不确定性：**")
            for item in uncertainties:
                st.markdown(f"- {item}")


configure_page("结论核验", "🔎")

try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"读取项目失败：{exc}")
    st.stop()

render_sidebar_note(project, database=db, project_id=project_id)
render_page_intro(
    "02 · CLAIM CHECK",
    "结论核验",
)
demo_mode = is_demo_project(project)
history_verdict_key = f"claim_history_verdict_{project_id}"
history_query_key = f"claim_history_query_{project_id}"
history_selection_key = f"claim_history_selection_{project_id}"
if history_verdict_key not in st.session_state:
    st.session_state[history_verdict_key] = "all"

st.markdown("### 核验一句话")
with st.form("claim_check_form", clear_on_submit=False):
    claim_text = st.text_area(
        "待核验结论",
        value=st.session_state.get(
            "claim_draft", EXAMPLE_CLAIM if demo_mode else ""
        ),
        height=110,
        help="建议一次只检查一个清晰、可验证的事实性表述。",
    )
    st.caption(
        "试着保留“普遍”二字：青迹会检查现有样本能否支撑这一群体性表达。"
        if demo_mode
        else "一次只检查一个明确表述；系统不会引用未授权或未批准的材料。"
    )
    submitted = st.form_submit_button(
        "开始核验", type="primary", width="stretch"
    )

if submitted:
    if not claim_text.strip():
        st.error("待核验结论不能为空。")
    elif len(claim_text.strip()) > 500:
        st.error("请将结论缩短到 500 字以内，并尽量一次只核验一个判断。")
    else:
        try:
            with st.spinner("正在检索已授权证据并判断完整语义关系……"):
                stored = check_and_store_claim(
                    db, project_id, claim_text.strip()
                )
        except Exception as exc:
            st.error(f"结论核验失败：{exc}")
        else:
            st.session_state["active_claim_id"] = int(stored.claim_id)
            st.session_state["claim_draft"] = claim_text.strip()
            st.session_state[history_verdict_key] = "all"
            st.session_state[history_query_key] = ""
            st.session_state[history_selection_key] = int(stored.claim_id)
            st.success("核验完成。请重点查看理由、证据范围和稳妥改写。")


st.markdown("### 从材料提取待核验结论")
draft_candidates = db.list_claim_candidates(project_id, status="draft")
candidate_submitted = False
eligible_evidence_count = sum(
    card.get("review_status") != "rejected"
    and card.get("consent_status") == "confirmed"
    for card in db.list_evidence_cards(project_id)
)
if not draft_candidates:
    st.info(
        "当前没有待核验结论草稿。导入已确认授权的材料后，模型会自动提取符合范围的主观发现。"
    )
else:
    st.caption(
        "这些候选在材料导入时从脱敏、已确认授权的内容中生成；"
        "候选本身不是结论；核验会使用已确认授权且未被人工排除的证据卡。"
    )
    if not eligible_evidence_count:
        st.warning("请先导入已确认授权且未被人工排除的证据卡，再核验候选结论。")
    candidate_by_id = {int(item["id"]): item for item in draft_candidates}
    with st.form(f"claim_candidate_selection_{project_id}", clear_on_submit=False):
        selected_candidate_ids: list[int] = []
        for candidate_id, candidate in candidate_by_id.items():
            claim_candidate = str(candidate.get("claim_text") or "").strip()
            checked = st.checkbox(
                f"CC{candidate_id} · {claim_candidate}",
                key=f"claim_candidate_{project_id}_{candidate_id}",
            )
            segment_ids = candidate.get("source_segment_ids") or []
            st.caption(
                f"来源材料：M{candidate.get('material_id', '—')} · "
                f"{candidate.get('original_filename') or '未命名材料'} · "
                "来源片段："
                + ("、".join(f"S{item}" for item in segment_ids) if segment_ids else "—")
            )
            uncertainties = candidate.get("uncertainties") or []
            if uncertainties:
                st.caption("模型不确定性：" + "；".join(uncertainties))
            if checked:
                selected_candidate_ids.append(candidate_id)
        selected_submitted = st.form_submit_button(
            "核验已选结论",
            type="primary",
            disabled=not eligible_evidence_count,
        )
        all_submitted = st.form_submit_button(
            f"一键核验全部待选结论（{len(draft_candidates)} 条）",
            disabled=not eligible_evidence_count,
        )
    candidate_submitted = selected_submitted or all_submitted
    candidate_ids_to_check = (
        list(candidate_by_id) if all_submitted else selected_candidate_ids
    )
    if candidate_submitted:
        if not candidate_ids_to_check:
            st.warning("请至少勾选一条候选结论。")
        else:
            try:
                with st.spinner("正在逐条核验候选结论并判断完整语义关系……"):
                    checked_results = []
                    for candidate_id in candidate_ids_to_check:
                        candidate = candidate_by_id[candidate_id]
                        stored = check_and_store_claim(
                            db, project_id, str(candidate["claim_text"])
                        )
                        db.mark_claim_candidate_checked(candidate_id, stored.claim_id)
                        checked_results.append(stored)
            except Exception as exc:
                st.error(f"批量核验候选结论失败：{exc}")
            else:
                active_claim_id = int(checked_results[-1].claim_id)
                st.session_state["active_claim_id"] = active_claim_id
                st.session_state[history_selection_key] = active_claim_id
                st.session_state[history_verdict_key] = "all"
                st.session_state[history_query_key] = ""
                st.success(f"已核验 {len(checked_results)} 条候选结论。")

claims = db.list_claims(project_id)
if claims:
    if st.button(
        f"一键重新核验全部结论（{len(claims)} 条）",
        key=f"recheck_all_claims_{project_id}",
        width="stretch",
    ):
        try:
            with st.spinner("正在使用最新证据重新核验全部结论……"):
                refreshed_claims = recheck_project_claims(db, project_id)
        except Exception as exc:
            st.error(f"批量重新核验失败：{exc}")
        else:
            claims = db.list_claims(project_id)
            if refreshed_claims:
                st.session_state["active_claim_id"] = int(refreshed_claims[-1].claim_id)
            st.success(f"已完成 {len(refreshed_claims)} 条结论的重新核验。")
active_claim_id = st.session_state.get("active_claim_id")
project_claim_ids = {int(item["id"]) for item in claims}
try:
    active_claim_id = (
        int(active_claim_id) if active_claim_id is not None else None
    )
except (TypeError, ValueError):
    active_claim_id = None
if active_claim_id not in project_claim_ids:
    active_claim_id = None
    st.session_state.pop("active_claim_id", None)
if active_claim_id is None and claims:
    active_claim_id = int(claims[0]["id"])

if claims:
    st.markdown("### 历史核验")
    history_filter_col, history_search_col = st.columns([2, 3])
    with history_filter_col:
        history_verdict = st.segmented_control(
            "核验状态",
            options=[
                "all",
                "supported",
                "partially_supported",
                "unsupported",
                "contradicted",
            ],
            format_func=lambda item: (
                "全部" if item == "all" else VERDICT_LABELS[item]
            ),
            key=history_verdict_key,
        )
    with history_search_col:
        history_query = st.text_input(
            "搜索历史结论",
            placeholder="输入结论中的关键词",
            key=history_query_key,
        )

    history_claims = db.list_claims(
        project_id,
        verdict=None if history_verdict == "all" else history_verdict,
        query=history_query,
    )
    if not history_claims:
        empty_state("当前筛选条件下没有历史结论。")
        st.stop()
    else:
        history_ids = [int(item["id"]) for item in history_claims]
        preferred_claim_id = (
            int(active_claim_id)
            if active_claim_id is not None
            and int(active_claim_id) in history_ids
            else history_ids[0]
        )
        if (
            st.session_state.get(history_selection_key) not in history_ids
            or submitted
            or candidate_submitted
        ):
            st.session_state[history_selection_key] = preferred_claim_id
        selected_claim_id = st.selectbox(
            "选择一条历史结论",
            options=history_ids,
            format_func=lambda item: next(
                (
                    f"C{claim['id']} · "
                    f"{VERDICT_LABELS.get(claim.get('verdict'), '未知')} · "
                    f"{claim.get('claim_text', '')[:70]}"
                    for claim in history_claims
                    if int(claim["id"]) == int(item)
                ),
                f"C{item}",
            ),
            key=history_selection_key,
        )
        active_claim_id = int(selected_claim_id)
        st.session_state["active_claim_id"] = active_claim_id
        selected_summary = next(
            item
            for item in history_claims
            if int(item["id"]) == active_claim_id
        )
        st.caption(
            f"当前显示 C{active_claim_id} · "
            f"核验时间 {format_datetime(selected_summary.get('checked_at'))} · "
            f"筛选结果 {len(history_claims)} 条"
        )

if active_claim_id is None:
    empty_state("还没有核验记录。输入上方示例结论即可开始。")
    st.stop()

claim = db.get_claim(int(active_claim_id))
if claim is None:
    st.warning("找不到当前核验记录，请重新核验。")
    st.stop()

st.markdown("### 四级核验结果")
legend = st.columns(4)
for column, verdict in zip(
    legend,
    ["supported", "partially_supported", "unsupported", "contradicted"],
):
    column.markdown(
        f"{VERDICT_ICONS[verdict]} **{VERDICT_LABELS[verdict]}**"
    )

verdict_box(claim.get("verdict"), claim.get("reason", ""))
st.markdown(f"**原始表述：** {claim.get('claim_text', '—')}")

rule_flags = claim.get("rule_flags") or []
if rule_flags:
    st.markdown(
        "**规则提醒：** "
        + "　".join(
            f"`{RULE_FLAG_LABELS.get(flag, flag)}`" for flag in rule_flags
        )
    )

st.markdown("#### 更稳妥的改写")
if claim.get("safe_rewrite"):
    st.success(claim["safe_rewrite"])
else:
    st.info("当前没有可用改写；请先补充直接相关材料。")

links = claim.get("evidence_links") or []
relation_labels = {
    "support": "支持证据",
    "contradict": "冲突证据",
    "context": "背景证据",
}
st.markdown("### 相关证据")
linked_cards = []
if not links:
    empty_state("当前未找到可引用证据。未授权或未审核的材料不会出现在这里。")
    st.page_link(
        "pages/1_材料与证据.py",
        label="去材料与证据审核证据卡",
        icon="🗂️",
    )
else:
    for relation in ("support", "contradict", "context"):
        relation_links = [
            link for link in links if link.get("relation") == relation
        ]
        if not relation_links:
            continue
        st.markdown(f"#### {relation_labels[relation]}")
        for link in relation_links:
            card = db.get_evidence_card(int(link["evidence_card_id"]))
            if card:
                linked_cards.append(card)
                st.markdown(evidence_card_html(card), unsafe_allow_html=True)
            if link.get("rationale"):
                st.caption(f"关联说明：{link['rationale']}")

st.markdown("### 证据语义判断")
latest_relation_run = db.get_latest_claim_run(
    int(active_claim_id), "llm_claim_evidence_review"
)
if latest_relation_run and latest_relation_run.get("status") == "completed":
    relation_output = latest_relation_run.get("output") or {}
    relation_uncertainties = relation_output.get("uncertainties") or []
    st.caption(
        f"最近一次语义判断：{relation_output.get('model') or '未标注'}；"
        "证据关系按完整语义判断，四级结论仍由本地规则计算。"
    )
    if relation_uncertainties:
        st.warning("模型标记的不确定性：" + "；".join(relation_uncertainties))
if not llm_settings.configured:
    st.info(
        "当前未启用语义判断，因此证据关系暂由本地规则处理。配置模型后，"
        "开始核验和重新核验会自动判断完整语义，减少关键词误关联。"
    )
else:
    st.caption(
        "系统只会读取已批准、已确认授权的脱敏证据卡。开始核验和重新核验时会自动写入"
        "语义关系；授权、人工审核、范围提醒和四级结论仍由本地规则控制。"
    )

st.markdown("### 可选的大模型辅助")
advice_key = (
    f"llm_advice_{project_id}_{active_claim_id}_"
    f"{claim.get('checked_at') or '未核验'}"
)
advice_data = st.session_state.get(advice_key)
advice_persisted = False
if advice_data is None:
    saved_run = db.get_latest_claim_run(
        int(active_claim_id), "llm_claim_assistance"
    )
    saved_input = (saved_run or {}).get("input") or {}
    if (
        saved_run
        and saved_run.get("status") == "completed"
        and saved_input.get("claim_checked_at") == claim.get("checked_at")
    ):
        advice_data = saved_run.get("output") or None
        advice_persisted = advice_data is not None

if not llm_settings.configured:
    st.info(
        "当前未启用云端模型。青迹仍会使用本地规则完成核验；如需开启，"
        "请先配置 QINGJI_LLM_ENABLED、QINGJI_LLM_API_KEY 和 QINGJI_LLM_MODEL。"
    )
else:
    st.caption(
        "只有点击按钮后才会发送本条结论和已批准、已授权的脱敏证据；"
        "模型建议不改变四级核验结果。"
    )
    request_advice = st.button(
        "请求大模型辅助（仅使用脱敏证据）",
        key=f"request_llm_{project_id}_{active_claim_id}",
    )
    evidence_ids = [
        int(card["id"]) for card in linked_cards if card.get("id") is not None
    ]
    if request_advice:
        try:
            with st.spinner("正在请求大模型辅助建议……"):
                advice = request_claim_assistance(
                    claim.get("claim_text", ""),
                    claim,
                    linked_cards,
                    config=llm_settings,
                )
            advice_data = advice.as_dict()
            st.session_state[advice_key] = advice_data
            db.create_agent_run(
                project_id,
                "llm_claim_assistance",
                claim_id=int(active_claim_id),
                input_data={
                    "claim_text": claim.get("claim_text", ""),
                    "claim_checked_at": claim.get("checked_at"),
                    "evidence_ids": evidence_ids,
                    "model": llm_settings.model,
                },
                output_data=advice_data,
            )
        except LLMConfigurationError as exc:
            st.warning(str(exc))
        except LLMError as exc:
            st.error(f"大模型辅助失败：{exc}")
            db.create_agent_run(
                project_id,
                "llm_claim_assistance",
                claim_id=int(active_claim_id),
                status="failed",
                input_data={
                    "claim_text": claim.get("claim_text", ""),
                    "claim_checked_at": claim.get("checked_at"),
                    "evidence_ids": evidence_ids,
                    "model": llm_settings.model,
                },
                error_message=str(exc)[:500],
            )
        except Exception as exc:
            st.error(f"大模型辅助失败：{exc}")


if advice_data:
    render_claim_advice(advice_data, persisted=advice_persisted)

st.markdown("### 检索诊断")
retrieval_run = db.get_latest_claim_run(
    int(active_claim_id), "claim_retrieval"
)
if retrieval_run is None:
    st.info("这条结论还没有检索诊断记录。重新核验后即可查看候选排序和排除原因。")
else:
    diagnostic = retrieval_run.get("output") or {}
    diagnostic_columns = st.columns(4)
    diagnostic_columns[0].metric(
        "可检索证据", diagnostic.get("eligible_count", 0)
    )
    diagnostic_columns[1].metric(
        "达到相关阈值", diagnostic.get("relevant_count", 0)
    )
    diagnostic_columns[2].metric(
        "最终引用", diagnostic.get("cited_count", 0)
    )
    diagnostic_columns[3].metric(
        "被规则排除",
        diagnostic.get("excluded_evidence_count", 0)
        + diagnostic.get("excluded_material_count", 0),
    )
    keywords = diagnostic.get("query_keywords") or []
    st.caption(
        "检索方式：本地关键词与中文字符片段排序；"
        f"相关阈值 {diagnostic.get('relevance_threshold', 0.08):.2f}；"
        f"最多进入核验 {diagnostic.get('max_evaluation_candidates', 8)} 条。"
    )
    st.markdown(
        "**识别到的关键词：** "
        + ("、".join(keywords) if keywords else "没有命中预设关键词，主要使用字符片段")
    )

    with st.expander("查看候选排序与命中依据"):
        ranked_rows = []
        for item in diagnostic.get("ranked_candidates") or []:
            ranked_rows.append(
                {
                    "排名": item.get("rank"),
                    "证据": f"E{item.get('evidence_id')} · {item.get('title', '')}",
                    "相关分": f"{float(item.get('score', 0)):.3f}",
                    "处理结果": RETRIEVAL_DECISION_LABELS.get(
                        item.get("decision"), item.get("decision", "—")
                    ),
                    "命中依据": item.get("explanation") or "未发现直接词面重合",
                    "来源定位": item.get("source_locator") or "—",
                }
            )
        if ranked_rows:
            st.caption(
                f"当前共有 {len(ranked_rows)} 条候选排序记录；"
                "表格展示相关分、处理结果、命中依据和来源定位。"
            )
            st.dataframe(ranked_rows, width="stretch", hide_index=True)
        else:
            empty_state("当前没有符合授权和审核要求的可检索证据。")

    exclusions = (diagnostic.get("excluded_evidence") or []) + (
        diagnostic.get("excluded_materials") or []
    )
    if exclusions:
        with st.expander("查看未进入检索的材料与证据"):
            for item in diagnostic.get("excluded_evidence") or []:
                st.markdown(
                    f"- **E{item.get('evidence_id')} · {item.get('title', '')}**："
                    + "；".join(item.get("reasons") or [])
                )
            for item in diagnostic.get("excluded_materials") or []:
                st.markdown(
                    f"- **M{item.get('material_id')} · {item.get('name', '')}**："
                    f"{item.get('reason', '未进入检索')}"
                )

st.markdown("### 仍缺少什么")
missing = claim.get("missing_evidence") or []
if missing:
    for item in missing:
        st.markdown(f"- {item}")
else:
    st.success("当前表述没有未解决的关键证据缺口。")

tasks = claim.get("followup_tasks") or []
if tasks:
    st.markdown("#### 补证任务")
    for task in tasks:
        status = TASK_STATUS_LABELS.get(task.get("status"), "未知")
        st.markdown(
            f"**T{task['id']} · {task.get('title', '补证任务')}**　`{status}`  \n"
            f"{task.get('recommended_action') or '—'}"
        )

st.markdown("### 补证与重新核验")
if demo_mode:
    st.caption(
        "下面的补充材料提供一个与原结论方向不同的观点，"
        "用于观察结论状态如何随证据变化。"
    )
    action_left, action_right = st.columns(2)
    with action_left:
        add_supplement = st.button(
            "加入不同观点材料",
            type="primary",
            width="stretch",
        )
    with action_right:
        rerun_check = st.button(
            "重新核验当前结论",
            width="stretch",
        )
else:
    add_supplement = False
    st.info(
        "请先到“材料与证据”导入新的经授权材料，"
        "并批准相应证据卡，然后回到这里重新核验。"
    )
    rerun_check = st.button(
        "重新核验当前结论",
        type="primary",
        width="stretch",
    )

if add_supplement:
    try:
        with st.spinner("正在加入补充材料……"):
            supplement = add_demo_supplement(db, project_id)
    except Exception as exc:
        st.error(f"补充材料添加失败：{exc}")
    else:
        material_id = getattr(supplement, "material_id", supplement)
        st.success(f"补充材料 M{material_id} 已加入，并已完成对应补证任务。")
        st.info("现在点击“重新核验当前结论”，观察是否出现相反证据。")

if rerun_check:
    try:
        with st.spinner("正在使用最新证据重新核验并判断语义关系……"):
            stored = recheck_claim(db, int(active_claim_id))
    except Exception as exc:
        st.error(f"重新核验失败：{exc}")
    else:
        st.session_state["active_claim_id"] = int(stored.claim_id)
        st.success("已使用最新证据完成重新核验。")
        st.rerun()

st.divider()
st.page_link(
    "pages/3_成果与缺口.py",
    label="查看全部成果、缺口并导出 Markdown",
    icon="📄",
)
