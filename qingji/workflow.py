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
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from .claims import evaluate_claim, validate_citation_ids
from .config import llm_settings
from .diagnostics import build_retrieval_diagnostic
from .evidence import split_text
from .llm import (
    LLMError,
    request_claim_evidence_review,
    request_evidence_assistance,
    request_evidence_card_generation,
)
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


@dataclass(frozen=True)
class EvidenceRegenerationResult:
    source_evidence_card_id: int
    replacement_evidence_card_id: int
    rejection_reason: str


@dataclass(frozen=True)
class MaterialEvidenceRegenerationResult:
    material_id: int
    source_evidence_card_ids: tuple[int, ...]
    replacement_evidence_card_ids: tuple[int, ...]
    rejection_reasons: tuple[str, ...]


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


def _model_generation_candidates(
    material_id: int,
    segments: Sequence[Mapping[str, Any]],
    source_role: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the original redacted segments as the model's card boundary.

    Evidence cards must be chosen by the model from persisted source segments.
    Local code may split and store text for traceability, but it must never
    merge text into a candidate card or supply a final card boundary.  The LLM
    request function batches these source segments within its own context limit.
    """

    del material_id, source_role
    copied = [dict(segment) for segment in segments]
    return copied, copied


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
    progress_callback: Callable[[str], None] | None = None,
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

    if progress_callback is not None:
        progress_callback("正在本地检查隐私信息……")

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
            "正常分段没有产生片段，已将脱敏材料全文交由模型重新提取可审核事实。"
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
        drafts: list[EvidenceDraft] = []
        if llm_settings.configured:
            try:
                if progress_callback is not None:
                    progress_callback("隐私检查已完成，正在整理脱敏材料并生成证据卡……")
                model_segments, full_card_segments = _model_generation_candidates(
                    material_id, segments, source_role
                )
                advice = request_evidence_card_generation(
                    model_segments,
                    consent_status=consent,
                    source_role=source_role,
                    context=context,
                    max_cards=_MAX_EVIDENCE_CARDS_PER_MATERIAL,
                    progress_callback=(
                        lambda completed, total: progress_callback(
                            f"已完成脱敏，正在生成证据卡（第 {completed}/{total} 批）。"
                        )
                        if progress_callback is not None
                        else None
                    ),
                )
                drafts = _model_card_drafts(material_id, full_card_segments, advice)
                discarded_card_count = int(
                    getattr(advice, "discarded_card_count", 0) or 0
                )
                if discarded_card_count:
                    warnings.append(
                        f"语义整理跳过 {discarded_card_count} 张重复引用片段的卡片，"
                        f"保留 {len(advice.cards)} 张有效语义卡；"
                        "未覆盖片段不会使用本地规则补卡。"
                    )
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
                        "材料已完成语义整理，但没有抽取出可独立复核的明确事实，"
                        "因此未生成证据卡。"
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
                    "语义整理未完成，本次不会使用本地规则生成证据卡。"
                    "请检查模型服务后重新导入或重新整理材料。"
                )
        else:
            warnings.append(
                "尚未配置可用的大模型，本次不会使用本地规则生成证据卡。"
            )
        if drafts and len(drafts) < len(segments):
            warnings.append(
                f"正文已保存为 {len(segments)} 个可追溯片段，并由模型生成 "
                f"{len(drafts)} 张审核卡。"
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


def _semantic_relation_overrides(
    claim_text: str,
    evidence_rows: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[int, str] | None, Mapping[int, str] | None, Any | None, str]:
    """Ask the configured model for conservative semantic evidence links.

    The model decides only the relation of an already approved, consent-confirmed
    card to the claim.  Citation eligibility and the final four-level verdict
    remain local checks.  Returning an error string instead of raising keeps a
    claim check available when the optional provider is temporarily unavailable.
    """

    if not llm_settings.configured:
        return None, None, None, ""
    try:
        advice = request_claim_evidence_review(
            claim_text,
            evidence_rows,
            config=llm_settings,
        )
    except LLMError as exc:
        return None, None, None, str(exc)

    overrides = {
        int(item.evidence_id): item.relation for item in advice.reviews
    }
    rationales = {
        int(item.evidence_id): (
            "语义判断："
            + (item.rationale or "该卡片与结论的完整语义未形成直接蕴含或冲突。")
        )
        for item in advice.reviews
    }
    return overrides, rationales, advice, ""


def _usable_semantic_rewrite(rewrite: str, claim_text: str) -> str:
    """Keep only a model rewrite that materially changes the original claim."""

    candidate = str(rewrite or "").strip()
    original = str(claim_text or "").strip()
    if not candidate:
        return ""
    normalize = lambda value: value.rstrip("。！？!?；; ").replace(" ", "")
    return "" if normalize(candidate) == normalize(original) else candidate


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
    semantic_advice = None
    semantic_error = ""
    effective_overrides = relation_overrides
    effective_rationales = relation_rationales
    # Explicit overrides are retained for audited/manual corrections.  Otherwise
    # use complete-semantic judgement whenever a model is configured, and fall
    # back to local lexical rules only if that optional call cannot complete.
    if relation_overrides is None and candidates:
        (
            effective_overrides,
            effective_rationales,
            semantic_advice,
            semantic_error,
        ) = _semantic_relation_overrides(claim_text, evidence_rows)
    evaluation = evaluate_claim(
        claim_text,
        candidates,
        max_candidates=8,
        relation_overrides=effective_overrides,
    )
    if semantic_advice is not None:
        semantic_rewrite = _usable_semantic_rewrite(
            semantic_advice.safe_rewrite, claim_text
        )
        if semantic_rewrite:
            evaluation = replace(evaluation, safe_rewrite=semantic_rewrite)
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

    _replace_claim_links(db, claim_id, evaluation, effective_rationales)
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
    if semantic_advice is not None:
        db.create_agent_run(
            project_id,
            "llm_claim_evidence_review",
            claim_id=int(claim_id),
            input_data={
                "claim_text": claim_text,
                "candidate_count": len(candidates),
                "mode": "automatic_semantic_entailment",
            },
            output_data=semantic_advice.as_dict(),
        )
    elif semantic_error:
        db.create_agent_run(
            project_id,
            "llm_claim_evidence_review",
            claim_id=int(claim_id),
            status="failed",
            input_data={
                "claim_text": claim_text,
                "candidate_count": len(candidates),
                "mode": "automatic_semantic_entailment",
            },
            error_message=semantic_error[:500],
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


def recheck_project_claims(
    db: Any, project_id: int
) -> tuple[StoredClaimResult, ...]:
    """Recheck every saved claim in one project against its latest evidence."""

    return tuple(
        recheck_claim(db, int(claim["id"]))
        for claim in db.list_claims(int(project_id))
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


def regenerate_rejected_evidence_card(
    db: Any, evidence_card_id: int
) -> EvidenceRegenerationResult:
    """Create one new draft from a rejected card and its recorded reason."""

    current = db.get_evidence_card(int(evidence_card_id))
    if current is None:
        raise ValueError(f"证据 E{evidence_card_id} 不存在。")
    if _status_value(current.get("review_status")) != ReviewStatus.REJECTED.value:
        raise ValueError("只有已拒绝的证据卡可以根据审核理由重新生成。")
    if _status_value(current.get("consent_status")) != ConsentStatus.CONFIRMED.value:
        raise ValueError("未确认授权的证据卡不能请求模型重新生成。")

    events = db.list_evidence_review_events(
        int(current["project_id"]), evidence_card_id=int(evidence_card_id), limit=100
    )
    if any(str(event.get("change_reason") or "").startswith("已根据拒绝理由生成替代卡") for event in events):
        raise ValueError("该拒绝卡已经生成过替代卡，请先审核替代卡。")
    rejection_event = next(
        (
            event
            for event in events
            if (event.get("after") or {}).get("review_status")
            == ReviewStatus.REJECTED.value
        ),
        None,
    )
    rejection_reason = str(
        (rejection_event or {}).get("change_reason")
        or "模型未提供具体拒绝理由，请收紧表述并保持原文边界。"
    ).strip()
    advice = request_evidence_assistance(
        current, review_feedback=rejection_reason
    )
    replacement_id = db.create_evidence_card(
        int(current["project_id"]),
        int(current["segment_id"]),
        advice.evidence_type,
        advice.title,
        str(current.get("quote") or "").strip(),
        advice.summary,
        source_locator=(
            f"{str(current.get('source_locator') or '').strip()} · "
            f"根据 E{evidence_card_id} 的拒绝理由重新生成"
        ).strip(" ·"),
        review_status=ReviewStatus.DRAFT.value,
    )
    db.create_evidence_review_event(
        int(evidence_card_id),
        before={"review_status": ReviewStatus.REJECTED.value},
        after={"review_status": ReviewStatus.REJECTED.value},
        change_reason=f"已根据拒绝理由生成替代卡 E{replacement_id}。",
    )
    return EvidenceRegenerationResult(
        source_evidence_card_id=int(evidence_card_id),
        replacement_evidence_card_id=replacement_id,
        rejection_reason=rejection_reason,
    )


def list_regenerable_rejected_evidence_cards(
    db: Any, project_id: int
) -> tuple[dict[str, Any], ...]:
    """Return rejected, authorized cards that do not yet have a replacement."""

    rejected_cards = db.list_evidence_cards(
        int(project_id), review_status=ReviewStatus.REJECTED.value
    )
    review_events = db.list_evidence_review_events(int(project_id), limit=500)
    regenerated_source_ids = {
        int(event["evidence_card_id"])
        for event in review_events
        if str(event.get("change_reason") or "").startswith(
            "已根据拒绝理由生成"
        )
    }
    return tuple(
        card
        for card in rejected_cards
        if _status_value(card.get("consent_status")) == ConsentStatus.CONFIRMED.value
        and int(card["id"]) not in regenerated_source_ids
    )


def regenerate_rejected_material_evidence_cards(
    db: Any, project_id: int
) -> tuple[MaterialEvidenceRegenerationResult, ...]:
    """Re-extract replacement cards from each rejected material with the model.

    Reusing a rejected card's quote only changes its label, not its evidence
    boundary.  This routine instead returns to the persisted redacted source
    segments and asks the model to extract new, reviewable facts while taking
    every recorded rejection reason for that material into account.
    """

    candidates = list_regenerable_rejected_evidence_cards(db, project_id)
    cards_by_material: dict[int, list[dict[str, Any]]] = {}
    for card in candidates:
        cards_by_material.setdefault(int(card["material_id"]), []).append(card)

    results: list[MaterialEvidenceRegenerationResult] = []
    for material_id, cards in cards_by_material.items():
        material = db.get_material(material_id)
        if material is None:
            raise ValueError(f"材料 M{material_id} 不存在。")
        if _status_value(material.get("consent_status")) != ConsentStatus.CONFIRMED.value:
            raise ValueError(f"材料 M{material_id} 尚未确认授权。")
        segments = db.list_segments(material_id)
        if not segments:
            raise ValueError(f"材料 M{material_id} 没有可供重新整理的脱敏片段。")

        source_card_ids = tuple(int(card["id"]) for card in cards)
        rejection_reasons: list[str] = []
        for card_id in source_card_ids:
            events = db.list_evidence_review_events(
                int(project_id), evidence_card_id=card_id, limit=100
            )
            rejection_event = next(
                (
                    event
                    for event in events
                    if (event.get("after") or {}).get("review_status")
                    == ReviewStatus.REJECTED.value
                ),
                None,
            )
            reason = str((rejection_event or {}).get("change_reason") or "").strip()
            if reason:
                rejection_reasons.append(reason)
        if not rejection_reasons:
            rejection_reasons.append("原卡未通过审核，请只保留可独立复核的明确事实。")

        model_segments, full_card_segments = _model_generation_candidates(
            material_id, segments, str(material.get("source_role") or "")
        )
        advice = request_evidence_card_generation(
            model_segments,
            consent_status=material.get("consent_status"),
            source_role=str(material.get("source_role") or ""),
            context=str(material.get("context") or ""),
            review_feedback=rejection_reasons,
            max_cards=_MAX_EVIDENCE_CARDS_PER_MATERIAL,
        )
        drafts = _model_card_drafts(material_id, full_card_segments, advice)
        if not drafts:
            raise ValueError(
                f"材料 M{material_id} 中没有可独立复核的事实，未生成替代卡。"
            )

        replacement_ids: list[int] = []
        for draft in drafts:
            replacement_ids.append(
                db.create_evidence_card(
                    int(project_id),
                    draft.segment_id,
                    draft.evidence_type,
                    draft.title,
                    draft.quote,
                    draft.summary,
                    source_locator=(
                        f"{draft.source_locator} · 根据被拒绝卡片的理由重新整理"
                    ).strip(" ·"),
                    review_status=ReviewStatus.DRAFT.value,
                )
            )
        replacement_text = "、".join(f"E{item}" for item in replacement_ids)
        for card_id in source_card_ids:
            db.create_evidence_review_event(
                card_id,
                before={"review_status": ReviewStatus.REJECTED.value},
                after={"review_status": ReviewStatus.REJECTED.value},
                change_reason=(
                    "已根据拒绝理由生成材料级替代卡 " + replacement_text + "。"
                ),
            )
        results.append(
            MaterialEvidenceRegenerationResult(
                material_id=material_id,
                source_evidence_card_ids=source_card_ids,
                replacement_evidence_card_ids=tuple(replacement_ids),
                rejection_reasons=tuple(dict.fromkeys(rejection_reasons)),
            )
        )
    return tuple(results)


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
