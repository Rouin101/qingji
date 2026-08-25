"""Project workspace operations shared by the UI and tests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .demo import DEMO_PROJECT_NAME


MAX_PROJECT_NAME_LENGTH = 80
MAX_PROJECT_DESCRIPTION_LENGTH = 500
_PROJECT_SCOPED_SESSION_KEYS = (
    "active_claim_id",
    "claim_draft",
    "last_import_result",
    "material_draft_text",
    "project_backup_payload",
    "project_backup_filename",
    "project_backup_source_id",
)


@dataclass(frozen=True)
class ProjectDeletionResult:
    """Summary of a permanent project deletion and local-file cleanup."""

    project_id: int
    removed_files: int
    warnings: tuple[str, ...] = ()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalized_project_fields(name: str, description: str) -> tuple[str, str]:
    normalized_name = (name or "").strip()
    normalized_description = (description or "").strip()

    if not normalized_name:
        raise ValueError("项目名称不能为空。")
    if len(normalized_name) > MAX_PROJECT_NAME_LENGTH:
        raise ValueError(f"项目名称不能超过 {MAX_PROJECT_NAME_LENGTH} 个字符。")
    if len(normalized_description) > MAX_PROJECT_DESCRIPTION_LENGTH:
        raise ValueError(
            f"项目说明不能超过 {MAX_PROJECT_DESCRIPTION_LENGTH} 个字符。"
        )
    return normalized_name, normalized_description


def _require_user_project(db: Any, project_id: int) -> dict[str, Any]:
    project = db.get_project(int(project_id))
    if project is None:
        raise ValueError("项目不存在或已被删除。")
    if project.get("name") == DEMO_PROJECT_NAME:
        raise ValueError("内置项目不能重命名、归档或删除。")
    return project


def create_project_workspace(
    db: Any,
    name: str,
    description: str = "",
) -> int:
    """Validate and create a user project without seeding demo content."""

    normalized_name, normalized_description = _normalized_project_fields(
        name, description
    )
    if db.get_project_by_name(normalized_name) is not None:
        raise ValueError("已存在同名项目，请直接切换或使用其他名称。")

    try:
        return int(db.create_project(normalized_name, normalized_description))
    except sqlite3.IntegrityError as exc:
        raise ValueError("已存在同名项目，请使用其他名称。") from exc


def rename_project_workspace(
    db: Any,
    project_id: int,
    name: str,
    description: str = "",
) -> dict[str, Any]:
    """Update a user project's display fields with duplicate-name protection."""

    project = _require_user_project(db, project_id)
    normalized_name, normalized_description = _normalized_project_fields(
        name, description
    )
    duplicate = db.get_project_by_name(normalized_name)
    if duplicate is not None and int(duplicate["id"]) != int(project_id):
        raise ValueError("已存在同名项目，请使用其他名称。")
    try:
        updated = db.update_project(
            int(project_id),
            name=normalized_name,
            description=normalized_description,
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("已存在同名项目，请使用其他名称。") from exc
    if updated is None:
        raise ValueError("项目不存在或已被删除。")
    return updated


def archive_project_workspace(db: Any, project_id: int) -> dict[str, Any]:
    """Archive a user project so it leaves the active workspace selector."""

    project = _require_user_project(db, project_id)
    if project.get("archived_at"):
        raise ValueError("项目已经归档。")
    updated = db.update_project(int(project_id), archived_at=_utc_now())
    if updated is None:
        raise ValueError("项目不存在或已被删除。")
    return updated


def restore_project_workspace(db: Any, project_id: int) -> dict[str, Any]:
    """Restore an archived user project to the active workspace list."""

    project = _require_user_project(db, project_id)
    if not project.get("archived_at"):
        raise ValueError("项目当前未归档。")
    updated = db.update_project(int(project_id), archived_at=None)
    if updated is None:
        raise ValueError("项目不存在或已被删除。")
    return updated


def delete_project_workspace(
    db: Any,
    project_id: int,
) -> ProjectDeletionResult:
    """Permanently delete an archived project.

    Database rows are removed with SQLite cascades. Material files are only
    unlinked when their resolved path matches Qingji's own per-material naming
    convention inside the database-adjacent ``raw``/``redacted`` directories.
    """

    project = _require_user_project(db, project_id)
    if not project.get("archived_at"):
        raise ValueError("请先归档项目，再执行永久删除。")

    materials = db.list_materials(int(project_id))
    db_dir = Path(db.path).resolve().parent
    raw_dir = (db_dir / "raw").resolve()
    redacted_dir = (db_dir / "redacted").resolve()
    removable: list[Path] = []
    for material in materials:
        material_id = int(material["id"])
        candidates = (
            (raw_dir / f"M{material_id}_raw.txt", raw_dir),
            (redacted_dir / f"M{material_id}_redacted.txt", redacted_dir),
        )
        for candidate, expected_parent in candidates:
            resolved = candidate.resolve()
            if resolved.parent == expected_parent and resolved.is_file():
                removable.append(resolved)

    if not db.delete_project(int(project_id)):
        raise ValueError("项目不存在或已被删除。")

    removed_files = 0
    warnings: list[str] = []
    for path in removable:
        try:
            path.unlink()
        except OSError:
            warnings.append(f"未能移除本地材料文件：{path.name}")
        else:
            removed_files += 1
    return ProjectDeletionResult(
        project_id=int(project_id),
        removed_files=removed_files,
        warnings=tuple(warnings),
    )


def activate_project(session_state: Any, project_id: int) -> None:
    """Switch project and clear UI state that must not cross workspaces."""

    normalized_id = int(project_id)
    if normalized_id <= 0:
        raise ValueError("项目编号必须为正整数。")
    session_state["qingji_project_id"] = normalized_id
    for key in _PROJECT_SCOPED_SESSION_KEYS:
        session_state.pop(key, None)
