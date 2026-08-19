"""Retrieval-diagnostic persistence and regression-evaluation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qingji.db import Database
from qingji.demo import create_demo_project
from qingji.retrieval_eval import evaluate_retrieval
from qingji.workflow import check_and_store_claim, import_text_material


class RetrievalDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "qingji.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _import(self, project_id: int, text: str, consent: str) -> object:
        return import_text_material(
            self.db,
            project_id,
            text,
            original_filename=f"{consent}.txt",
            source_role="受访者",
            context="诊断测试",
            captured_at="2026-08-19",
            consent_status=consent,
            custom_sensitive_terms=None,
            is_fictional=True,
        )

    def test_claim_check_persists_ranking_and_exclusion_reasons(self) -> None:
        project_id = self.db.create_project("检索诊断测试")
        approved_import = self._import(
            project_id, "受访者表示验证码位置不明显，需要工作人员帮助。", "confirmed"
        )
        approved_card_id = approved_import.evidence_card_ids[0]
        self.db.set_evidence_review_status(approved_card_id, "approved")
        self._import(
            project_id, "另一条已授权但尚未审核的材料。", "confirmed"
        )
        self._import(project_id, "这条材料尚未确认授权。", "unknown")

        stored = check_and_store_claim(
            self.db, project_id, "受访者操作验证码时需要帮助。"
        )
        run = self.db.get_latest_claim_run(
            stored.claim_id, "claim_retrieval"
        )

        self.assertIsNotNone(run)
        diagnostic = run["output"]
        self.assertEqual(diagnostic["eligible_count"], 1)
        self.assertEqual(diagnostic["excluded_evidence_count"], 1)
        self.assertEqual(diagnostic["excluded_material_count"], 1)
        self.assertEqual(
            diagnostic["ranked_candidates"][0]["evidence_id"],
            approved_card_id,
        )
        self.assertTrue(
            diagnostic["ranked_candidates"][0]["matched_keywords"]
        )
        self.assertIn(
            diagnostic["ranked_candidates"][0]["decision"],
            {"support", "context", "contradict"},
        )

    def test_demo_retrieval_regression_hits_every_expected_card(self) -> None:
        project_id = create_demo_project(self.db)
        report = evaluate_retrieval(self.db, project_id, top_k=3)

        self.assertEqual(report["case_count"], 3)
        self.assertEqual(report["hit_count"], 3)
        self.assertEqual(report["hit_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
