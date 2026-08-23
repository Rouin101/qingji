"""Shared Streamlit presentation helpers for 青迹."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st


_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


EVIDENCE_TYPE_LABELS = {
    "interview_statement": "受访者陈述",
    "staff_explanation": "工作人员说明",
    "field_observation": "团队现场观察",
    "formal_record": "文献或正式记录",
    "team_analysis": "团队分析",
}

CONSENT_LABELS = {
    "confirmed": "已确认授权",
    "unknown": "授权待确认",
    "denied": "未授权",
}

REVIEW_STATUS_LABELS = {
    "draft": "待审核",
    "approved": "已批准",
    "rejected": "已拒绝",
}

VERDICT_LABELS = {
    "supported": "已有支持",
    "partially_supported": "部分支持",
    "unsupported": "暂无支持",
    "contradicted": "存在冲突",
}

VERDICT_ICONS = {
    "supported": "✅",
    "partially_supported": "🟠",
    "unsupported": "⚪",
    "contradicted": "⚠️",
}

VERDICT_COLORS = {
    "supported": ("#0f766e", "#ecfdf5", "#99f6e4"),
    "partially_supported": ("#b45309", "#fffbeb", "#fde68a"),
    "unsupported": ("#475569", "#f8fafc", "#cbd5e1"),
    "contradicted": ("#b91c1c", "#fef2f2", "#fecaca"),
}

TASK_STATUS_LABELS = {
    "open": "待补证",
    "done": "已完成",
    "cancelled": "已取消",
}

WORKFLOW_STEPS = (
    ("overview", "项目概览", "app.py", "创建或切换项目，查看总体进度。"),
    ("materials", "材料与证据", "pages/1_材料与证据.py", "导入材料并审核证据卡。"),
    ("claims", "结论核验", "pages/2_结论核验.py", "检查报告表述是否超出证据。"),
    ("output", "成果与缺口", "pages/3_成果与缺口.py", "查看缺口、对应关系并导出。"),
)


NEXT_ACTION_PAGES = {
    "materials": "pages/1_材料与证据.py",
    "claims": "pages/2_结论核验.py",
    "output": "pages/3_成果与缺口.py",
}


@st.cache_resource(show_spinner=False)
def get_database() -> Any:
    """Return one initialized database handle per Streamlit process."""

    from .config import settings
    from .db import Database

    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    return database


def is_demo_project(project: Mapping[str, Any] | None) -> bool:
    """Return whether a project is Qingji's built-in workspace."""

    from .demo import DEMO_PROJECT_NAME

    return bool(project and project.get("name") == DEMO_PROJECT_NAME)


def get_demo_context() -> tuple[Any, int, dict[str, Any]]:
    """Load the active project, using the built-in workspace as a fallback."""

    from .demo import ensure_demo_project

    database = get_database()
    project_id = st.session_state.get("qingji_project_id")
    project = database.get_project(project_id) if project_id else None
    if project is None or project.get("archived_at"):
        project_id = int(ensure_demo_project(database))
        st.session_state["qingji_project_id"] = project_id
        project = database.get_project(project_id)
    if project is None:
        raise RuntimeError("内置项目初始化失败，请检查本地数据库是否可写。")
    return database, int(project_id), project


