"""Workflow orchestration for Qingji's text-only MVP.

This module ties the already-tested building blocks together:

- :func:`import_text_material`  — store raw + redacted text, persist segments,
  and draft evidence cards only for confirmed consent.
- :func:`check_and_store_claim` — evaluate one claim against the approved,
  authorized evidence set and persist the verdict, links and follow-up tasks.
- :func:`recheck_claim`         — re-run the same evaluation after new evidence
  is added, updating the existing claim instead of duplicating it.

Original material and redacted text are kept in ``raw/`` and ``redacted/``
directories next to the database.  In the real application those are exactly
``settings.raw_dir`` / ``settings.redacted_dir``; in tests the database usually
lives in a temporary directory, so the files stay isolated with it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

from .claims import evaluate_claim, validate_citation_ids
from .config import llm_settings
from .diagnostics import build_retrieval_diagnostic
from .evidence import generate_evidence_drafts, split_text
from .llm import LLMError, request_evidence_card_generation
from .models import (
    ClaimEvaluation,
    ConsentStatus,
    EvidenceCandidate,
    EvidenceDraft,
    EvidenceType,
    MaterialImportResult,
    ReviewStatus,
    TaskStatus,
)
from .privacy import redact_text
from .retrieval import evidence_candidate_from_mapping

#: Explicit note attached only when an imported material is marked as an example.
_FICTION_NOTE = "该材料已标记为内部示例，不应当作真实调研结论。"

_TASK_RECOMMENDATION = (
    "优先补充已获得记录与使用授权的材料，并明确其来源角色、采集场景与采集日期。"
    "请确保材料来源和事实属性记录准确，不要将未经核实的内容当作真实调研结论。"
)

_MAX_CLAIM_LENGTH = 500
_MAX_EVIDENCE_CARDS_PER_MATERIAL = 40
_EVIDENCE_CARD_TARGET_CHARS = 720


@dataclass(frozen=True)
class StoredClaimResult:
    """Returned by claim-checking helpers so the UI can navigate to the row."""

    claim_id: int
    evaluation: ClaimEvaluation
    diagnostic: dict[str, Any]


@dataclass(frozen=True)
class EvidenceReviewResult:
    """Evidence update plus the claims refreshed against the new evidence set."""

    evidence_card: dict[str, Any]
    rechecked_claim_ids: tuple[int, ...]
    review_event_id: int | None


def _status_value(value: Any) -> str:
    return getattr(value, "value", value) if value is not None else ""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_utf8(path: Path, content: str) -> None:
    # ``newline=""`` keeps line endings exactly as written so the on-disk raw
    # file always matches the SHA-256 computed from the original string.
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _model_card_drafts(
    material_id: int,
    segments: Sequence[Mapping[str, Any]],
    advice: Any,
) -> list[EvidenceDraft]:
    """Turn model-selected segment ids back into exact persisted quotes."""

    by_id = {int(segment["id"]): segment for segment in segments}
    drafts: list[EvidenceDraft] = []
    for card in advice.cards:
        selected = [by_id[segment_id] for segment_id in card.segment_ids]
        quote = " ".join(
            str(segment.get("redacted_text") or "").strip()
            for segment in selected
        ).strip()
        if not quote:
            continue
        locators = [str(segment.get("locator") or "") for segment in selected]
        first_locator = locators[0]
        last_locator = locators[-1]
        source_locator = (
            first_locator
            if first_locator == last_locator
            else f"{first_locator}–{last_locator}"
        )
        drafts.append(
            EvidenceDraft(
                material_id=int(material_id),
                segment_id=int(card.segment_ids[0]),
                evidence_type=EvidenceType(card.evidence_type),
                title=card.title,
                quote=quote,
                summary=card.summary,
                source_locator=source_locator,
            )
        )
    return drafts


def _storage_dirs(db: Any) -> tuple[Path, Path]:
    db_dir = Path(getattr(db, "path", Path("data"))).resolve().parent
    return db_dir / "raw", db_dir / "redacted"


def import_text_material(
    db: Any,
    project_id: int,
    text: str,
    *,
    original_filename: str,
    source_role: str,
    context: str,
    captured_at: str | None,
    consent_status: str | ConsentStatus,
    custom_sensitive_terms: list[str] | None,
    is_fictional: bool,
) -> MaterialImportResult:
    """Persist one text material and draft evidence cards when authorized.

    Steps mirror the MVP spec: validate input, save the original file, compute
    its SHA-256, redact locally, save the redacted copy, split into segments,
    and only then draft evidence cards for ``confirmed`` consent.
    """

    if not isinstance(text, str) or not text.strip():
        raise ValueError("材料正文不能为空。")
    original_filename = (original_filename or "").strip()
    if not original_filename:
        raise ValueError("材料名称不能为空，便于后续追溯来源。")

    consent = _status_value(consent_status)
    if consent not in {item.value for item in ConsentStatus}:
        raise ValueError(f"未知的授权状态：{consent!r}")

    raw_dir, redacted_dir = _storage_dirs(db)
    raw_dir.mkdir(parents=True, exist_ok=True)
    redacted_dir.mkdir(parents=True, exist_ok=True)

    material_id = db.create_material(
        project_id,
        "text",
        original_filename=original_filename,
        source_role=(source_role or "").strip(),
        context=(context or "").strip(),
        captured_at=captured_at,
        consent_status=consent,
        processing_status="ready",
        is_fictional=bool(is_fictional),
        notes=_FICTION_NOTE if is_fictional else "",
    )

    raw_path = raw_dir / f"M{material_id}_raw.txt"
    redacted_path = redacted_dir / f"M{material_id}_redacted.txt"
    _write_utf8(raw_path, text)
    redaction = redact_text(text, custom_terms=custom_sensitive_terms)
    _write_utf8(redacted_path, redaction.redacted_text)
    db.update_material(
        material_id, raw_path=str(raw_path), sha256=_digest(text)
    )

    pii_kinds = sorted({span.kind for span in redaction.spans})
    segments: list[dict[str, Any]] = []
    used_segment_fallback = False
    for chunk in split_text(redaction.redacted_text):
        segment_id = db.create_segment(
            material_id,
            chunk.sequence_no,
            chunk.text,
            locator=chunk.locator,
            pii_flags=pii_kinds,
        )
        segments.append(
            {"id": segment_id, "redacted_text": chunk.text, "locator": chunk.locator}
        )

    # A non-empty material should never silently finish with no segment.  This
    # protects imports whose extracted text contains unusual separators or
    # invisible characters that defeat the normal sentence splitter.
    if not segments and redaction.redacted_text.strip():
        used_segment_fallback = True
        segment_id = db.create_segment(
            material_id,
            1,
            redaction.redacted_text.strip(),
            locator="材料全文",
            pii_flags=pii_kinds,
        )
        segments.append(
            {
                "id": segment_id,
                "redacted_text": redaction.redacted_text.strip(),
                "locator": "材料全文",
            }
        )

    warnings: list[str] = []
    if used_segment_fallback:
        warnings.append(
            "正常分段没有产生片段，已使用脱敏材料全文作为兜底卡输入，请人工核对。"
        )
    if pii_kinds:
        warnings.append(
            "检测到敏感信息（手机号、身份证号、邮箱或自定义词），"
            "已替换为占位符，请核对脱敏文本。"
        )
    if consent != ConsentStatus.CONFIRMED.value:
        warnings.append("材料已保存，但在授权确认前不会生成可引用证据卡。")

    evidence_card_ids: list[int] = []
    if consent == ConsentStatus.CONFIRMED.value:
        drafts: list[EvidenceDraft] | None = None
        used_semantic_cards = False
        if llm_settings.configured:
            try:
                advice = request_evidence_card_generation(
                    segments,
                    consent_status=consent,
                    source_role=source_role,
                    context=context,
                    max_cards=_MAX_EVIDENCE_CARDS_PER_MATERIAL,
                )
                drafts = _model_card_drafts(material_id, segments, advice)
                used_semantic_cards = bool(drafts)
                db.create_agent_run(
                    project_id,
                    "llm_evidence_card_generation",
                    status="completed",
                    input_data={
                        "material_id": material_id,
                        "segment_count": len(segments),
                    },
                    output_data=advice.as_dict(),
                )
                if not drafts:
                    warnings.append(
                        "材料已完成语义整理，但没有抽取出明确事实，已使用本地规则生成兜底审核卡。"
                    )
            except (LLMError, ValueError, KeyError) as exc:
                db.create_agent_run(
                    project_id,
                    "llm_evidence_card_generation",
                    status="failed",
                    input_data={
                        "material_id": material_id,
                        "segment_count": len(segments),
                    },
                    error_message=str(exc),
                )
                warnings.append(
                    "语义整理未完成，已使用本地规则生成审核卡，请人工核对内容边界。"
                )

        if drafts is None or not drafts:
            drafts = generate_evidence_drafts(
                material_id,
                segments,
                source_role,
                max_cards=_MAX_EVIDENCE_CARDS_PER_MATERIAL,
                target_chars=_EVIDENCE_CARD_TARGET_CHARS,
            )
        if len(drafts) < len(segments):
            generation_action = (
                "语义整理生成" if used_semantic_cards else "合并生成"
            )
            warnings.append(
                f"正文已保存为 {len(segments)} 个可追溯片段，并{generation_action} "
                f"{len(drafts)} 张审核卡，避免长材料产生过多重复审核项。"
            )
        if not drafts:
            # Last-resort full-text card: preserving one reviewable card is
            # safer than reporting a successful import with zero cards.
            fallback_segment_id = db.create_segment(
                material_id,
                len(segments) + 1,
                redaction.redacted_text.strip(),
                locator="材料全文（兜底）",
                pii_flags=pii_kinds,
            )
            fallback_segment = {
                "id": fallback_segment_id,
                "redacted_text": redaction.redacted_text.strip(),
                "locator": "材料全文（兜底）",
            }
            drafts = generate_evidence_drafts(
                material_id,
                [fallback_segment],
                source_role,
                max_cards=1,
                target_chars=max(_EVIDENCE_CARD_TARGET_CHARS, 720),
            )
            warnings.append(
                "正常分段没有生成审核卡，系统已使用脱敏材料全文生成 1 张兜底卡，"
                "请重点人工核对其来源和内容边界。"
            )
        for draft in drafts:
            card_id = db.create_evidence_card(
                project_id,
                draft.segment_id,
                draft.evidence_type,
                draft.title,
                draft.quote,
                draft.summary,
                source_locator=draft.source_locator,
                review_status="draft",
            )
            evidence_card_ids.append(card_id)

    return MaterialImportResult(
        material_id=material_id,
        redacted_text=redaction.redacted_text,
        evidence_card_ids=evidence_card_ids,
        warnings=warnings,
    )


def _load_approved_candidates(
    db: Any,
    project_id: int,
    evidence_rows: list[dict[str, Any]] | None = None,
) -> list[EvidenceCandidate]:
    """Return evidence that is both manually approved and authorized."""

    rows = evidence_rows
    if rows is None:
        rows = db.list_evidence_cards(project_id, review_status="approved")
    return [
        evidence_candidate_from_mapping(row)
        for row in rows
        if _status_value(row.get("review_status")) == "approved"
        if _status_value(row.get("consent_status")) == ConsentStatus.CONFIRMED.value
    ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _find_claim_by_text(
    db: Any, project_id: int, claim_text: str
) -> dict[str, Any] | None:
    return next(
        (
            claim
            for claim in db.list_claims(project_id)
            if claim.get("claim_text") == claim_text
        ),
        None,
    )


def _replace_claim_links(
    db: Any,
    claim_id: int,
    evaluation: ClaimEvaluation,
    relation_rationales: Mapping[int, str] | None = None,
) -> None:
    """Rebuild support/contradict/context links from the latest evaluation."""
    for link in db.list_claim_evidence_links(claim_id):
        db.unlink_claim_evidence(claim_id, int(link["evidence_card_id"]))
    relations = (
        ("support", evaluation.supporting_evidence_ids),
        ("contradict", evaluation.contradicting_evidence_ids),
        ("context", evaluation.context_evidence_ids),
    )
    for relation, evidence_ids in relations:
        for evidence_id in evidence_ids:
            db.link_claim_evidence(
                claim_id,
                int(evidence_id),
                relation,
                rationale=(relation_rationales or {}).get(
                    int(evidence_id), _LINK_RATIONALES[relation]
                ),
                review_status="approved",
            )


_LINK_RATIONALES = {
    "support": "规则核验判定该材料直接支持结论核心表述。",
    "contradict": "规则核验判定该材料与结论表述方向相反。",
    "context": "规则核验将其作为背景材料，未用于直接证明或反驳。",
}


def _task_title(missing_item: str) -> str:
    title = f"补齐：{missing_item}"
    return title if len(title) <= 60 else title[:59] + "…"


def _sync_followup_tasks(
    db: Any, claim_id: int, missing_evidence: list[str]
) -> list[str]:
    """Keep rule-generated ``补齐：`` tasks aligned with current gaps.

    Manual tasks and cancelled tasks are left untouched.  A completed automatic
    task is reopened when the same evidence gap returns, while an open automatic
    task is completed once that gap is no longer present.
    """

    desired_titles = {_task_title(item) for item in missing_evidence}
    existing_tasks = db.list_followup_tasks(claim_id=claim_id)
    existing_by_title = {
        task["title"]: task
        for task in existing_tasks
        if str(task.get("title", "")).startswith("补齐：")
    }

    for title, task in existing_by_title.items():
        status = _status_value(task.get("status"))
        task_id = int(task["id"])
        changes: dict[str, Any] = {}
        if (
            status != TaskStatus.CANCELLED.value
            and task.get("recommended_action") != _TASK_RECOMMENDATION
        ):
            changes["recommended_action"] = _TASK_RECOMMENDATION
        if title in desired_titles and status == TaskStatus.DONE.value:
            changes.update(
                status=TaskStatus.OPEN.value,
                completion_material_id=None,
            )
        elif title not in desired_titles and status == TaskStatus.OPEN.value:
            changes["status"] = TaskStatus.DONE.value
        if changes:
            db.update_followup_task(task_id, **changes)

    created: list[str] = []
    for item in missing_evidence:
        title = _task_title(item)
        if title in existing_by_title:
            continue
        db.create_followup_task(
            claim_id,
            title,
            recommended_action=_TASK_RECOMMENDATION,
        )
        existing_by_title[title] = {"title": title, "status": TaskStatus.OPEN.value}
        created.append(title)
    return created


def _store_evaluation(
    db: Any,
    project_id: int,
    claim_text: str,
    claim_id: int | None,
    relation_overrides: Mapping[int, str] | None = None,
    relation_rationales: Mapping[int, str] | None = None,
) -> StoredClaimResult:
    evidence_rows = db.list_evidence_cards(project_id)
    material_rows = db.list_materials(project_id)
    candidates = _load_approved_candidates(db, project_id, evidence_rows)
    evaluation = evaluate_claim(
        claim_text,
        candidates,
        max_candidates=8,
        relation_overrides=relation_overrides,
    )
    diagnostic = build_retrieval_diagnostic(
        claim_text,
        evidence_rows,
        material_rows,
        evaluation,
    )

    # Final back-end citation validation: an ID outside this candidate set can
    # never be persisted, even if future relation logic regresses.
    if not validate_citation_ids(
        evaluation, {candidate.id for candidate in candidates}
    ):
        raise RuntimeError("内部校验失败：证据引用包含本次检索集合之外的编号。")

    if claim_id is None:
        existing = _find_claim_by_text(db, project_id, claim_text)
        if existing is not None:
            claim_id = int(existing["id"])

    if claim_id is None:
        claim_id = db.create_claim(
            project_id,
            claim_text,
            verdict=evaluation.verdict.value,
            reason=evaluation.reason,
            safe_rewrite=evaluation.safe_rewrite,
            missing_evidence=evaluation.missing_evidence,
            rule_flags=evaluation.rule_flags,
        )
    else:
        # Both check_and_store_claim (reusing an identical row) and
        # recheck_claim land here so the persisted row always reflects the
        # latest evaluation instead of a stale seeded verdict.
        db.update_claim(
            claim_id,
            verdict=evaluation.verdict.value,
            reason=evaluation.reason,
            safe_rewrite=evaluation.safe_rewrite,
            missing_evidence=evaluation.missing_evidence,
            rule_flags=evaluation.rule_flags,
            checked_at=_now_iso(),
        )

    _replace_claim_links(db, claim_id, evaluation, relation_rationales)
    _sync_followup_tasks(
        db, claim_id, evaluation.missing_evidence
    )
    db.create_agent_run(
        project_id,
        "claim_retrieval",
        claim_id=int(claim_id),
        input_data={"claim_text": claim_text},
        output_data=diagnostic,
    )
    return StoredClaimResult(
        claim_id=int(claim_id),
        evaluation=evaluation,
        diagnostic=diagnostic,
    )


def check_and_store_claim(
    db: Any,
    project_id: int,
    claim_text: str,
) -> StoredClaimResult:
    """Evaluate a claim and persist it, reusing an identical existing row."""
    claim_text = str(claim_text or "").strip()
    if not claim_text:
        raise ValueError("待核验结论不能为空。")
    if len(claim_text) > _MAX_CLAIM_LENGTH:
        raise ValueError(f"结论过长，请控制在 {_MAX_CLAIM_LENGTH} 字以内。")
    return _store_evaluation(db, int(project_id), claim_text, claim_id=None)


def recheck_claim(
    db: Any,
    claim_id: int,
    *,
    relation_overrides: Mapping[int, str] | None = None,
    relation_rationales: Mapping[int, str] | None = None,
) -> StoredClaimResult:
    """Re-evaluate an existing claim against the latest evidence set."""
    claim_id = int(claim_id)
    claim = db.get_claim(claim_id)
    if claim is None:
        raise ValueError(f"结论 {claim_id} 不存在，无法重新核验。")
    return _store_evaluation(
        db,
        int(claim["project_id"]),
        claim["claim_text"],
        claim_id=claim_id,
        relation_overrides=relation_overrides,
        relation_rationales=relation_rationales,
    )


def review_evidence_card(
    db: Any,
    evidence_card_id: int,
    *,
    title: str,
    summary: str,
    evidence_type: str,
    review_status: str,
    change_reason: str,
) -> EvidenceReviewResult:
    """Update one card and refresh every claim affected by the evidence set.

    Claim verdicts are snapshots of the approved evidence available at check
    time.  Approving, withdrawing, or editing an approved card can change
    retrieval order and therefore any claim in the same project, including a
    claim that did not previously cite this card.  The MVP keeps projects small,
    so refreshing the whole project is the safest deterministic behaviour.
    """

    evidence_card_id = int(evidence_card_id)
    current = db.get_evidence_card(evidence_card_id)
    if current is None:
        raise ValueError(f"证据 E{evidence_card_id} 不存在，无法保存审核结果。")

    normalized_title = str(title or "").strip()
    normalized_summary = str(summary or "").strip()
    if not normalized_title or not normalized_summary:
        raise ValueError("证据标题和摘要不能为空。")

    normalized_reason = str(change_reason or "").strip()
    if len(normalized_reason) > 500:
        raise ValueError("证据审核说明不能超过 500 字。")

    changes = {
        "title": normalized_title,
        "summary": normalized_summary,
        "evidence_type": _status_value(evidence_type),
        "review_status": _status_value(review_status),
    }
    evidence_fields_changed = any(
        _status_value(current.get(field)) != value
        for field, value in changes.items()
    )
    old_status = _status_value(current.get("review_status"))
    new_status = changes["review_status"]

    if not evidence_fields_changed:
        return EvidenceReviewResult(
            evidence_card=current,
            rechecked_claim_ids=(),
            review_event_id=None,
        )
    before_snapshot = {
        field: _status_value(current.get(field))
        for field in changes
    }

    updated = db.update_evidence_card(evidence_card_id, **changes)
    if updated is None:
        raise RuntimeError(f"证据 E{evidence_card_id} 保存失败。")

    rechecked_claim_ids: list[int] = []
    if evidence_fields_changed and "approved" in {old_status, new_status}:
        project_id = int(updated["project_id"])
        for claim in db.list_claims(project_id):
            claim_id = int(claim["id"])
            recheck_claim(db, claim_id)
            rechecked_claim_ids.append(claim_id)

    after_snapshot = {
        field: _status_value(updated.get(field))
        for field in changes
    }
    review_event_id = db.create_evidence_review_event(
        evidence_card_id,
        before=before_snapshot,
        after=after_snapshot,
        change_reason=normalized_reason,
        rechecked_claim_ids=rechecked_claim_ids,
    )

    return EvidenceReviewResult(
        evidence_card=updated,
        rechecked_claim_ids=tuple(rechecked_claim_ids),
        review_event_id=review_event_id,
    )


def review_evidence_cards(
    db: Any,
    updates: Sequence[Mapping[str, Any]],
) -> tuple[EvidenceReviewResult, ...]:
    """Apply several card reviews and refresh project claims only once.

    The single-card API remains the detailed path.  This bulk path is used by
    manual and model-assisted batch review so each provider result is persisted
    while SQLite claim recalculation happens at most once for the whole batch.
    """

    if not updates:
        return ()

    prepared: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    project_id: int | None = None
    for raw_update in updates:
        try:
            evidence_card_id = int(raw_update["evidence_card_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("批量审核缺少有效的证据卡编号。") from exc
        if evidence_card_id in seen_ids:
            raise ValueError(f"批量审核重复包含证据 E{evidence_card_id}。")
        seen_ids.add(evidence_card_id)
        current = db.get_evidence_card(evidence_card_id)
        if current is None:
            raise ValueError(f"证据 E{evidence_card_id} 不存在，无法保存审核结果。")
        current_project_id = int(current["project_id"])
        if project_id is None:
            project_id = current_project_id
        elif current_project_id != project_id:
            raise ValueError("批量审核的证据卡必须属于同一个项目。")

        normalized_title = str(raw_update.get("title") or "").strip()
        normalized_summary = str(raw_update.get("summary") or "").strip()
        if not normalized_title or not normalized_summary:
            raise ValueError(f"证据 E{evidence_card_id} 的标题和摘要不能为空。")
        normalized_reason = str(raw_update.get("change_reason") or "").strip()
        if len(normalized_reason) > 500:
            raise ValueError(f"证据 E{evidence_card_id} 的审核说明不能超过 500 字。")
        changes = {
            "title": normalized_title,
            "summary": normalized_summary,
            "evidence_type": _status_value(
                raw_update.get("evidence_type", "team_analysis")
            ),
            "review_status": _status_value(raw_update.get("review_status")),
        }
        old_status = _status_value(current.get("review_status"))
        if changes["review_status"] not in {item.value for item in ReviewStatus}:
            raise ValueError(f"证据 E{evidence_card_id} 的审核状态无效。")
        changed = any(
            _status_value(current.get(field)) != value
            for field, value in changes.items()
        )
        prepared.append(
            {
                "evidence_card_id": evidence_card_id,
                "current": current,
                "changes": changes,
                "old_status": old_status,
                "changed": changed,
                "change_reason": normalized_reason,
                "before": {
                    field: _status_value(current.get(field)) for field in changes
                },
            }
        )

    assert project_id is not None
    for item in prepared:
        if item["changed"]:
            updated = db.update_evidence_card(
                item["evidence_card_id"], **item["changes"]
            )
            if updated is None:
                raise RuntimeError(
                    f"证据 E{item['evidence_card_id']} 保存失败。"
                )
            item["updated"] = updated
        else:
            item["updated"] = item["current"]

    should_recheck = any(
        item["changed"]
        and "approved" in {item["old_status"], item["changes"]["review_status"]}
        for item in prepared
    )
    rechecked_claim_ids: tuple[int, ...] = ()
    if should_recheck:
        refreshed: list[int] = []
        for claim in db.list_claims(project_id):
            claim_id = int(claim["id"])
            recheck_claim(db, claim_id)
            refreshed.append(claim_id)
        rechecked_claim_ids = tuple(refreshed)

    results: list[EvidenceReviewResult] = []
    for item in prepared:
        updated = item["updated"]
        if not item["changed"]:
            results.append(
                EvidenceReviewResult(
                    evidence_card=updated,
                    rechecked_claim_ids=(),
                    review_event_id=None,
                )
            )
            continue
        after = {
            field: _status_value(updated.get(field))
            for field in item["changes"]
        }
        event_id = db.create_evidence_review_event(
            item["evidence_card_id"],
            before=item["before"],
            after=after,
            change_reason=item["change_reason"],
            rechecked_claim_ids=rechecked_claim_ids,
        )
        results.append(
            EvidenceReviewResult(
                evidence_card=updated,
                rechecked_claim_ids=rechecked_claim_ids,
                review_event_id=event_id,
            )
        )
    return tuple(results)
