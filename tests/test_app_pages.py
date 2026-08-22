"""Streamlit AppTest smoke tests — every page must load without exceptions.

The data directory is redirected to a temporary folder before any Qingji
module is imported.  ``unittest discover`` loads this module first
alphabetically, which lets the environment variable win for the whole process
without touching the developer's real ``data/`` folder.

Pages are visited through the real multi-page entry point so ``st.page_link``
and ``st.switch_page`` resolve like they do inside the running app.
"""

from __future__ import annotations

import os
import tempfile
import unittest

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="qingji_apptest_")
os.environ["QINGJI_DATA_DIR"] = _TEST_DATA_DIR

from streamlit.testing.v1 import AppTest  # noqa: E402
from qingji.backup import inspect_project_backup  # noqa: E402
from qingji.diagnostics import RETRIEVAL_DIAGNOSTIC_VERSION  # noqa: E402
from qingji.ui import format_datetime, get_database  # noqa: E402
from qingji.workflow import (  # noqa: E402
    check_and_store_claim,
    import_text_material,
)

PAGES = [
    "pages/1_材料与证据.py",
    "pages/2_结论核验.py",
    "pages/3_成果与缺口.py",
]


class AppPageSmokeTest(unittest.TestCase):
    @staticmethod
    def _open_claim_page() -> AppTest:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.switch_page("pages/2_结论核验.py")
        app.run()
        return app

    def test_all_pages_load_without_exceptions(self) -> None:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        self.assertEqual(
            app.exception,
            [],
            f"app.py raised: {app.exception}",
        )
        for path in PAGES:
            with self.subTest(page=path):
                app.switch_page(path)
                app.run()
                self.assertEqual(
                    app.exception,
                    [],
                    f"{path} raised: {app.exception}",
                )

    def test_material_form_keeps_input_after_validation_error(self) -> None:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        draft_text = "这段材料在校验失败后仍应保留。"
        app.text_area[0].set_value(draft_text)
        app.button[0].click()
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(app.text_area[0].value, draft_text)
        self.assertTrue(any("采集场景" in item.value for item in app.error))

    def test_project_backup_can_be_generated_from_overview(self) -> None:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        project_id = int(app.session_state["qingji_project_id"])

        app.button(key=f"generate_project_backup_{project_id}").click()
        app.run()

        self.assertEqual(app.exception, [])
        content = app.session_state["project_backup_payload"]
        inspection = inspect_project_backup(content)
        self.assertEqual(inspection.source_project_name, "数字便民服务体验调研")
        self.assertGreaterEqual(inspection.counts["materials"], 3)
        self.assertTrue(
            any("下载备份包" in button.label for button in app.get("download_button"))
        )

    def test_utc_timestamps_are_shown_in_shanghai_time(self) -> None:
        self.assertEqual(
            format_datetime("2026-08-20T03:15:00+00:00"),
            "2026-08-20 11:15",
        )

    def test_empty_claim_history_filter_hides_previous_details(self) -> None:
        app = self._open_claim_page()
        project_id = int(app.session_state["qingji_project_id"])
        query_key = f"claim_history_query_{project_id}"

        app.text_input(key=query_key).set_value("不可能命中的筛选词")
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(len(app.selectbox), 0)
        self.assertFalse(
            any("原始表述" in item.value for item in app.markdown),
            "筛选无结果时不应继续展示上一条结论详情",
        )

    def test_new_claim_resets_history_filters_and_becomes_active(self) -> None:
        app = self._open_claim_page()
        project_id = int(app.session_state["qingji_project_id"])
        verdict_key = f"claim_history_verdict_{project_id}"
        query_key = f"claim_history_query_{project_id}"

        app.text_input(key=query_key).set_value("不匹配新结论的旧筛选")
        app.run()

        new_claim = "这是一条用于验证筛选重置的新结论。"
        app.text_area[0].set_value(new_claim)
        app.button(key="FormSubmitter:claim_check_form-开始核验").click()
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(app.session_state[verdict_key], "all")
        self.assertEqual(app.session_state[query_key], "")
        self.assertEqual(app.text_input(key=query_key).value, "")
        self.assertEqual(app.segmented_control(key=verdict_key).value, "all")
        self.assertEqual(
            app.selectbox[0].value,
            int(app.session_state["active_claim_id"]),
        )
        self.assertTrue(
            any(
                "原始表述" in item.value and new_claim in item.value
                for item in app.markdown
            ),
            "新提交的结论应立即成为当前详情",
        )

    def test_claim_details_never_cross_project_boundary(self) -> None:
        app = self._open_claim_page()
        foreign_claim_id = int(app.session_state["active_claim_id"])
        database = get_database()
        project_id = database.create_project("跨项目结论隔离测试")

        app.session_state["qingji_project_id"] = project_id
        app.session_state["active_claim_id"] = foreign_claim_id
        app.run()

        self.assertEqual(app.exception, [])
        self.assertFalse(
            any("原始表述" in item.value for item in app.markdown),
            "当前项目无结论时不应显示其他项目详情",
        )

        local_claim_text = "这是当前项目自己的结论。"
        local_claim_id = database.create_claim(
            project_id,
            local_claim_text,
            reason="用于验证项目边界。",
        )
        app.session_state["active_claim_id"] = foreign_claim_id
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(
            int(app.session_state["active_claim_id"]), local_claim_id
        )
        self.assertEqual(app.selectbox[0].value, local_claim_id)
        self.assertTrue(
            any(
                "原始表述" in item.value and local_claim_text in item.value
                for item in app.markdown
            ),
            "应自动选择当前项目内的合法结论",
        )

    def test_evaluation_history_and_downloads_render(self) -> None:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        project_id = int(app.session_state["qingji_project_id"])
        database = get_database()
        case_set_id = "cs_apptest"
        evidence_set_id = "es_apptest"
        case = {
            "name": "页面评测",
            "category": "custom",
            "query": "验证码帮助",
            "expected_evidence_ids": [1],
            "expect_no_relevant": False,
        }
        common_input = {
            "top_k": 3,
            "case_set_id": case_set_id,
            "evidence_set_id": evidence_set_id,
            "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
            "relevance_threshold": 0.08,
            "cases": [case],
        }
        for passed in (False, True):
            database.create_agent_run(
                project_id,
                "retrieval_eval",
                input_data=common_input,
                output_data={
                    "top_k": 3,
                    "case_set_id": case_set_id,
                    "evidence_set_id": evidence_set_id,
                    "retrieval_version": RETRIEVAL_DIAGNOSTIC_VERSION,
                    "relevance_threshold": 0.08,
                    "case_count": 1,
                    "passed_count": int(passed),
                    "pass_rate": float(passed),
                    "categories": {
                        "custom": {
                            "case_count": 1,
                            "passed_count": int(passed),
                            "pass_rate": float(passed),
                        }
                    },
                    "results": [
                        {
                            **case,
                            "passed": passed,
                            "expected_id_ranks": {
                                "1": 1 if passed else None
                            },
                            "relevant_count": int(passed),
                        }
                    ],
                },
            )

        app.switch_page("pages/3_成果与缺口.py")
        app.run()

        self.assertEqual(app.exception, [])
        self.assertTrue(
            any("评测历史" in item.value for item in app.markdown)
        )
        labels = [item.label for item in app.download_button]
        self.assertIn("下载本次结果 CSV", labels)
        self.assertIn("下载本次结果 Markdown", labels)
        selection_key = f"retrieval_eval_selection_{project_id}"
        newest_run_id = database.list_project_runs(
            project_id, "retrieval_eval", limit=1
        )[0]["id"]
        self.assertEqual(app.selectbox(key=selection_key).value, newest_run_id)

    def test_rejecting_evidence_in_page_refreshes_existing_claim(self) -> None:
        database = get_database()
        project_id = database.create_project("页面撤回证据测试")
        imported = import_text_material(
            database,
            project_id,
            "一名模拟受访者使用线上办事平台时遇到困难，需要志愿者帮助。",
            original_filename="页面撤回测试.txt",
            source_role="模拟受访者",
            context="虚构页面回归测试",
            captured_at="2026-08-20",
            consent_status="confirmed",
            custom_sensitive_terms=None,
            is_fictional=True,
        )
        card_id = imported.evidence_card_ids[0]
        database.set_evidence_review_status(card_id, "approved")
        stored = check_and_store_claim(
            database,
            project_id,
            "有模拟受访者使用线上办事平台时遇到困难。",
        )
        self.assertEqual(database.get_claim(stored.claim_id)["verdict"], "supported")

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = project_id
        app.switch_page("pages/1_材料与证据.py")
        app.run()
        app.radio(key=f"decision_{card_id}").set_value("rejected")
        app.text_area(key=f"review_reason_{card_id}").set_value(
            "页面复核后撤回证据。"
        )
        app.button(
            key=f"FormSubmitter:evidence_edit_{card_id}-保存审核结果"
        ).click()
        app.run()

        self.assertEqual(app.exception, [])
        refreshed = database.get_claim(stored.claim_id)
        self.assertEqual(refreshed["verdict"], "unsupported")
        self.assertEqual(refreshed["evidence_links"], [])
        events = database.list_evidence_review_events(
            project_id, evidence_card_id=card_id
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["change_reason"], "页面复核后撤回证据。")
        self.assertTrue(
            any("审核历史（1）" in item.value for item in app.markdown)
        )
        self.assertTrue(
            all(
                task["status"] == "open"
                for task in database.list_followup_tasks(
                    claim_id=stored.claim_id
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