def configure_page(title: str, icon: str = "🌱") -> None:
    """Apply consistent page metadata and compact demo-friendly styling."""

    st.set_page_config(
        page_title=f"{title}｜青迹",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root {
            --qj-ink: #2b1a45;
            --qj-muted: #6d6690;
            --qj-primary: #6b35a0;
            --qj-primary-strong: #552a82;
            --qj-primary-soft: #a98fe0;
            --qj-pale: #f4effb;
            --qj-line: #e4dcf3;
        }
        [data-testid="stAppViewContainer"] {
            background:
              radial-gradient(circle at 88% 4%, rgba(107, 53, 160, .10), transparent 24rem),
              radial-gradient(circle at 8% 96%, rgba(169, 143, 224, .12), transparent 26rem),
              linear-gradient(180deg, #fdfcff 0, #ffffff 30rem);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #f7f4fc 0, #f1ebfa 100%);
            border-right: 1px solid var(--qj-line);
        }
        h1, h2, h3 { color: var(--qj-ink); letter-spacing: -.02em; }
        h1 { padding-bottom: .15rem; }
        .qj-kicker {
            color: var(--qj-primary);
            font-size: .82rem;
            font-weight: 750;
            letter-spacing: .13em;
            margin-bottom: .25rem;
        }
        .qj-lead {
            color: var(--qj-muted);
            font-size: 1.02rem;
            line-height: 1.7;
            max-width: 58rem;
            margin: -.35rem 0 1rem;
        }
        .qj-demo {
            background: linear-gradient(180deg, #fbf3ff 0, #f5ecfd 100%);
            border: 1px solid #e8d6fb;
            border-left: 5px solid #9b4dca;
            border-radius: .7rem;
            color: #5b2a8f;
            margin: .4rem 0 1.2rem;
            padding: .75rem 1rem;
        }
        .qj-card {
            background: rgba(255,255,255,.92);
            border: 1px solid var(--qj-line);
            border-radius: .8rem;
            box-shadow: 0 6px 22px rgba(43, 26, 69, .06);
            margin: .3rem 0 .8rem;
            padding: .9rem 1rem;
            transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
        }
        .qj-card:hover {
            border-color: #d2c1f4;
            box-shadow: 0 10px 28px rgba(107, 53, 160, .12);
            transform: translateY(-1px);
        }
        .qj-card-label {
            color: var(--qj-muted);
            font-size: .78rem;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .qj-quote {
            border-left: 3px solid #c9a8ea;
            color: #3a2b5e;
            line-height: 1.72;
            margin: .55rem 0;
            padding-left: .8rem;
        }
        .qj-meta {
            color: var(--qj-muted);
            font-size: .84rem;
            line-height: 1.55;
        }
        .qj-verdict {
            border: 1px solid;
            border-radius: .85rem;
            box-shadow: 0 4px 14px rgba(43, 26, 69, .05);
            margin: .25rem 0 1rem;
            padding: 1rem 1.1rem;
        }
        .qj-verdict strong { font-size: 1.12rem; }
        .qj-empty {
            background: linear-gradient(180deg, #faf7ff 0, #f5f0fc 100%);
            border: 1px dashed #cfc2ee;
            border-radius: .75rem;
            color: #6d6690;
            padding: 1.1rem;
            text-align: center;
        }
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,.92);
            border: 1px solid var(--qj-line);
            border-radius: .8rem;
            padding: .65rem .8rem;
        }
        div[data-testid="stForm"] {
            background: rgba(255,255,255,.86);
            border-color: var(--qj-line);
            border-radius: .85rem;
            padding: .3rem .65rem .8rem;
        }
        .stButton > button[kind="primary"],
        .stDownloadButton > button[kind="primary"] {
            background: var(--qj-primary);
            border-color: var(--qj-primary);
        }
        .stButton > button[kind="primary"]:hover,
        .stDownloadButton > button[kind="primary"]:hover {
            background: var(--qj-primary-strong);
            border-color: var(--qj-primary-strong);
        }
        .stButton > button:focus-visible,
        .stDownloadButton > button:focus-visible,
        .stFormSubmitButton > button:focus-visible {
            outline: 2px solid rgba(107, 53, 160, .5);
            outline-offset: 2px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_intro(kicker: str, title: str, lead: str) -> None:
    st.markdown(f'<div class="qj-kicker">{escape_html(kicker)}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="qj-lead">{escape_html(lead)}</div>', unsafe_allow_html=True)


def render_demo_banner(project: Mapping[str, Any] | None = None) -> None:
    if is_demo_project(project) or project is None:
        title = "当前项目工作区"
        message = (
            "当前项目已载入完整的材料、证据和结论，可直接按流程继续整理。"
            "新增材料请如实填写来源、授权状态和采集场景。"
        )
    else:
        title = "用户项目工作区"
        message = (
            "请只导入有权使用的材料，并如实记录授权状态。"
            "真实材料会先在本地脱敏；未确认授权的内容不会进入结论核验或可信导出。"
        )
    st.markdown(
        (
            '<div class="qj-demo">'
            f"<strong>{escape_html(title)}</strong><br>"
            f"{escape_html(message)}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def get_next_action(progress: Mapping[str, Any]) -> dict[str, str]:
    """Return one concrete next action for the current project state."""

    materials = int(progress.get("materials", 0) or 0)
    evidence_cards = int(progress.get("evidence_cards", 0) or 0)
    approved_cards = int(progress.get("approved_evidence_cards", 0) or 0)
    claims = int(progress.get("claims", 0) or 0)
    open_tasks = int(progress.get("open_followup_tasks", 0) or 0)
    if materials == 0:
        return {
            "key": "materials",
            "title": "导入一份文字材料",
            "detail": "填写来源、场景和授权信息，先把材料放进当前项目。",
            "button": "去导入材料",
            "page": NEXT_ACTION_PAGES["materials"],
        }
    if evidence_cards == 0:
        return {
            "key": "materials",
            "title": "完成材料检查并生成证据卡",
            "detail": "当前还没有证据卡；请先完成本地脱敏确认。",
            "button": "去处理材料",
            "page": NEXT_ACTION_PAGES["materials"],
        }
    if evidence_cards > approved_cards:
        return {
            "key": "materials",
            "title": "审核待处理的证据卡",
            "detail": "只有已确认授权且已批准的证据，才能进入结论核验。",
            "button": "去审核证据卡",
            "page": NEXT_ACTION_PAGES["materials"],
        }
    if claims == 0:
        return {
            "key": "claims",
            "title": "核验一句准备写入报告的话",
            "detail": "输入一句事实性表述，查看它目前能被证据支持到什么程度。",
            "button": "去开始核验",
            "page": NEXT_ACTION_PAGES["claims"],
        }
    if open_tasks:
        return {
            "key": "output",
            "title": "处理待补证任务",
            "detail": "查看缺口、补充材料，再回到结论页重新核验。",
            "button": "去查看补证任务",
            "page": NEXT_ACTION_PAGES["output"],
        }
    return {
        "key": "output",
        "title": "查看成果并导出",
        "detail": "核对结论—证据对应关系，确认无误后导出可信 Markdown。",
        "button": "去查看成果",
        "page": NEXT_ACTION_PAGES["output"],
    }


def _next_step_hint(progress: Mapping[str, Any]) -> str:
    """Return the compact sidebar version of the next-action guidance."""

    return f"下一步：{get_next_action(progress)['title']}"


def render_next_action(
    progress: Mapping[str, Any],
    *,
    heading: str = "建议下一步",
    current_step: str | None = None,
) -> None:
    """Show one state-aware action instead of presenting every entry equally."""

    action = get_next_action(progress)
    with st.container(border=True):
        st.markdown(f"#### {heading}")
        st.markdown(f"**{action['title']}**")
        st.caption(action["detail"])
        if current_step == action["key"]:
            st.caption("当前页面内即可完成这一步。")
        else:
            st.page_link(action["page"], label=action["button"], icon="➡️")


def render_sidebar_note(
    project: Mapping[str, Any] | None = None,
    *,
    database: Any | None = None,
    project_id: int | None = None,
) -> None:
    """Render shared navigation, project context and lightweight progress."""

    progress: Mapping[str, Any] | None = None
    if database is not None and project_id is not None:
        try:
            progress = database.get_project_stats(int(project_id))
        except Exception:
            progress = None
    with st.sidebar:
        st.page_link("app.py", label="项目概览")
        st.page_link("pages/1_材料与证据.py", label="材料与证据")
        st.page_link("pages/2_结论核验.py", label="结论核验")
        st.page_link("pages/3_成果与缺口.py", label="成果与缺口")
        st.divider()
        st.markdown("### 青迹")
        st.caption("让实践有迹可循，让结论有据可查。")
        if not (is_demo_project(project) or project is None):
            st.info(
                f"当前项目：{project.get('name', '未命名项目')}\n\n"
                "项目切换与新建请返回“项目概览”。"
            )
        if progress is not None:
            st.divider()
            st.markdown("### 当前进度")
            st.caption(
                f"材料 {int(progress.get('materials', 0) or 0)} · "
                f"已批准证据 {int(progress.get('approved_evidence_cards', 0) or 0)} · "
                f"结论 {int(progress.get('claims', 0) or 0)} · "
                f"待补证 {int(progress.get('open_followup_tasks', 0) or 0)}"
            )
            st.caption(_next_step_hint(progress))
            action = get_next_action(progress)
            st.page_link(action["page"], label=action["button"], icon="➡️")
        st.caption("v1.2 · 开发版")


def render_workflow_steps(current_step: str) -> None:
    """Show the recommended path and make adjacent pages one click away."""

    keys = [item[0] for item in WORKFLOW_STEPS]
    current_index = keys.index(current_step) if current_step in keys else 0
    with st.container(border=True):
        columns = st.columns(len(WORKFLOW_STEPS))
        for index, (key, label_text, page_path, help_text) in enumerate(
            WORKFLOW_STEPS
        ):
            if index == current_index:
                state = "🔵 当前"
            elif index < current_index:
                state = "↩️ 上一步"
            elif index == current_index + 1:
                state = "➡️ 下一步"
            else:
                state = "待开始"
            with columns[index]:
                st.page_link(
                    page_path,
                    label=f"{index + 1}. {label_text}",
                    icon="🔵" if index == current_index else None,
                )
                st.caption(f"{state} · {help_text}")


def row_to_dict(row: Any) -> dict[str, Any]:
    """Normalize sqlite rows, mappings and dataclasses for presentation."""

    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    if is_dataclass(row):
        return asdict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    data = getattr(row, "__dict__", None)
    return dict(data) if isinstance(data, dict) else {}


def value(row: Any, key: str, default: Any = "") -> Any:
    return row_to_dict(row).get(key, default)


def enum_value(item: Any) -> str:
    raw = getattr(item, "value", item)
    return "" if raw is None else str(raw)


def label(mapping: dict[str, str], item: Any, fallback: str = "—") -> str:
    raw = enum_value(item)
    return mapping.get(raw, raw or fallback)


def format_datetime(item: Any) -> str:
    if item in (None, ""):
        return "—"
    if isinstance(item, datetime):
        parsed = item
    elif isinstance(item, date):
        return item.strftime("%Y-%m-%d")
    text = str(item).replace("T", " ")
    if len(text) == 10:
        return text
    if not isinstance(item, datetime):
        try:
            parsed = datetime.fromisoformat(str(item).replace("Z", "+00:00"))
        except ValueError:
            return text[:16] if len(text) >= 16 else text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_LOCAL_TIMEZONE)
    return parsed.strftime("%Y-%m-%d %H:%M")


def verdict_box(verdict: Any, reason: str) -> None:
    raw = enum_value(verdict)
    foreground, background, border = VERDICT_COLORS.get(
        raw, ("#334155", "#f8fafc", "#cbd5e1")
    )
    icon = VERDICT_ICONS.get(raw, "🔎")
    title = VERDICT_LABELS.get(raw, raw or "尚未核验")
    st.markdown(
        (
            f'<div class="qj-verdict" style="color:{foreground};'
            f'background:{background};border-color:{border}">'
            f"<strong>{icon} {escape_html(title)}</strong><br>"
            f'<span style="line-height:1.7">{escape_html(reason or "暂无判断说明")}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def evidence_card_html(card: Any) -> str:
    data = row_to_dict(card)
    evidence_id = data.get("id", "—")
    title = data.get("title") or f"证据 E{evidence_id}"
    quote = data.get("quote") or data.get("redacted_text") or "暂无摘录"
    evidence_type = label(EVIDENCE_TYPE_LABELS, data.get("evidence_type"))
    role = data.get("source_role") or "来源角色未填写"
    context = data.get("context") or "场景未填写"
    locator = data.get("source_locator") or data.get("locator") or "位置待补充"
    consent = label(CONSENT_LABELS, data.get("consent_status"))
    review = label(REVIEW_STATUS_LABELS, data.get("review_status"))
    return (
        '<div class="qj-card">'
        f'<div class="qj-card-label">E{escape_html(evidence_id)} · '
        f"{escape_html(evidence_type)}</div>"
        f"<strong>{escape_html(title)}</strong>"
        f'<div class="qj-quote">{escape_html(quote)}</div>'
        f'<div class="qj-meta">来源角色：{escape_html(role)} · '
        f"场景：{escape_html(context)}<br>"
        f"定位：{escape_html(locator)} · {escape_html(consent)} · "
        f"{escape_html(review)}</div>"
        "</div>"
    )


def empty_state(message: str) -> None:
    st.markdown(
        f'<div class="qj-empty">{escape_html(message)}</div>',
        unsafe_allow_html=True,
    )


def escape_html(value_: Any) -> str:
    text = "" if value_ is None else str(value_)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
        .replace("\n", "<br>")
    )
