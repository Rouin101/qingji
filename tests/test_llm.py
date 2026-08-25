"""Tests for the opt-in, boundary-redacted model-assistance layer."""

from __future__ import annotations

import unittest

from qingji.config import LLMSettings
from qingji.llm import (
    LLMConfigurationError,
    LLMResponseError,
    build_claim_assistance_prompt,
    build_claim_evidence_review_prompt,
    build_evidence_assistance_prompt,
    build_evidence_card_generation_prompt,
    build_evidence_review_batch_prompt,
    build_evidence_review_prompt,
    probe_llm_connection,
    request_claim_evidence_review,
    request_evidence_review_batch,
    request_evidence_review,
    request_evidence_card_generation,
    request_evidence_assistance,
    request_claim_assistance,
)
from qingji.models import ClaimEvaluation, Verdict


def _config(**overrides: object) -> LLMSettings:
    values = {
        "enabled": True,
        "base_url": "https://example.test/v1",
        "api_key": "test-secret",
        "model": "test-model",
        "timeout_seconds": 10.0,
        "max_context_chars": 12000,
    }
    values.update(overrides)
    return LLMSettings(**values)


def _evaluation() -> ClaimEvaluation:
    return ClaimEvaluation(
        verdict=Verdict.PARTIALLY_SUPPORTED,
        reason="现有材料支持核心现象，但范围表达过强。",
        supporting_evidence_ids=[1],
        missing_evidence=["补充不同背景参与者的独立材料"],
        safe_rewrite="一份已审核材料提到，线上办事时遇到困难。",
        rule_flags=["group_generalization"],
    )


