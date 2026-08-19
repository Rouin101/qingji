"""Idempotent, explicitly fictional data for demonstrations and tests."""

from __future__ import annotations

import hashlib
from typing import Any

from .db import Database


DEMO_PROJECT_NAME = "数字便民服务体验调研（虚构测试项目）"
FICTION_NOTICE = (
    "【虚构测试数据】本材料中的人物、地点、对话和观察均为软件演示而编写，"
    "不对应任何真实个人或真实调研结论；模拟参与者已授权用于青迹功能测试。"
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _material_by_filename(
    db: Database, project_id: int, filename: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in db.list_materials(project_id)
            if item["original_filename"] == filename
        ),
        None,
    )


def _card_by_title(
    db: Database, project_id: int, title: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in db.list_evidence_cards(project_id)
            if item["title"] == title
        ),
        None,
    )


def _ensure_material_with_card(
    db: Database,
    project_id: int,
    *,
    filename: str,
    source_role: str,
    context: str,
    captured_at: str,
    text: str,
    locator: str,
    evidence_type: str,
    card_title: str,
    quote: str,
    summary: str,
) -> tuple[int, int]:
    material = _material_by_filename(db, project_id, filename)
    if material is None:
        material_id = db.create_material(
            project_id,
            "text",
            original_filename=filename,
            sha256=_digest(text),
            source_role=source_role,
            context=context,
            captured_at=captured_at,
            consent_status="confirmed",
            processing_status="ready",
            is_fictional=True,
            notes=FICTION_NOTICE,
        )
    else:
        material_id = int(material["id"])

    segments = db.list_segments(material_id)
    if segments:
        segment_id = int(segments[0]["id"])
    else:
        segment_id = db.create_segment(
            material_id,
            1,
            text,
            locator=locator,
            pii_flags=[],
        )

    card = _card_by_title(db, project_id, card_title)
    if card is None:
        card_id = db.create_evidence_card(
            project_id,
            segment_id,
            evidence_type,
            card_title,
            quote,
            summary,
            source_locator=locator,
            review_status="approved",
        )
    else:
        card_id = int(card["id"])
        if card["review_status"] != "approved":
            db.set_evidence_review_status(card_id, "approved")
    return material_id, card_id


def create_demo_project(db: Database) -> int:
    """Create the complete fictional baseline project once and return its id."""

    db.initialize()
    project = db.get_project_by_name(DEMO_PROJECT_NAME)
    if project is None:
        project_id = db.create_project(
            DEMO_PROJECT_NAME,
            FICTION_NOTICE
            + " 项目用于验证授权、脱敏、证据分类、结论核验与补证闭环。",
        )
    else:
        project_id = int(project["id"])

    interview_text = (
        FICTION_NOTICE
        + "\n受访者A（虚构）说：我第一次使用线上便民平台时，不知道验证码填在哪里，"
        "后来在志愿者的帮助下完成了申请。若页面能把下一步写得更醒目，会更方便。"
    )
    _, interview_card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="虚构测试材料_访谈A_已授权.txt",
        source_role="模拟受访者A（虚构）",
        context="虚构的便民服务体验访谈；已授权用于软件测试",
        captured_at="2026-07-15T09:10:00+08:00",
        text=interview_text,
        locator="虚构访谈A，第1段",
        evidence_type="interview_statement",
        card_title="【虚构｜已授权】首次使用时需要协助",
        quote=(
            "【虚构引文】我第一次使用线上便民平台时，不知道验证码填在哪里，"
            "后来在志愿者的帮助下完成了申请。"
        ),
        summary="一名虚构受访者称首次操作时需要志愿者协助。",
    )

    observation_text = (
        FICTION_NOTICE
        + "\n团队观察记录（虚构）：在20分钟模拟观察时段内，共设置6名模拟办事者；"
        "其中2人向模拟志愿者询问登录或验证码步骤，4人未求助即完成模拟流程。"
        "这一小规模演练不能代表任何真实居民群体。"
    )
    _, observation_card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="虚构测试材料_现场观察_已授权.txt",
        source_role="模拟调研团队观察员",
        context="虚构的20分钟平台使用观察；全体模拟参与者已授权",
        captured_at="2026-07-15T10:00:00+08:00",
        text=observation_text,
        locator="虚构观察记录，第1段",
        evidence_type="field_observation",
        card_title="【虚构｜已授权】6名模拟办事者中的求助情况",
        quote=(
            "【虚构观察】6名模拟办事者中，2人询问登录或验证码步骤，"
            "4人未求助即完成模拟流程。"
        ),
        summary="一次虚构小样本观察中，部分模拟办事者求助，多数未求助。",
    )

    staff_text = (
        FICTION_NOTICE
        + "\n工作人员B（虚构）说明：模拟服务点有时会收到关于登录步骤的咨询，"
        "但也有不少使用者可以独立完成。咨询记录尚未按年龄或使用经验分类统计。"
    )
    _, staff_card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="虚构测试材料_工作人员说明_已授权.txt",
        source_role="模拟工作人员B（虚构）",
        context="虚构工作人员说明；已授权用于软件测试",
        captured_at="2026-07-15T10:30:00+08:00",
        text=staff_text,
        locator="虚构工作人员说明，第1段",
        evidence_type="staff_explanation",
        card_title="【虚构｜已授权】登录咨询存在但未形成分类统计",
        quote=(
            "【虚构引文】有时会收到关于登录步骤的咨询，但也有不少使用者"
            "可以独立完成。"
        ),
        summary="虚构工作人员说明存在咨询个案，但没有群体性统计。",
    )

    claims = db.list_claims(project_id)
    claim = next(
        (
            item
            for item in claims
            if item["claim_text"] == "当地居民普遍认为线上办事平台使用困难。"
        ),
        None,
    )
    if claim is None:
        claim_id = db.create_claim(
            project_id,
            "当地居民普遍认为线上办事平台使用困难。",
            verdict="unsupported",
            reason=(
                "现有材料均为虚构测试材料，且只有个别陈述与小规模模拟观察，"
                "不能支持“当地居民普遍认为”这一群体性强量词结论。"
            ),
            safe_rewrite=(
                "在本次虚构测试中，一名模拟受访者表示首次操作时需要协助；"
                "一次6人模拟观察中有2人询问登录或验证码步骤。"
            ),
            missing_evidence=[
                "需要更多不同年龄和数字工具经验参与者的授权材料",
                "需要明确抽样范围与足以支持群体性结论的统计证据",
            ],
            rule_flags=["强量词：普遍", "样本范围不足"],
        )
    else:
        claim_id = int(claim["id"])

    db.link_claim_evidence(
        claim_id,
        interview_card_id,
        "support",
        rationale="仅支持一名虚构受访者的个人体验，不支持群体性推断。",
        review_status="approved",
    )
    db.link_claim_evidence(
        claim_id,
        observation_card_id,
        "context",
        rationale="虚构观察提供有限背景，但样本小且多数人未求助。",
        review_status="approved",
    )
    db.link_claim_evidence(
        claim_id,
        staff_card_id,
        "context",
        rationale="虚构说明同时包含能独立完成的情形，且明确缺少统计。",
        review_status="approved",
    )

    tasks = db.list_followup_tasks(claim_id=claim_id)
    if not any(task["title"] == "补充不同体验的授权访谈" for task in tasks):
        db.create_followup_task(
            claim_id,
            "补充不同体验的授权访谈",
            recommended_action=(
                "在真实研究中应依方案获得知情同意并覆盖不同使用经验；"
                "本演示仅添加明确标注的虚构测试访谈。"
            ),
        )
    return project_id


