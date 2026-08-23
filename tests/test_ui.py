import unittest

from qingji.ui import get_next_action


class NextActionGuidanceTest(unittest.TestCase):
    def test_guides_new_project_to_material_import(self):
        action = get_next_action({"materials": 0})
        self.assertEqual(action["key"], "materials")
        self.assertEqual(action["button"], "去导入材料")

    def test_guides_unreviewed_cards_to_review(self):
        action = get_next_action(
            {"materials": 2, "evidence_cards": 3, "approved_evidence_cards": 1}
        )
        self.assertEqual(action["key"], "materials")
        self.assertEqual(action["button"], "去审核证据卡")

    def test_guides_completed_project_to_output(self):
        action = get_next_action(
            {
                "materials": 2,
                "evidence_cards": 3,
                "approved_evidence_cards": 3,
                "claims": 2,
                "open_followup_tasks": 0,
            }
        )
        self.assertEqual(action["key"], "output")
        self.assertEqual(action["button"], "去查看成果")


if __name__ == "__main__":
    unittest.main()
