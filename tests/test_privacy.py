from __future__ import annotations

import unittest

from qingji.privacy import redact_text


class PrivacyTests(unittest.TestCase):
    def test_redacts_supported_pii_and_custom_terms(self) -> None:
        source = (
            "联系人张三，手机13812345678，身份证32010220050102123X，"
            "邮箱zhang.san+test@example.com，住在桃源村7号。"
        )

        result = redact_text(
            source,
            custom_terms={"张三": "[姓名]", "桃源村7号": "[精确住址]"},
        )

        self.assertEqual(
            result.redacted_text,
            "联系人[姓名]，手机[手机号]，身份证[身份证号]，"
            "邮箱[邮箱]，住在[精确住址]。",
        )
        self.assertEqual(
            {span.kind for span in result.spans},
            {"phone", "id_card", "email", "custom"},
        )
        for span in result.spans:
            self.assertEqual(source[span.start : span.end], span.original)

    def test_phone_pattern_does_not_double_match_inside_id(self) -> None:
        result = redact_text("身份证号为32010220050102123X。")

        self.assertEqual(result.redacted_text, "身份证号为[身份证号]。")
        self.assertEqual(len(result.spans), 1)
        self.assertEqual(result.spans[0].kind, "id_card")

    def test_no_sensitive_data_preserves_text(self) -> None:
        result = redact_text("今天完成了两次现场观察。")

        self.assertFalse(result.found_sensitive_data)
        self.assertEqual(result.redacted_text, "今天完成了两次现场观察。")


if __name__ == "__main__":
    unittest.main()
