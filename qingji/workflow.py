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
from typing import Any

from .claims import evaluate_claim, validate_citation_ids
from .evidence import generate_evidence_drafts, split_text
from .models import (
    ClaimEvaluation,
    ConsentStatus,
    EvidenceCandidate,
    EvidenceType,
    MaterialImportResult,
    ReviewStatus,
    TaskStatus,
)
from .privacy import redact_text

#: Local text for materials imported through the UI.  The page blocks real data,
#: so every workflow import is expected to be explicitly fictional test data.
_FICTION_NOTE = "虚构测试数据：用户导入，仅用于青迹功能演示，不对应真实个人或调研结论。"

_TASK_RECOMMENDATION = (
    "优先补充已获得记录与使用授权的虚构测试材料，"
    "并明确其来源角色、采集场景与采集日期。"
)

_MAX_CLAIM_LENGTH = 500


@dataclass(frozen=True)
class StoredClaimResult:
    """Returned by claim-checking helpers so the UI can navigate to the row."""

    claim_id: int
    evaluation: ClaimEvaluation


def _status_value(value: Any) -> str:
    return getattr(value, "value", value) if value is not None else ""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_utf8(path: Path, content: str) -> None:
    # ``newline=""`` keeps line endings exactly as written so the on-disk raw
    # file always matches the SHA-256 computed from the original string.
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


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

    warnings: list[str] = []
    if pii_kinds:
        warnings.append(
            "检测到敏感信息（手机号、身份证号、邮箱或自定义词），"
            "已替换为占位符，请核对脱敏文本。"
        )
    if consent != ConsentStatus.CONFIRMED.value:
        warnings.append("材料已保存，但在授权确认前不会生成可引用证据卡。")

    evidence_card_ids: list[int] = []
    if consent == ConsentStatus.CONFIRMED.value:
        for draft in generate_evidence_drafts(
            material_id, segments, source_role
        ):
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


def _row_to_candidate(row: dict[str, Any]) -> EvidenceCandidate:
    return EvidenceCandidate(
        id=int(row["id"]),
        material_id=int(row["material_id"]),
        segment_id=int(row["segment_id"]),
        title=row.get("title", ""),
        quote=row.get("quote", ""),
        summary=row.get("summary", ""),
        evidence_type=EvidenceType(row["evidence_type"])
        if row.get("evidence_type")
        else EvidenceType.TEAM_ANALYSIS,
        source_role=row.get("source_role", ""),
        context=row.get("context", ""),
        source_locator=row.get("source_locator") or row.get("segment_locator") or "",
        review_status=ReviewStatus(row["review_status"])
        if row.get("review_status")
        else ReviewStatus.DRAFT,
        consent_status=ConsentStatus(row["consent_status"])
        if row.get("consent_status")
        else ConsentStatus.UNKNOWN,
    )


def _load_approved_candidates(db: Any, project_id: int) -> list[EvidenceCandidate]:
    """Return evidence that is both manually approved and authorized."""
    return [
        _row_to_candidate(row)
        for row in db.list_evidence_cards(project_id, review_status="approved")
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


def _replace_claim_links(db: Any, claim_id: int, evaluation: ClaimEvaluation) -> None:
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
                rationale=_LINK_RATIONALES[relation],
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


def _create_idempotent_followup_tasks(
    db: Any, claim_id: int, missing_evidence: list[str]
) -> list[str]:
    """Create one open task per missing item, never reopening finished ones."""
    existing_titles = {
        task["title"]
        for task in db.list_followup_tasks(claim_id=claim_id)
        if _status_value(task.get("status")) != TaskStatus.CANCELLED.value
    }
    created: list[str] = []
    for item in missing_evidence:
        title = _task_title(item)
        if title in existing_titles:
            continue
        db.create_followup_task(
            claim_id,
            title,
            recommended_action=_TASK_RECOMMENDATION,
        )
        existing_titles.add(title)
        created.append(title)
    return created


def _store_evaluation(
    db: Any,
    project_id: int,
    claim_text: str,
    claim_id: int | None,
) -> StoredClaimResult:
    candidates = _load_approved_candidates(db, project_id)
    evaluation = evaluate_claim(claim_text, candidates, max_candidates=8)

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

    _replace_claim_links(db, claim_id, evaluation)
    _create_idempotent_followup_tasks(
        db, claim_id, evaluation.missing_evidence
    )
    return StoredClaimResult(claim_id=int(claim_id), evaluation=evaluation)


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


def recheck_claim(db: Any, claim_id: int) -> StoredClaimResult:
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
    )
