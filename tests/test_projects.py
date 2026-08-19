"""Project-workspace validation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qingji.db import Database
from qingji.projects import (
    MAX_PROJECT_DESCRIPTION_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    activate_project,
    create_project_workspace,
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


if __name__ == "__main__":
    unittest.main()
