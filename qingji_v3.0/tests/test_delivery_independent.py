"""Independent saved-version checks using fictional projects and temporary SQLite.

These tests do not call a model and do not assert report quality or approval.
"""
import copy
import json
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from core.delivery_check import delivery_check, delivery_markdown
from core.project_packages import export_package, import_package
from core.projects import ProjectStore
from core.review import Document, validate_model_result


class _ReadThenWriteCursor:
    def __init__(self, cursor, write):
        self.cursor, self.write = cursor, write

    def fetchone(self):
        row = self.cursor.fetchone()
        # End the SELECT statement, while an explicit transaction must remain.
        self.cursor.close()
        self.write()
        return row


class _InterleavedConnection:
    def __init__(self, connection, write):
        self.connection, self.write = connection, write

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, params)
        if sql == "SELECT data FROM projects WHERE id=?":
            return _ReadThenWriteCursor(cursor, self.write)
        return cursor

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def close(self):
        self.connection.close()


class IndependentDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(Path(self.temp.name) / "fictional.sqlite3")
        report = Document("report", "虚构签到报告", "本次有20名不同居民参加。")
        self.material = {"id": "m1", "name": "虚构签到说明", "text": "签到合计20人次，重复参加尚未去重。",
                         "source_role": "正式记录", "context": "人工构造的两个时段",
                         "collected_at": "2026-10-03", "enabled": True, "consent_status": "confirmed"}
        response = {"issues": [{"passage_id": "s1", "quote": report.text,
            "category": "数字口径", "support_status": "unsupported",
            "reason": "未去重的人次记录不能确定不同人数。", "next_step": "核对去重名单。",
            "suggested_text": "本次签到记录20人次，尚未去重。",
            "citations": [{"document_id": "m1", "quote": self.material["text"], "relation": "context"}]}]}
        self.result = validate_model_result(json.dumps(response), report,
            [Document("m1", self.material["name"], self.material["text"])]).to_dict()
        self.result = json.loads(json.dumps(self.result))
        self.result["used_material_ids"] = ["m1"]

    def tearDown(self):
        self.temp.cleanup()

    def source_project(self, with_history=True):
        project = self.store.create("虚构交接核对", self.result["report"], [self.material],
                                    result=None if with_history else self.result)
        if with_history:
            project = self.store.reviewed(project["id"], project["version"], self.result)
        return project

    def assert_import_then_local_recheck(self, with_history):
        source = self.source_project(with_history)
        imported = import_package(self.store, export_package(self.store, source["id"]))
        self.assertEqual(imported["result"], source["result"])
        self.assertTrue(imported["needs_review"])
        self.assertEqual(imported["materials"][0]["consent_status"], "unconfirmed")
        if with_history:
            self.assertTrue(self.store.revision(imported["id"], imported["history"][0]["id"])["imported_unverified"])
        else:
            self.assertEqual(imported["history"], [])
        before = copy.deepcopy(imported)
        with patch("core.review.configured_completion", side_effect=AssertionError("交付状态不得调用模型")):
            initial = delivery_check(imported)
            markdown = delivery_markdown(initial)
        self.assertEqual(imported, before)
        self.assertFalse(initial["review"]["current"])
        self.assertIn("未在本机复核", initial["review"]["label"])
        self.assertIn("未在本机复核", markdown)
        self.assertEqual(initial["materials"]["total"], 1)
        self.assertEqual(initial["materials"]["eligible_current"], 0)
        self.assertEqual(initial["review"]["support_counts"]["unsupported"], 1)

        # Re-authorizing alone does not convert the imported judgment to local.
        authorized = copy.deepcopy(imported["materials"])
        authorized[0]["consent_status"] = "confirmed"
        imported = self.store.save(imported["id"], imported["version"], {"materials": authorized})
        self.assertIn("未在本机复核", delivery_check(imported)["review"]["label"])

        # A genuine local reviewed transition may have an identical fingerprint;
        # imported_from remains provenance, not a permanent foreign-result flag.
        local = self.store.reviewed(imported["id"], imported["version"], copy.deepcopy(self.result))
        self.assertTrue(local.get("imported_from"))
        self.assertFalse(self.store.revision(local["id"], local["history"][0]["id"]).get("imported_unverified", False))
        local_check = delivery_check(local)
        self.assertTrue(local_check["review"]["current"])
        self.assertNotIn("未在本机复核", local_check["review"]["label"])
        self.assertEqual(local_check["review"]["label"], "AI审阅")
        self.assertNotIn("未在本机复核", delivery_markdown(local_check))
        self.assertEqual(local_check["review"]["support_counts"]["unsupported"], 1)
        self.assertEqual(self.store.get(local["id"])["version"], local["version"])

    def test_actual_imported_history_stays_unverified_until_local_recheck(self):
        self.assert_import_then_local_recheck(with_history=True)

    def test_imported_result_without_history_uses_provenance_until_first_local_recheck(self):
        self.assert_import_then_local_recheck(with_history=False)

    def test_project_and_history_are_one_read_snapshot_during_concurrent_commit(self):
        project = self.source_project(with_history=True)
        connect = self.store.connect
        with closing(connect()) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower(), "wal")
            old_entry = json.loads(db.execute("SELECT data FROM revisions WHERE project_id=?", (project["id"],)).fetchone()[0])
        injected = []

        def concurrent_commit():
            self.assertFalse(injected)
            injected.append(True)
            changed = copy.deepcopy(project)
            changed.pop("history", None)
            changed["version"] += 1
            changed["name"] = "另一个窗口已更新的虚构项目"
            entry = copy.deepcopy(old_entry)
            entry["summary"] = "并发新增复查"
            with closing(connect()) as writer, writer:
                writer.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(changed), project["id"]))
                writer.execute("INSERT INTO revisions VALUES (?,?,?,?)", (
                    uuid.uuid4().hex, project["id"], "2030-01-01T00:00:00+00:00", json.dumps(entry)))

        with patch.object(self.store, "connect", side_effect=lambda: _InterleavedConnection(connect(), concurrent_commit)):
            snapshot = self.store.get(project["id"])
        self.assertEqual(len(injected), 1)
        self.assertEqual(snapshot["version"], project["version"])
        self.assertEqual(snapshot["name"], project["name"])
        self.assertEqual(len(snapshot["history"]), 1,
                         "旧版本项目行不能混入并发提交的新历史。")
        check = delivery_check(snapshot)
        self.assertEqual(check["version"], project["version"])
        self.assertNotEqual(check["review"]["last_review_at"], "2030-01-01T00:00:00+00:00")
        refreshed = self.store.get(project["id"])
        self.assertEqual(refreshed["version"], project["version"] + 1)
        self.assertEqual(len(refreshed["history"]), 2)


if __name__ == "__main__":
    unittest.main()
