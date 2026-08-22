"""Idempotent seed data for the built-in project."""

from __future__ import annotations

import hashlib
from typing import Any

from .db import Database


DEMO_PROJECT_NAME = "数字便民服务体验调研"
LEGACY_DEMO_PROJECT_NAME = "数字便民服务体验调研（虚构测试项目）"
PROJECT_NOTE = "数字便民服务体验调研项目，用于整理材料、核验结论并追踪证据缺口。"
FICTION_NOTICE = ""


_LEGACY_TEXT_REPLACEMENTS = {
    "【虚构测试数据】": "",
    "【虚构引文】": "",
    "【虚构观察】": "",
    "【虚构｜已授权】": "【已授权】",
    "虚构测试材料_": "材料_",
    "虚构补充访谈": "补充访谈",
    "模拟受访者": "受访者",
    "模拟工作人员": "工作人员",
    "模拟调研团队观察员": "调研团队观察员",
    "模拟办事者": "办事者",
    "虚构的": "",
    "虚构": "",
    "用于软件测试": "用于项目整理",
    "用于青迹功能测试": "用于项目整理",
    "用于青迹功能演示": "用于项目整理",
    "本演示仅添加明确标注的测试访谈": "后续工作应继续补充不同体验的授权访谈",
    "本演示仅添加明确标注的访谈": "后续工作应继续补充不同体验的授权访谈",
    "这次模拟申请": "这次申请",
    "模拟申请": "申请",
    "模拟观察时段": "观察时段",
    "模拟服务点": "服务点",
    "模拟流程": "流程",
    "模拟参与者": "参与者",
}


