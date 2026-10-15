import json
import tempfile
import unittest
from pathlib import Path
from core.projects import ProjectStore, ProjectConflict
from core.review import Document, ReviewError, model_messages, validate_model_result
from core.privacy import redacted
from server import example_result

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"projects.sqlite3"
        self.store=ProjectStore(self.path)
        self.example=example_result()
        self.p=self.store.create("虚构项目",self.example["result"]["report"],
                                  [dict(m,enabled=True,consent_status="confirmed") for m in self.example["materials"]])
        self.p=self.store.reviewed(self.p["id"],self.p["version"],self.example["result"])

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_isolation_and_saved_author_choices(self):
        second=self.store.create("另一个项目")
        saved=self.store.save(self.p["id"],self.p["version"],{"choices":{"i1":"accepted"},"reading_size":20})
        reopened=ProjectStore(self.path).get(self.p["id"])
        self.assertEqual(reopened["choices"],{"i1":"accepted"})
        self.assertEqual(reopened["reading_size"],20)
        self.assertEqual(ProjectStore(self.path).get(second["id"])["materials"],[])
        self.assertEqual(saved["result"]["report"],self.p["result"]["report"])

    def test_stale_write_is_rejected_without_overwriting(self):
        self.store.save(self.p["id"],self.p["version"],{"name":"新版名称"})
        with self.assertRaises(ProjectConflict):
            self.store.save(self.p["id"],self.p["version"],{"name":"旧请求"})
        self.assertEqual(self.store.get(self.p["id"])["name"],"新版名称")

    def test_unchanged_save_does_not_revise_project_or_create_history(self):
        saved=self.store.save(self.p["id"],self.p["version"],{"name":self.p["name"],"materials":self.p["materials"]})
        self.assertEqual(saved,self.p)
        changed=self.store.save(saved["id"],saved["version"],{"name":"有实际改动"})
        self.assertEqual(changed["version"],saved["version"]+1)
        self.assertEqual(len(changed["history"]),len(saved["history"]))

    def test_material_ids_and_exclusion_are_retained(self):
        m=dict(self.p["materials"][0],enabled=False,source_role="现场观察",context="虚构大厅",collected_at="9月12日")
        saved=self.store.save(self.p["id"],self.p["version"],{"materials":[m]})
        self.assertEqual(saved["materials"][0]["id"],m["id"])
        self.assertEqual(saved["materials"][0]["text"],m["text"])
        self.assertTrue(saved["needs_review"])
        self.assertEqual(saved["materials"][0]["context"],"虚构大厅")

    def test_supplement_does_not_prove_claim_or_autocomplete_task(self):
        p=self.store.supplement(self.p["id"],self.p["version"],"i1",{"name":"新访谈","text":"另一位受访者表示能独立操作。"})
        self.assertEqual(p["materials"][-1]["consent_status"],"unconfirmed")
        self.assertTrue(p["needs_review"])
        t=p["tasks"][0]
        with self.assertRaises(ReviewError):
            self.store.task(p["id"],p["version"],t["id"],"done")
        with self.assertRaises(ReviewError):
            updated=self.store.reviewed(p["id"],p["version"],self.example["result"])
            self.store.task(updated["id"],updated["version"],t["id"],"done")
        p=self.store.get(p["id"])
        mats=[dict(m,consent_status="confirmed") for m in p["materials"]]
        p=self.store.save(p["id"],p["version"],{"materials":mats})
        updated=self.store.reviewed(p["id"],p["version"],self.example["result"])
        self.assertEqual(updated["tasks"][0]["status"],"awaiting_confirmation")
        done=self.store.task(updated["id"],updated["version"],t["id"],"done")
        self.assertEqual(done["tasks"][0]["status"],"done")

    def test_history_keeps_previous_judgment_materials_and_choices(self):
        p=self.store.save(self.p["id"],self.p["version"],{"choices":{"i1":"kept"}})
        updated=self.store.reviewed(p["id"],p["version"],self.example["result"])
        self.assertEqual(len(updated["history"]),2)
        record=self.store.revision(p["id"],updated["history"][0]["id"])
        self.assertEqual(record["choices"],{"i1":"kept"})
        self.assertEqual(record["previous_result"],p["result"])
        self.assertEqual(record["materials"],p["materials"])
        with self.assertRaises(ReviewError):
            self.store.revision(self.store.create("隔离项目")["id"],updated["history"][0]["id"])

    def test_failed_invalid_save_is_atomic(self):
        with self.assertRaises(ReviewError):
            self.store.save(self.p["id"],self.p["version"],{"name":"不能落盘","materials":[{"name":"x","text":"x","source_role":"伪造类型"}]})
        self.assertEqual(self.store.get(self.p["id"])["name"],"虚构项目")

    def test_supported_status_and_different_evidence_are_validated(self):
        r=Document("report","虚构报告","本次受访者表示需要帮助。")
        m=Document("m1","虚构访谈","一位受访者需要帮助，另一位可以独立完成。")
        result=validate_model_result(json.dumps({"issues":[{"passage_id":"s1","quote":r.text,"category":"范围外推","reason":"不同人的体验并存。","next_step":"限定对象。","support_status":"partial","citations":[{"document_id":"m1","quote":"另一位可以独立完成。","relation":"different"}]}]}),r,[m])
        self.assertEqual(result.issues[0].support_status,"partial")
        self.assertEqual(result.issues[0].citations[0].relation,"different")

    def test_privacy_is_not_sent_and_original_offsets_remain_verifiable(self):
        r=Document("report","虚构报告","联络记录13812345678，三人均表示需要帮助。")
        m=Document("m1","虚构访谈","联系邮箱example@test.invalid，三人需要帮助。")
        messages=model_messages(r,[m])
        self.assertNotIn("13812345678",messages[1]["content"])
        self.assertNotIn("example@test.invalid",messages[1]["content"])
        payload={"issues":[{"passage_id":"s1","quote":redacted(r.text),"category":"范围外推","reason":"核对范围。","next_step":"查看原文。","citations":[{"document_id":"m1","quote":redacted(m.text)}]}]}
        issue=validate_model_result(json.dumps(payload),r,[m]).issues[0]
        self.assertEqual(issue.quote,r.text)
        self.assertEqual(issue.citations[0].quote,m.text)
        self.assertEqual(m.text[issue.citations[0].start:issue.citations[0].end],m.text)

if __name__=="__main__":
    unittest.main()
