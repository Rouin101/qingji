"""虚构项目的本地协作、归档及旧数据兼容回归。"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects import ProjectConflict, ProjectStore
from core.review import ReviewError
from server import example_result


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "projects.sqlite3"
        self.store = ProjectStore(self.path)
        self.example = example_result()
        self.p = self.store.create("虚构实践团队", self.example["result"]["report"],
                                   [dict(m, enabled=True, consent_status="confirmed") for m in self.example["materials"]],
                                   actor="虚构同学甲")
        self.p = self.store.reviewed(self.p["id"], self.p["version"], self.example["result"])

    def tearDown(self):
        self.temp.cleanup()

    def add_members(self):
        self.p = self.store.members(self.p["id"], self.p["version"],
                                    [{"name": "虚构同学甲", "role": "访谈整理"},
                                     {"name": "虚构同学乙", "role": "材料核对"}], actor="虚构同学甲")
        return self.p["members"][0]["id"]

    def practice_task(self, **kwargs):
        self.p = self.store.create_task(self.p["id"], self.p["version"], "联系下一位受访者", **kwargs)
        return self.p["tasks"][-1]["id"]

    def test_member_assignment_survives_restart_without_granting_permissions(self):
        mid = self.add_members()
        tid = self.practice_task(assignee_id=mid, due_date="2026-10-08", notes="先确认采访安排", actor="自声明其他同学")
        reopened = ProjectStore(self.path).get(self.p["id"])
        self.assertEqual(reopened["tasks"][-1]["assignee_id"], mid)
        self.assertEqual(reopened["tasks"][-1]["notes"], "先确认采访安排")
        self.assertEqual(reopened["members"][0]["role"], "访谈整理")
        self.assertEqual(reopened["activity"][-1]["actor"], "自声明其他同学")
        self.assertNotIn("permissions", reopened["members"][0])
        self.assertEqual(tid, reopened["tasks"][-1]["id"])

    def test_removing_member_unassigns_tasks_but_keeps_task_and_discussion(self):
        mid = self.add_members()
        tid = self.practice_task(assignee_id=mid)
        self.p = self.store.comment(self.p["id"], self.p["version"], "task", tid, "现场安排需要提前确认", actor="虚构同学乙")
        remaining = self.p["members"][1:]
        updated = self.store.members(self.p["id"], self.p["version"], remaining)
        self.assertEqual(updated["tasks"][-1]["assignee_id"], "")
        self.assertEqual(updated["tasks"][-1]["id"], tid)
        self.assertEqual(updated["comments"][-1]["target_state"], "current")
        self.assertEqual(updated["comments"][-1]["actor"], "虚构同学乙")
        self.assertTrue(any(a["action"] == "task_unassigned" for a in updated["activity"]))

    def test_invalid_roster_and_actor_are_atomic(self):
        for roster in ([{"name": "同学甲"}, {"name": "同学甲"}],
                       [{"name": "同学甲", "role": "x" * 41}],
                       [{"name": "同学甲", "id": None}],
                       [{"name": "同学甲", "id": "same"}, {"name": "同学乙", "id": "same"}]):
            with self.assertRaises(ReviewError):
                self.store.members(self.p["id"], self.p["version"], roster)
        with self.assertRaises(ReviewError):
            self.store.members(self.p["id"], self.p["version"], [{"name": "同学甲"}], actor="x" * 61)
        self.assertEqual(self.store.get(self.p["id"]), self.p)

    def test_assignment_and_due_date_validation_do_not_partially_update(self):
        tid = self.practice_task(notes="原始记录")
        for changes in ({"action": "不应保存", "assignee_id": "other-project-member"},
                        {"notes": "不应保存", "due_date": "2026-02-30"},
                        {"due_date": "2026-1-01"},
                        {"kind": "practice"}):
            with self.assertRaises(ReviewError):
                self.store.task_detail(self.p["id"], self.p["version"], tid, changes)
        self.assertEqual(self.store.get(self.p["id"]), self.p)

    def test_practice_task_can_finish_without_claim_review_and_keeps_notes(self):
        p = self.store.create("只有日常分工的虚构项目")
        p = self.store.create_task(p["id"], p["version"], "整理访谈提纲", notes="已与团队确认")
        done = self.store.task(p["id"], p["version"], p["tasks"][0]["id"], "done", actor="虚构同学甲")
        self.assertEqual(done["tasks"][0]["status"], "done")
        self.assertEqual(done["tasks"][0]["notes"], "已与团队确认")
        self.assertEqual(done["history"], [])
        reopened = self.store.task(done["id"], done["version"], done["tasks"][0]["id"], "open")
        self.assertEqual(reopened["tasks"][0]["status"], "open")

    def test_review_does_not_move_practice_task_to_evidence_confirmation(self):
        tid = self.practice_task()
        reviewed = self.store.reviewed(self.p["id"], self.p["version"], self.example["result"])
        self.assertEqual(next(t for t in reviewed["tasks"] if t["id"] == tid)["status"], "open")

    def test_assigned_evidence_task_still_requires_authorized_material_review(self):
        mid = self.add_members()
        self.p = self.store.supplement(self.p["id"], self.p["version"], "i1",
                                       {"name": "虚构访谈补记", "text": "另一位受访者可以独立完成。"})
        tid = self.p["tasks"][0]["id"]
        self.p = self.store.task_detail(self.p["id"], self.p["version"], tid,
                                        {"assignee_id": mid, "notes": "等待授权与复查", "due_date": "2026-10-08"})
        with self.assertRaises(ReviewError):
            self.store.task(self.p["id"], self.p["version"], tid, "done")
        self.p = self.store.reviewed(self.p["id"], self.p["version"], self.example["result"])
        with self.assertRaises(ReviewError):
            self.store.task(self.p["id"], self.p["version"], tid, "done")
        self.p = self.store.save(self.p["id"], self.p["version"],
                                 {"materials": [dict(m, consent_status="confirmed") for m in self.p["materials"]]})
        self.p = self.store.reviewed(self.p["id"], self.p["version"], self.example["result"])
        done = self.store.task(self.p["id"], self.p["version"], tid, "done")
        self.assertEqual(done["tasks"][0]["assignee_id"], mid)
        self.assertEqual(done["tasks"][0]["notes"], "等待授权与复查")
        self.assertEqual(done["tasks"][0]["status"], "done")

    def test_comment_targets_are_project_scoped(self):
        other = self.store.create("另一个虚构项目")
        other = self.store.create_task(other["id"], other["version"], "其他团队任务")
        for target_type, target_id in (("project", other["id"]), ("task", other["tasks"][0]["id"]),
                                       ("material", "m-absent"), ("issue", "i-absent"), ("unknown", "")):
            with self.assertRaises(ReviewError):
                self.store.comment(self.p["id"], self.p["version"], target_type, target_id, "不能错挂讨论")
        self.assertEqual(self.store.get(self.p["id"]), self.p)

    def test_issue_comment_is_historical_when_same_id_is_reused_for_other_quote(self):
        self.p = self.store.comment(self.p["id"], self.p["version"], "issue", "i1", "这句需要限制受访范围", actor="虚构同学甲")
        original = copy.deepcopy(self.p["comments"][0])
        changed = copy.deepcopy(self.example["result"])
        changed["issues"][0]["quote"] = "另一句结论"
        updated = self.store.reviewed(self.p["id"], self.p["version"], changed)
        self.assertEqual(updated["comments"][0]["target_state"], "historical")
        self.assertEqual(updated["comments"][0]["target_snapshot"], original["target_snapshot"])
        self.assertNotEqual(updated["comments"][0]["target_snapshot"]["quote"], changed["issues"][0]["quote"])

    def test_material_comment_tracks_change_and_removal_without_losing_snapshot(self):
        mid = self.p["materials"][0]["id"]
        self.p = self.store.comment(self.p["id"], self.p["version"], "material", mid, "这份访谈需要补充采集场景")
        mats = [dict(m) for m in self.p["materials"]]
        mats[0]["text"] += "新增现场补记。"
        self.p = self.store.save(self.p["id"], self.p["version"], {"materials": mats})
        self.assertEqual(self.p["comments"][0]["target_state"], "changed")
        removed = self.store.save(self.p["id"], self.p["version"], {"materials": mats[1:]})
        self.assertEqual(removed["comments"][0]["target_state"], "removed")
        self.assertEqual(removed["comments"][0]["body"], "这份访谈需要补充采集场景")
        self.assertEqual(removed["comments"][0]["target_snapshot"]["name"], self.example["materials"][0]["name"])

    def test_comment_and_assignment_stale_versions_are_rejected(self):
        tid = self.practice_task()
        self.store.comment(self.p["id"], self.p["version"], "task", tid, "已联系")
        with self.assertRaises(ProjectConflict):
            self.store.task_detail(self.p["id"], self.p["version"], tid, {"notes": "旧请求"})
        with self.assertRaises(ProjectConflict):
            self.store.comment(self.p["id"], self.p["version"], "task", tid, "旧讨论")
        self.assertEqual(len(self.store.get(self.p["id"])["comments"]), 1)

    def test_archive_restores_all_contents_without_deleting_history(self):
        self.add_members()
        self.practice_task()
        self.p = self.store.comment(self.p["id"], self.p["version"], "project", "", "项目总结讨论")
        archived = self.store.archive(self.p["id"], self.p["version"], True, actor="虚构同学甲")
        self.assertTrue(archived["archived"])
        self.assertIsNotNone(archived["archived_at"])
        self.assertEqual(archived["report"], self.p["report"])
        self.assertEqual(archived["history"], self.p["history"])
        self.assertEqual(archived["comments"], self.p["comments"])
        self.assertTrue(next(p for p in self.store.list() if p["id"] == archived["id"])["archived"])
        restored = self.store.archive(archived["id"], archived["version"], False)
        self.assertFalse(restored["archived"])
        self.assertIsNone(restored["archived_at"])
        self.assertEqual(restored["tasks"], self.p["tasks"])

    def test_unchanged_team_task_and_archive_dont_create_extra_activity(self):
        self.add_members()
        tid = self.practice_task()
        original = self.p
        updated = self.store.members(original["id"], original["version"], original["members"])
        self.assertEqual(updated, original)
        updated = self.store.task_detail(original["id"], original["version"], tid, {"notes": ""})
        self.assertEqual(updated, original)
        updated = self.store.task(original["id"], original["version"], tid, "open")
        self.assertEqual(updated, original)
        updated = self.store.archive(original["id"], original["version"], False)
        self.assertEqual(updated, original)

    def test_activity_has_visible_retention_count_and_discussion_limit_is_atomic(self):
        with self.store.connect() as db:
            legacy = json.loads(db.execute("SELECT data FROM projects WHERE id=?", (self.p["id"],)).fetchone()[0])
            legacy["activity"] = [{"id": str(i), "action": "saved", "actor": "同学甲", "created_at": "2026-10-01", "detail": "记录"} for i in range(200)]
            legacy["comments"] = [{"id": str(i), "target_type": "project", "target_id": self.p["id"],
                                    "target_snapshot": {"name": self.p["name"]}, "body": "虚构讨论", "actor": "同学甲", "created_at": "2026-10-01"} for i in range(500)]
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(legacy), self.p["id"]))
        saved = self.store.save(self.p["id"], self.p["version"], {"description": "增加一条实际更新"})
        self.assertEqual(len(saved["activity"]), 200)
        self.assertEqual(saved["activity_earlier_count"], 1)
        self.assertEqual(saved["activity"][0]["id"], "1")
        with self.assertRaisesRegex(ReviewError, "500"):
            self.store.comment(saved["id"], saved["version"], "project", "", "超过限额")
        self.assertEqual(self.store.get(saved["id"]), saved)

    def test_legacy_project_and_evidence_tasks_migrate_on_read_and_next_save(self):
        self.p = self.store.supplement(self.p["id"], self.p["version"], "i1", None)
        with self.store.connect() as db:
            legacy = json.loads(db.execute("SELECT data FROM projects WHERE id=?", (self.p["id"],)).fetchone()[0])
            for key in ("members", "comments", "activity", "activity_earlier_count", "archived", "archived_at"):
                legacy.pop(key)
            for key in ("kind", "assignee_id", "due_date", "notes"):
                legacy["tasks"][0].pop(key)
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(legacy), self.p["id"]))
        read = self.store.get(self.p["id"])
        self.assertEqual(read["tasks"][0]["kind"], "evidence")
        self.assertEqual(read["members"], [])
        self.assertFalse(read["archived"])
        self.assertEqual(read["version"], self.p["version"])
        updated = self.store.save(read["id"], read["version"], {"description": "迁移后更新"})
        self.assertEqual(updated["tasks"][0]["id"], self.p["tasks"][0]["id"])
        self.assertEqual(updated["tasks"][0]["kind"], "evidence")
        self.assertEqual(len(updated["history"]), len(self.p["history"]))

    def test_list_sorts_by_update_and_reports_team_open_and_overdue_counts(self):
        mid = self.add_members()
        self.practice_task(assignee_id=mid, due_date="2001-01-01")
        self.store.create("后创建项目")
        with patch("core.projects.now", return_value="2099-01-01T00:00:00+00:00"):
            self.store.save(self.p["id"], self.p["version"], {"description": "最近更新"})
        listed = self.store.list()
        self.assertEqual(listed[0]["id"], self.p["id"])
        self.assertEqual(listed[0]["team_count"], 2)
        self.assertEqual(listed[0]["task_count"], 1)
        self.assertEqual(listed[0]["overdue_count"], 1)

    def test_material_tags_are_trimmed_and_do_not_invalidate_current_review(self):
        mats = copy.deepcopy(self.p["materials"])
        mats[0]["tags"] = ["  社区  ", "访谈", "社区", ""]
        saved = self.store.save(self.p["id"], self.p["version"], {"materials": mats})
        self.assertEqual(saved["materials"][0]["tags"], ["社区", "访谈"])
        self.assertFalse(saved["needs_review"])
        self.assertEqual(saved["result"], self.p["result"])
        for tags in (["超长" * 13], ["标签"] * 13, [None], "标签"):
            invalid = copy.deepcopy(saved["materials"])
            invalid[0]["tags"] = tags
            with self.assertRaises(ReviewError):
                self.store.save(saved["id"], saved["version"], {"materials": invalid})
        self.assertEqual(self.store.get(saved["id"]), saved)

    def test_changed_material_does_not_replace_review_source_snapshot(self):
        previous_materials = copy.deepcopy(self.p["materials"])
        current = copy.deepcopy(previous_materials)
        current[0]["text"] = "已经替换为另一份访谈内容。"
        current[0]["consent_status"] = "unconfirmed"
        saved = self.store.save(self.p["id"], self.p["version"], {"materials": current})
        self.assertEqual(saved["review_materials"], previous_materials)
        self.assertNotEqual(saved["review_materials"], saved["materials"])
        reviewed = self.store.reviewed(saved["id"], saved["version"], self.example["result"])
        self.assertEqual(reviewed["review_materials"], current)
        record = self.store.revision(reviewed["id"], reviewed["history"][0]["id"])
        self.assertEqual(record["previous_materials"], previous_materials)
        self.assertEqual(record["materials"], current)

    def test_old_project_review_sources_fallback_to_matching_revision(self):
        original_materials = copy.deepcopy(self.p["materials"])
        mats = copy.deepcopy(original_materials)
        mats[0]["text"] = "修改后的文本不应冒充旧引用。"
        self.p = self.store.save(self.p["id"], self.p["version"], {"materials": mats})
        with self.store.connect() as db:
            stored = json.loads(db.execute("SELECT data FROM projects WHERE id=?", (self.p["id"],)).fetchone()[0])
            stored.pop("review_materials")
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(stored), self.p["id"]))
        reopened = self.store.get(self.p["id"])
        self.assertEqual(reopened["review_materials"], original_materials)
        self.assertNotEqual(reopened["review_materials"], reopened["materials"])
        replaced = self.store.save(reopened["id"], reopened["version"], {"report": {"name": "新报告", "text": "新的一份报告。"}})
        self.assertIsNone(replaced["result"])
        self.assertEqual(replaced["review_materials"], [])

    def test_old_revision_previous_sources_use_earlier_record_even_if_result_repeats(self):
        original_materials = copy.deepcopy(self.p["materials"])
        mats = copy.deepcopy(original_materials)
        mats[0]["text"] += "追加一条后来的材料记录。"
        self.p = self.store.save(self.p["id"], self.p["version"], {"materials": mats})
        self.p = self.store.reviewed(self.p["id"], self.p["version"], self.example["result"])
        rid = self.p["history"][0]["id"]
        with self.store.connect() as db:
            stored = json.loads(db.execute("SELECT data FROM revisions WHERE id=?", (rid,)).fetchone()[0])
            stored.pop("previous_materials")
            db.execute("UPDATE revisions SET data=? WHERE id=?", (json.dumps(stored), rid))
        record = self.store.revision(self.p["id"], rid)
        self.assertEqual(record["previous_materials"], original_materials)
        self.assertNotEqual(record["previous_materials"], record["materials"])


if __name__ == "__main__":
    unittest.main()
