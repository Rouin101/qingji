"""End-to-end workflow tests for the text-only evidence chain."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from qingji.claims import validate_citation_ids
from qingji.db import Database
from qingji.models import (
    ConsentStatus,
    ReviewStatus,
    Verdict,
)
from qingji.workflow import (
    StoredClaimResult,
    check_and_store_claim,
    import_text_material,
    recheck_claim,
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
        self.project_id = self.db.create_project("虚构测试项目", "仅供功能测试")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

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
        self.assertIn("虚构测试数据", material["notes"])

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


if __name__ == "__main__":
    unittest.main()
