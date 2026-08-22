"""Tests for the opt-in, boundary-redacted model-assistance layer."""

from __future__ import annotations

import unittest

from qingji.config import LLMSettings
from qingji.llm import (
    LLMConfigurationError,
    LLMResponseError,
    build_claim_assistance_prompt,
    build_evidence_assistance_prompt,
    probe_llm_connection,
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
