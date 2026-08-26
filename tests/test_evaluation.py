"""Custom project retrieval-evaluation import and execution tests."""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from qingji.llm import LLMConfigurationError
from qingji.db import Database
from qingji.evaluation import (
    MAX_EVAL_FILE_BYTES,
    build_eval_case_set_id,
    build_eval_history_rows,
    build_eval_template,
    build_evidence_set_id,
    export_eval_run_csv,
    export_eval_run_markdown,
    parse_eval_csv,
    run_project_retrieval_eval,
)
from qingji.diagnostics import RETRIEVAL_DIAGNOSTIC_VERSION
from qingji.retrieval_eval import RetrievalEvalCase
from qingji.workflow import import_text_material


def _full_coverage_advice(segments, **_kwargs):
    cards = tuple(
        SimpleNamespace(
            segment_ids=(int(segment["id"]),),
            title="模型片段卡",
            summary="模型根据该脱敏片段生成的可复核摘要。",
            evidence_type="formal_record",
        )
        for segment in segments
    )
    return SimpleNamespace(
        cards=cards,
        discarded_card_count=0,
        as_dict=lambda: {"cards": len(cards), "model": "test-model"},
    )

class CustomEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "qingji.db")
        self.db.initialize()
        self._model_config_patcher = patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        )
        self._claim_review_patcher = patch(
            "qingji.workflow.request_claim_evidence_review",
            side_effect=LLMConfigurationError("test fallback"),
        )
        self._model_cards_patcher = patch(
            "qingji.workflow.request_evidence_card_generation",
            side_effect=_full_coverage_advice,
        )
        self._model_config_patcher.start()
        self._model_cards_patcher.start()
        self._claim_review_patcher.start()

    def tearDown(self) -> None:
        self._claim_review_patcher.stop()
        self._model_cards_patcher.stop()
        self._model_config_patcher.stop()
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
        self.assertEqual(parse_eval_csv(template.decode("utf-8")), cases)

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
        with self.assertRaisesRegex(ValueError, "列数超过表头"):
            parse_eval_csv(
                header + "坏行,custom,未转义,逗号,E1,false\n"
            )
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            parse_eval_csv(b"x" * (MAX_EVAL_FILE_BYTES + 1))

    def test_case_set_fingerprint_is_order_independent(self) -> None:
        first = RetrievalEvalCase(
            "目标", "custom", "测试查询", expected_evidence_ids=(3, 1)
        )
        second = RetrievalEvalCase(
            "零命中", "zero_hit", "无关查询", expect_no_relevant=True
        )
        self.assertEqual(
            build_eval_case_set_id((first, second)),
            build_eval_case_set_id((second, first)),
        )
        changed = RetrievalEvalCase(
            "目标", "custom", "另一查询", expected_evidence_ids=(1, 3)
        )
        self.assertNotEqual(
            build_eval_case_set_id((first, second)),
            build_eval_case_set_id((changed, second)),
        )

        evidence_a = {
            "id": 2,
            "title": "标题A",
            "quote": "摘录A",
            "summary": "摘要A",
            "context": "场景A",
            "source_role": "受访者",
            "review_status": "approved",
            "consent_status": "confirmed",
        }
        evidence_b = {
            **evidence_a,
            "id": 1,
            "title": "标题B",
            "quote": "摘录B",
        }
        evidence_set_id = build_evidence_set_id((evidence_a, evidence_b))
        self.assertEqual(
            evidence_set_id,
            build_evidence_set_id((evidence_b, evidence_a)),
        )
        self.assertNotEqual(
            evidence_set_id,
            build_evidence_set_id(
                ({**evidence_a, "summary": "内容已变更"}, evidence_b)
            ),
        )
        self.assertNotEqual(
            evidence_set_id, build_evidence_set_id((evidence_a,))
        )
        self.assertEqual(
            evidence_set_id,
            build_evidence_set_id(
                (
                    evidence_a,
                    evidence_b,
                    {**evidence_a, "id": 3, "review_status": "draft"},
                )
            ),
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
        self.assertTrue(report["case_set_id"].startswith("cs_"))
        self.assertTrue(report["evidence_set_id"].startswith("es_"))
        self.assertEqual(
            report["retrieval_version"], RETRIEVAL_DIAGNOSTIC_VERSION
        )
        latest = self.db.get_latest_project_run(
            project_id, "retrieval_eval"
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest["output"]["passed_count"], 2)
        self.assertEqual(
            latest["input"]["evidence_set_id"], report["evidence_set_id"]
        )
        self.assertEqual(
            latest["output"]["evidence_set_id"], report["evidence_set_id"]
        )

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

    def test_history_comparison_and_run_exports_are_safe(self) -> None:
        project_id = self.db.create_project("评测|历史")
        case = {
            "name": "=潜在公式<script>alert(1)</script>",
            "category": "custom<img src=x onerror=alert(1)>",
            "query": "查询|含换行\n第二行<script>alert(1)</script>&",
            "expected_evidence_ids": [1],
            "expect_no_relevant": False,
        }
        case_set_id = build_eval_case_set_id((case,))

        def create_run(
            *,
            passed: bool,
            top_k: int,
            evidence_set_id: str | None = "es_current",
        ) -> int:
            result = {
                **case,
                "passed": passed,
                "hit": passed,
                "expected_id_ranks": {"1": 1 if passed else None},
                "relevant_evidence_ids": [1] if passed else [],
                "relevant_count": int(passed),
            }
            input_data = {
                "top_k": top_k,
                "case_set_id": case_set_id,
                "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
                "relevance_threshold": 0.08,
                "cases": [case],
            }
            output_data = {
                "top_k": top_k,
                "case_set_id": case_set_id,
                "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
                "relevance_threshold": 0.08,
                "case_count": 1,
                "passed_count": int(passed),
                "pass_rate": float(passed),
                "categories": {
                    case["category"]: {
                        "case_count": 1,
                        "passed_count": int(passed),
                        "pass_rate": float(passed),
                    }
                },
                "results": [result],
            }
            if evidence_set_id is not None:
                input_data["evidence_set_id"] = evidence_set_id
                output_data["evidence_set_id"] = evidence_set_id
            return self.db.create_agent_run(
                project_id,
                "retrieval_eval",
                input_data=input_data,
                output_data=output_data,
            )

        older_id = create_run(passed=False, top_k=3)
        newer_id = create_run(passed=True, top_k=3)
        different_config_id = create_run(passed=True, top_k=5)
        different_evidence_id = create_run(
            passed=True, top_k=3, evidence_set_id="es_other"
        )
        legacy_id = create_run(
            passed=True, top_k=3, evidence_set_id=None
        )
        runs = self.db.list_project_runs(project_id, "retrieval_eval")
        rows = build_eval_history_rows(runs)
        newer = next(row for row in rows if row["run_id"] == newer_id)
        different = next(
            row for row in rows if row["run_id"] == different_config_id
        )
        different_evidence = next(
            row for row in rows if row["run_id"] == different_evidence_id
        )
        legacy = next(row for row in rows if row["run_id"] == legacy_id)
        self.assertEqual(newer["comparison_status"], "可直接比较")
        self.assertEqual(newer["comparable_to_run_id"], older_id)
        self.assertEqual(newer["pass_rate_delta"], 1.0)
        self.assertEqual(different["comparison_status"], "无可比历史")
        self.assertEqual(
            different_evidence["comparison_status"], "无可比历史"
        )
        self.assertEqual(legacy["evidence_set_id"], "未记录")
        self.assertEqual(legacy["comparison_status"], "证据集未记录，无法比较")

        selected_run = next(run for run in runs if run["id"] == newer_id)
        csv_bytes = export_eval_run_csv(selected_run)
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        csv_rows = list(
            csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
        )
        self.assertEqual(
            csv_rows[0]["name"],
            "'=潜在公式<script>alert(1)</script>",
        )
        self.assertEqual(csv_rows[0]["result"], "passed")
        self.assertEqual(csv_rows[0]["evidence_set_id"], "es_current")

        markdown = export_eval_run_markdown(
            selected_run, "评测|历史<script>alert(1)</script>&"
        )
        self.assertIn("不是事实正确率，也不是外部基准成绩", markdown)
        self.assertIn("评测\\|历史&lt;script&gt;alert(1)&lt;/script&gt;&amp;", markdown)
        self.assertIn(
            "查询\\|含换行<br>第二行&lt;script&gt;alert(1)&lt;/script&gt;&amp;",
            markdown,
        )
        self.assertIn("=潜在公式&lt;script&gt;alert(1)&lt;/script&gt;", markdown)
        self.assertIn("custom&lt;img src=x onerror=alert(1)&gt;", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("<img", markdown)
        self.assertIn("证据集：es_current", markdown)
        self.assertIn(f"运行编号：R{newer_id}", markdown)


if __name__ == "__main__":
    unittest.main()
