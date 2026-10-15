"""虚构历史快照的变化摘要：不调用模型，不使用真实实践材料。"""

import copy
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from core.project_packages import export_package
from core.projects import ProjectStore
from core.review_changes import review_changes


def issue(quote, start=0, identity="i1", **updates):
    item = {"id": identity, "quote": quote, "start": start, "end": start + len(quote), "category": "范围外推",
            "reason": "只描述虚构本次对象。", "next_step": "保留原始材料。", "suggested_text": None,
            "support_status": "pending", "citations": []}
    return item | updates


def result(text, items=None, used=None, mode="preliminary"):
    value = {"mode": mode, "report": {"id": "report", "name": "虚构报告", "text": text, "notes": []},
             "issues": items if items is not None else [issue(text)], "notices": [], "coverage": "submitted_text"}
    if used is not None:
        value["used_material_ids"] = used
    return value


def material(identity="m1", **updates):
    return {"id": identity, "name": "虚构访谈", "text": "本次3位受访者表示更方便。", "notes": [],
            "source_role": "受访者陈述", "context": "虚构大厅", "collected_at": "2026-10-03",
            "consent_status": "confirmed", "enabled": True, "tags": []} | updates


def entry(before, after, previous_materials=None, materials=None):
    return {"previous_result": before, "result": after, "previous_materials": previous_materials or [],
            "materials": materials or [], "choices": {}}