class LLMTests(unittest.TestCase):
    def test_prompt_only_contains_eligible_boundary_redacted_fields(self) -> None:
        prompt, allowed = build_claim_assistance_prompt(
            "居民普遍认为平台使用困难。",
            _evaluation(),
            [
                {
                    "id": 1,
                    "title": "受访者联系 test@example.com",
                    "quote": "一名受访者遇到困难，手机号 13812345678。",
                    "summary": "需要帮助",
                    "evidence_type": "interview_statement",
                    "source_locator": "M1-S1",
                    "review_status": "approved",
                    "consent_status": "confirmed",
                },
                {
                    "id": 2,
                    "title": "未批准证据",
                    "quote": "不应进入模型上下文",
                    "summary": "draft",
                    "review_status": "draft",
                    "consent_status": "confirmed",
                },
                {
                    "id": 3,
                    "title": "未授权证据",
                    "quote": "不应进入模型上下文",
                    "summary": "unknown",
                    "review_status": "approved",
                    "consent_status": "unknown",
                },
            ],
        )

        self.assertEqual(allowed, {1})
        self.assertIn('"evidence_id":1', prompt)
        self.assertNotIn('"evidence_id":2', prompt)
        self.assertNotIn('"evidence_id":3', prompt)
        self.assertNotIn("test@example.com", prompt)
        self.assertNotIn("13812345678", prompt)
        self.assertIn("[邮箱]", prompt)
        self.assertIn("[手机号]", prompt)

    def test_user_derived_evaluation_text_is_redacted_too(self) -> None:
        evaluation = {
            "verdict": "unsupported",
            "reason": "联系人 test@example.com 提供的信息不足。",
            "supporting_evidence_ids": [],
            "missing_evidence": [],
            "safe_rewrite": "请联系 13812345678 进一步核对。",
            "rule_flags": [],
        }
        prompt, _ = build_claim_assistance_prompt(
            "需要核对邮箱 test@example.com。",
            evaluation,
            [],
        )
        self.assertNotIn("test@example.com", prompt)
        self.assertNotIn("13812345678", prompt)
        self.assertIn("[邮箱]", prompt)
        self.assertIn("[手机号]", prompt)

    def test_request_uses_json_contract_and_returns_structured_advice(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url, headers, payload, timeout):
            captured.update(
                url=url,
                headers=headers,
                payload=payload,
                timeout=timeout,
            )
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"材料支持核心现象。",'
                                '"safe_rewrite":"一份材料提到使用时遇到困难。",'
                                '"follow_up_suggestions":["补充不同背景样本"],'
                                '"uncertainties":["样本范围有限"],'
                                '"cited_evidence_ids":[1]}'
                            )
                        }
                    }
                ]
            }

        advice = request_claim_assistance(
            "居民普遍认为平台使用困难。",
            _evaluation(),
            [
                {
                    "id": 1,
                    "title": "受访者体验",
                    "quote": "使用时遇到困难",
                    "summary": "需要帮助",
                    "evidence_type": "interview_statement",
                    "source_locator": "M1-S1",
                    "review_status": "approved",
                    "consent_status": "confirmed",
                }
            ],
            config=_config(),
            post_json=fake_post,
        )

        self.assertEqual(advice.cited_evidence_ids, (1,))
        self.assertEqual(advice.follow_up_suggestions, ("补充不同背景样本",))
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["timeout"], 10.0)
        payload = captured["payload"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("13812345678", str(payload))

    def test_invalid_citation_is_rejected(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"有建议。",'
                                '"safe_rewrite":"保守改写。",'
                                '"follow_up_suggestions":[],"uncertainties":[],'
                                '"cited_evidence_ids":[999]}'
                            )
                        }
                    }
                ]
            }

        with self.assertRaises(LLMResponseError):
            request_claim_assistance(
                "一个结论。",
                _evaluation(),
                [],
                config=_config(),
                post_json=fake_post,
            )

    def test_disabled_configuration_never_calls_provider(self) -> None:
        with self.assertRaises(LLMConfigurationError):
            request_claim_assistance(
                "一个结论。",
                _evaluation(),
                [],
                config=_config(enabled=False),
                post_json=lambda *args: self.fail("provider should not be called"),
            )

    def test_evidence_prompt_requires_consent_and_redacts_card_fields(self) -> None:
        with self.assertRaises(ValueError):
            build_evidence_assistance_prompt(
                {
                    "consent_status": "unknown",
                    "quote": "不应发送",
                }
            )

        prompt = build_evidence_assistance_prompt(
            {
                "consent_status": "confirmed",
                "title": "受访者 test@example.com 的体验",
                "summary": "手机号 13812345678 反馈需要帮助",
                "quote": "使用时遇到困难，身份证 110101199001011234。",
                "evidence_type": "interview_statement",
            }
        )
        self.assertNotIn("test@example.com", prompt)
        self.assertNotIn("13812345678", prompt)
        self.assertNotIn("110101199001011234", prompt)
        self.assertIn("[邮箱]", prompt)
        self.assertIn("[手机号]", prompt)
        self.assertIn("[身份证号]", prompt)

    def test_evidence_assistance_returns_draft_without_auto_approval(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"平台操作体验",'
                                '"summary":"一名受访者提到操作时需要帮助。",'
                                '"evidence_type":"interview_statement",'
                                '"uncertainties":["仅代表该来源经历"]}'
                            )
                        }
                    }
                ]
            }

        row = {
            "id": 7,
            "consent_status": "confirmed",
            "review_status": "draft",
            "title": "原始标题",
            "summary": "原始摘要",
            "quote": "操作时需要帮助。",
            "evidence_type": "interview_statement",
        }
        advice = request_evidence_assistance(
            row,
            config=_config(),
            post_json=fake_post,
        )

        self.assertEqual(advice.title, "平台操作体验")
        self.assertEqual(advice.evidence_type, "interview_statement")
        self.assertEqual(advice.uncertainties, ("仅代表该来源经历",))
        self.assertEqual(row["review_status"], "draft")

    def test_evidence_assistance_rejects_unknown_type(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"标题","summary":"摘要",'
                                '"evidence_type":"invented_type",'
                                '"uncertainties":[]}'
                            )
                        }
                    }
                ]
            }

        with self.assertRaises(LLMResponseError):
            request_evidence_assistance(
                {
                    "consent_status": "confirmed",
                    "quote": "操作时需要帮助。",
                    "evidence_type": "interview_statement",
                },
                config=_config(),
                post_json=fake_post,
            )

    def test_semantic_card_generation_uses_segment_ids_and_redacts_prompt(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url, headers, payload, timeout):
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"cards":['
                                '{"segment_ids":[11],"title":"线上办理需要帮助",'
                                '"summary":"一名受访者提到线上办理时需要工作人员帮助。",'
                                '"evidence_type":"interview_statement",'
                                '"uncertainties":["仅代表该来源"]},'
                                '{"segment_ids":[12,13],"title":"窗口提供协助",'
                                '"summary":"相邻片段说明工作人员提供了现场协助。",'
                                '"evidence_type":"staff_explanation",'
                                '"uncertainties":[]}'
                                '],"uncertainties":[]}'
                            )
                        }
                    }
                ]
            }

        prompt, allowed_ids = build_evidence_card_generation_prompt(
            [
                {
                    "id": 11,
                    "sequence_no": 1,
                    "locator": "第1段",
                    "redacted_text": "受访者 test@example.com 表示需要帮助。",
                },
                {
                    "id": 12,
                    "sequence_no": 2,
                    "locator": "第2段",
                    "redacted_text": "工作人员说明可以现场协助。",
                },
                {
                    "id": 13,
                    "sequence_no": 3,
                    "locator": "第3段",
                    "redacted_text": "协助流程在窗口完成。",
                },
            ],
            source_role="受访者",
            context="访谈",
        )
        self.assertEqual(allowed_ids, (11, 12, 13))
        self.assertNotIn("test@example.com", prompt)
        self.assertIn("[邮箱]", prompt)

        advice = request_evidence_card_generation(
            [
                {
                    "id": 11,
                    "sequence_no": 1,
                    "locator": "第1段",
                    "redacted_text": "受访者 test@example.com 表示需要帮助。",
                },
                {
                    "id": 12,
                    "sequence_no": 2,
                    "locator": "第2段",
                    "redacted_text": "工作人员说明可以现场协助。",
                },
                {
                    "id": 13,
                    "sequence_no": 3,
                    "locator": "第3段",
                    "redacted_text": "协助流程在窗口完成。",
                },
            ],
            config=_config(),
            post_json=fake_post,
        )
        self.assertEqual(len(advice.cards), 2)
        self.assertEqual(advice.cards[0].segment_ids, (11,))
        self.assertEqual(advice.cards[1].segment_ids, (12, 13))
        self.assertNotIn("test@example.com", str(captured["payload"]))

    def test_semantic_card_generation_rejects_non_contiguous_segments(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"cards":[{"segment_ids":[1,3],'
                                '"title":"标题","summary":"摘要",'
                                '"evidence_type":"formal_record",'
                                '"uncertainties":[]}],"uncertainties":[]}'
                            )
                        }
                    }
                ]
            }

        with self.assertRaises(LLMResponseError):
            request_evidence_card_generation(
                [
                    {"id": 1, "redacted_text": "第一段"},
                    {"id": 2, "redacted_text": "第二段"},
                    {"id": 3, "redacted_text": "第三段"},
                ],
                config=_config(),
                post_json=fake_post,
            )

    def test_semantic_card_generation_discards_only_overlapping_cards(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"cards":['
                                '{"segment_ids":[1],"title":"第一项",'
                                '"summary":"第一段记录了具体事实。",'
                                '"evidence_type":"formal_record",'
                                '"uncertainties":[]},'
                                '{"segment_ids":[1,2],"title":"重叠项",'
                                '"summary":"这张卡与第一张重复使用第一段。",'
                                '"evidence_type":"formal_record",'
                                '"uncertainties":[]},'
                                '{"segment_ids":[3],"title":"第三项",'
                                '"summary":"第三段记录了另一项具体事实。",'
                                '"evidence_type":"formal_record",'
                                '"uncertainties":[]}'
                                '],"uncertainties":[]}'
                            )
                        }
                    }
                ]
            }

        advice = request_evidence_card_generation(
            [
                {"id": 1, "redacted_text": "第一段"},
                {"id": 2, "redacted_text": "第二段"},
                {"id": 3, "redacted_text": "第三段"},
            ],
            config=_config(),
            post_json=fake_post,
        )

        self.assertEqual(
            [card.segment_ids for card in advice.cards],
            [(1,), (3,)],
        )
        self.assertEqual(advice.discarded_card_count, 1)

    def test_semantic_card_generation_reports_progress_for_multiple_batches(self) -> None:
        import re

        completed: list[tuple[int, int]] = []

        def fake_post(url, headers, payload, timeout):
            prompt = payload["messages"][-1]["content"]
            segment_id = int(re.search(r'"segment_id":(\d+)', prompt).group(1))
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"cards":[{"segment_ids":['
                                f"{segment_id}"
                                '],"title":"标题","summary":"摘要",'
                                '"evidence_type":"formal_record",'
                                '"uncertainties":[]}],"uncertainties":[]}'
                            )
                        }
                    }
                ]
            }

        request_evidence_card_generation(
            [
                {"id": 1, "redacted_text": "甲" * 700},
                {"id": 2, "redacted_text": "乙" * 700},
                {"id": 3, "redacted_text": "丙" * 700},
            ],
            config=_config(max_context_chars=3000),
            post_json=fake_post,
            progress_callback=lambda completed_count, total: completed.append(
                (completed_count, total)
            ),
        )

        self.assertEqual(completed[-1], (2, 2))

    def test_evidence_review_prompt_is_redacted_and_requires_consent(self) -> None:
        with self.assertRaises(ValueError):
            build_evidence_review_prompt(
                {"id": 1, "consent_status": "unknown", "quote": "不应发送"}
            )

        prompt = build_evidence_review_prompt(
            {
                "id": 1,
                "consent_status": "confirmed",
                "title": "受访者 test@example.com",
                "summary": "手机号 13812345678",
                "quote": "身份证 110101199001011234，使用时遇到困难。",
                "evidence_type": "interview_statement",
                "source_role": "受访者",
                "context": "访谈",
            }
        )
        self.assertNotIn("test@example.com", prompt)
        self.assertNotIn("13812345678", prompt)
        self.assertNotIn("110101199001011234", prompt)
        self.assertIn("review_status", prompt)

    def test_evidence_review_returns_bounded_status(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"review_status":"approved",'
                                '"review_reason":"来源和片段边界清楚。",'
                                '"uncertainties":["仅代表该受访者"]}'
                            )
                        }
                    }
                ]
            }

        advice = request_evidence_review(
            {
                "id": 7,
                "consent_status": "confirmed",
                "title": "平台体验",
                "summary": "需要帮助",
                "quote": "操作时需要帮助。",
                "evidence_type": "interview_statement",
            },
            config=_config(),
            post_json=fake_post,
        )
        self.assertEqual(advice.review_status, "approved")
        self.assertEqual(advice.review_reason, "来源和片段边界清楚。")
        self.assertEqual(advice.uncertainties, ("仅代表该受访者",))

    def test_evidence_review_rejects_unknown_status(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"review_status":"draft",'
                                '"review_reason":"需要人工确认",'
                                '"uncertainties":[]}'
                            )
                        }
                    }
                ]
            }

        with self.assertRaises(LLMResponseError):
            request_evidence_review(
                {
                    "id": 7,
                    "consent_status": "confirmed",
                    "quote": "操作时需要帮助。",
                },
                config=_config(),
                post_json=fake_post,
            )

    def test_claim_evidence_review_redacts_and_demotes_omitted_cards(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url, headers, payload, timeout):
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"evidence_reviews":['
                                '{"evidence_id":1,"relation":"support",'
                                '"rationale":"对象与行为直接对应"}],'
                                '"safe_rewrite":"现有材料显示，部分居民使用平台时遇到困难。",'
                                '"uncertainties":["样本范围有限"]}'
                            )
                        }
                    }
                ]
            }

        rows = [
            {
                "id": 1,
                "review_status": "approved",
                "consent_status": "confirmed",
                "title": "受访者 test@example.com",
                "summary": "手机号 13812345678 反馈困难",
                "quote": "使用平台时遇到困难。",
                "evidence_type": "interview_statement",
                "source_locator": "第1段",
            },
            {
                "id": 2,
                "review_status": "approved",
                "consent_status": "confirmed",
                "title": "背景材料",
                "summary": "平台存在服务流程",
                "quote": "平台提供线上服务。",
                "evidence_type": "formal_record",
                "source_locator": "第2段",
            },
        ]
        prompt, allowed = build_claim_evidence_review_prompt(
            "居民使用平台时遇到困难。", rows
        )
        self.assertEqual(allowed, {1, 2})
        self.assertNotIn("test@example.com", prompt)
        self.assertNotIn("13812345678", prompt)
        self.assertIn("量词/数量", prompt)
        self.assertIn("必须返回 context", prompt)
        self.assertIn("safe_rewrite", prompt)

        advice = request_claim_evidence_review(
            "居民使用平台时遇到困难。",
            rows,
            config=_config(),
            post_json=fake_post,
        )
        relations = {item.evidence_id: item.relation for item in advice.reviews}
        self.assertEqual(relations, {1: "support", 2: "context"})
        self.assertEqual(
            advice.safe_rewrite, "现有材料显示，部分居民使用平台时遇到困难。"
        )
        self.assertIn("[邮箱]", str(captured["payload"]))

    def test_batch_evidence_review_uses_one_json_response_for_all_cards(self) -> None:
        rows = [
            {
                "id": 7,
                "review_status": "draft",
                "consent_status": "confirmed",
                "title": "卡片一",
                "summary": "需要帮助",
                "quote": "操作时需要帮助。",
                "evidence_type": "interview_statement",
            },
            {
                "id": 8,
                "review_status": "draft",
                "consent_status": "confirmed",
                "title": "卡片二",
                "summary": "完成顺利",
                "quote": "整个操作很顺利。",
                "evidence_type": "interview_statement",
            },
        ]
        prompt, allowed = build_evidence_review_batch_prompt(rows)
        self.assertEqual(allowed, {7, 8})
        self.assertIn('"evidence_id":7', prompt)
        self.assertIn('"evidence_id":8', prompt)

        calls = 0

        def fake_post(url, headers, payload, timeout):
            nonlocal calls
            calls += 1
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"reviews":['
                                '{"evidence_id":7,"review_status":"approved",'
                                '"review_reason":"来源清晰","uncertainties":[]},'
                                '{"evidence_id":8,"review_status":"rejected",'
                                '"review_reason":"需要人工复核","uncertainties":[]}'
                                ']}'
                            )
                        }
                    }
                ]
            }

        advice = request_evidence_review_batch(
            rows,
            config=_config(),
            post_json=fake_post,
        )
        self.assertEqual(calls, 1)
        self.assertEqual(
            [item.review_status for _, item in advice.reviews],
            ["approved", "rejected"],
        )

    def test_batch_evidence_review_retries_a_prose_response_once(self) -> None:
        calls = 0

        def fake_post(url, headers, payload, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "choices": [
                        {"message": {"content": "这张卡片来源清晰，可以批准。"}}
                    ]
                }
            self.assertIn("格式重试", payload["messages"][-1]["content"])
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"reviews":[{"evidence_id":7,'
                                '"review_status":"approved",'
                                '"review_reason":"来源清晰",'
                                '"uncertainties":[]}]}'
                            )
                        }
                    }
                ]
            }

        advice = request_evidence_review_batch(
            [
                {
                    "id": 7,
                    "consent_status": "confirmed",
                    "review_status": "draft",
                    "title": "平台体验",
                    "summary": "需要帮助",
                    "quote": "操作时需要帮助。",
                }
            ],
            config=_config(),
            post_json=fake_post,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(advice.reviews[0][1].review_status, "approved")

    def test_batch_evidence_review_accepts_single_uncertainty_string(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"reviews":[{"evidence_id":7,'
                                '"review_status":"approved",'
                                '"review_reason":"来源清晰",'
                                '"uncertainties":"仅代表该材料"}]}'
                            )
                        }
                    }
                ]
            }

        advice = request_evidence_review_batch(
            [
                {
                    "id": 7,
                    "consent_status": "confirmed",
                    "review_status": "draft",
                    "title": "平台体验",
                    "summary": "需要帮助",
                    "quote": "操作时需要帮助。",
                }
            ],
            config=_config(),
            post_json=fake_post,
        )

        self.assertEqual(advice.reviews[0][1].uncertainties, ("仅代表该材料",))

    def test_batch_evidence_review_ignores_invalid_uncertainty_shape(self) -> None:
        def fake_post(url, headers, payload, timeout):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"reviews":[{"evidence_id":7,'
                                '"review_status":"approved",'
                                '"review_reason":"来源清晰",'
                                '"uncertainties":{"note":"格式不规范"}}]}'
                            )
                        }
                    }
                ]
            }

        advice = request_evidence_review_batch(
            [
                {
                    "id": 7,
                    "consent_status": "confirmed",
                    "review_status": "draft",
                    "title": "平台体验",
                    "summary": "需要帮助",
                    "quote": "操作时需要帮助。",
                }
            ],
            config=_config(),
            post_json=fake_post,
        )

        self.assertEqual(advice.reviews[0][1].review_status, "approved")
        self.assertEqual(advice.reviews[0][1].uncertainties, ())

    def test_probe_uses_no_project_material_and_returns_provider_model(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(url, headers, payload, timeout):
            captured["payload"] = payload
            return {
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "message": {
                            "content": '{"ok":true}',
                        }
                    }
                ],
            }

        model = probe_llm_connection(config=_config(), post_json=fake_post)

        self.assertEqual(model, "deepseek-v4-flash")
        self.assertNotIn("材料", str(captured["payload"]))
        self.assertNotIn("证据", str(captured["payload"]))


if __name__ == "__main__":
    unittest.main()
