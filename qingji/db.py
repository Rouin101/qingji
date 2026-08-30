"""SQLite persistence for Qingji.

The storage layer deliberately keeps a small, dependency-free API.  Every
public read method returns a plain ``dict`` (or a list of them), while create
methods return the inserted integer id.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _value(value: Any) -> Any:
    """Turn string enums into values without coupling this module to models."""

    return value.value if isinstance(value, Enum) else value


def _json(value: Any, default: Any) -> str:
    if value is None:
        value = default
    if isinstance(value, str):
        # Preserve already-valid JSON supplied by low-level callers.
        try:
            json.loads(value)
        except (TypeError, ValueError):
            pass
        else:
            return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Database:
    """Small CRUD wrapper around Qingji's SQLite database."""

    PROJECT_FIELDS = {"name", "description", "archived_at", "updated_at"}
    MATERIAL_FIELDS = {
        "material_type",
        "original_filename",
        "raw_path",
        "sha256",
        "source_role",
        "context",
        "captured_at",
        "consent_status",
        "processing_status",
        "is_fictional",
        "notes",
        "updated_at",
    }
    SEGMENT_FIELDS = {
        "sequence_no",
        "redacted_text",
        "start_ms",
        "end_ms",
        "locator",
        "pii_flags_json",
        "updated_at",
    }
    EVIDENCE_FIELDS = {
        "evidence_type",
        "title",
        "quote",
        "summary",
        "source_locator",
        "review_status",
        "updated_at",
    }
    CLAIM_FIELDS = {
        "claim_text",
        "verdict",
        "reason",
        "safe_rewrite",
        "missing_evidence_json",
        "rule_flags_json",
        "checked_at",
        "updated_at",
    }
    CLAIM_CANDIDATE_FIELDS = {
        "status",
        "claim_id",
        "checked_at",
        "updated_at",
    }
    TASK_FIELDS = {
        "title",
        "recommended_action",
        "status",
        "completion_material_id",
        "updated_at",
    }

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or settings.database_path).expanduser()
        self.search_backend = "like"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create all core tables and the best available search index.

        FTS5 with the trigram tokenizer is preferred because it works well for
        short Chinese text.  Older SQLite builds may have FTS5 but not trigram,
        or no FTS5 at all; both cases fall back without preventing the app from
        starting.
        """

        schema = """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL
                REFERENCES projects(id) ON DELETE CASCADE,
            material_type TEXT NOT NULL
                CHECK (material_type IN ('text', 'audio', 'image', 'document')),
            original_filename TEXT NOT NULL DEFAULT '',
            raw_path TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            source_role TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '',
            captured_at TEXT,
            consent_status TEXT NOT NULL DEFAULT 'unknown'
                CHECK (consent_status IN ('unknown', 'confirmed', 'denied')),
            processing_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (processing_status IN ('draft', 'ready', 'failed')),
            is_fictional INTEGER NOT NULL DEFAULT 0
                CHECK (is_fictional IN (0, 1)),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_materials_project
            ON materials(project_id);
        CREATE INDEX IF NOT EXISTS idx_materials_sha256
            ON materials(sha256);

        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL
                REFERENCES materials(id) ON DELETE CASCADE,
            sequence_no INTEGER NOT NULL DEFAULT 1,
            redacted_text TEXT NOT NULL,
            start_ms INTEGER,
            end_ms INTEGER,
            locator TEXT NOT NULL DEFAULT '',
            pii_flags_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(material_id, sequence_no),
            CHECK (start_ms IS NULL OR start_ms >= 0),
            CHECK (end_ms IS NULL OR end_ms >= 0),
            CHECK (
                start_ms IS NULL OR end_ms IS NULL OR end_ms >= start_ms
            )
        );
        CREATE INDEX IF NOT EXISTS idx_segments_material
            ON segments(material_id);

        CREATE TABLE IF NOT EXISTS evidence_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL
                REFERENCES projects(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL
                REFERENCES segments(id) ON DELETE CASCADE,
            evidence_type TEXT NOT NULL CHECK (evidence_type IN (
                'interview_statement',
                'staff_explanation',
                'field_observation',
                'formal_record',
                'team_analysis'
            )),
            title TEXT NOT NULL,
            quote TEXT NOT NULL,
            summary TEXT NOT NULL,
            source_locator TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (review_status IN ('draft', 'approved', 'rejected')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_project_review
            ON evidence_cards(project_id, review_status);
        CREATE INDEX IF NOT EXISTS idx_evidence_segment
            ON evidence_cards(segment_id);

        CREATE TABLE IF NOT EXISTS evidence_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL
                REFERENCES projects(id) ON DELETE CASCADE,
            evidence_card_id INTEGER NOT NULL
                REFERENCES evidence_cards(id) ON DELETE CASCADE,
            before_json TEXT NOT NULL DEFAULT '{}',
            after_json TEXT NOT NULL DEFAULT '{}',
            change_reason TEXT NOT NULL,
            rechecked_claim_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_review_events_project
            ON evidence_review_events(project_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_review_events_evidence
            ON evidence_review_events(evidence_card_id, id DESC);

        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL
                REFERENCES projects(id) ON DELETE CASCADE,
            claim_text TEXT NOT NULL,
            verdict TEXT NOT NULL DEFAULT 'unsupported'
                CHECK (verdict IN (
                    'supported',
                    'partially_supported',
                    'unsupported',
                    'contradicted'
                )),
            reason TEXT NOT NULL DEFAULT '',
            safe_rewrite TEXT NOT NULL DEFAULT '',
            missing_evidence_json TEXT NOT NULL DEFAULT '[]',
            rule_flags_json TEXT NOT NULL DEFAULT '[]',
            checked_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_claims_project
            ON claims(project_id);

        CREATE TABLE IF NOT EXISTS claim_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            claim_text TEXT NOT NULL,
            source_segment_ids_json TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT '',
            uncertainties_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'checked')),
            claim_id INTEGER REFERENCES claims(id) ON DELETE SET NULL,
            checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_claim_candidates_project_status
            ON claim_candidates(project_id, status, id DESC);

        CREATE TABLE IF NOT EXISTS claim_evidence_links (
            claim_id INTEGER NOT NULL
                REFERENCES claims(id) ON DELETE CASCADE,
            evidence_card_id INTEGER NOT NULL
                REFERENCES evidence_cards(id) ON DELETE CASCADE,
            relation TEXT NOT NULL
                CHECK (relation IN ('support', 'contradict', 'context')),
            rationale TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (review_status IN ('draft', 'approved', 'rejected')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (claim_id, evidence_card_id)
        );
        CREATE INDEX IF NOT EXISTS idx_links_evidence
            ON claim_evidence_links(evidence_card_id);

        CREATE TABLE IF NOT EXISTS followup_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL
                REFERENCES claims(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            recommended_action TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'done', 'cancelled')),
            completion_material_id INTEGER
                REFERENCES materials(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_claim_status
            ON followup_tasks(claim_id, status);

        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER
                REFERENCES projects(id) ON DELETE CASCADE,
            claim_id INTEGER
                REFERENCES claims(id) ON DELETE CASCADE,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_agent_runs_project_type
            ON agent_runs(project_id, run_type, id DESC);
        """

        with self.connect() as connection:
            connection.executescript(schema)
            project_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(projects)")
            }
            if "archived_at" not in project_columns:
                connection.execute(
                    "ALTER TABLE projects ADD COLUMN archived_at TEXT"
                )
            agent_run_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(agent_runs)")
            }
            if "claim_id" not in agent_run_columns:
                connection.execute(
                    "ALTER TABLE agent_runs ADD COLUMN claim_id INTEGER"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_claim_type "
                "ON agent_runs(claim_id, run_type, id DESC)"
            )
            self.search_backend = self._initialize_search(connection)

    def _initialize_search(self, connection: sqlite3.Connection) -> str:
        existing = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'evidence_fts'"
        ).fetchone()
        if existing:
            sql = (existing["sql"] or "").lower()
            backend = "fts5_trigram" if "trigram" in sql else "fts5_unicode61"
        else:
            backend = "like"
            for tokenizer, label in (
                ("trigram", "fts5_trigram"),
                ("unicode61", "fts5_unicode61"),
            ):
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE evidence_fts USING fts5("
                        "title, quote, summary, "
                        "content='evidence_cards', content_rowid='id', "
                        f"tokenize='{tokenizer}')"
                    )
                except sqlite3.OperationalError:
                    continue
                backend = label
                break

        if backend == "like":
            return backend

        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS evidence_fts_ai
            AFTER INSERT ON evidence_cards BEGIN
                INSERT INTO evidence_fts(rowid, title, quote, summary)
                VALUES (new.id, new.title, new.quote, new.summary);
            END;
            CREATE TRIGGER IF NOT EXISTS evidence_fts_ad
            AFTER DELETE ON evidence_cards BEGIN
                INSERT INTO evidence_fts(
                    evidence_fts, rowid, title, quote, summary
                )
                VALUES (
                    'delete', old.id, old.title, old.quote, old.summary
                );
            END;
            CREATE TRIGGER IF NOT EXISTS evidence_fts_au
            AFTER UPDATE OF title, quote, summary ON evidence_cards BEGIN
                INSERT INTO evidence_fts(
                    evidence_fts, rowid, title, quote, summary
                )
                VALUES (
                    'delete', old.id, old.title, old.quote, old.summary
                );
                INSERT INTO evidence_fts(rowid, title, quote, summary)
                VALUES (new.id, new.title, new.quote, new.summary);
            END;
            """
        )
        # Rebuild is safe and repairs an index after an interrupted migration.
        connection.execute("INSERT INTO evidence_fts(evidence_fts) VALUES('rebuild')")
        return backend

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for json_field, alias in (
            ("pii_flags_json", "pii_flags"),
            ("missing_evidence_json", "missing_evidence"),
            ("rule_flags_json", "rule_flags"),
            ("input_json", "input"),
            ("output_json", "output"),
            ("before_json", "before"),
            ("after_json", "after"),
            ("rechecked_claim_ids_json", "rechecked_claim_ids"),
            ("source_segment_ids_json", "source_segment_ids"),
            ("uncertainties_json", "uncertainties"),
        ):
            if json_field in result:
                try:
                    result[alias] = json.loads(result[json_field])
                except (TypeError, ValueError):
                    result[alias] = []
        return result

    @classmethod
    def _rows(cls, rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
        return [cls._row(row) for row in rows]  # type: ignore[misc]

    def _get(self, table: str, row_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ?", (row_id,)
            ).fetchone()
        return self._row(row)

    def _delete(self, table: str, row_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE id = ?", (row_id,)
            )
        return cursor.rowcount > 0

    def _update(
        self,
        table: str,
        row_id: int,
        allowed: set[str],
        changes: Mapping[str, Any],
        *,
        json_fields: set[str] | None = None,
    ) -> dict[str, Any] | None:
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Unsupported {table} fields: {sorted(invalid)}")
        values = dict(changes)
        json_fields = json_fields or set()
        for key in json_fields:
            if key in values:
                values[key] = _json(values[key], [])
        for key, value in list(values.items()):
            values[key] = _value(value)
        if "updated_at" in allowed:
            values.setdefault("updated_at", _utc_now())
        if not values:
            return self._get(table, row_id)
        assignments = ", ".join(f"{field} = ?" for field in values)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                (*values.values(), row_id),
            )
        return self._get(table, row_id)

    # Projects
    def create_project(self, name: str, description: str = "") -> int:
        now = _utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO projects(name, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (name.strip(), description, now, now),
            )
        return int(cursor.lastrowid)

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        return self._get("projects", project_id)

    def get_project_by_name(self, name: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
        return self._row(row)

    def list_projects(
        self, *, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        where = "" if include_archived else "WHERE archived_at IS NULL"
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM projects {where} "
                "ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return self._rows(rows)

    def list_archived_projects(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects WHERE archived_at IS NOT NULL "
                "ORDER BY archived_at DESC, id DESC"
            ).fetchall()
        return self._rows(rows)

    def update_project(
        self, project_id: int, **changes: Any
    ) -> dict[str, Any] | None:
        return self._update(
            "projects", project_id, self.PROJECT_FIELDS, changes
        )

    def delete_project(self, project_id: int) -> bool:
        return self._delete("projects", project_id)

    # Materials
    def create_material(
        self,
        project_id: int,
        material_type: str,
        *,
        original_filename: str = "",
        raw_path: str = "",
        sha256: str = "",
        source_role: str = "",
        context: str = "",
        captured_at: str | None = None,
        consent_status: str = "unknown",
        processing_status: str = "draft",
        is_fictional: bool = False,
        notes: str = "",
    ) -> int:
        now = _utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO materials(
                    project_id, material_type, original_filename, raw_path,
                    sha256, source_role, context, captured_at, consent_status,
                    processing_status, is_fictional, notes, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    _value(material_type),
                    original_filename,
                    raw_path,
                    sha256,
                    source_role,
                    context,
                    captured_at,
                    _value(consent_status),
                    _value(processing_status),
                    int(is_fictional),
                    notes,
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def get_material(self, material_id: int) -> dict[str, Any] | None:
        return self._get("materials", material_id)

    def list_materials(
        self,
        project_id: int,
        *,
        consent_status: str | None = None,
        processing_status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if consent_status is not None:
            clauses.append("consent_status = ?")
            params.append(_value(consent_status))
        if processing_status is not None:
            clauses.append("processing_status = ?")
            params.append(_value(processing_status))
        sql = (
            "SELECT * FROM materials WHERE "
            + " AND ".join(clauses)
            + " ORDER BY captured_at DESC, id DESC"
        )
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return self._rows(rows)

    def update_material(
        self, material_id: int, **changes: Any
    ) -> dict[str, Any] | None:
        return self._update(
            "materials", material_id, self.MATERIAL_FIELDS, changes
        )

    def delete_material(self, material_id: int) -> bool:
        return self._delete("materials", material_id)

    # Segments
    def create_segment(
        self,
        material_id: int,
        sequence_no: int,
        redacted_text: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        locator: str = "",
        pii_flags: Sequence[Any] | str | None = None,
    ) -> int:
        now = _utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO segments(
                    material_id, sequence_no, redacted_text, start_ms, end_ms,
                    locator, pii_flags_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    material_id,
                    sequence_no,
                    redacted_text,
                    start_ms,
                    end_ms,
                    locator,
                    _json(pii_flags, []),
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def get_segment(self, segment_id: int) -> dict[str, Any] | None:
        return self._get("segments", segment_id)

    def list_segments(self, material_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM segments WHERE material_id = ? "
                "ORDER BY sequence_no, id",
                (material_id,),
            ).fetchall()
        return self._rows(rows)

    def update_segment(
        self, segment_id: int, **changes: Any
    ) -> dict[str, Any] | None:
        if "pii_flags" in changes:
            changes["pii_flags_json"] = changes.pop("pii_flags")
        return self._update(
            "segments",
            segment_id,
            self.SEGMENT_FIELDS,
            changes,
            json_fields={"pii_flags_json"},
        )

    def delete_segment(self, segment_id: int) -> bool:
        return self._delete("segments", segment_id)

    # Evidence cards
    def create_evidence_card(
        self,
        project_id: int,
        segment_id: int,
        evidence_type: str,
        title: str,
        quote: str,
        summary: str,
        *,
        source_locator: str = "",
        review_status: str = "draft",
    ) -> int:
        now = _utc_now()
        with self.connect() as connection:
            segment_project = connection.execute(
                """
                SELECT m.project_id
                FROM segments s
                JOIN materials m ON m.id = s.material_id
                WHERE s.id = ?
                """,
                (segment_id,),
            ).fetchone()
            if segment_project is None:
                raise ValueError(f"Segment {segment_id} does not exist")
            if int(segment_project["project_id"]) != int(project_id):
                raise ValueError("Evidence card and segment must share a project")
            cursor = connection.execute(
                """
                INSERT INTO evidence_cards(
                    project_id, segment_id, evidence_type, title, quote,
                    summary, source_locator, review_status, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    segment_id,
                    _value(evidence_type),
                    title,
                    quote,
                    summary,
                    source_locator,
                    _value(review_status),
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def get_evidence_card(
        self, evidence_card_id: int
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                self._evidence_select() + " WHERE ec.id = ?",
                (evidence_card_id,),
            ).fetchone()
        return self._row(row)

    def list_evidence_cards(
        self,
        project_id: int,
        *,
        review_status: str | None = None,
        evidence_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ec.project_id = ?"]
        params: list[Any] = [project_id]
        if review_status is not None:
            clauses.append("ec.review_status = ?")
            params.append(_value(review_status))
        if evidence_type is not None:
            clauses.append("ec.evidence_type = ?")
            params.append(_value(evidence_type))
        sql = (
            self._evidence_select()
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ec.created_at DESC, ec.id DESC"
        )
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return self._rows(rows)

    @staticmethod
    def _evidence_select() -> str:
        return """
            SELECT
                ec.*,
                s.material_id,
                s.locator AS segment_locator,
                s.redacted_text,
                m.source_role,
                m.context,
                m.consent_status,
                m.material_type,
                m.original_filename,
                m.is_fictional
            FROM evidence_cards ec
            JOIN segments s ON s.id = ec.segment_id
            JOIN materials m ON m.id = s.material_id
        """

    def update_evidence_card(
        self, evidence_card_id: int, **changes: Any
    ) -> dict[str, Any] | None:
        return self._update(
            "evidence_cards",
            evidence_card_id,
            self.EVIDENCE_FIELDS,
            changes,
        )

    def set_evidence_review_status(
        self, evidence_card_id: int, review_status: str
    ) -> dict[str, Any] | None:
        return self.update_evidence_card(
            evidence_card_id, review_status=review_status
        )

    def create_evidence_review_event(
        self,
        evidence_card_id: int,
        *,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        change_reason: str,
        rechecked_claim_ids: Sequence[int] = (),
    ) -> int:
        """Append one immutable evidence-review event for an evidence card."""

        reason = str(change_reason or "").strip()
        if len(reason) > 500:
            raise ValueError("证据审核说明不能超过 500 字。")
        normalized_claim_ids = list(dict.fromkeys(int(item) for item in rechecked_claim_ids))
        now = _utc_now()
        with self.connect() as connection:
            evidence = connection.execute(
                "SELECT project_id FROM evidence_cards WHERE id = ?",
                (int(evidence_card_id),),
            ).fetchone()
            if evidence is None:
                raise ValueError(f"Evidence card {evidence_card_id} does not exist")
            project_id = int(evidence["project_id"])
            if normalized_claim_ids:
                placeholders = ", ".join("?" for _ in normalized_claim_ids)
                rows = connection.execute(
                    "SELECT id, project_id FROM claims "
                    f"WHERE id IN ({placeholders})",
                    normalized_claim_ids,
                ).fetchall()
                if len(rows) != len(normalized_claim_ids) or any(
                    int(row["project_id"]) != project_id for row in rows
                ):
                    raise ValueError(
                        "重新核验的结论必须全部属于证据所在项目。"
                    )
            cursor = connection.execute(
                "INSERT INTO evidence_review_events("
                "project_id, evidence_card_id, before_json, after_json, "
                "change_reason, rechecked_claim_ids_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    int(evidence_card_id),
                    _json(dict(before), {}),
                    _json(dict(after), {}),
                    reason,
                    _json(normalized_claim_ids, []),
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def list_evidence_review_events(
        self,
        project_id: int,
        *,
        evidence_card_id: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List newest review events without crossing the project boundary."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit 必须是 1 到 500 之间的整数。")
        clauses = ["project_id = ?"]
        params: list[Any] = [int(project_id)]
        if evidence_card_id is not None:
            clauses.append("evidence_card_id = ?")
            params.append(int(evidence_card_id))
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evidence_review_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return self._rows(rows)

    def delete_evidence_card(self, evidence_card_id: int) -> bool:
        return self._delete("evidence_cards", evidence_card_id)

    def search_evidence(
        self,
        project_id: int,
        query: str,
        *,
        limit: int = 10,
        approved_only: bool = True,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            cards = self.list_evidence_cards(project_id)
            if approved_only:
                cards = [
                    row
                    for row in cards
                    if row.get("review_status") != "rejected"
                    and row.get("consent_status") == "confirmed"
                ]
            return cards[:limit]

        # Detect the index in case another process initialized this instance's
        # database.
        with self.connect() as connection:
            table = connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'evidence_fts'"
            ).fetchone()
            if table:
                sql_text = (table["sql"] or "").lower()
                self.search_backend = (
                    "fts5_trigram"
                    if "trigram" in sql_text
                    else "fts5_unicode61"
                )
            else:
                self.search_backend = "like"

            rows: list[sqlite3.Row] = []
            # Trigram requires three code points; LIKE is more predictable for
            # tiny queries and is also the universal failure fallback.
            if self.search_backend.startswith("fts5") and len(query) >= 3:
                match_query = '"' + query.replace('"', '""') + '"'
                status_clause = (
                    "AND ec.review_status != 'rejected' "
                    "AND m.consent_status = 'confirmed'"
                    if approved_only
                    else ""
                )
                try:
                    rows = connection.execute(
                        """
                        SELECT
                            ec.*,
                            s.material_id,
                            s.locator AS segment_locator,
                            s.redacted_text,
                            m.source_role,
                            m.context,
                            m.consent_status,
                            m.material_type,
                            m.original_filename,
                            m.is_fictional,
                            bm25(evidence_fts) AS search_score
                        FROM evidence_fts
                        JOIN evidence_cards ec ON ec.id = evidence_fts.rowid
                        JOIN segments s ON s.id = ec.segment_id
                        JOIN materials m ON m.id = s.material_id
                        WHERE evidence_fts MATCH ?
                          AND ec.project_id = ?
                        """
                        + status_clause
                        + " ORDER BY search_score, ec.id DESC LIMIT ?",
                        (match_query, project_id, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []

            if not rows:
                pattern = f"%{query}%"
                clauses = [
                    "ec.project_id = ?",
                    "(ec.title LIKE ? OR ec.quote LIKE ? "
                    "OR ec.summary LIKE ? OR s.redacted_text LIKE ?)",
                ]
                params: list[Any] = [
                    project_id,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                ]
                if approved_only:
                    clauses.append("ec.review_status != 'rejected'")
                    clauses.append("m.consent_status = 'confirmed'")
                rows = connection.execute(
                    self._evidence_select()
                    + " WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY ec.id DESC LIMIT ?",
                    (*params, limit),
                ).fetchall()
        return self._rows(rows)

    search_evidence_cards = search_evidence

    # Claims
    def create_claim(
        self,
        project_id: int,
        claim_text: str,
        *,
        verdict: str = "unsupported",
        reason: str = "",
        safe_rewrite: str = "",
        missing_evidence: Sequence[Any] | str | None = None,
        rule_flags: Sequence[Any] | str | None = None,
        checked_at: str | None = None,
    ) -> int:
        now = _utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO claims(
                    project_id, claim_text, verdict, reason, safe_rewrite,
                    missing_evidence_json, rule_flags_json, checked_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    claim_text,
                    _value(verdict),
                    reason,
                    safe_rewrite,
                    _json(missing_evidence, []),
                    _json(rule_flags, []),
                    checked_at or now,
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def get_claim(self, claim_id: int) -> dict[str, Any] | None:
        claim = self._get("claims", claim_id)
        if claim is not None:
            claim["evidence_links"] = self.list_claim_evidence_links(claim_id)
            claim["followup_tasks"] = self.list_followup_tasks(claim_id=claim_id)
        return claim

    def list_claims(
        self,
        project_id: int,
        *,
        verdict: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM claims WHERE project_id = ?"
        params: list[Any] = [project_id]
        if verdict is not None:
            sql += " AND verdict = ?"
            params.append(_value(verdict))
        normalized_query = (query or "").strip()
        if normalized_query:
            escaped_query = (
                normalized_query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            sql += " AND claim_text LIKE ? ESCAPE '\\'"
            params.append(f"%{escaped_query}%")
        sql += " ORDER BY checked_at DESC, id DESC"
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return self._rows(rows)

    def get_claim_verdict_stats(self, project_id: int) -> dict[str, int]:
        """Return a stable four-outcome distribution for one project."""

        verdicts = (
            "supported",
            "partially_supported",
            "unsupported",
            "contradicted",
        )
        counts = {verdict: 0 for verdict in verdicts}
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT verdict, COUNT(*) AS count FROM claims "
                "WHERE project_id = ? GROUP BY verdict",
                (project_id,),
            ).fetchall()
        for row in rows:
            if row["verdict"] in counts:
                counts[row["verdict"]] = int(row["count"])
        return counts

    def update_claim(
        self, claim_id: int, **changes: Any
    ) -> dict[str, Any] | None:
        if "missing_evidence" in changes:
            changes["missing_evidence_json"] = changes.pop("missing_evidence")
        if "rule_flags" in changes:
            changes["rule_flags_json"] = changes.pop("rule_flags")
        return self._update(
            "claims",
            claim_id,
            self.CLAIM_FIELDS,
            changes,
            json_fields={"missing_evidence_json", "rule_flags_json"},
        )

    def delete_claim(self, claim_id: int) -> bool:
        return self._delete("claims", claim_id)

    # Claim/evidence links
    # Model-generated claim candidates remain drafts until separately checked.
    def create_claim_candidate(
        self,
        project_id: int,
        material_id: int,
        claim_text: str,
        *,
        source_segment_ids: Sequence[int],
        model: str = "",
        uncertainties: Sequence[str] | None = None,
    ) -> int:
        normalized_text = str(claim_text or "").strip()
        if not normalized_text:
            raise ValueError("候选结论不能为空")
        segment_ids = list(dict.fromkeys(int(item) for item in source_segment_ids))
        if not segment_ids:
            raise ValueError("候选结论必须保留来源片段")
        now = _utc_now()
        with self.connect() as connection:
            material = connection.execute(
                "SELECT project_id FROM materials WHERE id = ?", (material_id,)
            ).fetchone()
            if material is None or int(material["project_id"]) != int(project_id):
                raise ValueError("候选结论与材料必须属于同一项目")
            placeholders = ",".join("?" for _ in segment_ids)
            matched = connection.execute(
                "SELECT COUNT(*) FROM segments WHERE material_id = ? "
                f"AND id IN ({placeholders})",
                (material_id, *segment_ids),
            ).fetchone()[0]
            if int(matched) != len(segment_ids):
                raise ValueError("候选结论的来源片段不属于该材料")
            cursor = connection.execute(
                """
                INSERT INTO claim_candidates(
                    project_id, material_id, claim_text,
                    source_segment_ids_json, model, uncertainties_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    project_id,
                    material_id,
                    normalized_text,
                    _json(segment_ids, []),
                    str(model or ""),
                    _json(uncertainties, []),
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def list_claim_candidates(
        self, project_id: int, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["cc.project_id = ?"]
        params: list[Any] = [project_id]
        if status is not None:
            clauses.append("cc.status = ?")
            params.append(_value(status))
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT cc.*, m.original_filename, m.source_role, m.context
                FROM claim_candidates cc
                JOIN materials m ON m.id = cc.material_id
                WHERE """
                + " AND ".join(clauses)
                + " ORDER BY cc.created_at DESC, cc.id DESC",
                params,
            ).fetchall()
        return self._rows(rows)

    def mark_claim_candidate_checked(
        self, candidate_id: int, claim_id: int
    ) -> dict[str, Any] | None:
        now = _utc_now()
        with self.connect() as connection:
            candidate = connection.execute(
                "SELECT project_id FROM claim_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            claim = connection.execute(
                "SELECT project_id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if candidate is None or claim is None:
                raise ValueError("候选结论或核验结论不存在")
            if int(candidate["project_id"]) != int(claim["project_id"]):
                raise ValueError("候选结论和核验结论必须属于同一项目")
            connection.execute(
                """
                UPDATE claim_candidates
                SET status = 'checked', claim_id = ?, checked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (claim_id, now, now, candidate_id),
            )
        return self._get("claim_candidates", candidate_id)
    def link_claim_evidence(
        self,
        claim_id: int,
        evidence_card_id: int,
        relation: str,
        *,
        rationale: str = "",
        review_status: str = "draft",
    ) -> None:
        now = _utc_now()
        with self.connect() as connection:
            claim_project = connection.execute(
                "SELECT project_id FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            evidence_project = connection.execute(
                "SELECT project_id FROM evidence_cards WHERE id = ?",
                (evidence_card_id,),
            ).fetchone()
            if claim_project is None or evidence_project is None:
                raise ValueError("Claim and evidence card must both exist")
            if claim_project["project_id"] != evidence_project["project_id"]:
                raise ValueError("Claim and evidence card must share a project")
            connection.execute(
                """
                INSERT INTO claim_evidence_links(
                    claim_id, evidence_card_id, relation, rationale,
                    review_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(claim_id, evidence_card_id) DO UPDATE SET
                    relation = excluded.relation,
                    rationale = excluded.rationale,
                    review_status = excluded.review_status,
                    updated_at = excluded.updated_at
                """,
                (
                    claim_id,
                    evidence_card_id,
                    _value(relation),
                    rationale,
                    _value(review_status),
                    now,
                    now,
                ),
            )

    def list_claim_evidence_links(
        self, claim_id: int
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    l.*,
                    ec.title AS evidence_title,
                    ec.quote AS evidence_quote,
                    ec.evidence_type,
                    ec.source_locator
                FROM claim_evidence_links l
                JOIN evidence_cards ec ON ec.id = l.evidence_card_id
                WHERE l.claim_id = ?
                ORDER BY l.created_at, l.evidence_card_id
                """,
                (claim_id,),
            ).fetchall()
        return self._rows(rows)

    def unlink_claim_evidence(
        self, claim_id: int, evidence_card_id: int
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM claim_evidence_links "
                "WHERE claim_id = ? AND evidence_card_id = ?",
                (claim_id, evidence_card_id),
            )
        return cursor.rowcount > 0

    # Follow-up tasks
    def create_followup_task(
        self,
        claim_id: int,
        title: str,
        *,
        recommended_action: str = "",
        status: str = "open",
        completion_material_id: int | None = None,
    ) -> int:
        now = _utc_now()
        with self.connect() as connection:
            self._validate_completion_material_project(
                connection, claim_id, completion_material_id
            )
            cursor = connection.execute(
                """
                INSERT INTO followup_tasks(
                    claim_id, title, recommended_action, status,
                    completion_material_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    title,
                    recommended_action,
                    _value(status),
                    completion_material_id,
                    now,
                    now,
                ),
            )
        return int(cursor.lastrowid)

    def get_followup_task(self, task_id: int) -> dict[str, Any] | None:
        return self._get("followup_tasks", task_id)

    def list_followup_tasks(
        self,
        *,
        project_id: int | None = None,
        claim_id: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("c.project_id = ?")
            params.append(project_id)
        if claim_id is not None:
            clauses.append("t.claim_id = ?")
            params.append(claim_id)
        if status is not None:
            clauses.append("t.status = ?")
            params.append(_value(status))
        sql = """
            SELECT
                t.*,
                c.project_id,
                c.claim_text,
                m.original_filename AS completion_material_filename
            FROM followup_tasks t
            JOIN claims c ON c.id = t.claim_id
            LEFT JOIN materials m ON m.id = t.completion_material_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY t.created_at DESC, t.id DESC"
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return self._rows(rows)

    def update_followup_task(
        self, task_id: int, **changes: Any
    ) -> dict[str, Any] | None:
        if "completion_material_id" in changes:
            task = self.get_followup_task(task_id)
            if task is not None:
                with self.connect() as connection:
                    self._validate_completion_material_project(
                        connection,
                        int(task["claim_id"]),
                        changes["completion_material_id"],
                    )
        return self._update(
            "followup_tasks", task_id, self.TASK_FIELDS, changes
        )

    @staticmethod
    def _validate_completion_material_project(
        connection: sqlite3.Connection,
        claim_id: int,
        completion_material_id: int | None,
    ) -> None:
        if completion_material_id is None:
            return
        claim = connection.execute(
            "SELECT project_id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if claim is None:
            raise ValueError(f"Claim {claim_id} does not exist")
        material = connection.execute(
            "SELECT project_id FROM materials WHERE id = ?",
            (completion_material_id,),
        ).fetchone()
        if material is None:
            raise ValueError(
                f"Completion material {completion_material_id} does not exist"
            )
        if int(claim["project_id"]) != int(material["project_id"]):
            raise ValueError(
                "Follow-up task and completion material must share a project"
            )

    def set_followup_task_status(
        self,
        task_id: int,
        status: str,
        *,
        completion_material_id: int | None = None,
    ) -> dict[str, Any] | None:
        changes: dict[str, Any] = {"status": status}
        if completion_material_id is not None:
            changes["completion_material_id"] = completion_material_id
        return self.update_followup_task(task_id, **changes)

    def delete_followup_task(self, task_id: int) -> bool:
        return self._delete("followup_tasks", task_id)

    # Explainable workflow runs
    def create_agent_run(
        self,
        project_id: int,
        run_type: str,
        *,
        claim_id: int | None = None,
        status: str = "completed",
        input_data: Mapping[str, Any] | None = None,
        output_data: Mapping[str, Any] | None = None,
        error_message: str = "",
        finished_at: str | None = None,
    ) -> int:
        now = _utc_now()
        with self.connect() as connection:
            if claim_id is not None:
                claim = connection.execute(
                    "SELECT project_id FROM claims WHERE id = ?", (claim_id,)
                ).fetchone()
                if claim is None:
                    raise ValueError(f"Claim {claim_id} does not exist")
                if int(claim["project_id"]) != int(project_id):
                    raise ValueError(
                        "Agent run and claim must share a project"
                    )
            cursor = connection.execute(
                """
                INSERT INTO agent_runs(
                    project_id, claim_id, run_type, status, input_json,
                    output_json, error_message, created_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    claim_id,
                    run_type,
                    status,
                    _json(input_data, {}),
                    _json(output_data, {}),
                    error_message,
                    now,
                    finished_at or (now if status == "completed" else None),
                ),
            )
        return int(cursor.lastrowid)

    def get_latest_claim_run(
        self, claim_id: int, run_type: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs "
                "WHERE claim_id = ? AND run_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (claim_id, run_type),
            ).fetchone()
        return self._row(row)

    def get_agent_run(self, run_id: int) -> dict[str, Any] | None:
        return self._get("agent_runs", int(run_id))

    def list_model_runs(
        self,
        project_id: int,
        *,
        status: str | None = None,
        run_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return project-local LLM runs for the model operations center."""

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        clauses = ["project_id = ?", "run_type LIKE 'llm_%'"]
        params: list[Any] = [int(project_id)]
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status))
        if run_type is not None:
            clauses.append("run_type = ?")
            params.append(str(run_type))
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return self._rows(rows)

    def get_latest_project_run(
        self, project_id: int, run_type: str
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs "
                "WHERE project_id = ? AND run_type = ? "
                "ORDER BY id DESC LIMIT 1",
                (project_id, run_type),
            ).fetchone()
        return self._row(row)

    def list_project_runs(
        self,
        project_id: int,
        run_type: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return newest-first workflow runs isolated to one project and type."""

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs "
                "WHERE project_id = ? AND run_type = ? "
                "ORDER BY id DESC LIMIT ?",
                (int(project_id), str(run_type), limit),
            ).fetchall()
        return self._rows(rows)

    # Dashboard/statistics
    def get_project_stats(self, project_id: int) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM materials
                        WHERE project_id = :project_id) AS materials,
                    (SELECT COUNT(*) FROM segments s
                        JOIN materials m ON m.id = s.material_id
                        WHERE m.project_id = :project_id) AS segments,
                    (SELECT COUNT(*) FROM evidence_cards
                        WHERE project_id = :project_id) AS evidence_cards,
                    (SELECT COUNT(*) FROM evidence_cards
                        WHERE project_id = :project_id
                          AND review_status = 'approved')
                        AS approved_evidence_cards,
                    (SELECT COUNT(*) FROM evidence_cards ec
                        JOIN segments s ON s.id = ec.segment_id
                        JOIN materials m ON m.id = s.material_id
                        WHERE ec.project_id = :project_id
                          AND ec.review_status != 'rejected'
                          AND m.consent_status = 'confirmed') AS eligible_evidence_cards,
                    (SELECT COUNT(*) FROM claims
                        WHERE project_id = :project_id) AS claims,
                    (SELECT COUNT(*) FROM followup_tasks t
                        JOIN claims c ON c.id = t.claim_id
                        WHERE c.project_id = :project_id) AS followup_tasks,
                    (SELECT COUNT(*) FROM followup_tasks t
                        JOIN claims c ON c.id = t.claim_id
                        WHERE c.project_id = :project_id
                          AND t.status = 'open') AS open_followup_tasks
                """,
                {"project_id": project_id},
            ).fetchone()
        return {key: int(value) for key, value in dict(row).items()}

    project_stats = get_project_stats

    def foreign_keys_enabled(self) -> bool:
        with self.connect() as connection:
            value = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        return bool(value)
