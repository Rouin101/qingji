"""Custom project retrieval-evaluation import and execution tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qingji.db import Database
from qingji.evaluation import (
    build_eval_template,
    parse_eval_csv,
    run_project_retrieval_eval,
)
from qingji.retrieval_eval import RetrievalEvalCase
from qingji.workflow import import_text_material


class CustomEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "qingji.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _approved_card(self, project_id: int, text: str) -> int:
        imported = import_text_material(
            self.db,
            project_id,
            text,
            original_filename="评测材料.txt",
            source_role="受访者",
            context="自定义评测测试",
            captured_at="2026-08-19",
            consent_status="confirmed",
            custom_sensitive_terms=None,
            is_fictional=True,
        )
        card_id = imported.evidence_card_ids[0]
        self.db.set_evidence_review_status(card_id, "approved")
        return card_id

    def test_template_and_csv_parser_support_target_and_zero_hit(self) -> None:
        project_id = self.db.create_project("模板解析测试")
        card_id = self._approved_card(
            project_id, "验证码位置不明显，需要工作人员帮助。"
        )
        template = build_eval_template(
            self.db.list_evidence_cards(project_id)
        )

        cases = parse_eval_csv(template)

        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].expected_evidence_ids, (card_id,))
        self.assertFalse(cases[0].expect_no_relevant)
        self.assertTrue(cases[1].expect_no_relevant)

    def test_parser_rejects_ambiguous_or_incomplete_cases(self) -> None:
        header = (
            "name,category,query,expected_evidence_ids,"
            "expect_no_relevant\n"
        )
        with self.assertRaisesRegex(ValueError, "不能同时"):
            parse_eval_csv(
                header + "冲突,zero_hit,测试查询,E1,true\n"
            )
        with self.assertRaisesRegex(ValueError, "必须填写"):
            parse_eval_csv(
                header + "缺目标,custom,测试查询,,false\n"
            )

    def test_project_eval_runs_persists_and_blocks_cross_project_ids(self) -> None:
        project_id = self.db.create_project("当前项目")
        card_id = self._approved_card(
            project_id, "受访者表示验证码位置不明显，需要帮助。"
        )
        other_project_id = self.db.create_project("其他项目")
        other_card_id = self._approved_card(
            other_project_id, "另一项目的独立材料。"
        )
        cases = (
            RetrievalEvalCase(
                "目标召回",
                "custom",
                "验证码位置不明显，需要帮助。",
                expected_evidence_ids=(card_id,),
            ),
            RetrievalEvalCase(
                "无关查询",
                "zero_hit",
                "校园宿舍空调维修进度。",
                expect_no_relevant=True,
            ),
        )

        report = run_project_retrieval_eval(
            self.db, project_id, cases, top_k=3
        )

        self.assertEqual(report["passed_count"], 2)
        self.assertEqual(report["case_count"], 2)
        latest = self.db.get_latest_project_run(
            project_id, "retrieval_eval"
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest["output"]["passed_count"], 2)

        cross_project_case = (
            RetrievalEvalCase(
                "越权目标",
                "custom",
                "独立材料",
                expected_evidence_ids=(other_card_id,),
            ),
        )
        with self.assertRaisesRegex(ValueError, "不属于当前项目"):
            run_project_retrieval_eval(
                self.db, project_id, cross_project_case
            )


if __name__ == "__main__":
    unittest.main()
