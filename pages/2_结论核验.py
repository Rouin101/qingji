"""Claim checking and evidence-gap workflow page."""

from __future__ import annotations

import streamlit as st

from qingji.demo import add_demo_supplement
from qingji.ui import (
    TASK_STATUS_LABELS,
    VERDICT_ICONS,
    VERDICT_LABELS,
    configure_page,
    empty_state,
    evidence_card_html,
    get_demo_context,
    is_demo_project,
    render_demo_banner,
    render_page_intro,
    render_sidebar_note,
    verdict_box,
)
from qingji.workflow import check_and_store_claim, recheck_claim


EXAMPLE_CLAIM = "当地居民普遍认为线上办事平台使用困难。"
RULE_FLAG_LABELS = {
    "group_generalization": "群体性概括",
    "absolute_quantifier": "绝对量词",
    "strong_intensity": "强程度表达",
    "causal_language": "因果表达",
    "precise_quantity": "精确数量",
}


configure_page("结论核验", "🔎")

try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"读取项目失败：{exc}")
    st.stop()

render_sidebar_note(project)
render_page_intro(
    "02 · CLAIM CHECK",
    "结论核验",
    "输入一句准备写入报告的话。青迹只使用已授权、已审核的证据，说明它目前能支持到什么程度。",
)
render_demo_banner(project)
demo_mode = is_demo_project(project)

st.markdown("### 核验一句话")
with st.form("claim_check_form"):
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
            with st.spinner("正在检索已授权证据并检查表述边界……"):
                stored = check_and_store_claim(
                    db, project_id, claim_text.strip()
                )
        except Exception as exc:
            st.error(f"结论核验失败：{exc}")
        else:
            st.session_state["active_claim_id"] = int(stored.claim_id)
            st.session_state["claim_draft"] = claim_text.strip()
            st.success("核验完成。请重点查看理由、证据范围和稳妥改写。")

claims = db.list_claims(project_id)
active_claim_id = st.session_state.get("active_claim_id")
if active_claim_id is None and claims:
    active_claim_id = int(claims[0]["id"])

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
if not links:
    empty_state("当前未找到可引用证据。未授权或未审核的材料不会出现在这里。")
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
                st.markdown(evidence_card_html(card), unsafe_allow_html=True)
            if link.get("rationale"):
                st.caption(f"关联说明：{link['rationale']}")

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
        "下面的补充材料也是虚构测试数据，并提供一个与原结论方向不同的观点，"
        "用于测试结论状态如何随证据变化。"
    )
    action_left, action_right = st.columns(2)
    with action_left:
        add_supplement = st.button(
            "加入虚构的不同观点材料",
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
        with st.spinner("正在加入虚构补充材料……"):
            supplement = add_demo_supplement(db, project_id)
    except Exception as exc:
        st.error(f"补充材料添加失败：{exc}")
    else:
        material_id = getattr(supplement, "material_id", supplement)
        st.success(f"虚构补充材料 M{material_id} 已加入，并已完成对应补证任务。")
        st.info("现在点击“重新核验当前结论”，观察是否出现相反证据。")

if rerun_check:
    try:
        with st.spinner("正在使用最新证据重新核验……"):
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
