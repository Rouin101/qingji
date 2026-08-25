"""Streamlit AppTest smoke tests — every page must load without exceptions.

The data directory is redirected to a temporary folder for the whole module.
The explicit settings refresh also keeps this true when another test module
has already imported Qingji before this one.

Pages are visited through the real multi-page entry point so ``st.page_link``
and ``st.switch_page`` resolve like they do inside the running app.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="qingji_apptest_")
os.environ["QINGJI_DATA_DIR"] = _TEST_DATA_DIR
os.environ["QINGJI_LLM_ENABLED"] = "false"

import qingji.config as qingji_config  # noqa: E402
import qingji.db as qingji_db  # noqa: E402

qingji_config.settings = qingji_config.Settings.from_env()
qingji_db.settings = qingji_config.settings

from streamlit.testing.v1 import AppTest  # noqa: E402
from qingji.backup import inspect_project_backup  # noqa: E402
from qingji.diagnostics import RETRIEVAL_DIAGNOSTIC_VERSION  # noqa: E402
from qingji.llm import (  # noqa: E402
    EvidenceCardGenerationAdvice,
    EvidenceCardGenerationItem,
)
from qingji.ui import format_datetime, get_database  # noqa: E402
from qingji.workflow import (  # noqa: E402
    check_and_store_claim,
    import_text_material,
)

get_database.clear()

PAGES = [
    "pages/1_材料与证据.py",
    "pages/2_结论核验.py",
    "pages/3_成果与缺口.py",
]


def _generate_test_evidence_cards(
    segments, *, max_cards: int, **_kwargs
) -> EvidenceCardGenerationAdvice:
    return EvidenceCardGenerationAdvice(
        cards=tuple(
            EvidenceCardGenerationItem(
                segment_ids=(int(segment["id"]),),
                title=f"测试材料片段 {index}",
                summary="模型从该片段中抽取了可供人工复核的明确事实。",
                evidence_type="formal_record",
                uncertainties=(),
            )
            for index, segment in enumerate(segments[:max_cards], start=1)
        ),
        uncertainties=(),
        model="test-model",
        chunk_count=1,
    )


def _import_model_generated_material(*args, **kwargs):
    with patch(
        "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
    ), patch(
        "qingji.workflow.request_evidence_card_generation",
        side_effect=_generate_test_evidence_cards,
    ):
        return import_text_material(*args, **kwargs)


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
        self.assertTrue(any("勾选" in item.value for item in app.warning))

    def test_material_consent_defaults_to_confirmed(self) -> None:
        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        self.assertEqual(
            app.radio(key="material_consent_choice").value,
            "confirmed",
        )
        self.assertEqual(
            app.radio(key="batch_consent_choice").value,
            "confirmed",
        )

    def test_evidence_review_defaults_to_approved(self) -> None:
        database = get_database()
        project_id = database.create_project("证据审核默认状态检查")
        imported = _import_model_generated_material(
            database,
            project_id,
            "受访者表示线上办事时需要人工帮助。",
            original_filename="审核默认状态.txt",
            source_role="受访者",
            context="审核默认状态检查场景",
            captured_at="2026-08-23",
            consent_status="confirmed",
            custom_sensitive_terms=None,
            is_fictional=False,
        )
        card_id = int(imported.evidence_card_ids[0])

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = project_id
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(app.radio(key=f"decision_{card_id}").value, "approved")

    def test_bulk_approval_approves_authorized_draft_cards(self) -> None:
        database = get_database()
        project_id = database.create_project("批量审核页面检查")
        imported = _import_model_generated_material(
            database,
            project_id,
            "受访者表示线上办事时需要人工帮助。",
            original_filename="批量审核材料.txt",
            source_role="受访者",
            context="批量审核页面检查场景",
            captured_at="2026-08-23",
            consent_status="confirmed",
            custom_sensitive_terms=None,
            is_fictional=False,
        )
        card_id = int(imported.evidence_card_ids[0])

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = project_id
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        app.checkbox(key=f"bulk_review_confirm_{project_id}").set_value(True)
        app.button(key=f"bulk_approve_evidence_{project_id}").click()
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(database.get_evidence_card(card_id)["review_status"], "approved")

    def test_claim_form_keeps_input_after_validation_error(self) -> None:
        app = self._open_claim_page()
        invalid_claim = "超出长度限制的结论。" * 80
        app.text_area[0].set_value(invalid_claim)
        app.button(key="FormSubmitter:claim_check_form-开始核验").click()
        app.run()

        self.assertEqual(app.exception, [])
        self.assertEqual(app.text_area[0].value, invalid_claim)
        self.assertTrue(any("500 字以内" in item.value for item in app.error))

    def test_batch_material_import_creates_one_material_per_file(self) -> None:
        database = get_database()
        project_id = database.create_project("批量材料页面检查")

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = project_id
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        app.file_uploader(key="batch_material_files").set_value(
            [
                ("批量材料A.txt", "受访者甲表示流程清楚。".encode(), "text/plain"),
                ("批量材料B.md", "受访者乙表示需要帮助。".encode(), "text/markdown"),
            ]
        )
        app.text_input(key="batch_context").set_value("批量材料页面检查场景")
        app.radio(key="batch_consent_choice").set_value("confirmed")
        app.checkbox(key="batch_material_confirmed").set_value(True)
        app.button(
            key="FormSubmitter:batch_material_import_form-批量本地检查并生成证据卡"
        ).click()
        app.run()

        self.assertEqual(app.exception, [])
        materials = database.list_materials(project_id)
        self.assertEqual(
            {item["original_filename"] for item in materials},
            {"批量材料A.txt", "批量材料B.md"},
        )
        self.assertTrue(any("已处理 2 个文件" in item.value for item in app.success))

    def test_single_file_upload_is_locked_after_selection(self) -> None:
        database = get_database()
        project_id = database.create_project("单文件上传锁定页面检查")

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = project_id
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        app.file_uploader(key="single_material_file").set_value(
            ("锁定上传.txt", "受访者表示线上服务方便。".encode(), "text/plain")
        )
        app.run()

        self.assertEqual(app.exception, [])
        uploader = app.file_uploader(key="single_material_file")
        self.assertTrue(uploader.disabled)
        self.assertIsNotNone(uploader.value)
        self.assertFalse(
            any(item.key == "clear_single_material_file" for item in app.button)
        )

    def test_switching_project_resets_material_import_draft_and_upload_lock(self) -> None:
        database = get_database()
        first_project_id = database.create_project("材料导入状态项目甲")
        second_project_id = database.create_project("材料导入状态项目乙")

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = first_project_id
        app.switch_page("pages/1_材料与证据.py")
        app.run()

        app.file_uploader(key="single_material_file").set_value(
            ("项目甲材料.txt", "项目甲的正文不应留到项目乙。".encode(), "text/plain")
        )
        app.run()
        self.assertTrue(app.file_uploader(key="single_material_file").disabled)
        self.assertIn("项目甲的正文", app.text_area(key="material_draft_text").value)

        app.session_state["qingji_project_id"] = second_project_id
        app.run()

        self.assertEqual(app.exception, [])
        uploader = app.file_uploader(key="single_material_file")
        self.assertFalse(uploader.disabled)
        self.assertIsNone(uploader.value)
        self.assertEqual(app.text_area(key="material_draft_text").value, "")
        self.assertEqual(
            app.text_input(key="material_filename").value,
            "手工录入_项目记录.txt",
        )

    def test_bulk_regeneration_button_replaces_per_card_buttons(self) -> None:
        database = get_database()
        project_id = database.create_project("批量拒绝卡重新生成页面检查")
        imported = _import_model_generated_material(
            database,
            project_id,
            "正式记录显示现场安排了人工协助窗口。",
            original_filename="拒绝卡重新生成测试.txt",
            source_role="正式记录",
            context="批量拒绝卡重新生成页面检查场景",
            captured_at="2026-08-25",
            consent_status="confirmed",
            custom_sensitive_terms=None,
            is_fictional=False,
        )
        database.set_evidence_review_status(
            int(imported.evidence_card_ids[0]), "rejected"
        )
        configured = qingji_config.LLMSettings(
            enabled=True,
            base_url="https://example.test/v1",
            api_key="test-key",
            model="test-model",
            timeout_seconds=30,
            max_context_chars=12000,
        )

        with patch.object(qingji_config, "llm_settings", configured):
            app = AppTest.from_file("app.py", default_timeout=30)
            app.run()
            app.session_state["qingji_project_id"] = project_id
            app.switch_page("pages/1_材料与证据.py")
            app.run()

        self.assertEqual(app.exception, [])
        self.assertTrue(
            any(
                item.label == "一键根据拒绝理由重新生成全部被拒绝卡片"
                for item in app.button
            )
        )
        self.assertFalse(
            any(item.label == "根据拒绝理由重新生成待审核卡" for item in app.button)
        )

    def test_followup_task_can_be_completed_and_reopened(self) -> None:
        database = get_database()
        project_id = database.create_project("补证任务页面检查")
        imported = import_text_material(
            database,
            project_id,
            "受访者甲表示已完成线上申请。",
            original_filename="补证完成材料.txt",
            source_role="受访者",
            context="补证任务页面检查场景",
            captured_at="2026-08-22",
            consent_status="confirmed",
            custom_sensitive_terms=None,
            is_fictional=False,
        )
        claim_id = database.create_claim(
            project_id,
            "待补证页面检查结论。",
            reason="需要补充材料。",
        )
        task_id = database.create_followup_task(
            claim_id,
            "补充一份授权材料",
            recommended_action="导入并确认一份材料。",
        )

        app = AppTest.from_file("app.py", default_timeout=30)
        app.run()
        app.session_state["qingji_project_id"] = project_id
        app.switch_page("pages/3_成果与缺口.py")
        app.run()

        app.selectbox(key=f"completion_material_{task_id}").set_value(
            imported.material_id
        )
        app.button(
            key=f"FormSubmitter:complete_task_{task_id}-标记为已完成"
        ).click()
        app.run()

        self.assertEqual(app.exception, [])
        completed = database.get_followup_task(task_id)
        self.assertEqual(completed["status"], "done")
        self.assertEqual(
            int(completed["completion_material_id"]), imported.material_id
        )

        app.button(key=f"reopen_task_{task_id}").click()
        app.run()

        self.assertEqual(app.exception, [])
        reopened = database.get_followup_task(task_id)
        self.assertEqual(reopened["status"], "open")
        self.assertIsNone(reopened["completion_material_id"])

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
        imported = _import_model_generated_material(
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
