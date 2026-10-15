"""Pilot baseline summary and export tests."""

from __future__ import annotations

import unittest

from qingji.pilot import (
    export_pilot_baseline_markdown,
    export_pilot_sessions_csv,
    summarize_pilot_sessions,
)


class PilotMetricsTests(unittest.TestCase):
    def test_summary_only_compares_completed_rows_with_both_durations(self) -> None:
        rows = [
            {
                "status": "completed",
                "manual_minutes": 50,
                "qingji_minutes": 30,
                "overclaim_alerts": 3,
                "adopted_alerts": 2,
                "false_positives": 1,
                "false_negatives": 0,
                "completed_followups": 2,
            },
            {
                "status": "completed",
                "manual_minutes": None,
                "qingji_minutes": 20,
                "overclaim_alerts": 1,
                "adopted_alerts": 1,
                "false_positives": 0,
                "false_negatives": 1,
                "completed_followups": 0,
            },
            {
                "status": "in_progress",
                "manual_minutes": 40,
                "qingji_minutes": 25,
                "overclaim_alerts": 0,
                "adopted_alerts": 0,
                "false_positives": 0,
                "false_negatives": 0,
                "completed_followups": 1,
            },
        ]

        summary = summarize_pilot_sessions(rows)

        self.assertEqual(summary["sessions"], 3)
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["comparable"], 1)
        self.assertEqual(summary["manual_minutes"], 50)
        self.assertEqual(summary["qingji_minutes"], 30)
        self.assertEqual(summary["overclaim_alerts"], 4)
        self.assertEqual(summary["false_negatives"], 1)
        self.assertEqual(summary["completed_followups"], 3)

    def test_csv_is_utf8_bom_and_uses_readable_status(self) -> None:
        content = export_pilot_sessions_csv(
            [
                {
                    "session_code": "试用-01",
                    "session_date": "2026-09-22",
                    "operator_alias": "P01",
                    "status": "completed",
                }
            ]
        )

        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        decoded = content.decode("utf-8-sig")
        self.assertIn("会话编号", decoded)
        self.assertIn("试用-01", decoded)
        self.assertIn("已完成", decoded)

    def test_baseline_excludes_unfinished_and_reports_missing_durations(self) -> None:
        rows = [
            {
                "status": "completed",
                "manual_minutes": 50,
                "qingji_minutes": 30,
                "overclaim_alerts": 2,
                "false_positives": 1,
                "confusion_notes": "入口不好找",
            },
            {
                "status": "completed",
                "manual_minutes": None,
                "qingji_minutes": 20,
                "overclaim_alerts": 1,
            },
            {
                "status": "in_progress",
                "manual_minutes": 80,
                "qingji_minutes": 10,
                "overclaim_alerts": 9,
            },
        ]

        report = export_pilot_baseline_markdown("试用项目", rows).decode("utf-8")

        self.assertIn("耗时可比：1", report)
        self.assertIn("原流程合计：50 分钟；青迹流程合计：30 分钟", report)
        self.assertIn("净差：+20 分钟", report)
        self.assertIn("越界提醒：3", report)
        self.assertIn("已完成但缺少至少一项耗时：1", report)
        self.assertIn("未完成或已暂停会话：1", report)
        self.assertNotIn("越界提醒：12", report)

    def test_baseline_without_comparable_sessions_does_not_claim_savings(self) -> None:
        report = export_pilot_baseline_markdown(
            "试用项目", [{"status": "completed", "manual_minutes": None}]
        ).decode("utf-8")

        self.assertIn("暂无可比耗时，不计算节省时间", report)
        self.assertNotIn("净差：", report)


if __name__ == "__main__":
    unittest.main()
