"""End-to-end workflow tests for the text-only evidence chain."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from qingji.claims import validate_citation_ids
from qingji.db import Database
from qingji.llm import (
    ClaimEvidenceReviewAdvice,
    ClaimEvidenceReviewItem,
    EvidenceCardGenerationAdvice,
    EvidenceCardGenerationItem,
    EvidenceAdvice,
)
from qingji.models import (
    ConsentStatus,
    ReviewStatus,
    Verdict,
)
from qingji.workflow import (
    EvidenceReviewResult,
    StoredClaimResult,
    check_and_store_claim,
    import_text_material,
    list_regenerable_rejected_evidence_cards,
    regenerate_rejected_evidence_card,
    regenerate_rejected_material_evidence_cards,
    recheck_claim,
    review_evidence_card,
    review_evidence_cards,
)

DIFFICULTY_TEXT = (
    "模拟受访者A说：我使用线上办事平台提交材料时遇到了困难，"
    "不知道验证码填在哪里，后来在志愿者的帮助下完成了申请。"
)
OPPOSITE_TEXT = (
    "模拟受访者B说：我没有遇到困难，整个操作很顺利，几分钟就完成了。"
)
GROUP_CLAIM = "当地居民普遍认为线上办事平台使用困难。"
SIMPLE_CLAIM = "有模拟受访者使用线上办事平台时遇到困难。"


class WorkflowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.db")
        self.db.initialize()
        self.project_id = self.db.create_project("数字便民服务体验调研", "项目材料整理")
        self._llm_settings_patcher = patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=False)
        )
        self._llm_settings_patcher.start()
        self._card_generation_patcher = patch(
            "qingji.workflow.request_evidence_card_generation",
            side_effect=self._default_model_card_generation,
        )
        self._card_generation_patcher.start()

    def tearDown(self) -> None:
        self._card_generation_patcher.stop()
        self._llm_settings_patcher.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _default_model_card_generation(
        segments, *, max_cards: int, **_kwargs
    ) -> EvidenceCardGenerationAdvice:
        cards = tuple(
            EvidenceCardGenerationItem(
                segment_ids=(int(segment["id"]),),
                title=f"材料片段 {index}",
                summary="模型从该片段中抽取了可供人工复核的事实。",
                evidence_type="formal_record",
                uncertainties=(),
            )
            for index, segment in enumerate(segments[:max_cards], start=1)
        )
        return EvidenceCardGenerationAdvice(
            cards=cards,
            uncertainties=(),
            model="test-model",
            chunk_count=1,
        )

    def _import(
        self,
        text: str,
        *,
        source_role: str = "模拟受访者（虚构）",
        context: str = "虚构的线上办事体验访谈",
        consent: str = "confirmed",
        custom_terms: list[str] | None = None,
        filename: str = "虚构测试材料_访谈.txt",
    ) -> dict:
        with patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        ):
            result = import_text_material(
                self.db,
                self.project_id,
                text,
                original_filename=filename,
                source_role=source_role,
                context=context,
                captured_at="2026-07-15T09:10:00+08:00",
                consent_status=ConsentStatus(consent),
                custom_sensitive_terms=custom_terms,
                is_fictional=True,
            )
        for card_id in result.evidence_card_ids:
            self.db.set_evidence_review_status(card_id, "approved")
        return result

    def _approved_candidate_ids(self) -> set[int]:
        return {
            int(row["id"])
            for row in self.db.list_evidence_cards(
                self.project_id, review_status="approved"
            )
            if row.get("consent_status") == "confirmed"
        }

    def test_authorized_import_persists_material_segments_and_cards(self) -> None:
        result = self._import(DIFFICULTY_TEXT)

        self.assertGreater(result.material_id, 0)
        self.assertGreater(len(result.evidence_card_ids), 0)
        self.assertEqual(result.redacted_text, DIFFICULTY_TEXT)
        self.assertEqual(result.warnings, [])

        material = self.db.get_material(result.material_id)
        self.assertIsNotNone(material)
        self.assertEqual(material["consent_status"], "confirmed")
        self.assertEqual(material["processing_status"], "ready")
        self.assertEqual(material["is_fictional"], 1)
        self.assertIn("内部示例", material["notes"])

        segments = self.db.list_segments(result.material_id)
        self.assertGreaterEqual(len(segments), 1)
        self.assertEqual(segments[0]["redacted_text"], DIFFICULTY_TEXT)

        cards = self.db.list_evidence_cards(self.project_id)
        self.assertEqual(
            {int(card["id"]) for card in cards}, set(result.evidence_card_ids)
        )
        self.assertEqual(
            {card["review_status"] for card in cards}, {"approved"}
        )
        self.assertEqual(cards[0]["material_id"], result.material_id)

    def test_confirmed_import_uses_model_cards_and_reconstructs_exact_quotes(self) -> None:
        advice = EvidenceCardGenerationAdvice(
            cards=(
                EvidenceCardGenerationItem(
                    segment_ids=(1,),
                    title="平台操作困难",
                    summary="材料记录了线上操作中的具体困难。",
                    evidence_type="formal_record",
                    uncertainties=(),
                ),
                EvidenceCardGenerationItem(
                    segment_ids=(2,),
                    title="后续得到协助",
                    summary="材料记录了工作人员提供帮助。",
                    evidence_type="formal_record",
                    uncertainties=(),
                ),
            ),
            uncertainties=(),
            model="test-model",
            chunk_count=1,
        )

        with patch(
            "qingji.workflow.llm_settings",
            SimpleNamespace(configured=True),
        ), patch(
            "qingji.workflow.request_evidence_card_generation",
            return_value=advice,
        ) as generate_cards:
            result = import_text_material(
                self.db,
                self.project_id,
                "第一条事实。第二条事实。",
                original_filename="模型卡片测试.txt",
                source_role="正式记录",
                context="模型卡片测试场景",
                captured_at="2026-08-24",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=False,
            )

        generate_cards.assert_called_once()
        cards = [
            self.db.get_evidence_card(card_id)
            for card_id in result.evidence_card_ids
        ]
        self.assertEqual(
            [card["quote"] for card in cards],
            ["第一条事实。", "第二条事实。"],
        )
        self.assertEqual(
            self.db.get_latest_project_run(
                self.project_id, "llm_evidence_card_generation"
            )["status"],
            "completed",
        )

    def test_confirmed_import_keeps_valid_model_cards_after_overlap(self) -> None:
        advice = EvidenceCardGenerationAdvice(
            cards=(
                EvidenceCardGenerationItem(
                    segment_ids=(1,),
                    title="第一条事实",
                    summary="模型确认第一条是可审核的具体事实。",
                    evidence_type="formal_record",
                    uncertainties=(),
                ),
            ),
            uncertainties=(),
            model="test-model",
            chunk_count=1,
            discarded_card_count=1,
        )

        with patch(
            "qingji.workflow.llm_settings",
            SimpleNamespace(configured=True),
        ), patch(
            "qingji.workflow.request_evidence_card_generation",
            return_value=advice,
        ):
            result = import_text_material(
                self.db,
                self.project_id,
                "第一条事实。第二条事实。",
                original_filename="模型重叠卡片测试.txt",
                source_role="正式记录",
                context="模型重叠卡片测试场景",
                captured_at="2026-08-25",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=False,
            )

        cards = [
            self.db.get_evidence_card(card_id)
            for card_id in result.evidence_card_ids
        ]
        self.assertEqual(
            [card["quote"] for card in cards],
            ["第一条事实。"],
        )
        self.assertTrue(
            any("不会使用本地规则补卡" in warning for warning in result.warnings)
        )
        self.assertEqual(
            self.db.get_latest_project_run(
                self.project_id, "llm_evidence_card_generation"
            )["status"],
            "completed",
        )

    def test_long_import_compacts_model_card_candidates(self) -> None:
        advice = EvidenceCardGenerationAdvice(
            cards=(),
            uncertainties=(),
            model="test-model",
            chunk_count=1,
        )
        long_text = "\n\n".join(
            f"第{index}条记录：" + "用于验证长材料候选块合并。" * 25
            for index in range(32)
        )

        with patch(
            "qingji.workflow.llm_settings",
            SimpleNamespace(configured=True),
        ), patch(
            "qingji.workflow.request_evidence_card_generation",
            return_value=advice,
        ) as generate_cards:
            result = import_text_material(
                self.db,
                self.project_id,
                long_text,
                original_filename="长材料候选块测试.txt",
                source_role="正式记录",
                context="长材料测试场景",
                captured_at="2026-08-25",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=False,
            )

        model_candidates = generate_cards.call_args.args[0]
        self.assertEqual(
            len(model_candidates), len(self.db.list_segments(result.material_id))
        )
        self.assertEqual(result.evidence_card_ids, [])
        self.assertTrue(any("未生成证据卡" in warning for warning in result.warnings))

    def test_unauthorized_material_has_no_cards_and_is_not_citable(self) -> None:
        result = self._import(DIFFICULTY_TEXT, consent="unknown")

        self.assertEqual(result.evidence_card_ids, [])
        self.assertTrue(
            any("授权确认" in warning for warning in result.warnings)
        )
        self.assertEqual(self.db.list_evidence_cards(self.project_id), [])

        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        self.assertEqual(stored.evaluation.verdict, Verdict.UNSUPPORTED)
        self.assertEqual(
            self.db.list_claim_evidence_links(stored.claim_id), []
        )

    def test_authorized_real_material_is_supported_without_demo_warning(self) -> None:
        with patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        ):
            result = import_text_material(
                self.db,
                self.project_id,
                "受访者表示：首次操作时需要工作人员协助。",
                original_filename="经授权访谈记录.txt",
                source_role="受访者",
                context="社区服务体验访谈",
                captured_at="2026-08-19",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=False,
            )

        material = self.db.get_material(result.material_id)
        self.assertEqual(material["is_fictional"], 0)
        self.assertEqual(material["consent_status"], "confirmed")
        self.assertEqual(result.warnings, [])
        self.assertGreater(len(result.evidence_card_ids), 0)

    def test_raw_and_redacted_files_are_saved_separately(self) -> None:
        original = (
            "联系人虚构姓名，手机13812345678。"
            + DIFFICULTY_TEXT
        )
        result = self._import(
            original,
            custom_terms=["虚构姓名"],
        )

        material = self.db.get_material(result.material_id)
        raw_path = Path(material["raw_path"])
        redacted_dir = Path(self.temp_dir.name) / "redacted"
        redacted_path = redacted_dir / f"M{result.material_id}_redacted.txt"

        self.assertTrue(raw_path.exists())
        self.assertTrue(redacted_path.exists())
        self.assertEqual(raw_path.read_text(encoding="utf-8"), original)
        self.assertEqual(
            redacted_path.read_text(encoding="utf-8"),
            result.redacted_text,
        )
        self.assertIn("[手机号]", result.redacted_text)
        self.assertIn("[自定义信息]", result.redacted_text)
        self.assertNotIn("13812345678", result.redacted_text)
        self.assertNotEqual(raw_path.read_text(encoding="utf-8"), result.redacted_text)
        self.assertEqual(
            material["sha256"], hashlib.sha256(original.encode("utf-8")).hexdigest()
        )

    def test_citation_ids_stay_within_approved_candidate_set(self) -> None:
        self._import(DIFFICULTY_TEXT)
        self._import(OPPOSITE_TEXT, filename="虚构测试材料_补充访谈.txt")

        stored = check_and_store_claim(self.db, self.project_id, GROUP_CLAIM)
        allowed = self._approved_candidate_ids()

        self.assertTrue(
            validate_citation_ids(stored.evaluation, allowed)
        )
        for link in self.db.list_claim_evidence_links(stored.claim_id):
            self.assertIn(int(link["evidence_card_id"]), allowed)

    def test_partial_support_creates_open_followup_tasks(self) -> None:
        self._import(DIFFICULTY_TEXT)

        stored = check_and_store_claim(self.db, self.project_id, GROUP_CLAIM)

        self.assertIsInstance(stored, StoredClaimResult)
        self.assertEqual(stored.evaluation.verdict, Verdict.PARTIALLY_SUPPORTED)
        tasks = self.db.list_followup_tasks(claim_id=stored.claim_id)
        self.assertGreaterEqual(len(tasks), 1)
        self.assertTrue(all(task["status"] == "open" for task in tasks))
        self.assertGreaterEqual(len(stored.evaluation.missing_evidence), 1)
        self.assertTrue(
            any("补充" in item for item in stored.evaluation.missing_evidence)
        )

    def test_recheck_with_opposite_viewpoint_changes_verdict(self) -> None:
        self._import(DIFFICULTY_TEXT)
        stored = check_and_store_claim(self.db, self.project_id, GROUP_CLAIM)
        self.assertEqual(stored.evaluation.verdict, Verdict.PARTIALLY_SUPPORTED)

        self._import(OPPOSITE_TEXT, filename="虚构测试材料_补充访谈.txt")
        rechecked = recheck_claim(self.db, stored.claim_id)

        self.assertEqual(rechecked.claim_id, stored.claim_id)
        self.assertEqual(rechecked.evaluation.verdict, Verdict.CONTRADICTED)
        claim = self.db.get_claim(stored.claim_id)
        self.assertEqual(claim["verdict"], Verdict.CONTRADICTED.value)
        relations = {
            link["relation"]
            for link in self.db.list_claim_evidence_links(stored.claim_id)
        }
        self.assertIn("contradict", relations)
        self.assertIn("support", relations)

    def test_repeated_recheck_does_not_duplicate_tasks(self) -> None:
        self._import(DIFFICULTY_TEXT)
        stored = check_and_store_claim(self.db, self.project_id, GROUP_CLAIM)
        task_count_after_check = len(
            self.db.list_followup_tasks(claim_id=stored.claim_id)
        )

        recheck_claim(self.db, stored.claim_id)
        recheck_claim(self.db, stored.claim_id)

        self.assertEqual(
            len(self.db.list_followup_tasks(claim_id=stored.claim_id)),
            task_count_after_check,
        )

    def test_same_claim_text_updates_instead_of_duplicating(self) -> None:
        self._import(DIFFICULTY_TEXT)
        first = check_and_store_claim(self.db, self.project_id, GROUP_CLAIM)
        self.assertEqual(first.evaluation.verdict, Verdict.PARTIALLY_SUPPORTED)

        self._import(OPPOSITE_TEXT, filename="虚构测试材料_补充访谈.txt")
        second = check_and_store_claim(self.db, self.project_id, GROUP_CLAIM)

        self.assertEqual(first.claim_id, second.claim_id)
        self.assertEqual(second.evaluation.verdict, Verdict.CONTRADICTED)
        self.assertEqual(len(self.db.list_claims(self.project_id)), 1)
        self.assertEqual(
            self.db.get_claim(first.claim_id)["verdict"],
            Verdict.CONTRADICTED.value,
        )

    def test_recheck_missing_claim_raises(self) -> None:
        with self.assertRaises(ValueError):
            recheck_claim(self.db, 999)

    def test_empty_claim_and_empty_text_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            check_and_store_claim(self.db, self.project_id, "   ")
        with self.assertRaises(ValueError):
            self._import("   ")

    def test_export_after_full_flow_contains_claim_and_evidence(self) -> None:
        from qingji.export import export_project_markdown

        self._import(DIFFICULTY_TEXT)
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)

        markdown = export_project_markdown(self.db, self.project_id)
        self.assertIn(SIMPLE_CLAIM, markdown)
        self.assertIn(f"C{stored.claim_id}", markdown)
        self.assertIn("已有支持", markdown)
        self.assertNotIn("13812345678", markdown)

    def test_export_includes_followup_task_status_and_completion_material(self) -> None:
        from qingji.export import export_project_markdown

        imported = self._import(DIFFICULTY_TEXT)
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        task_id = self.db.create_followup_task(
            stored.claim_id,
            "导出任务状态",
            recommended_action="补充并核对一份材料。",
        )

        open_markdown = export_project_markdown(self.db, self.project_id)
        self.assertIn("## 补证任务", open_markdown)
        self.assertIn("导出任务状态", open_markdown)
        self.assertIn("待补证", open_markdown)

        self.db.set_followup_task_status(
            task_id,
            "done",
            completion_material_id=imported.material_id,
        )
        done_markdown = export_project_markdown(self.db, self.project_id)
        self.assertIn("已完成", done_markdown)
        self.assertIn("完成材料：", done_markdown)

    def test_withdrawing_approved_evidence_refreshes_claim_and_export(self) -> None:
        from qingji.export import export_project_markdown

        imported = self._import(DIFFICULTY_TEXT)
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        card = self.db.get_evidence_card(imported.evidence_card_ids[0])
        self.assertEqual(stored.evaluation.verdict, Verdict.SUPPORTED)

        review = review_evidence_card(
            self.db,
            int(card["id"]),
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="rejected",
            change_reason="来源复核未通过，撤回证据。",
        )

        self.assertIsInstance(review, EvidenceReviewResult)
        self.assertEqual(review.rechecked_claim_ids, (stored.claim_id,))
        self.assertIsNotNone(review.review_event_id)
        refreshed = self.db.get_claim(stored.claim_id)
        self.assertEqual(refreshed["verdict"], Verdict.UNSUPPORTED.value)
        self.assertEqual(refreshed["evidence_links"], [])
        self.assertIsNotNone(
            self.db.get_latest_claim_run(stored.claim_id, "claim_retrieval")
        )
        markdown = export_project_markdown(self.db, self.project_id)
        self.assertNotIn("- 核验结果：已有支持", markdown)
        self.assertIn("- 支持证据：无", markdown)
        self.assertIn("## 证据审核变更日志", markdown)
        self.assertIn("来源复核未通过，撤回证据。", markdown)

    def test_rejected_evidence_can_generate_one_traceable_replacement(self) -> None:
        imported = self._import(DIFFICULTY_TEXT)
        card = self.db.get_evidence_card(imported.evidence_card_ids[0])
        review_evidence_card(
            self.db,
            int(card["id"]),
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="rejected",
            change_reason="原卡把个人经历概括得过宽。",
        )
        advice = EvidenceAdvice(
            title="个体线上办理经历",
            summary="一名受访者提到线上办理时需要志愿者帮助。",
            evidence_type="interview_statement",
            uncertainties=(),
            model="test-model",
        )
        self.assertEqual(
            [item["id"] for item in list_regenerable_rejected_evidence_cards(self.db, self.project_id)],
            [card["id"]],
        )
        with patch("qingji.workflow.request_evidence_assistance", return_value=advice) as generate:
            regenerated = regenerate_rejected_evidence_card(self.db, int(card["id"]))

        replacement = self.db.get_evidence_card(regenerated.replacement_evidence_card_id)
        self.assertEqual(replacement["review_status"], "draft")
        self.assertIn(f"E{card['id']} 的拒绝理由重新生成", replacement["source_locator"])
        self.assertEqual(generate.call_args.kwargs["review_feedback"], "原卡把个人经历概括得过宽。")
        self.assertEqual(
            list_regenerable_rejected_evidence_cards(self.db, self.project_id), ()
        )
        with self.assertRaises(ValueError):
            regenerate_rejected_evidence_card(self.db, int(card["id"]))

    def test_bulk_regeneration_reextracts_from_material_with_rejection_feedback(self) -> None:
        imported = self._import(DIFFICULTY_TEXT)
        card = self.db.get_evidence_card(imported.evidence_card_ids[0])
        review_evidence_card(
            self.db,
            int(card["id"]),
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="rejected",
            change_reason="原卡混入了分析性表述，请只保留受访者的明确经历。",
        )
        advice = EvidenceCardGenerationAdvice(
            cards=(
                EvidenceCardGenerationItem(
                    segment_ids=(int(card["segment_id"]),),
                    title="受访者线上办理时遇到验证码填写困难",
                    summary="受访者明确提到不知道验证码填写位置，后在志愿者帮助下完成申请。",
                    evidence_type="interview_statement",
                    uncertainties=(),
                ),
            ),
            uncertainties=(),
            model="test-model",
            chunk_count=1,
        )

        with patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        ), patch(
            "qingji.workflow.request_evidence_card_generation",
            return_value=advice,
        ) as generate_cards:
            regenerated = regenerate_rejected_material_evidence_cards(
                self.db, self.project_id
            )

        self.assertEqual(len(regenerated), 1)
        result = regenerated[0]
        self.assertEqual(result.source_evidence_card_ids, (int(card["id"]),))
        self.assertEqual(len(result.replacement_evidence_card_ids), 1)
        replacement = self.db.get_evidence_card(result.replacement_evidence_card_ids[0])
        self.assertEqual(replacement["review_status"], "draft")
        self.assertIn("根据被拒绝卡片的理由重新整理", replacement["source_locator"])
        self.assertEqual(
            generate_cards.call_args.kwargs["review_feedback"],
            ["原卡混入了分析性表述，请只保留受访者的明确经历。"],
        )
        self.assertEqual(
            list_regenerable_rejected_evidence_cards(self.db, self.project_id), ()
        )

    def test_approving_evidence_refreshes_only_its_project_claims(self) -> None:
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        initial_tasks = self.db.list_followup_tasks(claim_id=stored.claim_id)
        self.assertTrue(initial_tasks)
        self.assertTrue(all(task["status"] == "open" for task in initial_tasks))
        other_project_id = self.db.create_project("另一个项目")
        other = check_and_store_claim(self.db, other_project_id, SIMPLE_CLAIM)
        other_run_before = self.db.get_latest_claim_run(
            other.claim_id, "claim_retrieval"
        )

        with patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        ):
            imported = import_text_material(
                self.db,
                self.project_id,
                DIFFICULTY_TEXT,
                original_filename="待批准材料.txt",
                source_role="模拟受访者（虚构）",
                context="虚构访谈",
                captured_at="2026-07-15T09:10:00+08:00",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=True,
            )
        card = self.db.get_evidence_card(imported.evidence_card_ids[0])
        review = review_evidence_card(
            self.db,
            int(card["id"]),
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="approved",
            change_reason="",
        )

        self.assertEqual(review.rechecked_claim_ids, (stored.claim_id,))
        self.assertIsNotNone(review.review_event_id)
        self.assertEqual(
            self.db.list_evidence_review_events(
                self.project_id, evidence_card_id=int(card["id"])
            )[0]["change_reason"],
            "",
        )
        self.assertEqual(
            self.db.get_claim(stored.claim_id)["verdict"], Verdict.SUPPORTED.value
        )
        resolved_tasks = self.db.list_followup_tasks(claim_id=stored.claim_id)
        self.assertTrue(all(task["status"] == "done" for task in resolved_tasks))
        self.assertEqual(
            self.db.get_claim(other.claim_id)["verdict"], Verdict.UNSUPPORTED.value
        )
        self.assertEqual(
            self.db.get_latest_claim_run(other.claim_id, "claim_retrieval")["id"],
            other_run_before["id"],
        )

        no_change = review_evidence_card(
            self.db,
            int(card["id"]),
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="approved",
            change_reason="",
        )
        self.assertIsNone(no_change.review_event_id)
        self.assertEqual(
            len(
                self.db.list_evidence_review_events(
                    self.project_id, evidence_card_id=int(card["id"])
                )
            ),
            1,
        )

        withdrawn = review_evidence_card(
            self.db,
            int(card["id"]),
            title=card["title"],
            summary=card["summary"],
            evidence_type=card["evidence_type"],
            review_status="rejected",
            change_reason="复核后撤回该证据。",
        )
        self.assertEqual(withdrawn.rechecked_claim_ids, (stored.claim_id,))
        self.assertIsNotNone(withdrawn.review_event_id)
        reopened_tasks = self.db.list_followup_tasks(claim_id=stored.claim_id)
        self.assertTrue(all(task["status"] == "open" for task in reopened_tasks))
        events = self.db.list_evidence_review_events(
            self.project_id, evidence_card_id=int(card["id"])
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["change_reason"], "复核后撤回该证据。")
        self.assertEqual(events[0]["before"]["review_status"], "approved")
        self.assertEqual(events[0]["after"]["review_status"], "rejected")

    def test_followup_recommendation_is_safe_for_real_projects(self) -> None:
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        tasks = self.db.list_followup_tasks(claim_id=stored.claim_id)
        self.assertTrue(tasks)
        for task in tasks:
            recommendation = task["recommended_action"]
            self.assertIn("已获得记录与使用授权的材料", recommendation)
            self.assertNotIn("补充已获得记录与使用授权的虚构测试材料", recommendation)

        legacy_recommendation = "优先补充已获得记录与使用授权的虚构测试材料。"
        self.db.update_followup_task(
            int(tasks[0]["id"]), recommended_action=legacy_recommendation
        )
        recheck_claim(self.db, stored.claim_id)
        migrated = self.db.get_followup_task(int(tasks[0]["id"]))
        self.assertIn(
            "已获得记录与使用授权的材料", migrated["recommended_action"]
        )
        self.assertNotEqual(migrated["recommended_action"], legacy_recommendation)

    def test_team_analysis_alone_never_supports_claim(self) -> None:
        result = self._import(
            "团队分析：推测平台设计可能对部分使用者造成不便。",
            source_role="团队分析",
            context="虚构的团队内部讨论",
        )
        for card_id in result.evidence_card_ids:
            self.db.set_evidence_review_status(card_id, "approved")

        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        self.assertEqual(stored.evaluation.verdict, Verdict.UNSUPPORTED)
        self.assertEqual(stored.evaluation.supporting_evidence_ids, [])

    def test_long_material_keeps_model_selected_source_boundaries(self) -> None:
        long_text = "".join(
            f"第{index}位受访者记录：使用线上平台时描述了办理流程和遇到的问题。"
            for index in range(1, 901)
        )
        with patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        ):
            result = import_text_material(
                self.db,
                self.project_id,
                long_text,
                original_filename="长材料.txt",
                source_role="受访者",
                context="长材料测试",
                captured_at="2026-08-24",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=True,
            )

        segments = self.db.list_segments(result.material_id)
        self.assertGreater(len(segments), len(result.evidence_card_ids))
        self.assertLessEqual(len(result.evidence_card_ids), 40)
        self.assertTrue(any("由模型生成" in warning for warning in result.warnings))
        card_quotes = "\n".join(
            self.db.get_evidence_card(card_id)["quote"]
            for card_id in result.evidence_card_ids
        )
        self.assertIn("第1位受访者", card_quotes)
        self.assertTrue(
            all(
                self.db.get_evidence_card(card_id)["quote"].count("受访者记录") == 1
                for card_id in result.evidence_card_ids
            )
        )

    def test_bulk_review_refreshes_project_claims_once_per_batch(self) -> None:
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        with patch(
            "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
        ):
            imported = import_text_material(
                self.db,
                self.project_id,
                DIFFICULTY_TEXT,
                original_filename="批量审核材料.txt",
                source_role="受访者",
                context="批量审核测试",
                captured_at="2026-08-24",
                consent_status=ConsentStatus.CONFIRMED,
                custom_sensitive_terms=None,
                is_fictional=True,
            )
        updates = [
            {
                "evidence_card_id": card_id,
                "title": self.db.get_evidence_card(card_id)["title"],
                "summary": self.db.get_evidence_card(card_id)["summary"],
                "evidence_type": self.db.get_evidence_card(card_id)["evidence_type"],
                "review_status": "approved",
                "change_reason": "批量审核测试",
            }
            for card_id in imported.evidence_card_ids
        ]
        results = review_evidence_cards(self.db, updates)

        self.assertTrue(results)
        self.assertTrue(
            all(stored.claim_id in result.rechecked_claim_ids for result in results)
        )
        self.assertEqual(
            self.db.get_claim(stored.claim_id)["verdict"],
            Verdict.SUPPORTED.value,
        )

    def test_confirmed_model_relation_can_replace_local_support_link(self) -> None:
        imported = self._import(DIFFICULTY_TEXT)
        stored = check_and_store_claim(self.db, self.project_id, SIMPLE_CLAIM)
        card_id = imported.evidence_card_ids[0]
        self.assertEqual(stored.evaluation.verdict, Verdict.SUPPORTED)

        rechecked = recheck_claim(
            self.db,
            stored.claim_id,
            relation_overrides={card_id: "context"},
            relation_rationales={card_id: "模型复核：仅共享主题词，未直接对应结论。"},
        )

        self.assertEqual(rechecked.evaluation.verdict, Verdict.UNSUPPORTED)
        links = self.db.list_claim_evidence_links(stored.claim_id)
        self.assertEqual([link["relation"] for link in links], ["context"])
        self.assertIn("模型复核", links[0]["rationale"])

    def test_configured_model_automatically_uses_semantic_relations(self) -> None:
        imported = self._import(DIFFICULTY_TEXT)
        card_id = imported.evidence_card_ids[0]
        advice = ClaimEvidenceReviewAdvice(
            reviews=(
                ClaimEvidenceReviewItem(
                    evidence_id=card_id,
                    relation="context",
                    rationale="材料只涉及线上平台，未蕴含目标结论。",
                ),
            ),
            uncertainties=(),
            model="test-model",
            safe_rewrite="现有材料不足以说明所有使用者都会遇到困难。",
        )
        configured = SimpleNamespace(configured=True, model="test-model")

        with (
            patch("qingji.workflow.llm_settings", configured),
            patch(
                "qingji.workflow.request_claim_evidence_review",
                return_value=advice,
            ) as request_review,
        ):
            stored = check_and_store_claim(
                self.db, self.project_id, SIMPLE_CLAIM
            )

        self.assertEqual(stored.evaluation.verdict, Verdict.UNSUPPORTED)
        self.assertEqual(
            stored.evaluation.safe_rewrite,
            "现有材料不足以说明所有使用者都会遇到困难。",
        )
        request_review.assert_called_once()
        links = self.db.list_claim_evidence_links(stored.claim_id)
        self.assertEqual([link["relation"] for link in links], ["context"])
        self.assertIn("语义判断", links[0]["rationale"])
        semantic_run = self.db.get_latest_claim_run(
            stored.claim_id, "llm_claim_evidence_review"
        )
        self.assertEqual(semantic_run["status"], "completed")
        self.assertEqual(semantic_run["output"]["model"], "test-model")

    def test_confirmed_import_uses_the_model_when_normal_splitting_fails(self) -> None:
        with patch("qingji.workflow.split_text", return_value=[]):
            with patch(
                "qingji.workflow.llm_settings", SimpleNamespace(configured=True)
            ):
                result = import_text_material(
                    self.db,
                    self.project_id,
                    "即使分段器异常，这份脱敏正文也应保留为可审核证据。",
                    original_filename="分段异常材料.txt",
                    source_role="受访者",
                    context="分段兜底测试",
                    captured_at="2026-08-24",
                    consent_status=ConsentStatus.CONFIRMED,
                    custom_sensitive_terms=None,
                    is_fictional=True,
                )

        self.assertEqual(len(result.evidence_card_ids), 1)
        card = self.db.get_evidence_card(result.evidence_card_ids[0])
        self.assertEqual(card["title"], "材料片段 1")
        self.assertTrue(any("交由模型重新提取" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
