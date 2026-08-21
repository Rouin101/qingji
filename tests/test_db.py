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
                "evidence_review_events",
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
            connection.execute(
                "CREATE TABLE agent_runs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "project_id INTEGER, run_type TEXT NOT NULL, "
                "status TEXT NOT NULL, input_json TEXT NOT NULL DEFAULT '{}', "
                "output_json TEXT NOT NULL DEFAULT '{}', "
                "error_message TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL, finished_at TEXT)"
            )
        legacy_db = Database(legacy_path)
        legacy_db.initialize()
        with sqlite3.connect(legacy_path) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(projects)")
            }
        self.assertIn("archived_at", columns)
        with sqlite3.connect(legacy_path) as connection:
            agent_run_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(agent_runs)")
            }
        self.assertIn("claim_id", agent_run_columns)
        with sqlite3.connect(legacy_path) as connection:
            review_event_table = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'evidence_review_events'"
            ).fetchone()
        self.assertIsNotNone(review_event_table)

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

    def test_evidence_review_events_are_project_scoped_and_immutable(self) -> None:
        project_a = self.db.create_project("审核项目A")
        project_b = self.db.create_project("审核项目B")
        material_a = self.db.create_material(project_a, "text")
        segment_a = self.db.create_segment(material_a, 1, "测试")
        card_a = self.db.create_evidence_card(
            project_a,
            segment_a,
            "field_observation",
            "原标题",
            "摘录",
            "原摘要",
        )
        claim_a = self.db.create_claim(project_a, "项目A结论")
        claim_b = self.db.create_claim(project_b, "项目B结论")

        first = self.db.create_evidence_review_event(
            card_a,
            before={"title": "原标题", "review_status": "draft"},
            after={"title": "新标题", "review_status": "approved"},
            change_reason="已核对来源与授权。",
            rechecked_claim_ids=[claim_a],
        )
        second = self.db.create_evidence_review_event(
            card_a,
            before={"title": "新标题", "review_status": "approved"},
            after={"title": "再次修改", "review_status": "approved"},
            change_reason="修正摘要表述。",
        )

        history = self.db.list_evidence_review_events(
            project_a, evidence_card_id=card_a
        )
        self.assertEqual([item["id"] for item in history], [second, first])
        self.assertEqual(history[1]["before"]["title"], "原标题")
        self.assertEqual(history[1]["after"]["review_status"], "approved")
        self.assertEqual(history[1]["rechecked_claim_ids"], [claim_a])
        self.assertEqual(
            self.db.list_evidence_review_events(project_b), []
        )
        with self.assertRaises(ValueError):
            self.db.create_evidence_review_event(
                card_a,
                before={},
                after={},
                change_reason="错误跨项目记录",
                rechecked_claim_ids=[claim_b],
            )
        for invalid_limit in (0, 501, True, "2"):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises(ValueError):
                    self.db.list_evidence_review_events(
                        project_a, limit=invalid_limit
                    )
        self.assertFalse(hasattr(self.db, "update_evidence_review_event"))
        self.assertFalse(hasattr(self.db, "delete_evidence_review_event"))

    def test_update_apis_reject_parent_reassignment(self) -> None:
        project_a = self.db.create_project("项目A")
        project_b = self.db.create_project("项目B")
        material_a = self.db.create_material(project_a, "text")
        material_b = self.db.create_material(project_b, "text")
        segment_a = self.db.create_segment(material_a, 1, "A")
        segment_b = self.db.create_segment(material_b, 1, "B")
        evidence_a = self.db.create_evidence_card(
            project_a,
            segment_a,
            "field_observation",
            "A",
            "A",
            "A",
        )
        claim_a = self.db.create_claim(project_a, "A")
        claim_b = self.db.create_claim(project_b, "B")
        task_a = self.db.create_followup_task(claim_a, "A")

        attempts = {
            "material.project_id": lambda: self.db.update_material(
                material_a, project_id=project_b
            ),
            "segment.material_id": lambda: self.db.update_segment(
                segment_a, material_id=material_b
            ),
            "evidence.project_id": lambda: self.db.update_evidence_card(
                evidence_a, project_id=project_b
            ),
            "evidence.segment_id": lambda: self.db.update_evidence_card(
                evidence_a, segment_id=segment_b
            ),
            "claim.project_id": lambda: self.db.update_claim(
                claim_a, project_id=project_b
            ),
            "task.claim_id": lambda: self.db.update_followup_task(
                task_a, claim_id=claim_b
            ),
        }
        for field, attempt in attempts.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    attempt()

        self.assertEqual(self.db.get_material(material_a)["project_id"], project_a)
        self.assertEqual(self.db.get_segment(segment_a)["material_id"], material_a)
        evidence = self.db.get_evidence_card(evidence_a)
        self.assertEqual(evidence["project_id"], project_a)
        self.assertEqual(evidence["segment_id"], segment_a)
        self.assertEqual(self.db.get_claim(claim_a)["project_id"], project_a)
        self.assertEqual(self.db.get_followup_task(task_a)["claim_id"], claim_a)

    def test_followup_completion_material_must_share_claim_project(self) -> None:
        project_a = self.db.create_project("任务项目A")
        project_b = self.db.create_project("任务项目B")
        material_a = self.db.create_material(project_a, "text")
        material_b = self.db.create_material(project_b, "text")
        claim_a = self.db.create_claim(project_a, "A")

        with self.assertRaises(ValueError):
            self.db.create_followup_task(
                claim_a, "跨项目完成", completion_material_id=material_b
            )

        task_id = self.db.create_followup_task(
            claim_a, "同项目完成", completion_material_id=material_a
        )
        with self.assertRaises(ValueError):
            self.db.set_followup_task_status(
                task_id, "done", completion_material_id=material_b
            )
        task = self.db.get_followup_task(task_id)
        self.assertEqual(task["status"], "open")
        self.assertEqual(task["completion_material_id"], material_a)

        updated = self.db.set_followup_task_status(
            task_id, "done", completion_material_id=material_a
        )
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["completion_material_id"], material_a)

    def test_agent_run_claim_must_share_project(self) -> None:
        project_a = self.db.create_project("运行项目A")
        project_b = self.db.create_project("运行项目B")
        claim_a = self.db.create_claim(project_a, "A")

        run_id = self.db.create_agent_run(
            project_a, "claim_retrieval", claim_id=claim_a
        )
        self.assertEqual(
            self.db.get_latest_claim_run(claim_a, "claim_retrieval")["id"],
            run_id,
        )
        with self.assertRaises(ValueError):
            self.db.create_agent_run(
                project_b, "claim_retrieval", claim_id=claim_a
            )
        with self.assertRaises(ValueError):
            self.db.create_agent_run(
                project_a, "claim_retrieval", claim_id=999999
            )

    def test_project_run_history_is_ordered_filtered_and_limited(self) -> None:
        project_a = self.db.create_project("历史项目A")
        project_b = self.db.create_project("历史项目B")
        first = self.db.create_agent_run(project_a, "retrieval_eval")
        self.db.create_agent_run(project_a, "claim_retrieval")
        second = self.db.create_agent_run(project_a, "retrieval_eval")
        self.db.create_agent_run(project_b, "retrieval_eval")

        history = self.db.list_project_runs(
            project_a, "retrieval_eval", limit=10
        )
        self.assertEqual([run["id"] for run in history], [second, first])
        self.assertEqual(
            [run["id"] for run in self.db.list_project_runs(
                project_a, "retrieval_eval", limit=1
            )],
            [second],
        )
        for invalid_limit in (0, 501, True, "2"):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises(ValueError):
                    self.db.list_project_runs(
                        project_a, "retrieval_eval", limit=invalid_limit
                    )

    def test_claim_history_filters_search_and_stats(self) -> None:
        project_id = self.db.create_project("结论历史测试")
        supported_id = self.db.create_claim(
            project_id,
            "材料显示服务完成率达到 80%。",
            verdict="supported",
        )
        unsupported_id = self.db.create_claim(
            project_id,
            "所有受访者都认为流程简单。",
            verdict="unsupported",
        )
        contradicted_id = self.db.create_claim(
            project_id,
            "受访者一致认为流程困难。",
            verdict="contradicted",
        )

        unsupported = self.db.list_claims(
            project_id, verdict="unsupported"
        )
        self.assertEqual([item["id"] for item in unsupported], [unsupported_id])
        literal_percent = self.db.list_claims(project_id, query="80%")
        self.assertEqual(
            [item["id"] for item in literal_percent], [supported_id]
        )
        keyword = self.db.list_claims(project_id, query="流程")
        self.assertEqual(
            {item["id"] for item in keyword},
            {unsupported_id, contradicted_id},
        )

        self.assertEqual(
            self.db.get_claim_verdict_stats(project_id),
            {
                "supported": 1,
                "partially_supported": 0,
                "unsupported": 1,
                "contradicted": 1,
            },
        )

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
