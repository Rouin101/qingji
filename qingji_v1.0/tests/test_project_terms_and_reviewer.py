"""Regression checks for project-only aliases and review attribution."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from qingji.db import Database
from qingji.backup import export_project_backup, restore_project_backup
from qingji.llm import request_project_term_pairs
from qingji.project_terms import validate_pairs
from qingji.retrieval import evidence_candidate_from_mapping, rank_evidence_with_explanations
from qingji.workflow import review_evidence_card


class ProjectTermAndReviewerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.initialize()

    def test_project_alias_changes_only_explicit_ranking(self):
        project_a = self.db.create_project("食堂调研")
        project_b = self.db.create_project("其他调研")
        self.db.update_project(project_a, term_pairs_json=json.dumps(
            validate_pairs([{"source": "饭堂", "target": "餐厅"}, {"source": "排队", "target": "候餐"}]), ensure_ascii=False))
        self.assertEqual(json.loads(self.db.get_project(project_b)["term_pairs_json"]), [])
        candidate = evidence_candidate_from_mapping({
            "id": 1, "material_id": 1, "segment_id": 1, "title": "餐厅候餐",
            "quote": "餐厅候餐", "summary": "餐厅候餐", "review_status": "approved",
            "consent_status": "confirmed", "evidence_type": "interview_statement",
        })
        before = rank_evidence_with_explanations("饭堂排队", [candidate])[0].score
        pairs = tuple((item["source"], item["target"]) for item in json.loads(self.db.get_project(project_a)["term_pairs_json"]))
        after = rank_evidence_with_explanations("饭堂排队", [candidate], term_pairs=pairs)[0].score
        self.assertEqual(before, 0)
        self.assertGreater(after, before)

    def test_model_only_reads_approved_authorized_cards_and_does_not_save(self):
        seen = {}
        def fake_post(url, headers, payload, timeout):
            seen["prompt"] = payload["messages"][1]["content"]
            return {"choices": [{"message": {"content": json.dumps({"pairs": [
                {"source": "饭堂", "target": "餐厅"},
                {"source": "全部学生", "target": "学生"},
            ]}, ensure_ascii=False)}}]}
        config = SimpleNamespace(configured=True, model="test", base_url="https://example.invalid", api_key="test", timeout_seconds=2)
        project_id = self.db.create_project("食堂调研")
        pairs = request_project_term_pairs(self.db.get_project(project_id), [
            {"title": "餐厅候餐", "summary": "受访者需要候餐", "consent_status": "confirmed", "review_status": "approved"},
            {"title": "秘密材料", "summary": "不得发送", "consent_status": "denied", "review_status": "approved"},
        ], config=config, post_json=fake_post)
        self.assertEqual(pairs, [{"source": "饭堂", "target": "餐厅"}])
        self.assertNotIn("秘密材料", seen["prompt"])
        self.assertEqual(self.db.get_project(project_id)["term_pairs_json"], "[]")

    def test_reviewer_is_preserved_in_review_event(self):
        project = self.db.create_project("审核测试")
        material = self.db.create_material(project, "text", consent_status="confirmed")
        segment = self.db.create_segment(material, 1, "受访者说明餐厅排队。")
        card_id = self.db.create_evidence_card(project, segment, "interview_statement", "餐厅", "受访者说明餐厅排队。", "餐厅排队。")
        review_evidence_card(self.db, card_id, title="餐厅", summary="餐厅排队。", evidence_type="interview_statement", review_status="approved", change_reason="已核对", reviewer="甲同学")
        events = self.db.list_evidence_review_events(project)
        self.assertEqual(events[0]["reviewer"], "甲同学")
        self.assertTrue(events[0]["created_at"])
        self.db.update_project(project, term_pairs_json=json.dumps([{"source": "饭堂", "target": "餐厅"}], ensure_ascii=False))
        restored = restore_project_backup(self.db, export_project_backup(self.db, project).content, "审核测试恢复")
        restored_project = self.db.get_project(restored.project_id)
        self.assertEqual(json.loads(restored_project["term_pairs_json"]), [{"source": "饭堂", "target": "餐厅"}])
        self.assertEqual(self.db.list_evidence_review_events(restored.project_id)[0]["reviewer"], "甲同学")


if __name__ == "__main__":
    unittest.main()