class ReviewChangesTests(unittest.TestCase):
    def test_candidate_only_change_is_visible_without_claiming_support_changed(self):
        quote = "所有居民都受益。"
        before = result(quote, [issue(quote)], [])
        after = result(quote, [issue(quote, suggested_text="本次三位受访者表示更方便。")], [])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["changed"][0]["fields"],
                         [{"field":"suggested_text", "before":None, "after":"本次三位受访者表示更方便。"}])
        self.assertIn("原句记录1条变化", changes["summary"])

    def test_next_step_only_change_is_visible_for_the_same_original_sentence(self):
        quote = "所有居民都受益。"
        before = result(quote, [issue(quote)], [])
        after = result(quote, [issue(quote, next_step="补访其他对象，记录不同情况。")], [])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["changed"][0]["fields"],
                         [{"field":"next_step", "before":"保留原始材料。", "after":"补访其他对象，记录不同情况。"}])

    def test_no_baseline_is_not_all_new_or_all_resolved(self):
        changes = review_changes(entry(None, result("所有居民都受益。", used=[])))
        self.assertFalse(changes["baseline_available"])
        self.assertFalse(changes["records"]["available"])
        self.assertNotIn("listed_new", changes["records"])
        self.assertTrue(changes["scope"]["current_known"])

    def test_reused_issue_id_for_different_quote_is_not_paired(self):
        before = result("所有居民都受益。", used=[])
        after = result("活动造成长期行为改变。", used=[])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["matched_count"], 0)
        self.assertEqual(len(changes["records"]["listed_new"]), 1)
        self.assertEqual(len(changes["records"]["no_longer_listed"]), 1)
        self.assertEqual(changes["records"]["changed"], [])

    def test_unique_quote_matches_after_movement_and_id_reassignment(self):
        quote = "本次3位受访者表示更方便。"
        before = result(quote, [issue(quote, support_status="partial")], [], "ai")
        after = result("背景。\n" + quote, [issue(quote, 4, "i9", support_status="supported")], [], "ai")
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["matched_count"], 1)
        self.assertEqual(changes["records"]["changed"][0]["fields"],
                         [{"field": "support_status", "before": "partial", "after": "supported"}])

    def test_repeated_quote_in_changed_report_remains_ambiguous_even_with_same_ids(self):
        quote = "本次访谈对象表示方便。"
        text = quote + "\n" + quote
        before = result(text, [issue(quote), issue(quote, len(quote) + 1, "i2")], [])
        after = result("新背景。\n" + text, [issue(quote, 5), issue(quote, len(quote) + 6, "i2")], [])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["matched_count"], 0)
        self.assertEqual(len(changes["records"]["ambiguous_previous"]), 2)
        self.assertEqual(len(changes["records"]["ambiguous_current"]), 2)
        self.assertEqual(changes["records"]["listed_new"], [])

    def test_repeated_quote_in_unchanged_report_uses_unique_positions_and_not_order_or_id(self):
        quote = "本次访谈对象表示方便。"
        text = quote + "\n" + quote
        first = issue(quote)
        second = issue(quote, len(quote) + 1, "i2")
        before = result(text, [first, second], [])
        after = result(text, [second | {"id": "i1", "reason": "第二个位置的说明变化。"}, first | {"id": "i2"}], [])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["matched_count"], 2)
        self.assertEqual(changes["records"]["changed"][0]["current_position"], [len(quote) + 1, len(text)])
        self.assertEqual(changes["records"]["ambiguous_current"], [])

    def test_same_quote_with_duplicate_position_is_not_guessed(self):
        quote = "本次访谈对象表示方便。"
        before = result(quote, [issue(quote), issue(quote, identity="i2")], [])
        after = result(quote, [issue(quote, reason="新说明。")], [])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["records"]["matched_count"], 0)
        self.assertEqual(len(changes["records"]["ambiguous_previous"]), 2)

    def test_category_reason_and_citation_position_relation_changes_are_explicit(self):
        quote = "本次3位受访者表示更方便。"
        citation = {"document_id": "m1", "document_name": "虚构访谈", "start": 0, "end": 2,
                    "quote": "方便", "relation": "support"}
        before = result(quote, [issue(quote, citations=[citation])], ["m1"])
        after = result(quote, [issue(quote, category="来源表述", reason="说明来源。",
                                    citations=[citation | {"start": 5, "end": 7, "relation": "context"}])], ["m1"])
        changes = review_changes(entry(before, after, [material()], [material()]))
        self.assertEqual([f["field"] for f in changes["records"]["changed"][0]["fields"]],
                         ["category", "reason", "citations"])

    def test_citation_document_change_and_repetition_change_are_not_lost(self):
        quote = "本次3位受访者表示更方便。"
        citation = {"document_id": "m1", "document_name": "虚构访谈", "start": 0, "end": 2,
                    "quote": "方便", "relation": "support"}
        before = result(quote, [issue(quote, citations=[citation])], ["m1"])
        for citations in ([citation | {"document_id": "m2"}], [citation, citation]):
            with self.subTest(citations=citations):
                after = result(quote, [issue(quote, citations=citations)], ["m1"])
                self.assertEqual(review_changes(entry(before, after))["records"]["changed"][0]["fields"][0]["field"], "citations")

    def test_citation_order_alone_is_not_a_changed_basis(self):
        quote = "本次对象表示方便。"
        citations = [{"document_id": "m1", "start": 0, "end": 2, "quote": "方便", "relation": "support"},
                     {"document_id": "m2", "start": 0, "end": 2, "quote": "限制", "relation": "context"}]
        before = result(quote, [issue(quote, citations=citations)], [])
        after = result(quote, [issue(quote, citations=citations[::-1])], [])
        self.assertEqual(review_changes(entry(before, after))["records"]["changed"], [])

    def test_pending_is_not_converted_to_unsupported(self):
        quote = "本次对象表示方便。"
        before = result(quote, used=[])
        del before["issues"][0]["support_status"]
        after = result(quote, used=[])
        self.assertEqual(review_changes(entry(before, after))["records"]["changed"], [])
        self.assertEqual(after["issues"][0]["support_status"], "pending")

    def test_line_changes_do_not_claim_semantic_sentences(self):
        before = result("共同背景。\n所有居民都受益。\n20人次。", [], [])
        after = result("共同背景。\n仅本次对象受益。\n20人次不等于20人。", [], [])
        changes = review_changes(entry(before, after))
        self.assertEqual(changes["report"]["modified_lines"], 2)
        self.assertEqual(changes["report"]["added_lines"], 0)
        self.assertIn("2行", changes["summary"])
        self.assertNotIn("句", changes["summary"])

    def test_line_insert_delete_and_long_repetition_are_bounded(self):
        before = result("a\nb\nc", [], [])
        after = result("a\nx\ny\nc", [], [])
        delta = review_changes(entry(before, after))["report"]
        self.assertEqual((delta["modified_lines"], delta["added_lines"], delta["removed_lines"]), (1, 1, 0))
        text = "相同。\n" * 4500
        delta = review_changes(entry(result(text, [], []), result(text + "补充。", [], [])))["report"]
        self.assertEqual(delta["added_lines"], 1)

    def test_material_diff_compares_snapshots_and_exposes_text_source_authorization(self):
        before = result("本次对象表示方便。", used=["m1"])
        after = copy.deepcopy(before)
        old = material()
        new = material(text="新虚构文字。", context="另一虚构场景", consent_status="unconfirmed", enabled=False)
        changes = review_changes(entry(before, after, [old, material("m2")], [new, material("m3")]))
        self.assertEqual(changes["materials"]["changed"][0]["fields"], ["text", "consent_status", "enabled", "source"])
        self.assertEqual(changes["materials"]["added"][0]["id"], "m3")
        self.assertEqual(changes["materials"]["removed"][0]["id"], "m2")

    def test_missing_scope_is_unknown_and_zero_is_known_not_derived_from_authorization(self):
        before = result("本次对象表示方便。")
        after = result("本次对象表示方便。", used=[])
        changes = review_changes(entry(before, after, [material()], [material()]))
        self.assertFalse(changes["scope"]["previous_known"])
        self.assertTrue(changes["scope"]["current_known"])
        self.assertIsNone(changes["scope"]["changed"])
        self.assertEqual(changes["scope"]["current_ids"], [])
        self.assertIn("未记录", changes["summary"])
        before["used_material_ids"] = ["m1"]
        self.assertTrue(review_changes(entry(before, after, [material()], [material()]))["scope"]["changed"])

    def test_missing_material_snapshot_is_not_everything_added(self):
        before = result("本次对象表示方便。", used=["m1"])
        value = entry(before, copy.deepcopy(before), [], [material()])
        value.pop("previous_materials")
        changes = review_changes(value)
        self.assertFalse(changes["materials"]["available"])
        self.assertEqual(changes["materials"]["added"], [])

    def test_input_unchanged_and_imported_history_is_explicit(self):
        before = result("本次对象表示方便。", used=[])
        value = entry(before, result("仅本次对象表示方便。", used=[])) | {"imported_unverified": True}
        original = copy.deepcopy(value)
        changes = review_changes(value)
        self.assertEqual(value, original)
        self.assertTrue(any("未在本机复核" in text for text in changes["notes"]))

    def test_imported_history_without_baseline_is_still_unverified(self):
        changes = review_changes(entry(None, result("本次对象表示方便。", used=[])) | {"imported_unverified": True})
        self.assertTrue(any("未在本机复核" in text for text in changes["notes"]))

    def test_legacy_revision_recovers_previous_materials_from_actual_earlier_result(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / "legacy.sqlite3")
            quote = "本次对象表示方便。"
            first = result(quote, used=["m1"])
            p = store.create("虚构旧快照项目", first["report"], [material()])
            p = store.reviewed(p["id"], p["version"], first)
            p = store.save(p["id"], p["version"], {"materials": [material(text="复查时材料。", context="新场景")]})
            p = store.reviewed(p["id"], p["version"], result(quote, [issue(quote, reason="新说明。")], ["m1"]))
            revision_id = p["history"][0]["id"]
            with closing(store.connect()) as db, db:
                raw = json.loads(db.execute("SELECT data FROM revisions WHERE id=?", (revision_id,)).fetchone()[0])
                del raw["previous_materials"]
                db.execute("UPDATE revisions SET data=? WHERE id=?", (json.dumps(raw), revision_id))
            view = store.revision(p["id"], revision_id)
            self.assertTrue(view["changes"]["materials"]["available"])
            self.assertEqual(view["previous_materials"][0]["text"], material()["text"])
            self.assertEqual(view["changes"]["materials"]["changed"][0]["fields"], ["text", "source"])

    def test_legacy_without_reliable_previous_snapshot_is_unknown_not_new_material(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / "missing.sqlite3")
            quote = "本次对象表示方便。"
            first = result(quote, used=["m1"])
            p = store.create("虚构不完整旧快照", first["report"], [material()], result=first)
            p = store.reviewed(p["id"], p["version"], result(quote, [issue(quote, reason="新说明。")], ["m1"]))
            revision_id = p["history"][0]["id"]
            with closing(store.connect()) as db, db:
                raw = json.loads(db.execute("SELECT data FROM revisions WHERE id=?", (revision_id,)).fetchone()[0])
                del raw["previous_materials"]
                db.execute("UPDATE revisions SET data=? WHERE id=?", (json.dumps(raw), revision_id))
            view = store.revision(p["id"], revision_id)
            self.assertFalse(view["changes"]["materials"]["available"])
            self.assertEqual(view["changes"]["materials"]["added"], [])

    def test_revision_read_does_not_write_db_or_backup_and_ignores_later_material_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ProjectStore(Path(folder) / "fictional.sqlite3")
            quote = "本次3位受访者表示更方便。"
            first = result(quote, used=["m1"])
            p = store.create("虚构变化摘要项目", first["report"], [material()])
            p = store.reviewed(p["id"], p["version"], first)
            p = store.save(p["id"], p["version"], {"materials": [material(text="复查时的虚构材料。", context="复查场景")]})
            second = result(quote, [issue(quote, reason="本轮说明更新。")], ["m1"])
            p = store.reviewed(p["id"], p["version"], second)
            revision_id = p["history"][0]["id"]
            p = store.save(p["id"], p["version"], {"materials": [material(text="核对结束后后来修改的文字。", context="更晚场景")]})
            package_before = export_package(store, p["id"])
            with closing(store.connect()) as db:
                db_before = db.execute("SELECT data FROM revisions ORDER BY rowid").fetchall()
                project_before = db.execute("SELECT data FROM projects").fetchall()
            first_view = store.revision(p["id"], revision_id)
            second_view = store.revision(p["id"], revision_id)
            self.assertEqual(first_view["changes"], second_view["changes"])
            self.assertEqual(first_view["materials"][0]["text"], "复查时的虚构材料。")
            self.assertEqual(first_view["previous_materials"][0]["text"], material()["text"])
            self.assertEqual(first_view["changes"]["materials"]["changed"][0]["fields"], ["text", "source"])
            self.assertEqual(export_package(store, p["id"]), package_before)
            with closing(store.connect()) as db:
                self.assertEqual(db.execute("SELECT data FROM revisions ORDER BY rowid").fetchall(), db_before)
                self.assertEqual(db.execute("SELECT data FROM projects").fetchall(), project_before)
            self.assertNotIn('"changes"', "".join(row[0] for row in db_before))


if __name__ == "__main__":
    unittest.main()
