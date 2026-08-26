"""Portable, validated project backups for Qingji.

The package deliberately contains one project only. Database identifiers are
treated as source identifiers and remapped during restore so an imported
project can never overwrite rows that already exist in the local database.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .projects import _normalized_project_fields


BACKUP_FORMAT = "qingji-project-backup"
BACKUP_FORMAT_VERSION = 1
MAX_BACKUP_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_BACKUP_MEMBERS = 1000
_MANIFEST_PATH = "manifest.json"
_PAYLOAD_PATH = "project.json"
_TABLES = (
    "materials",
    "segments",
    "evidence_cards",
    "evidence_review_events",
    "claims",
    "claim_evidence_links",
    "claim_candidates",
    "followup_tasks",
    "agent_runs",
)


@dataclass(frozen=True)
class ProjectBackup:
    """A complete in-memory backup ready for a Streamlit download button."""

    filename: str
    content: bytes
    source_project_name: str
    material_file_count: int


@dataclass(frozen=True)
class BackupInspection:
    """Safe package metadata shown before the user confirms a restore."""

    source_project_name: str
    source_project_description: str
    created_at: str
    counts: Mapping[str, int]
    material_file_count: int


@dataclass(frozen=True)
class ProjectRestoreResult:
    """Summary of a successfully restored project."""

    project_id: int
    project_name: str
    restored_rows: Mapping[str, int]
    restored_files: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_filename(project_name: str) -> str:
    normalized = re.sub(r"[\\/:*?\"<>|\s]+", "_", project_name).strip("._")
    return f"青迹_{normalized or '项目'}_备份_v1.zip"


def _rows(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _managed_material_files(
    db: Any, materials: list[dict[str, Any]]
) -> list[tuple[str, bytes, str, int]]:
    db_dir = Path(db.path).resolve().parent
    raw_dir = (db_dir / "raw").resolve()
    redacted_dir = (db_dir / "redacted").resolve()
    collected: list[tuple[str, bytes, str, int]] = []
    collected_size = 0
    for material in materials:
        material_id = int(material["id"])
        raw_value = str(material.get("raw_path") or "").strip()
        candidates = (
            ("raw", raw_dir / f"M{material_id}_raw.txt", raw_dir, bool(raw_value)),
            (
                "redacted",
                redacted_dir / f"M{material_id}_redacted.txt",
                redacted_dir,
                False,
            ),
        )
        if raw_value:
            recorded = Path(raw_value).resolve()
            expected = candidates[0][1].resolve()
            if recorded != expected:
                raise ValueError(
                    f"材料 M{material_id} 的原文不在青迹托管目录内，未生成备份。"
                )
        for kind, candidate, expected_parent, required in candidates:
            resolved = candidate.resolve()
            if resolved.parent != expected_parent:
                raise ValueError("材料文件路径超出青迹数据目录。")
            if not resolved.is_file():
                if required:
                    raise ValueError(f"材料 M{material_id} 的原文文件缺失，未生成备份。")
                continue
            content = resolved.read_bytes()
            collected_size += len(content)
            if collected_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("项目材料文件合计超过 100 MiB，暂不支持页面备份。")
            package_path = f"materials/M{material_id}_{kind}.txt"
            collected.append((package_path, content, kind, material_id))
    return collected


def export_project_backup(db: Any, project_id: int) -> ProjectBackup:
    """Export one project and its managed material files as a checked ZIP."""

    with db.connect() as connection:
        project_row = connection.execute(
            "SELECT * FROM projects WHERE id = ?", (int(project_id),)
        ).fetchone()
        if project_row is None:
            raise ValueError("项目不存在或已被删除。")
        project = dict(project_row)
        data = {
            "project": project,
            "materials": _rows(
                connection,
                "SELECT * FROM materials WHERE project_id = ? ORDER BY id",
                (int(project_id),),
            ),
            "segments": _rows(
                connection,
                "SELECT s.* FROM segments s JOIN materials m ON m.id=s.material_id "
                "WHERE m.project_id=? ORDER BY s.id",
                (int(project_id),),
            ),
            "evidence_cards": _rows(
                connection,
                "SELECT * FROM evidence_cards WHERE project_id=? ORDER BY id",
                (int(project_id),),
            ),
            "evidence_review_events": _rows(
                connection,
                "SELECT * FROM evidence_review_events WHERE project_id=? ORDER BY id",
                (int(project_id),),
            ),
            "claims": _rows(
                connection,
                "SELECT * FROM claims WHERE project_id=? ORDER BY id",
                (int(project_id),),
            ),
            "claim_candidates": _rows(
                connection,
                "SELECT * FROM claim_candidates WHERE project_id=? ORDER BY id",
                (int(project_id),),
            ),
            "claim_evidence_links": _rows(
                connection,
                "SELECT l.* FROM claim_evidence_links l "
                "JOIN claims c ON c.id=l.claim_id WHERE c.project_id=? "
                "ORDER BY l.claim_id,l.evidence_card_id",
                (int(project_id),),
            ),
            "followup_tasks": _rows(
                connection,
                "SELECT t.* FROM followup_tasks t JOIN claims c ON c.id=t.claim_id "
                "WHERE c.project_id=? ORDER BY t.id",
                (int(project_id),),
            ),
            "agent_runs": _rows(
                connection,
                "SELECT * FROM agent_runs WHERE project_id=? ORDER BY id",
                (int(project_id),),
            ),
        }

    material_files = _managed_material_files(db, data["materials"])
    raw_material_ids = {
        material_id
        for _, _, kind, material_id in material_files
        if kind == "raw"
    }
    portable_materials: list[dict[str, Any]] = []
    for material in data["materials"]:
        portable = dict(material)
        material_id = int(material["id"])
        portable["raw_path"] = (
            f"materials/M{material_id}_raw.txt"
            if material_id in raw_material_ids
            else ""
        )
        portable_materials.append(portable)
    data["materials"] = portable_materials
    payload = {
        "format_version": BACKUP_FORMAT_VERSION,
        "project": data["project"],
        "tables": {table: data[table] for table in _TABLES},
    }
    payload_bytes = _json_bytes(payload)
    file_manifest = [
        {
            "path": path,
            "sha256": _digest(content),
            "size": len(content),
            "kind": kind,
            "source_material_id": material_id,
        }
        for path, content, kind, material_id in material_files
    ]
    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": _utc_now(),
        "source_project": {
            "id": int(data["project"]["id"]),
            "name": str(data["project"]["name"]),
            "description": str(data["project"].get("description") or ""),
        },
        "payload": {
            "path": _PAYLOAD_PATH,
            "sha256": _digest(payload_bytes),
            "size": len(payload_bytes),
        },
        "files": file_manifest,
        "counts": {table: len(data[table]) for table in _TABLES},
    }

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_MANIFEST_PATH, _json_bytes(manifest))
        archive.writestr(_PAYLOAD_PATH, payload_bytes)
        for path, content, _, _ in material_files:
            archive.writestr(path, content)
    content = output.getvalue()
    if len(content) > MAX_BACKUP_BYTES:
        raise ValueError("项目备份包超过 50 MiB，暂不支持在页面中导出。")
    return ProjectBackup(
        filename=_safe_filename(str(project["name"])),
        content=content,
        source_project_name=str(project["name"]),
        material_file_count=len(material_files),
    )


def _load_json_member(archive: zipfile.ZipFile, path: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(path).decode("utf-8"))
    except KeyError as exc:
        raise ValueError(f"备份包缺少 {path}。") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"备份包中的 {path} 不是有效 UTF-8 JSON。") from exc
    if not isinstance(value, dict):
        raise ValueError(f"备份包中的 {path} 结构无效。")
    return value


def _json_field(row: Mapping[str, Any], field: str, expected: type) -> Any:
    try:
        value = json.loads(str(row.get(field)))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"备份包中的 {field} 不是有效 JSON。") from exc
    if not isinstance(value, expected):
        raise ValueError(f"备份包中的 {field} 类型无效。")
    return value


def _unique_ids(rows: list[dict[str, Any]], table: str) -> set[int]:
    ids = [_old_id(row, table) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"备份包中的 {table} 包含重复编号。")
    return set(ids)


def _positive_int(value: Any, label: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"备份包中的{label}编号无效。") from exc
    if normalized <= 0:
        raise ValueError(f"备份包中的{label}编号无效。")
    return normalized


def _validate_source_relations(payload: Mapping[str, Any]) -> None:
    project = payload["project"]
    tables = payload["tables"]
    project_id = _old_id(project, "projects")
    material_ids = _unique_ids(tables["materials"], "materials")
    segment_ids = _unique_ids(tables["segments"], "segments")
    evidence_ids = _unique_ids(tables["evidence_cards"], "evidence_cards")
    claim_ids = _unique_ids(tables["claims"], "claims")
    _unique_ids(tables["followup_tasks"], "followup_tasks")
    _unique_ids(tables["claim_candidates"], "claim_candidates")
    _unique_ids(tables["agent_runs"], "agent_runs")
    project_tables = (
        "materials",
        "evidence_cards",
        "evidence_review_events",
        "claims",
        "agent_runs",
        "claim_candidates",
    )
    for table in project_tables:
        if any(
            _positive_int(row.get("project_id"), "项目") != project_id
            for row in tables[table]
        ):
            raise ValueError(f"备份包中的 {table} 跨越了项目边界。")
    for row in tables["materials"]:
        if row.get("is_fictional") not in (0, 1, False, True):
            raise ValueError("备份包中的材料来源标记无效。")
    for row in tables["segments"]:
        if _positive_int(row.get("material_id"), "材料") not in material_ids:
            raise ValueError("备份包中的片段材料引用无效。")
        _json_field(row, "pii_flags_json", list)
    for row in tables["evidence_cards"]:
        if _positive_int(row.get("segment_id"), "片段") not in segment_ids:
            raise ValueError("备份包中的证据片段引用无效。")
    for row in tables["claims"]:
        _json_field(row, "missing_evidence_json", list)
        _json_field(row, "rule_flags_json", list)
    for row in tables["claim_candidates"]:
        if _positive_int(row.get("material_id"), "材料") not in material_ids:
            raise ValueError("备份包中的候选结论材料引用无效。")
        source_ids = _json_field(row, "source_segment_ids_json", list)
        if not source_ids or any(
            _positive_int(item, "片段") not in segment_ids for item in source_ids
        ):
            raise ValueError("备份包中的候选结论来源片段无效。")
        _json_field(row, "uncertainties_json", list)
        if row.get("status") not in {"draft", "checked"}:
            raise ValueError("备份包中的候选结论状态无效。")
        claim_id = row.get("claim_id")
        if claim_id is not None and _positive_int(claim_id, "结论") not in claim_ids:
            raise ValueError("备份包中的候选结论核验记录无效。")
    for row in tables["evidence_review_events"]:
        if (
            _positive_int(row.get("evidence_card_id"), "证据")
            not in evidence_ids
        ):
            raise ValueError("备份包中的审核证据引用无效。")
        _json_field(row, "before_json", dict)
        _json_field(row, "after_json", dict)
        rechecked_ids = _json_field(row, "rechecked_claim_ids_json", list)
        if any(_positive_int(item, "结论") not in claim_ids for item in rechecked_ids):
            raise ValueError("备份包中的审核结论引用无效。")
    for row in tables["claim_evidence_links"]:
        if _positive_int(row.get("claim_id"), "结论") not in claim_ids:
            raise ValueError("备份包中的证据链接结论引用无效。")
        if (
            _positive_int(row.get("evidence_card_id"), "证据")
            not in evidence_ids
        ):
            raise ValueError("备份包中的证据链接证据引用无效。")
    for row in tables["followup_tasks"]:
        if _positive_int(row.get("claim_id"), "结论") not in claim_ids:
            raise ValueError("备份包中的任务结论引用无效。")
        completion_id = row.get("completion_material_id")
        if (
            completion_id is not None
            and _positive_int(completion_id, "完成材料") not in material_ids
        ):
            raise ValueError("备份包中的任务完成材料引用无效。")
    for row in tables["agent_runs"]:
        claim_id = row.get("claim_id")
        if (
            claim_id is not None
            and _positive_int(claim_id, "结论") not in claim_ids
        ):
            raise ValueError("备份包中的运行记录结论引用无效。")
        _json_field(row, "input_json", dict)
        _json_field(row, "output_json", dict)


def _validated_package(content: bytes) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    if not isinstance(content, bytes) or not content:
        raise ValueError("请选择有效的青迹项目备份包。")
    if len(content) > MAX_BACKUP_BYTES:
        raise ValueError("备份包不能超过 50 MiB。")
    try:
        archive = zipfile.ZipFile(BytesIO(content), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("文件不是有效的 ZIP 备份包。") from exc

    with archive:
        members = archive.infolist()
        if len(members) > MAX_BACKUP_MEMBERS:
            raise ValueError("备份包包含过多文件。")
        names: set[str] = set()
        total_size = 0
        for member in members:
            path = PurePosixPath(member.filename)
            if (
                member.filename in names
                or member.filename.startswith("/")
                or "\\" in member.filename
                or ".." in path.parts
                or member.is_dir()
                or member.flag_bits & 0x1
            ):
                raise ValueError("备份包包含不安全或重复的文件路径。")
            names.add(member.filename)
            total_size += int(member.file_size)
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("备份包解压后的内容超过 100 MiB。")
        manifest = _load_json_member(archive, _MANIFEST_PATH)
        payload = _load_json_member(archive, _PAYLOAD_PATH)
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("这不是青迹项目备份包。")
        if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
            raise ValueError("备份包版本不受当前青迹版本支持。")
        if payload.get("format_version") != BACKUP_FORMAT_VERSION:
            raise ValueError("项目数据版本与清单不一致。")

        payload_meta = manifest.get("payload")
        if (
            not isinstance(payload_meta, dict)
            or payload_meta.get("path") != _PAYLOAD_PATH
        ):
            raise ValueError("备份包数据清单无效。")
        payload_bytes = archive.read(_PAYLOAD_PATH)
        if (
            payload_meta.get("size") != len(payload_bytes)
            or payload_meta.get("sha256") != _digest(payload_bytes)
        ):
            raise ValueError("项目数据哈希校验失败，备份包可能已损坏或被修改。")

        project = payload.get("project")
        tables = payload.get("tables")
        source_project = manifest.get("source_project")
        if not isinstance(project, dict) or not isinstance(tables, dict):
            raise ValueError("备份包缺少项目数据表。")
        if (
            not isinstance(source_project, dict)
            or source_project.get("name") != project.get("name")
        ):
            raise ValueError("备份包中的项目信息不一致。")
        # Backups created before import-time candidate drafts had no such table.
        # They remain valid: restoring them simply yields no pending candidates.
        legacy_candidates = "claim_candidates" not in tables
        if legacy_candidates:
            tables["claim_candidates"] = []
        for table in _TABLES:
            rows = tables.get(table)
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) for row in rows
            ):
                raise ValueError(f"备份包中的 {table} 数据结构无效。")
        counts = manifest.get("counts")
        if legacy_candidates and isinstance(counts, dict):
            counts = {**counts, "claim_candidates": 0}
        if not isinstance(counts, dict) or any(
            counts.get(table) != len(tables[table]) for table in _TABLES
        ):
            raise ValueError("备份包记录数量与清单不一致。")
        _validate_source_relations(payload)

        declared = {_MANIFEST_PATH, _PAYLOAD_PATH}
        file_contents: dict[str, bytes] = {}
        raw_files = manifest.get("files")
        if not isinstance(raw_files, list):
            raise ValueError("备份包文件清单无效。")
        material_ids = {int(row.get("id", 0)) for row in tables["materials"]}
        for item in raw_files:
            if not isinstance(item, dict):
                raise ValueError("备份包文件清单无效。")
            path = item.get("path")
            kind = item.get("kind")
            try:
                material_id = int(item.get("source_material_id"))
            except (TypeError, ValueError) as exc:
                raise ValueError("备份包文件缺少有效材料编号。") from exc
            expected = f"materials/M{material_id}_{kind}.txt"
            if (
                kind not in {"raw", "redacted"}
                or path != expected
                or material_id not in material_ids
            ):
                raise ValueError("备份包文件与材料清单不匹配。")
            if path in declared or path not in names:
                raise ValueError("备份包文件清单包含重复或缺失项。")
            file_content = archive.read(path)
            if (
                item.get("size") != len(file_content)
                or item.get("sha256") != _digest(file_content)
            ):
                raise ValueError(f"材料文件 {path} 哈希校验失败。")
            if kind == "raw":
                material = next(
                    row for row in tables["materials"] if int(row["id"]) == material_id
                )
                if material.get("sha256") and material.get("sha256") != _digest(
                    file_content
                ):
                    raise ValueError(
                        f"材料 M{material_id} 的原文哈希与数据库记录不一致。"
                    )
            declared.add(path)
            file_contents[path] = file_content
        for material in tables["materials"]:
            material_id = int(material["id"])
            expected_raw = f"materials/M{material_id}_raw.txt"
            recorded_raw = str(material.get("raw_path") or "")
            if recorded_raw not in {"", expected_raw}:
                raise ValueError("备份包中的材料原文路径无效。")
            if bool(recorded_raw) != (expected_raw in file_contents):
                raise ValueError("备份包中的材料原文与文件清单不一致。")
        if names != declared:
            raise ValueError("备份包包含未声明的文件。")
        return manifest, payload, file_contents


def inspect_project_backup(content: bytes) -> BackupInspection:
    """Validate a package and return only metadata suitable for preview."""

    manifest, payload, files = _validated_package(content)
    project = payload["project"]
    return BackupInspection(
        source_project_name=str(project.get("name") or ""),
        source_project_description=str(project.get("description") or ""),
        created_at=str(manifest.get("created_at") or ""),
        counts={table: len(payload["tables"][table]) for table in _TABLES},
        material_file_count=len(files),
    )


def _old_id(row: Mapping[str, Any], table: str) -> int:
    try:
        value = int(row["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"备份包中的 {table} 记录缺少有效编号。") from exc
    if value <= 0:
        raise ValueError(f"备份包中的 {table} 记录编号无效。")
    return value


def _mapped(mapping: Mapping[int, int], value: Any, label: str) -> int:
    try:
        old_id = int(value)
        return mapping[old_id]
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"备份包中的{label}引用无效。") from exc


def _remap_json_refs(value: Any, maps: Mapping[str, Mapping[int, int]], key: str = "") -> Any:
    singular = {
        "project_id": "project",
        "material_id": "material",
        "completion_material_id": "material",
        "evidence_id": "evidence",
        "evidence_card_id": "evidence",
        "claim_id": "claim",
    }
    plural = {
        "expected_evidence_ids": "evidence",
        "relevant_evidence_ids": "evidence",
        "supporting_evidence_ids": "evidence",
        "contradicting_evidence_ids": "evidence",
        "context_evidence_ids": "evidence",
        "rechecked_claim_ids": "claim",
    }
    if key in singular and value is not None:
        return _mapped(maps[singular[key]], value, key)
    if key in plural and isinstance(value, list):
        return [_mapped(maps[plural[key]], item, key) for item in value]
    if key == "expected_id_ranks" and isinstance(value, dict):
        return {
            str(_mapped(maps["evidence"], old, key)): rank
            for old, rank in value.items()
        }
    if isinstance(value, dict):
        return {
            item_key: _remap_json_refs(item, maps, item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_remap_json_refs(item, maps) for item in value]
    return value


def _remap_json_text(
    raw: Any,
    maps: Mapping[str, Mapping[int, int]],
    default: Any,
    *,
    root_key: str = "",
) -> str:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("备份包包含无效的 JSON 字段。") from exc
    if not isinstance(value, type(default)):
        raise ValueError("备份包中的 JSON 字段类型无效。")
    return json.dumps(
        _remap_json_refs(value, maps, root_key),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def restore_project_backup(db: Any, content: bytes, restored_name: str) -> ProjectRestoreResult:
    """Restore a validated backup as a new project with remapped identifiers."""

    _, payload, material_files = _validated_package(content)
    project = payload["project"]
    tables = payload["tables"]
    normalized_name, _ = _normalized_project_fields(restored_name, "")
    description = str(project.get("description") or "")
    _, normalized_description = _normalized_project_fields(normalized_name, description)
    if db.get_project_by_name(normalized_name) is not None:
        raise ValueError("已存在同名项目，请为恢复项目填写其他名称。")

    written_files: list[Path] = []
    temporary_files: list[Path] = []
    maps: dict[str, dict[int, int]] = {
        "project": {},
        "material": {},
        "segment": {},
        "evidence": {},
        "claim": {},
        "task": {},
        "run": {},
    }
    db_dir = Path(db.path).resolve().parent
    raw_dir = (db_dir / "raw").resolve()
    redacted_dir = (db_dir / "redacted").resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    redacted_dir.mkdir(parents=True, exist_ok=True)
    try:
        with db.connect() as connection:
            duplicate = connection.execute(
                "SELECT 1 FROM projects WHERE name=?", (normalized_name,)
            ).fetchone()
            if duplicate:
                raise ValueError("已存在同名项目，请为恢复项目填写其他名称。")
            cursor = connection.execute(
                "INSERT INTO projects(name,description,archived_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?)",
                (
                    normalized_name,
                    normalized_description,
                    None,
                    project.get("created_at") or _utc_now(),
                    project.get("updated_at") or _utc_now(),
                ),
            )
            project_id = int(cursor.lastrowid)
            maps["project"][_old_id(project, "projects")] = project_id

            for row in tables["materials"]:
                old_id = _old_id(row, "materials")
                cursor = connection.execute(
                    "INSERT INTO materials(project_id,material_type,"
                    "original_filename,raw_path,sha256,source_role,context,"
                    "captured_at,consent_status,processing_status,is_fictional,notes,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        row.get("material_type"),
                        row.get("original_filename") or "",
                        "",
                        row.get("sha256") or "",
                        row.get("source_role") or "",
                        row.get("context") or "",
                        row.get("captured_at"),
                        row.get("consent_status"),
                        row.get("processing_status"),
                        int(bool(row.get("is_fictional"))),
                        row.get("notes") or "",
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )
                new_id = int(cursor.lastrowid)
                if old_id in maps["material"]:
                    raise ValueError("备份包包含重复的材料编号。")
                maps["material"][old_id] = new_id
                for kind, directory in (("raw", raw_dir), ("redacted", redacted_dir)):
                    package_path = f"materials/M{old_id}_{kind}.txt"
                    file_content = material_files.get(package_path)
                    if file_content is None:
                        continue
                    final_path = directory / f"M{new_id}_{kind}.txt"
                    if final_path.exists():
                        raise ValueError(f"恢复目标文件已存在：{final_path.name}")
                    temporary_path = directory / f".{final_path.name}.restoring-{uuid.uuid4().hex}"
                    temporary_files.append(temporary_path)
                    temporary_path.write_bytes(file_content)
                    os.replace(temporary_path, final_path)
                    temporary_files.remove(temporary_path)
                    written_files.append(final_path)
                    if kind == "raw":
                        if row.get("sha256") and row.get("sha256") != _digest(file_content):
                            raise ValueError(
                                f"材料 M{old_id} 的原文哈希与数据库记录不一致。"
                            )
                        connection.execute(
                            "UPDATE materials SET raw_path=? WHERE id=?",
                            (str(final_path), new_id),
                        )

            for row in tables["segments"]:
                old_id = _old_id(row, "segments")
                cursor = connection.execute(
                    "INSERT INTO segments(material_id,sequence_no,redacted_text,"
                    "start_ms,end_ms,locator,"
                    "pii_flags_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        _mapped(maps["material"], row.get("material_id"), "材料"),
                        row.get("sequence_no"),
                        row.get("redacted_text"),
                        row.get("start_ms"),
                        row.get("end_ms"),
                        row.get("locator") or "",
                        row.get("pii_flags_json") or "[]",
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )
                if old_id in maps["segment"]:
                    raise ValueError("备份包包含重复的片段编号。")
                maps["segment"][old_id] = int(cursor.lastrowid)

            for row in tables["evidence_cards"]:
                old_id = _old_id(row, "evidence_cards")
                cursor = connection.execute(
                    "INSERT INTO evidence_cards(project_id,segment_id,"
                    "evidence_type,title,quote,summary,"
                    "source_locator,review_status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        _mapped(maps["segment"], row.get("segment_id"), "片段"),
                        row.get("evidence_type"),
                        row.get("title"),
                        row.get("quote"),
                        row.get("summary"),
                        row.get("source_locator") or "",
                        row.get("review_status"),
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )
                if old_id in maps["evidence"]:
                    raise ValueError("备份包包含重复的证据编号。")
                maps["evidence"][old_id] = int(cursor.lastrowid)

            for row in tables["claims"]:
                old_id = _old_id(row, "claims")
                cursor = connection.execute(
                    "INSERT INTO claims(project_id,claim_text,verdict,reason,"
                    "safe_rewrite,missing_evidence_json,"
                    "rule_flags_json,checked_at,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        row.get("claim_text"),
                        row.get("verdict"),
                        row.get("reason") or "",
                        row.get("safe_rewrite") or "",
                        row.get("missing_evidence_json") or "[]",
                        row.get("rule_flags_json") or "[]",
                        row.get("checked_at") or _utc_now(),
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )
                if old_id in maps["claim"]:
                    raise ValueError("备份包包含重复的结论编号。")
                maps["claim"][old_id] = int(cursor.lastrowid)


            for row in tables["claim_candidates"]:
                source_segments = _remap_json_text(
                    row.get("source_segment_ids_json") or "[]",
                    maps,
                    [],
                    root_key="source_segment_ids",
                )
                claim_old = row.get("claim_id")
                claim_new = (
                    None
                    if claim_old is None
                    else _mapped(maps["claim"], claim_old, "结论")
                )
                connection.execute(
                    "INSERT INTO claim_candidates(project_id,material_id,claim_text,"
                    "source_segment_ids_json,model,uncertainties_json,status,claim_id,"
                    "checked_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        _mapped(maps["material"], row.get("material_id"), "材料"),
                        row.get("claim_text"),
                        source_segments,
                        row.get("model") or "",
                        row.get("uncertainties_json") or "[]",
                        row.get("status") or "draft",
                        claim_new,
                        row.get("checked_at"),
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )
            for row in tables["evidence_review_events"]:
                rechecked = _remap_json_text(
                    row.get("rechecked_claim_ids_json") or "[]",
                    maps,
                    [],
                    root_key="rechecked_claim_ids",
                )
                connection.execute(
                    "INSERT INTO evidence_review_events(project_id,"
                    "evidence_card_id,before_json,after_json,"
                    "change_reason,rechecked_claim_ids_json,created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        project_id,
                        _mapped(
                            maps["evidence"],
                            row.get("evidence_card_id"),
                            "证据",
                        ),
                        row.get("before_json") or "{}",
                        row.get("after_json") or "{}",
                        row.get("change_reason") or "",
                        rechecked,
                        row.get("created_at") or _utc_now(),
                    ),
                )

            for row in tables["claim_evidence_links"]:
                connection.execute(
                    "INSERT INTO claim_evidence_links(claim_id,evidence_card_id,"
                    "relation,rationale,review_status,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        _mapped(maps["claim"], row.get("claim_id"), "结论"),
                        _mapped(
                            maps["evidence"],
                            row.get("evidence_card_id"),
                            "证据",
                        ),
                        row.get("relation"),
                        row.get("rationale") or "",
                        row.get("review_status"),
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )

            for row in tables["followup_tasks"]:
                old_id = _old_id(row, "followup_tasks")
                completion_old = row.get("completion_material_id")
                completion_new = (
                    None
                    if completion_old is None
                    else _mapped(maps["material"], completion_old, "完成材料")
                )
                cursor = connection.execute(
                    "INSERT INTO followup_tasks(claim_id,title,recommended_action,"
                    "status,completion_material_id,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        _mapped(maps["claim"], row.get("claim_id"), "结论"),
                        row.get("title"),
                        row.get("recommended_action") or "",
                        row.get("status"),
                        completion_new,
                        row.get("created_at") or _utc_now(),
                        row.get("updated_at") or _utc_now(),
                    ),
                )
                if old_id in maps["task"]:
                    raise ValueError("备份包包含重复的任务编号。")
                maps["task"][old_id] = int(cursor.lastrowid)

            for row in tables["agent_runs"]:
                old_id = _old_id(row, "agent_runs")
                claim_old = row.get("claim_id")
                claim_new = (
                    None
                    if claim_old is None
                    else _mapped(maps["claim"], claim_old, "结论")
                )
                input_json = _remap_json_text(
                    row.get("input_json") or "{}", maps, {}
                )
                output_json = _remap_json_text(
                    row.get("output_json") or "{}", maps, {}
                )
                cursor = connection.execute(
                    "INSERT INTO agent_runs(project_id,claim_id,run_type,status,"
                    "input_json,output_json,error_message,"
                    "created_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        claim_new,
                        row.get("run_type"),
                        row.get("status"),
                        input_json,
                        output_json,
                        row.get("error_message") or "",
                        row.get("created_at") or _utc_now(),
                        row.get("finished_at"),
                    ),
                )
                if old_id in maps["run"]:
                    raise ValueError("备份包包含重复的运行记录编号。")
                maps["run"][old_id] = int(cursor.lastrowid)
    except Exception:
        for path in temporary_files + written_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    restored_rows = {table: len(tables[table]) for table in _TABLES}
    return ProjectRestoreResult(
        project_id=project_id,
        project_name=normalized_name,
        restored_rows=restored_rows,
        restored_files=len(written_files),
    )
