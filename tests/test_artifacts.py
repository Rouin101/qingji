"""Regression tests for trusted Markdown, DOCX and PDF project exports."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from qingji.artifacts import EXPORT_FORMATS, write_export_files
from qingji.export import render_project_markdown
from qingji.presentation import export_project_report_files


SAMPLE_MARKDOWN = """# 青迹可信证据导出｜导出测试项目

> 本文档仅说明当前材料的支持程度。

## 已核验结论

### C1｜线上服务减少了往返时间。

- 核验结果：已有支持
- 支持证据：E1

## 证据目录

### E1｜受访者陈述

> 受访者表示线上预约减少了来回跑的次数。

## 补证任务

- **补充反例材料**（对应 C1 · 待补证）
  - 建议行动：补充不同使用群体的体验记录。
"""


class ExportArtifactTests(unittest.TestCase):
    def test_all_selected_formats_are_written_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            files = write_export_files(
                SAMPLE_MARKDOWN,
                42,
                EXPORT_FORMATS,
                output_root=temporary_directory,
            )

            self.assertEqual(set(files), set(EXPORT_FORMATS))
            self.assertEqual(
                files["markdown"].read_text(encoding="utf-8"),
                SAMPLE_MARKDOWN,
            )
            self.assertEqual(files["markdown"].parent.name, "markdown")

            document = Document(files["docx"])
            body_text = "\n".join(item.text for item in document.paragraphs)
            self.assertIn("线上服务减少了往返时间", body_text)

            reader = PdfReader(files["pdf"])
            self.assertGreaterEqual(len(reader.pages), 1)
            self.assertGreater(files["pdf"].stat().st_size, 1000)

    def test_selected_format_controls_written_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            files = write_export_files(
                SAMPLE_MARKDOWN,
                7,
                ["pdf"],
                output_root=Path(temporary_directory),
            )
            self.assertEqual(set(files), {"pdf"})
            self.assertTrue(files["pdf"].is_file())
            self.assertFalse(
                (Path(temporary_directory) / "markdown").exists()
            )

    def test_confirmed_draft_evidence_is_exported_but_rejected_evidence_is_not(self) -> None:
        rendered = render_project_markdown(
            {"id": 1, "name": "资格规则测试"},
            [{"id": 1, "claim_text": "测试结论", "verdict": "supported"}],
            [
                {
                    "id": 11,
                    "review_status": "draft",
                    "consent_status": "confirmed",
                    "title": "待复核但可引用",
                    "quote": "授权后的待复核证据。",
                },
                {
                    "id": 12,
                    "review_status": "rejected",
                    "consent_status": "confirmed",
                    "title": "已排除证据",
                    "quote": "不应导出的证据。",
                },
            ],
            [
                {"claim_id": 1, "evidence_card_id": 11, "relation": "support"},
                {"claim_id": 1, "evidence_card_id": 12, "relation": "support"},
            ],
        )
        self.assertIn("E11", rendered)
        self.assertIn("待复核但可引用", rendered)
        self.assertNotIn("E12", rendered)
        self.assertNotIn("已排除证据", rendered)
    def test_report_profile_exports_only_selected_findings(self) -> None:
        class FakeDatabase:
            def get_project(self, _project_id):
                return {"id": 9, "name": "报告筛选项目", "description": "项目说明"}

            def list_claims(self, _project_id):
                return [
                    {"id": 1, "claim_text": "选中结论", "safe_rewrite": "选中结论", "reason": "有材料支持", "verdict": "supported"},
                    {"id": 2, "claim_text": "未选结论", "safe_rewrite": "未选结论", "reason": "不应进入", "verdict": "unsupported"},
                ]

            def list_followup_tasks(self, project_id=None):
                return [
                    {"id": 10, "title": "选中任务", "recommended_action": "补充材料", "status": "open"},
                    {"id": 11, "title": "未选任务", "recommended_action": "不应进入", "status": "open"},
                ]

            def list_materials(self, _project_id):
                return [{"id": 1, "captured_at": "2026-08-28", "original_filename": "访谈记录.txt", "source_role": "受访者"}]

            def list_evidence_cards(self, _project_id):
                return [{"id": 21, "review_status": "draft", "consent_status": "confirmed", "title": "支持证据", "quote": "支持选中结论。", "source_role": "受访者", "source_locator": "第 1 段"}]

            def list_claim_evidence_links(self, claim_id):
                return [{"claim_id": 1, "evidence_card_id": 21, "relation": "support"}] if claim_id == 1 else []

        with tempfile.TemporaryDirectory() as temporary_directory:
            files = export_project_report_files(
                FakeDatabase(), 9, ["markdown", "docx", "pdf"],
                profile="report", title="自定义成果报告", team_name="实践团队",
                author="测试作者", report_date="2026-08-28",
                claim_ids=[1], task_ids=[10], output_root=temporary_directory,
            )
            rendered = files["markdown"].read_text(encoding="utf-8")
            self.assertIn("自定义成果报告", rendered)
            self.assertIn("选中结论", rendered)
            self.assertIn("选中任务", rendered)
            self.assertNotIn("未选结论", rendered)
            self.assertNotIn("未选任务", rendered)
            self.assertTrue(files["docx"].is_file())
            self.assertTrue(files["pdf"].is_file())
    def test_empty_or_unknown_selection_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            write_export_files(SAMPLE_MARKDOWN, 1, [])
        with self.assertRaises(ValueError):
            write_export_files(SAMPLE_MARKDOWN, 1, ["html"])


if __name__ == "__main__":
    unittest.main()