from __future__ import annotations

import unittest

from qingji.metadata import infer_material_metadata


class MetadataSuggestionTests(unittest.TestCase):
    def test_extracts_explicit_role_context_and_date(self) -> None:
        suggestion = infer_material_metadata(
            "来源角色：工作人员\n采集场景：新沂市人民法院现场调研\n采集日期：2026年8月24日\n"
            "工作人员介绍了线上服务流程。",
            "调研记录.txt",
        )

        self.assertEqual(suggestion.source_role, "工作人员")
        self.assertEqual(suggestion.context, "新沂市人民法院现场调研")
        self.assertEqual(suggestion.captured_at.isoformat(), "2026-08-24")

    def test_uses_filename_only_when_it_contains_activity_signal(self) -> None:
        suggestion = infer_material_metadata(
            "官网公开资料：本地服务平台说明。",
            "数字法治_新沂徐州线上调研成果报告.docx",
        )

        self.assertEqual(suggestion.source_role, "正式记录")
        self.assertIn("新沂徐州线上调研", suggestion.context)

    def test_does_not_invent_missing_metadata(self) -> None:
        suggestion = infer_material_metadata("这是一段没有来源和时间的正文。", "材料.txt")

        self.assertIsNone(suggestion.source_role)
        self.assertEqual(suggestion.context, "")
        self.assertIsNone(suggestion.captured_at)


if __name__ == "__main__":
    unittest.main()