def add_demo_supplement(db: Database, project_id: int) -> int:
    """Idempotently add one fictional interview with a different viewpoint.

    Returns the supplemental material id.
    """

    db.initialize()
    project = db.get_project(project_id)
    if project is None:
        raise ValueError(f"Project {project_id} does not exist")

    supplement_text = (
        FICTION_NOTICE
        + "\n受访者C（虚构）说：我经常使用线上办事平台，页面步骤对我来说比较清楚，"
        "这次模拟申请没有遇到困难，大约两分钟就完成了。不过第一次使用的人可能"
        "仍需要更明显的提示。"
    )
    material_id, card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="虚构测试材料_补充访谈C_已授权.txt",
        source_role="模拟受访者C（虚构）",
        context="虚构的补充观点访谈；已授权用于软件测试",
        captured_at="2026-07-16T14:00:00+08:00",
        text=supplement_text,
        locator="虚构补充访谈C，第1段",
        evidence_type="interview_statement",
        card_title="【虚构｜已授权】熟悉线上服务者可独立完成",
        quote=(
            "【虚构引文】我经常使用线上办事平台，页面步骤对我来说比较清楚，"
            "这次模拟申请没有遇到困难，大约两分钟就完成了。"
        ),
        summary="另一名虚构受访者持不同观点，称熟悉线上办事平台且未遇到困难。",
    )

    claim = next(
        (
            item
            for item in db.list_claims(project_id)
            if item["claim_text"] == "当地居民普遍认为线上办事平台使用困难。"
        ),
        None,
    )
    if claim is not None:
        claim_id = int(claim["id"])
        db.link_claim_evidence(
            claim_id,
            card_id,
            "contradict",
            rationale=(
                "该虚构受访者认为步骤清楚并独立完成，显示现有体验并不一致。"
            ),
            review_status="approved",
        )
        for task in db.list_followup_tasks(claim_id=claim_id):
            if task["title"] == "补充不同体验的授权访谈":
                db.set_followup_task_status(
                    int(task["id"]),
                    "done",
                    completion_material_id=material_id,
                )
    return material_id


# Friendly aliases for callers that prefer "seed" terminology.
ensure_demo_project = create_demo_project
seed_demo_project = create_demo_project

