import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.collaboration import result_fingerprint
from core.project_packages import (IMPORT_WARNING, MAX_PACKAGE_BYTES, export_package,
                                   import_package)
from core.projects import ProjectStore
from core.review import Document, ReviewError, validate_model_result


class ProjectPackageTests(unittest.TestCase):
    """仅虚构文字与临时数据库；不读取连接配置、不调用真实模型。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(Path(self.temp.name) / "projects.sqlite3")
        self.report = Document("report", "虚构报告", "当地所有居民都无法独立使用设备。")
        self.material = {"id": "m1", "name": "虚构访谈", "text": "本次三位受访者首次操作时均需要帮助。",
                         "source_role": "受访者陈述", "context": "虚构大厅，三位居民", "collected_at": "2026-10-01",
                         "enabled": True, "consent_status": "confirmed"}
        raw = {"issues": [{"passage_id": "s1", "quote": self.report.text, "category": "范围外推",
                           "reason": "当前记录只能支持本次三位受访者的体验。", "next_step": "核对对象与样本覆盖范围。",
                           "support_status": "partial", "suggested_text": "本次三位受访者首次操作时均需要帮助。",
                           "citations": [{"document_id": "m1", "quote": self.material["text"], "relation": "support"}]}]}
        self.result = validate_model_result(json.dumps(raw), self.report,
                                            [Document("m1", self.material["name"], self.material["text"])]).to_dict()
        self.result = json.loads(json.dumps(self.result))
        self.result["used_material_ids"] = ["m1"]
        p = self.store.create("虚构设备体验实践", self.result["report"], [self.material])
        p = self.store.reviewed(p["id"], p["version"], self.result)
        p = self.store.members(p["id"], p["version"], [{"id": "u1", "name": "甲同学", "role": "访谈"}], actor="甲同学")
        p = self.store.supplement(p["id"], p["version"], "i1", None, actor="甲同学")
        self.task_id = p["tasks"][0]["id"]
        p = self.store.task_detail(p["id"], p["version"], self.task_id,
                                   {"assignee_id": "u1", "due_date": "2026-10-08", "notes": "与队员核对采集对象"})
        p = self.store.create_task(p["id"], p["version"], "整理访谈记录", assignee_id="u1")
        self.practice_id = p["tasks"][-1]["id"]
        for kind, target in (("project", p["id"]), ("material", "m1"), ("task", self.task_id), ("issue", "i1")):
            p = self.store.comment(p["id"], p["version"], kind, target, "虚构成员认为需要限定对象范围。", actor="甲同学")
        p = self.store.save(p["id"], p["version"], {"choices": {"i1": "kept"}})
        p = self.store.reviewed(p["id"], p["version"], self.result)
        p = self.store.task(p["id"], p["version"], self.task_id, "done", actor="甲同学")
        p = self.store.task(p["id"], p["version"], self.practice_id, "done")
        self.p = self.store.save(p["id"], p["version"], {"choices": {"i1": "accepted"}, "manual_text": "虚构编辑正文。", "reading_size": 20})

    def tearDown(self):
        self.temp.cleanup()

    def package(self):
        return export_package(self.store, self.p["id"])

    @staticmethod
    def resigned(package):
        package["sha256"] = hashlib.sha256(json.dumps(package["payload"], ensure_ascii=False,
                                            sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        return package

    def rows(self):
        with self.store.connect() as db:
            return tuple(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("projects", "revisions"))

    def assertRejected(self, package):
        before = self.rows()
        with self.assertRaises(ReviewError):
            import_package(self.store, package, actor="虚构接收者")
        self.assertEqual(self.rows(), before)

    def test_complete_round_trip_preserves_judgments_team_and_history(self):
        package = self.package()
        original = self.store.get(self.p["id"])
        restored = import_package(self.store, package, actor="虚构接收者")
        self.assertNotEqual(restored["id"], original["id"])
        self.assertEqual(self.store.get(original["id"]), original)
        self.assertEqual(restored["report"], original["report"])
        self.assertEqual(restored["result"], original["result"])
        self.assertEqual(restored["members"], original["members"])
        self.assertEqual(restored["manual_text"], "虚构编辑正文。")
        self.assertEqual(restored["choices"], {"i1": "accepted"})
        self.assertEqual(restored["reading_size"], 20)
        self.assertEqual(len(restored["history"]), 2)
        self.assertTrue(restored["needs_review"])
        self.assertEqual(restored["materials"][0]["consent_status"], "unconfirmed")
        self.assertEqual(restored["imported_from"]["warning"], IMPORT_WARNING)
        evidence = next(t for t in restored["tasks"] if t["id"] == self.task_id)
        # fixture 的最终作者编辑已使旧完成确认重新打开；交接不能复活旧 done。
        self.assertEqual(evidence["status"], "open")
        self.assertEqual(evidence["confirmed_at"], original["tasks"][0]["confirmed_at"])
        self.assertEqual(evidence["assignee_id"], "u1")
        self.assertEqual(evidence["notes"], "与队员核对采集对象")
        self.assertEqual(next(t for t in restored["tasks"] if t["id"] == self.practice_id)["status"], "done")
        self.assertEqual(next(c for c in restored["comments"] if c["target_type"] == "project")["target_id"], restored["id"])
        self.assertEqual(next(c for c in restored["comments"] if c["target_type"] == "issue")["target_state"], "current")
        with self.assertRaises(ReviewError):
            self.store.task(restored["id"], restored["version"], self.task_id, "done")
        restored_entry = self.store.revision(restored["id"], restored["history"][0]["id"])
        self.assertTrue(restored_entry["imported_unverified"])
        self.assertEqual(restored_entry["choices"], {"i1": "kept"})
        self.assertEqual(restored_entry["previous_result"], original["result"])
        self.assertEqual(result_fingerprint(restored["result"]), result_fingerprint(original["result"]))

    def test_repeated_import_is_independent_and_reexportable(self):
        first = import_package(self.store, self.package())
        second = import_package(self.store, self.package())
        self.assertNotEqual(first["id"], second["id"])
        again = import_package(self.store, export_package(self.store, first["id"]))
        self.assertEqual(len(again["history"]), 2)
        self.assertEqual(again["result"], first["result"])

    def test_checksum_detects_changes_but_recomputed_hash_is_not_trusted_validation(self):
        package = self.package()
        package["payload"]["project"]["name"] = "被改动的名称"
        self.assertRejected(package)
        package = self.package()
        package["payload"]["project"]["result"]["issues"][0]["citations"][0]["quote"] = "凭空添加的引文"
        self.assertRejected(self.resigned(package))

    def test_invalid_supported_degree_relation_and_offsets_are_rejected(self):
        for field, value in (("support_status", "认证属实"), ("start", True), ("end", -1), ("category", "科研审稿")):
            with self.subTest(field=field):
                package = self.package()
                package["payload"]["project"]["result"]["issues"][0][field] = value
                self.assertRejected(self.resigned(package))
        for changes in ({"document_id": "https://example.invalid/private"}, {"relation": "verified"}, {"start": 9000}):
            package = self.package()
            package["payload"]["revisions"][0]["data"]["result"]["issues"][0]["citations"][0].update(changes)
            self.assertRejected(self.resigned(package))

    def test_unknown_choices_long_manual_text_and_invalid_assignment_are_rejected(self):
        for key, value in (("choices", {"i999": "accepted"}), ("choices", {"i1": "approved"}), ("manual_text", "甲" * 24001)):
            package = self.package()
            package["payload"]["project"][key] = value
            self.assertRejected(self.resigned(package))
        for changes in ({"assignee_id": "not_a_member"}, {"due_date": "2026-02-30"}, {"material_ids": ["m_missing"]}):
            package = self.package()
            package["payload"]["project"]["tasks"][0].update(changes)
            self.assertRejected(self.resigned(package))

    def test_missing_material_id_is_not_repaired_and_duplicate_ids_are_rejected(self):
        package = self.package()
        package["payload"]["project"]["materials"][0]["id"] = ""
        self.assertRejected(self.resigned(package))
        for collection in ("materials", "tasks", "members", "comments"):
            package = self.package()
            items = package["payload"]["project"][collection]
            items.append(copy.deepcopy(items[0]))
            self.assertRejected(self.resigned(package))

    def test_removed_or_changed_material_uses_real_old_revision_snapshot(self):
        p = self.store.save(self.p["id"], self.p["version"], {"materials": []})
        # 当前仍显示旧判断，但原引用来自上一轮真实材料快照，不能冒充空材料。
        package = export_package(self.store, p["id"])
        restored = import_package(self.store, package)
        self.assertEqual(restored["materials"], [])
        self.assertEqual(restored["review_materials"][0]["text"], self.material["text"])
        self.assertEqual(restored["result"], self.result)

    def test_changed_material_text_does_not_replace_old_citation_snapshot(self):
        changed = dict(self.p["materials"][0], text="新观察记录：另一位居民能够独立完成。")
        p = self.store.save(self.p["id"], self.p["version"], {"materials": [changed]})
        restored = import_package(self.store, export_package(self.store, p["id"]))
        self.assertEqual(restored["materials"][0]["text"], changed["text"])
        self.assertEqual(restored["review_materials"][0]["text"], self.material["text"])
        self.assertEqual(restored["result"], self.result)

    def test_removed_linked_material_is_retained_as_historical_task_relation(self):
        with self.store.connect() as db:
            p = json.loads(db.execute("SELECT data FROM projects WHERE id=?", (self.p["id"],)).fetchone()[0])
            p["tasks"][0]["material_ids"] = ["m1"]
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(p), self.p["id"]))
        p = self.store.save(self.p["id"], self.p["version"], {"materials": []})
        restored = import_package(self.store, export_package(self.store, p["id"]))
        self.assertEqual(restored["materials"], [])
        self.assertEqual(restored["tasks"][0]["material_ids"], ["m1"])
        with self.assertRaises(ReviewError):
            self.store.task(restored["id"], restored["version"], self.task_id, "done")

    def test_tags_and_exclusion_remain_while_consent_is_reset(self):
        extra = {"id": "m2", "name": "虚构观察", "text": "另一位居民独立完成操作。", "enabled": False,
                 "consent_status": "confirmed", "tags": ["反例", "设备体验"]}
        p = self.store.save(self.p["id"], self.p["version"], {"materials": self.p["materials"] + [extra]})
        restored = import_package(self.store, export_package(self.store, p["id"]))
        self.assertEqual(restored["materials"][1]["tags"], ["反例", "设备体验"])
        self.assertFalse(restored["materials"][1]["enabled"])
        self.assertEqual(restored["materials"][1]["consent_status"], "unconfirmed")

    def test_blank_project_and_report_only_history_are_supported(self):
        blank = self.store.create("虚构空项目")
        restored = import_package(self.store, export_package(self.store, blank["id"]))
        self.assertEqual(restored["report"]["text"], "")
        self.assertEqual(restored["history"], [])
        report_only = copy.deepcopy(self.result)
        report_only["issues"][0]["citations"] = []
        report_only["used_material_ids"] = []
        p = self.store.create("虚构只核对报告", report_only["report"])
        p = self.store.reviewed(p["id"], p["version"], report_only)
        restored = import_package(self.store, export_package(self.store, p["id"]))
        self.assertEqual(restored["result"], report_only)
        self.assertEqual(restored["review_materials"], [])

    def test_old_project_without_new_fields_resolves_saved_review_context(self):
        with self.store.connect() as db:
            p = json.loads(db.execute("SELECT data FROM projects WHERE id=?", (self.p["id"],)).fetchone()[0])
            for key in ("members", "comments", "activity", "activity_earlier_count", "archived", "archived_at", "review_materials"):
                p.pop(key, None)
            for task in p["tasks"]:
                task.update(assignee_id="")
            p["materials"] = []
            p["needs_review"] = True
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(p), self.p["id"]))
        restored = import_package(self.store, self.package())
        self.assertEqual(restored["members"], [])
        self.assertEqual(restored["review_materials"][0]["text"], self.material["text"])

    def test_malformed_nested_values_fail_as_input_errors_without_writes(self):
        changes = [("result", {"mode": [], "report": self.result["report"], "issues": []}),
                   ("members", ["not a member"]), ("comments", [{"id": "c1", "target_type": [], "target_id": "i1"}]),
                   ("activity_earlier_count", True), ("reading_size", 16.0), ("materials", None)]
        for key, value in changes:
            with self.subTest(key=key):
                package = self.package()
                package["payload"]["project"][key] = value
                self.assertRejected(self.resigned(package))

    def test_source_package_is_not_mutated_and_long_name_stays_within_limit(self):
        p = self.store.save(self.p["id"], self.p["version"], {"name": "甲" * 200})
        package = export_package(self.store, p["id"])
        before = copy.deepcopy(package)
        restored = import_package(self.store, package)
        self.assertEqual(package, before)
        self.assertLessEqual(len(restored["name"]), 200)
        self.assertTrue(restored["name"].endswith("（交接副本）"))

    def test_old_previous_result_resolves_snapshot_from_matching_revision(self):
        package = self.package()
        newer = package["payload"]["revisions"][-1]["data"]
        newer.pop("previous_materials", None)
        newer["materials"] = []
        report_only = copy.deepcopy(newer["result"])
        report_only["issues"][0]["citations"] = []
        report_only["used_material_ids"] = []
        newer["result"] = report_only
        package["payload"]["project"]["result"] = report_only
        package["payload"]["project"]["review_materials"] = []
        restored = import_package(self.store, self.resigned(package))
        revision = self.store.revision(restored["id"], restored["history"][0]["id"])
        self.assertEqual(revision["previous_materials"][0]["text"], self.material["text"])
        self.assertEqual(revision["previous_result"], self.result)

    def test_missing_old_snapshot_rejects_incomplete_history(self):
        package = self.package()
        entry = package["payload"]["revisions"][-1]["data"]
        entry.pop("previous_materials", None)
        package["payload"]["revisions"] = [package["payload"]["revisions"][-1]]
        entry["materials"] = []
        entry["result"] = copy.deepcopy(entry["result"])
        entry["result"]["issues"][0]["citations"] = []
        entry["result"]["used_material_ids"] = []
        self.assertRejected(self.resigned(package))

    def test_current_materials_cannot_replace_missing_review_snapshot(self):
        package = self.package()
        package["payload"]["project"].pop("review_materials", None)
        package["payload"]["revisions"] = []
        package["payload"]["project"]["needs_review"] = False
        self.assertRejected(self.resigned(package))

    def test_unknown_sensitive_field_inside_result_report_is_rejected(self):
        package = self.package()
        package["payload"]["project"]["result"]["report"]["api_key"] = "fictional-secret"
        self.assertRejected(self.resigned(package))

    def test_reused_issue_id_does_not_attach_old_discussion_to_new_quote(self):
        package = self.package()
        original = package["payload"]["project"]["result"]
        changed = copy.deepcopy(original)
        changed["issues"][0]["reason"] = "新版本的判断说明。"
        package["payload"]["project"]["result"] = changed
        restored = import_package(self.store, self.resigned(package))
        old_comment = next(c for c in restored["comments"] if c["target_type"] == "issue")
        self.assertEqual(old_comment["target_state"], "historical")
        self.assertEqual(old_comment["target_snapshot"]["result_fingerprint"], result_fingerprint(original))

    def test_package_version_size_and_malformed_structure_are_rejected(self):
        for changes in ({"format": "other"}, {"schema_version": True}, {"schema_version": 999}, {"exported_at": "today"}):
            package = self.package()
            package.update(changes)
            self.assertRejected(package)
        package = self.package()
        package["payload"]["project"]["description"] = "x" * MAX_PACKAGE_BYTES
        self.assertRejected(self.resigned(package))
        package = self.package()
        package["payload"]["revisions"] = [copy.deepcopy(package["payload"]["revisions"][0])] * 101
        self.assertRejected(self.resigned(package))

    def test_more_than_100_revisions_refuses_export_without_dropping_history(self):
        with self.store.connect() as db:
            content = db.execute("SELECT data FROM revisions WHERE project_id=? LIMIT 1", (self.p["id"],)).fetchone()[0]
            for i in range(99):
                db.execute("INSERT INTO revisions VALUES (?,?,?,?)", (f"extra{i}", self.p["id"], self.p["created_at"], content))
        before = self.rows()
        with self.assertRaises(ReviewError):
            self.package()
        self.assertEqual(self.rows(), before)

    def test_project_secret_and_unknown_configuration_fields_are_not_exported(self):
        with self.store.connect() as db:
            p = json.loads(db.execute("SELECT data FROM projects WHERE id=?", (self.p["id"],)).fetchone()[0])
            p["api_key"] = "fictional-do-not-export"
            p["service_config"] = {"url": "https://example.invalid", "secret": "fictional-do-not-export"}
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(p), self.p["id"]))
        serialized = json.dumps(self.package())
        self.assertNotIn("fictional-do-not-export", serialized)
        self.assertNotIn("service_config", serialized)

    def test_revision_id_collision_rolls_back_new_project_atomically(self):
        package = self.package()
        before = self.rows()
        existing_revision = self.p["history"][0]["id"]
        # project UUID, import activity UUID, first new revision UUID.
        with patch("core.project_packages.uuid.uuid4", side_effect=[SimpleNamespace(hex="freshproject"),
                           SimpleNamespace(hex="freshactivity"), SimpleNamespace(hex=existing_revision)]):
            with self.assertRaises(ReviewError):
                import_package(self.store, package)
        self.assertEqual(self.rows(), before)
        with self.assertRaises(ReviewError):
            self.store.get("freshproject")


if __name__ == "__main__":
    unittest.main()
