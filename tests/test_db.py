from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from qingji.db import Database
from qingji.demo import (
    DEMO_PROJECT_NAME,
    add_demo_supplement,
    create_demo_project,
)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(self.db_path)
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initialize_creates_core_tables_and_foreign_keys(self) -> None:
        self.assertTrue(self.db.foreign_keys_enabled())
        with sqlite3.connect(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue(
            {
                "projects",
                "materials",
                "segments",
                "evidence_cards",
                "claims",
                "claim_evidence_links",
                "followup_tasks",
            }.issubset(tables)
        )
        self.assertIn(
            self.db.search_backend,
            {"fts5_trigram", "fts5_unicode61", "like"},
        )

    def test_initialize_migrates_existing_projects_for_archiving(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                "CREATE TABLE projects ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL UNIQUE, "
                "description TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        legacy_db = Database(legacy_path)
        legacy_db.initialize()
        with sqlite3.connect(legacy_path) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(projects)")
            }
        self.assertIn("archived_at", columns)

    def test_crud_search_stats_and_cascade(self) -> None:
        project_id = self.db.create_project("测试项目", "仅供测试")
        material_id = self.db.create_material(
            project_id,
            "text",
            original_filename="test.txt",
            consent_status="confirmed",
            processing_status="ready",
        )
        segment_id = self.db.create_segment(
            material_id,
            1,
            "模拟参与者认为验证码提示不够明显。",
            locator="第1段",
            pii_flags=["phone"],
        )
        card_id = self.db.create_evidence_card(
            project_id,
            segment_id,
            "interview_statement",
            "验证码提示",
            "验证码提示不够明显",
            "一名模拟参与者需要更明显的提示。",
            source_locator="第1段",
            review_status="draft",
        )
        self.assertEqual(self.db.search_evidence(project_id, "验证码"), [])
        card = self.db.set_evidence_review_status(card_id, "approved")
        self.assertEqual(card["review_status"], "approved")
        results = self.db.search_evidence(project_id, "验证码")
        self.assertEqual([item["id"] for item in results], [card_id])
        self.assertEqual(results[0]["material_id"], material_id)

        claim_id = self.db.create_claim(
            project_id,
            "所有人都认为提示不明显。",
            missing_evidence=["缺少代表性样本"],
            rule_flags=["强量词"],
        )
        self.db.link_claim_evidence(
            claim_id,
            card_id,
            "support",
            review_status="approved",
        )
        task_id = self.db.create_followup_task(
            claim_id, "补充访谈", recommended_action="扩大样本"
        )
        self.assertEqual(
            self.db.get_claim(claim_id)["missing_evidence"],
            ["缺少代表性样本"],
        )
        self.assertEqual(len(self.db.list_claim_evidence_links(claim_id)), 1)
        self.db.set_followup_task_status(
            task_id, "done", completion_material_id=material_id
        )
        self.assertEqual(
            self.db.get_followup_task(task_id)["status"], "done"
        )

        stats = self.db.get_project_stats(project_id)
        self.assertEqual(stats["materials"], 1)
        self.assertEqual(stats["approved_evidence_cards"], 1)
        self.assertEqual(stats["claims"], 1)
        self.assertEqual(stats["open_followup_tasks"], 0)

        self.assertTrue(self.db.delete_project(project_id))
        self.assertIsNone(self.db.get_material(material_id))
        self.assertIsNone(self.db.get_evidence_card(card_id))
        self.assertIsNone(self.db.get_claim(claim_id))

    def test_rejects_cross_project_evidence_links(self) -> None:
        project_a = self.db.create_project("项目A")
        project_b = self.db.create_project("项目B")
        material_id = self.db.create_material(project_a, "text")
        segment_id = self.db.create_segment(material_id, 1, "测试")
        card_id = self.db.create_evidence_card(
            project_a,
            segment_id,
            "field_observation",
            "测试",
            "测试",
            "测试",
        )
        claim_id = self.db.create_claim(project_b, "测试结论")
        with self.assertRaises(ValueError):
            self.db.link_claim_evidence(claim_id, card_id, "support")

    def test_demo_seed_and_supplement_are_idempotent(self) -> None:
        first_project_id = create_demo_project(self.db)
        second_project_id = create_demo_project(self.db)
        self.assertEqual(first_project_id, second_project_id)
        self.assertEqual(
            self.db.get_project(first_project_id)["name"], DEMO_PROJECT_NAME
        )

        initial_stats = self.db.get_project_stats(first_project_id)
        self.assertEqual(initial_stats["materials"], 3)
        self.assertEqual(initial_stats["approved_evidence_cards"], 3)
        self.assertEqual(initial_stats["claims"], 1)
        self.assertEqual(initial_stats["open_followup_tasks"], 1)
        for material in self.db.list_materials(first_project_id):
            self.assertEqual(material["consent_status"], "confirmed")
            self.assertEqual(material["is_fictional"], 1)
            self.assertIn("虚构测试数据", material["notes"])

        first_material_id = add_demo_supplement(self.db, first_project_id)
        second_material_id = add_demo_supplement(self.db, first_project_id)
        self.assertEqual(first_material_id, second_material_id)
        final_stats = self.db.get_project_stats(first_project_id)
        self.assertEqual(final_stats["materials"], 4)
        self.assertEqual(final_stats["approved_evidence_cards"], 4)
        self.assertEqual(final_stats["open_followup_tasks"], 0)

        claim = self.db.list_claims(first_project_id)[0]
        relations = {
            link["relation"]
            for link in self.db.list_claim_evidence_links(claim["id"])
        }
        self.assertIn("contradict", relations)


if __name__ == "__main__":
    unittest.main()
