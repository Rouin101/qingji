"""青迹 Streamlit entry page."""

from __future__ import annotations

import streamlit as st

from qingji.ui import (
    VERDICT_LABELS,
    configure_page,
    empty_state,
    format_datetime,
    get_demo_context,
    render_demo_banner,
    render_page_intro,
    render_sidebar_note,
    verdict_box,
)


configure_page("项目概览", "🌱")
render_sidebar_note()
render_page_intro(
    "QINGJI · 可信社会实践",
    "青迹",
    "把已授权的现场材料变成可回溯证据，检查每一句结论是否说过了头。",
)
render_demo_banner()

try:
    db, project_id, project = get_demo_context()
except Exception as exc:
    st.error(f"应用初始化失败：{exc}")
    st.info("请确认当前目录可写，并重新运行应用。")
    st.stop()

st.markdown(f"### {project['name']}")
st.caption(project.get("description") or "社会实践证据链演示项目")

try:
    stats = db.get_project_stats(project_id)
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

with st.expander("演示建议（3分钟）"):
    st.markdown(
        """
        1. 在“材料与证据”查看已授权、已脱敏的虚构测试材料。
        2. 核验“当地居民普遍认为线上办事平台使用困难”。
        3. 观察青迹如何识别“普遍”这一强量词，并指出样本边界。
        4. 添加一份持不同观点的虚构补充材料，重新核验。
        5. 在“成果与缺口”下载可追溯的 Markdown。
        """
    )
