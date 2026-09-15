"""Independent counterexamples for citation eligibility and claim boundaries."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qingji.claims import evaluate_claim
from qingji.db import Database
from qingji.diagnostics import build_retrieval_diagnostic, claim_uses_current_rules
from qingji.evaluation import build_evidence_set_id, build_eval_template
from qingji.evidence import is_retrievable_evidence
from qingji.export import export_project_markdown
from qingji.llm import build_claim_evidence_review_prompt, ClaimEvidenceReviewAdvice, ClaimEvidenceReviewItem
from qingji.models import EvidenceCandidate, EvidenceType, ReviewStatus, ConsentStatus, Verdict
from qingji.presentation import render_outcome_report_markdown
from qingji.retrieval import is_retrievable
from qingji.workflow import check_and_store_claim, review_evidence_card, review_evidence_cards


def card(text, identity=1, kind=EvidenceType.INTERVIEW_STATEMENT):
    return EvidenceCandidate(identity, identity, identity, text, text, text,
                             kind, "受访者", "同一场景", "第1段",
                             ReviewStatus.APPROVED, ConsentStatus.CONFIRMED)


class ClaimBoundaryTests(unittest.TestCase):
    def test_quantity_and_negation_counterexamples_even_with_model_support(self):
        cases = [
            ("活动共有50人参加。", "活动共有10人参加。", Verdict.CONTRADICTED),
            ("活动共有五十人参加。", "活动共有十人参加。", Verdict.CONTRADICTED),
            ("图书馆周末开放。", "图书馆周末不开放。", Verdict.CONTRADICTED),
            ("图书馆周末不开放。", "图书馆周末开放。", Verdict.CONTRADICTED),
            ("活动共有50人参加。", "活动共有50份问卷。", Verdict.UNSUPPORTED),
            ("活动共有50人参加。", "活动有50人报名，实际10人参加。", Verdict.UNSUPPORTED),
            ("活动共有50人参加。", "活动共有50人参加。", Verdict.SUPPORTED),
            ("图书馆周末开放。", "图书馆周末开放。", Verdict.SUPPORTED),
            ("图书馆周末不开放。", "图书馆周末并非不开放。", Verdict.UNSUPPORTED),
            ("活动共有50人参加。", "不能证明活动共有50人参加。", Verdict.UNSUPPORTED),
        ]
        for claim, quote, expected in cases:
            for overrides in (None, {1: "support"}):
                with self.subTest(claim=claim, quote=quote, model=overrides):
                    result = evaluate_claim(claim, [card(quote, kind=EvidenceType.FORMAL_RECORD)], relation_overrides=overrides)
                    self.assertEqual(result.verdict, expected)

    def test_three_files_do_not_establish_population_scope(self):
        evidence = [card("受访者甲表示线上平台使用困难。", i) for i in range(1, 4)]
        result = evaluate_claim("当地居民普遍认为线上平台使用困难。", evidence)
        self.assertEqual(result.verdict, Verdict.PARTIALLY_SUPPORTED)
        self.assertNotIn("独立材料", result.safe_rewrite)
        self.assertNotIn("普遍认为", result.safe_rewrite)

    def test_formal_label_alone_cannot_prove_causality_or_intensity(self):
        for claim in ("平台改版导致办理时间减少。", "办理时间显著减少。"):
            with self.subTest(claim=claim):
                result = evaluate_claim(claim, [card(claim, kind=EvidenceType.FORMAL_RECORD)], relation_overrides={1: "support"})
                self.assertEqual(result.verdict, Verdict.PARTIALLY_SUPPORTED)

    def test_different_experiences_do_not_refute_an_existential_claim(self):
        claim = "一名受访者使用平台遇到困难。"
        evidence = [card(claim), card("另一名受访者使用平台没有遇到困难。", 2)]
        for overrides in (None, {1: "support", 2: "contradict"}):
            result = evaluate_claim(claim, evidence, relation_overrides=overrides)
            self.assertEqual(result.verdict, Verdict.SUPPORTED)
            self.assertEqual(result.contradicting_evidence_ids, [])
            self.assertIn(2, result.context_evidence_ids)
        self.assertEqual(evaluate_claim(claim, evidence[1:]).verdict, Verdict.UNSUPPORTED)

    def test_different_named_people_and_times_are_context(self):
        cases = [
            ("受访者甲使用平台遇到困难。", "受访者乙使用平台没有遇到困难。"),
            ("图书馆周末开放。", "图书馆周一开放。"),
            ("图书馆2026年开放。", "图书馆2025年开放。"),
        ]
        for claim, quote in cases:
            with self.subTest(claim=claim):
                self.assertEqual(evaluate_claim(claim, [card(quote)], relation_overrides={1: "support"}).verdict, Verdict.UNSUPPORTED)

    def test_summary_cannot_override_negative_source_quote(self):
        evidence = replace(card("图书馆周末不开放。"), title="图书馆周末开放", summary="图书馆周末开放")
        result = evaluate_claim("图书馆周末开放。", [evidence], relation_overrides={1: "support"})
        self.assertEqual(result.verdict, Verdict.CONTRADICTED)

    def test_team_analysis_alone_is_context(self):
        text = "线上平台使用困难。"
        result = evaluate_claim(text, [card(text, kind=EvidenceType.TEAM_ANALYSIS)], relation_overrides={1: "support"})
        self.assertEqual(result.verdict, Verdict.UNSUPPORTED)

    def test_all_status_and_consent_combinations(self):
        for status in ("draft", "approved", "rejected", "invalid", None):
            for consent in ("confirmed", "unknown", "denied"):
                with self.subTest(status=status, consent=consent):
                    expected = status in {"draft", "approved"} and consent == "confirmed"
                    row = {"review_status": status, "consent_status": consent}
                    self.assertEqual(is_retrievable_evidence(row), expected)
                    self.assertEqual(is_retrievable(replace(card("平台使用困难"), **row)), expected)


class EvidenceStateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Database(Path(self.directory.name) / "test.db")
        self.db.initialize()
        self.project = self.db.create_project("状态回归")
        text = "一名受访者使用线上平台遇到困难。"
        material = self.db.create_material(self.project, "text", consent_status="confirmed", is_fictional=True)
        segment = self.db.create_segment(material, 1, text, locator="第1段")
        self.eid = self.db.create_evidence_card(self.project, segment, "interview_statement", text, text, text)
        self.claim_text = text
        patcher = patch("qingji.workflow.llm_settings", SimpleNamespace(configured=False))
        patcher.start()
        self.addCleanup(patcher.stop)

    def update(self, status, bulk=False, **changes):
        row = self.db.get_evidence_card(self.eid)
        values = {key: row[key] for key in ("title", "summary", "evidence_type")}
        values.update(review_status=status, change_reason="回归测试", **changes)
        if bulk:
            return review_evidence_cards(self.db, [{"evidence_card_id": self.eid, **values}])[0]
        return review_evidence_card(self.db, self.eid, **values)

    def test_draft_is_retrieved_sent_to_model_and_exported_with_its_real_status(self):
        stored = check_and_store_claim(self.db, self.project, self.claim_text)
        self.assertTrue(claim_uses_current_rules(self.db, stored.claim_id))
        self.assertEqual(stored.evaluation.verdict, Verdict.SUPPORTED)
        rows = self.db.list_evidence_cards(self.project)
        prompt, allowed = build_claim_evidence_review_prompt(self.claim_text, rows)
        self.assertEqual(allowed, {self.eid})
        self.assertIn('"review_status":"draft"', prompt)
        self.assertIn("待复核（可引用）", export_project_markdown(self.db, self.project))
        report = render_outcome_report_markdown(self.db.get_project(self.project), self.db.list_claims(self.project), [], [], rows, self.db.list_claim_evidence_links(stored.claim_id))
        self.assertIn("待复核（可引用）", report)
        self.assertIn(str(self.eid), build_eval_template(rows).decode("utf-8-sig"))
        self.assertNotEqual(build_evidence_set_id(rows), build_evidence_set_id([]))
        diagnostic = build_retrieval_diagnostic(self.claim_text, rows, [], stored.evaluation)
        self.assertEqual(diagnostic["eligible_count"], len(diagnostic["ranked_candidates"]))

    def test_exclusion_and_restoration_refresh_claims_links_tasks_and_exports(self):
        stored = check_and_store_claim(self.db, self.project, self.claim_text)
        for bulk in (False, True):
            with self.subTest(bulk=bulk):
                result = self.update("rejected", bulk=bulk)
                self.assertIn(stored.claim_id, result.rechecked_claim_ids)
                self.assertEqual(self.db.get_claim(stored.claim_id)["verdict"], "unsupported")
                self.assertEqual(self.db.list_claim_evidence_links(stored.claim_id), [])
                self.assertTrue(any(t["status"] == "open" for t in self.db.list_followup_tasks(project_id=self.project)))
                self.assertNotIn(f"### E{self.eid}｜", export_project_markdown(self.db, self.project))
                self.update("draft", bulk=bulk)
                self.assertEqual(self.db.get_claim(stored.claim_id)["verdict"], "supported")
                self.assertFalse(any(t["status"] == "open" for t in self.db.list_followup_tasks(project_id=self.project)))

    def test_editing_draft_type_refreshes_existing_claim(self):
        stored = check_and_store_claim(self.db, self.project, self.claim_text)
        self.update("draft", evidence_type="team_analysis")
        self.assertEqual(self.db.get_claim(stored.claim_id)["verdict"], "unsupported")

    def test_model_rewrite_cannot_restore_rejected_quantity(self):
        text = "活动共有10人参加。"
        self.db.update_evidence_card(self.eid, title=text, quote=text, summary=text, evidence_type="formal_record")
        advice = ClaimEvidenceReviewAdvice(
            reviews=(ClaimEvidenceReviewItem(self.eid, "support", "模型错误地支持"),),
            uncertainties=(), model="test-only", safe_rewrite="活动确有50人参加。",
        )
        with patch("qingji.workflow.llm_settings", SimpleNamespace(configured=True)), patch("qingji.workflow.request_claim_evidence_review", return_value=advice):
            stored = check_and_store_claim(self.db, self.project, "活动共有50人参加。")
        self.assertEqual(stored.evaluation.verdict, Verdict.CONTRADICTED)
        self.assertNotEqual(stored.evaluation.safe_rewrite, advice.safe_rewrite)
        link = self.db.list_claim_evidence_links(stored.claim_id)[0]
        self.assertEqual(link["relation"], "contradict")
        self.assertIn("本地边界检查", link["rationale"])
        self.assertNotIn("模型错误地支持", link["rationale"])


if __name__ == "__main__":
    unittest.main()
