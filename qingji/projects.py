"""Project workspace operations shared by the UI and tests."""

from __future__ import annotations

import sqlite3
from typing import Any


MAX_PROJECT_NAME_LENGTH = 80
MAX_PROJECT_DESCRIPTION_LENGTH = 500
_PROJECT_SCOPED_SESSION_KEYS = (
    "active_claim_id",
    "claim_draft",
    "last_import_result",
    "material_draft_text",
)


def create_project_workspace(
    db: Any,
    name: str,
    description: str = "",
) -> int:
    """Validate and create a user project without seeding demo content."""

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
    if db.get_project_by_name(normalized_name) is not None:
        raise ValueError("已存在同名项目，请直接切换或使用其他名称。")

    try:
        return int(db.create_project(normalized_name, normalized_description))
    except sqlite3.IntegrityError as exc:
        raise ValueError("已存在同名项目，请使用其他名称。") from exc


def activate_project(session_state: Any, project_id: int) -> None:
    """Switch project and clear UI state that must not cross workspaces."""

    normalized_id = int(project_id)
    if normalized_id <= 0:
        raise ValueError("项目编号必须为正整数。")
    session_state["qingji_project_id"] = normalized_id
    for key in _PROJECT_SCOPED_SESSION_KEYS:
        session_state.pop(key, None)
