"""Project-workspace validation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qingji.db import Database
from qingji.demo import create_demo_project
from qingji.projects import (
    MAX_PROJECT_DESCRIPTION_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    activate_project,
    archive_project_workspace,
    create_project_workspace,
    delete_project_workspace,
    rename_project_workspace,
    restore_project_workspace,
)


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "qingji.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_project_trims_fields_and_starts_empty(self) -> None:
        project_id = create_project_workspace(
            self.db,
            "  社区公共服务调研  ",
            "  收集经授权材料并核验报告表述。  ",
        )

        project = self.db.get_project(project_id)
        self.assertEqual(project["name"], "社区公共服务调研")
        self.assertEqual(
            project["description"], "收集经授权材料并核验报告表述。"
        )
        self.assertEqual(self.db.get_project_stats(project_id)["materials"], 0)

    def test_blank_and_duplicate_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能为空"):
            create_project_workspace(self.db, "   ")

        create_project_workspace(self.db, "重复项目")
        with self.assertRaisesRegex(ValueError, "同名项目"):
            create_project_workspace(self.db, "重复项目")

    def test_field_length_limits_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, str(MAX_PROJECT_NAME_LENGTH)):
            create_project_workspace(
                self.db, "项" * (MAX_PROJECT_NAME_LENGTH + 1)
            )
        with self.assertRaisesRegex(
            ValueError, str(MAX_PROJECT_DESCRIPTION_LENGTH)
        ):
            create_project_workspace(
                self.db,
                "合法项目名",
                "说" * (MAX_PROJECT_DESCRIPTION_LENGTH + 1),
            )

    def test_activate_project_clears_cross_project_ui_state(self) -> None:
        session_state = {
            "qingji_project_id": 1,
            "active_claim_id": 9,
            "claim_draft": "旧项目结论",
            "last_import_result": object(),
            "material_draft_text": "旧材料",
            "unrelated_preference": "keep",
        }

        activate_project(session_state, 2)

        self.assertEqual(session_state["qingji_project_id"], 2)
        self.assertNotIn("active_claim_id", session_state)
        self.assertNotIn("claim_draft", session_state)
        self.assertNotIn("last_import_result", session_state)
        self.assertNotIn("material_draft_text", session_state)
        self.assertEqual(session_state["unrelated_preference"], "keep")

    def test_rename_archive_and_restore_project(self) -> None:
        first_id = create_project_workspace(self.db, "项目甲", "旧说明")
        create_project_workspace(self.db, "项目乙")

        updated = rename_project_workspace(
            self.db, first_id, "  项目甲新版  ", "  新说明  "
        )
        self.assertEqual(updated["name"], "项目甲新版")
        self.assertEqual(updated["description"], "新说明")
        with self.assertRaisesRegex(ValueError, "同名项目"):
            rename_project_workspace(self.db, first_id, "项目乙")

        archived = archive_project_workspace(self.db, first_id)
        self.assertTrue(archived["archived_at"])
        self.assertNotIn(first_id, [item["id"] for item in self.db.list_projects()])
        self.assertIn(
            first_id,
            [item["id"] for item in self.db.list_archived_projects()],
        )

        restored = restore_project_workspace(self.db, first_id)
        self.assertIsNone(restored["archived_at"])
        self.assertIn(first_id, [item["id"] for item in self.db.list_projects()])

    def test_demo_project_cannot_be_managed(self) -> None:
        demo_id = create_demo_project(self.db)
        for operation in (
            lambda: rename_project_workspace(self.db, demo_id, "新名称"),
            lambda: archive_project_workspace(self.db, demo_id),
        ):
            with self.assertRaisesRegex(ValueError, "内置虚构测试项目"):
                operation()

    def test_permanent_delete_requires_archive_and_exact_name(self) -> None:
        project_id = create_project_workspace(self.db, "待删除项目")
        material_id = self.db.create_material(project_id, "text")
        raw_dir = Path(self.temp_dir.name) / "raw"
        redacted_dir = Path(self.temp_dir.name) / "redacted"
        raw_dir.mkdir()
        redacted_dir.mkdir()
        raw_path = raw_dir / f"M{material_id}_raw.txt"
        redacted_path = redacted_dir / f"M{material_id}_redacted.txt"
        raw_path.write_text("原文", encoding="utf-8")
        redacted_path.write_text("脱敏文本", encoding="utf-8")
        self.db.update_material(material_id, raw_path=str(raw_path))

        with self.assertRaisesRegex(ValueError, "先归档"):
            delete_project_workspace(self.db, project_id, "待删除项目")
        archive_project_workspace(self.db, project_id)
        with self.assertRaisesRegex(ValueError, "输入不一致"):
            delete_project_workspace(self.db, project_id, "名称错误")

        result = delete_project_workspace(self.db, project_id, "待删除项目")
        self.assertEqual(result.removed_files, 2)
        self.assertEqual(result.warnings, ())
        self.assertIsNone(self.db.get_project(project_id))
        self.assertFalse(raw_path.exists())
        self.assertFalse(redacted_path.exists())


if __name__ == "__main__":
    unittest.main()