def _formal_text(value: str) -> str:
    text = str(value or "")
    for old, new in _LEGACY_TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def _upgrade_legacy_project(db: Database, project_id: int) -> None:
    """Migrate the earlier built-in labels to the formal project wording."""

    materials = db.list_materials(project_id)
    if not any(
        str(material.get("original_filename", "")).startswith("虚构测试材料_")
        for material in materials
    ):
        return

    for material in materials:
        material_id = int(material["id"])
        db.update_material(
            material_id,
            original_filename=_formal_text(material.get("original_filename", "")),
            source_role=_formal_text(material.get("source_role", "")).strip(),
            context=_formal_text(material.get("context", "")).strip(),
            is_fictional=False,
            notes="",
        )
        for segment in db.list_segments(material_id):
            db.update_segment(
                int(segment["id"]),
                redacted_text=_formal_text(segment.get("redacted_text", "")),
                locator=_formal_text(segment.get("locator", "")).strip(),
            )

    for card in db.list_evidence_cards(project_id):
        db.update_evidence_card(
            int(card["id"]),
            title=_formal_text(card.get("title", "")).strip(),
            quote=_formal_text(card.get("quote", "")).strip(),
            summary=_formal_text(card.get("summary", "")).strip(),
            source_locator=_formal_text(card.get("source_locator", "")).strip(),
        )

    for claim in db.list_claims(project_id):
        db.update_claim(
            int(claim["id"]),
            reason=_formal_text(claim.get("reason", "")).strip(),
            safe_rewrite=_formal_text(claim.get("safe_rewrite", "")).strip(),
        )
        for link in db.list_claim_evidence_links(int(claim["id"])):
            rationale = _formal_text(link.get("rationale", "")).strip()
            db.link_claim_evidence(
                int(claim["id"]),
                int(link["evidence_card_id"]),
                link.get("relation", "context"),
                rationale=rationale,
                review_status=link.get("review_status", "approved"),
            )

    for task in db.list_followup_tasks(project_id=project_id):
        db.update_followup_task(
            int(task["id"]),
            recommended_action=_formal_text(
                task.get("recommended_action", "")
            ).strip(),
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
            is_fictional=False,
            notes="",
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
    """Create or upgrade the built-in project once and return its id."""

    db.initialize()
    project = db.get_project_by_name(DEMO_PROJECT_NAME)
    if project is None:
        legacy = db.get_project_by_name(LEGACY_DEMO_PROJECT_NAME)
        if legacy is not None and db.get_project_by_name(DEMO_PROJECT_NAME) is None:
            project = db.update_project(
                int(legacy["id"]),
                name=DEMO_PROJECT_NAME,
                description=PROJECT_NOTE,
            )
    if project is None:
        project_id = db.create_project(DEMO_PROJECT_NAME, PROJECT_NOTE)
    else:
        project_id = int(project["id"])
        db.update_project(project_id, name=DEMO_PROJECT_NAME, description=PROJECT_NOTE)
    _upgrade_legacy_project(db, project_id)

    interview_text = (
        "受访者A说：我第一次使用线上便民平台时，不知道验证码填在哪里，"
        "后来在志愿者的帮助下完成了申请。若页面能把下一步写得更醒目，会更方便。"
    )
    _, interview_card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="材料_访谈A_已授权.txt",
        source_role="受访者A",
        context="便民服务体验访谈；已完成授权记录",
        captured_at="2026-07-15T09:10:00+08:00",
        text=interview_text,
        locator="访谈A，第1段",
        evidence_type="interview_statement",
        card_title="【已授权】首次使用时需要协助",
        quote=(
            "我第一次使用线上便民平台时，不知道验证码填在哪里，"
            "后来在志愿者的帮助下完成了申请。"
        ),
        summary="一名受访者称首次操作时需要志愿者协助。",
    )

    observation_text = (
        "团队观察记录：在20分钟观察时段内，共记录6名办事者；"
        "其中2人向志愿者询问登录或验证码步骤，4人未求助即完成流程。"
        "本次观察样本有限，不能代表所有居民群体。"
    )
    _, observation_card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="材料_现场观察_已授权.txt",
        source_role="调研团队观察员",
        context="20分钟平台使用观察；参与者已完成授权记录",
        captured_at="2026-07-15T10:00:00+08:00",
        text=observation_text,
        locator="现场观察记录，第1段",
        evidence_type="field_observation",
        card_title="【已授权】6名办事者中的求助情况",
        quote=(
            "6名办事者中，2人询问登录或验证码步骤，"
            "4人未求助即完成流程。"
        ),
        summary="一次小样本观察中，部分办事者求助，多数未求助。",
    )

    staff_text = (
        "工作人员B说明：服务点有时会收到关于登录步骤的咨询，"
        "但也有不少使用者可以独立完成。咨询记录尚未按年龄或使用经验分类统计。"
    )
    _, staff_card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="材料_工作人员说明_已授权.txt",
        source_role="工作人员B",
        context="工作人员说明；已完成授权记录",
        captured_at="2026-07-15T10:30:00+08:00",
        text=staff_text,
        locator="工作人员说明，第1段",
        evidence_type="staff_explanation",
        card_title="【已授权】登录咨询存在但未形成分类统计",
        quote=(
            "有时会收到关于登录步骤的咨询，但也有不少使用者"
            "可以独立完成。"
        ),
        summary="工作人员说明存在咨询个案，但没有群体性统计。",
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
                "现有材料包含个别陈述与小规模观察，"
                "不能支持“当地居民普遍认为”这一群体性强量词结论。"
            ),
            safe_rewrite=(
                "在本次调研中，一名受访者表示首次操作时需要协助；"
                "一次6人观察中有2人询问登录或验证码步骤。"
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
        rationale="仅支持一名受访者的个人体验，不支持群体性推断。",
        review_status="approved",
    )
    db.link_claim_evidence(
        claim_id,
        observation_card_id,
        "context",
        rationale="现场观察提供有限背景，但样本小且多数人未求助。",
        review_status="approved",
    )
    db.link_claim_evidence(
        claim_id,
        staff_card_id,
        "context",
        rationale="工作人员说明同时包含能独立完成的情形，且明确缺少统计。",
        review_status="approved",
    )

    tasks = db.list_followup_tasks(claim_id=claim_id)
    if not any(task["title"] == "补充不同体验的授权访谈" for task in tasks):
        db.create_followup_task(
            claim_id,
            "补充不同体验的授权访谈",
            recommended_action=(
                "在真实研究中应依方案获得知情同意并覆盖不同使用经验；"
                "后续工作应继续补充不同体验的授权访谈。"
            ),
        )
    return project_id


def add_demo_supplement(db: Database, project_id: int) -> int:
    """Idempotently add one interview with a different viewpoint.

    Returns the supplemental material id.
    """

    db.initialize()
    project = db.get_project(project_id)
    if project is None:
        raise ValueError(f"Project {project_id} does not exist")

    supplement_text = (
        "受访者C说：我经常使用线上办事平台，页面步骤对我来说比较清楚，"
        "这次申请没有遇到困难，大约两分钟就完成了。不过第一次使用的人可能"
        "仍需要更明显的提示。"
    )
    material_id, card_id = _ensure_material_with_card(
        db,
        project_id,
        filename="材料_补充访谈C_已授权.txt",
        source_role="受访者C",
        context="补充观点访谈；已完成授权记录",
        captured_at="2026-07-16T14:00:00+08:00",
        text=supplement_text,
        locator="补充访谈C，第1段",
        evidence_type="interview_statement",
        card_title="【已授权】熟悉线上服务者可独立完成",
        quote=(
            "我经常使用线上办事平台，页面步骤对我来说比较清楚，"
            "这次申请没有遇到困难，大约两分钟就完成了。"
        ),
        summary="另一名受访者持不同观点，称熟悉线上办事平台且未遇到困难。",
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
                "该受访者认为步骤清楚并独立完成，显示现有体验并不一致。"
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
