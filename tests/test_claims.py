from __future__ import annotations

import unittest

from qingji.claims import evaluate_claim, validate_citation_ids
from qingji.models import (
    ConsentStatus,
    EvidenceCandidate,
    EvidenceType,
    ReviewStatus,
    Verdict,
)


def candidate(
    evidence_id: int,
    quote: str,
    *,
    material_id: int | None = None,
    review_status: ReviewStatus = ReviewStatus.APPROVED,
    consent_status: ConsentStatus = ConsentStatus.CONFIRMED,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        id=evidence_id,
        material_id=material_id or evidence_id,
        segment_id=evidence_id,
        title="模拟访谈证据",
        quote=quote,
        summary=quote,
        evidence_type=EvidenceType.INTERVIEW_STATEMENT,
        source_role="受访居民",
        context="线上办事体验模拟访谈",
        source_locator="第1段第1句",
        review_status=review_status,
        consent_status=consent_status,
    )


class ClaimTests(unittest.TestCase):
    def test_group_claim_is_only_partially_supported_by_one_interview(self) -> None:
        claim = "当地居民普遍认为线上办事平台使用困难"
        evidence = [
            candidate(7, "我在网上办事系统提交材料时不会操作，遇到了困难。")
        ]

        result = evaluate_claim(claim, evidence)

        self.assertEqual(result.verdict, Verdict.PARTIALLY_SUPPORTED)
        self.assertEqual(result.supporting_evidence_ids, [7])
        self.assertIn("group_generalization", result.rule_flags)
        self.assertIn("一份已审核材料", result.safe_rewrite)
        self.assertTrue(validate_citation_ids(result, {7}))

    def test_opposite_experience_is_detected_as_conflict(self) -> None:
        claim = "当地居民普遍认为线上办事平台使用困难"
        evidence = [
            candidate(7, "我使用线上办事平台时遇到困难。"),
            candidate(8, "我没有遇到困难，整个操作很顺利。"),
        ]

        result = evaluate_claim(claim, evidence)

        self.assertEqual(result.verdict, Verdict.CONTRADICTED)
        self.assertEqual(result.supporting_evidence_ids, [7])
        self.assertEqual(result.contradicting_evidence_ids, [8])

    def test_draft_and_unapproved_sources_are_never_cited(self) -> None:
        claim = "线上办事平台使用困难"
        evidence = [
            candidate(
                99,
                "我使用线上办事平台时遇到困难。",
                review_status=ReviewStatus.DRAFT,
            )
        ]

        result = evaluate_claim(claim, evidence)

        self.assertEqual(result.verdict, Verdict.UNSUPPORTED)
        self.assertEqual(result.supporting_evidence_ids, [])
        self.assertEqual(result.context_evidence_ids, [])

    def test_causal_language_is_downgraded_without_formal_evidence(self) -> None:
        evidence = [candidate(3, "不会操作线上平台让我多次寻求工作人员帮助。")]

        result = evaluate_claim("平台设计导致居民办事困难", evidence)

        self.assertNotEqual(result.verdict, Verdict.SUPPORTED)
        self.assertIn("causal_language", result.rule_flags)


if __name__ == "__main__":
    unittest.main()
