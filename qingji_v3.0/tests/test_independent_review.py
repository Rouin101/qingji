"""独立复核：虚构临时项目与内存模型替身，无网络或真实材料。

测试期望正确拒绝过期问题与非法版本；发现未修复问题时会失败，不能当通过记录。
"""
import copy
import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import server
from core.project_packages import MAX_PACKAGE_BYTES, export_package, import_package
from core.projects import ProjectConflict, ProjectStore
from core.review import Document, ReviewError, preliminary_review


def result(quote="当地所有居民都需要帮助。", category="范围外推"):
    return {"mode": "ai", "report": {"id": "report", "name": "虚构社会实践报告", "text": quote,
                                    "notes": [], "source_role": "待确认", "context": "", "collected_at": ""},
            "issues": [{"id": "i1", "start": 0, "end": len(quote), "quote": quote, "category": category,
                        "reason": "这是虚构材料的核对说明。", "next_step": "核对实际对象范围。",
                        "suggested_text": None, "support_status": "partial", "citations": []}],
            "notices": [], "coverage": "submitted_text", "used_material_ids": ["m1"]}


class IndependentStateReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(Path(self.temp.name) / "independent.sqlite3")
        self.original = result()
        material = {"id": "m1", "name": "虚构访谈", "text": "三位受访者表示需要帮助。",
                    "consent_status": "confirmed", "enabled": True}
        p = self.store.create("独立复核虚构项目", self.original["report"], [material])
        self.p = self.store.reviewed(p["id"], p["version"], self.original)
        self.store_patch = patch.object(server, "STORE", self.store)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.temp.cleanup()

    def chat_body(self):
        return {"project_id": self.p["id"], "version": self.p["version"],
                "issue": copy.deepcopy(self.original["issues"][0]), "question": "这条结论需要补充什么？",
                "allow_external_processing": True}

    def test_stale_chat_request_cannot_attach_to_reused_issue_id_after_recheck(self):
        self.store.reviewed(self.p["id"], self.p["version"], result("活动显著提升了居民服务技能。", "成效依据"))
        complete = Mock(return_value=json.dumps({"answer": "这是新结论的答复。"}))
        with patch.object(server, "configured_completion", complete):
            with self.assertRaises((ProjectConflict, ReviewError)):
                server.answer_question(self.chat_body())
        complete.assert_not_called()

    def test_chat_reply_is_rejected_if_authorization_changes_while_model_is_running(self):
        def complete(_messages):
            current = self.store.get(self.p["id"])
            materials = [dict(m, consent_status="unconfirmed") for m in current["materials"]]
            self.store.save(current["id"], current["version"], {"materials": materials})
            return json.dumps({"answer": "按旧处理范围生成的答复。"})

        with patch.object(server, "configured_completion", side_effect=complete) as call:
            with self.assertRaises(ProjectConflict):
                server.answer_question(self.chat_body())
        self.assertEqual(call.call_count, 1)
        current = self.store.get(self.p["id"])
        self.assertTrue(current["needs_review"])
        self.assertEqual(current["materials"][0]["consent_status"], "unconfirmed")

    def test_invalid_float_version_is_rejected_before_any_review_model_call(self):
        body = {"action": "review", "id": self.p["id"], "version": float(self.p["version"]),
                "mode": "ai", "allow_external_processing": True}
        with patch.object(server, "configured_completion", return_value='{"issues":[]}') as complete:
            with self.assertRaises((ProjectConflict, ReviewError)):
                server.project_action(body)
        complete.assert_not_called()

    def test_review_result_cannot_overwrite_a_material_change_during_model_request(self):
        def complete(_messages):
            current = self.store.get(self.p["id"])
            materials = [dict(m, text="另一份已经保存的虚构新记录。") for m in current["materials"]]
            self.store.save(current["id"], current["version"], {"materials": materials})
            return '{"issues":[]}'

        before_history = len(self.p["history"])
        with patch.object(server, "configured_completion", side_effect=complete):
            with self.assertRaises(ProjectConflict):
                server.project_action({"action": "review", "id": self.p["id"], "version": self.p["version"],
                                       "mode": "ai", "allow_external_processing": True})
        current = self.store.get(self.p["id"])
        self.assertEqual(current["materials"][0]["text"], "另一份已经保存的虚构新记录。")
        self.assertTrue(current["needs_review"])
        self.assertEqual(len(current["history"]), before_history)

    @unittest.skipUnless(shutil.which("node"), "下载序列化合同验证需要前端Node运行环境")
    def test_successful_export_fits_the_same_size_limit_used_by_ui_import(self):
        quotes = [f"第{i}位虚构受访者表示需要帮助。" for i in range(1, 201)]
        large = result()
        large["report"]["text"] = "\n".join(quotes)
        large["issues"] = []
        offset = 0
        for i, quote in enumerate(quotes, 1):
            issue = copy.deepcopy(self.original["issues"][0])
            issue.update(id=f"i{i}", start=offset, end=offset + len(quote), quote=quote,
                         reason="当前记录只能说明本次接触的对象，需要核对实际覆盖范围。")
            large["issues"].append(issue)
            offset += len(quote) + 1
        p = self.store.create("虚构较长实践过程", large["report"], self.p["materials"])
        p = self.store.reviewed(p["id"], p["version"], large)
        entry = self.store.revision(p["id"], p["history"][0]["id"])
        entry.pop("discussions", None)  # 运行时视图不能作为原始历史JSON插回测试库。
        entry.pop("changes", None)
        entry.update(previous_result=copy.deepcopy(large), previous_report=copy.deepcopy(large["report"]),
                     previous_materials=copy.deepcopy(p["materials"]))
        with self.store.connect() as db:
            for i in range(68):
                db.execute("INSERT INTO revisions VALUES (?,?,?,?)", (f"independentextra{i}", p["id"], p["created_at"], json.dumps(entry, ensure_ascii=False)))
        db.close()
        package = export_package(self.store, p["id"])
        compact = json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # 执行当前下载按钮的实际JSON.stringify参数，避免继续硬编码已修复的旧美化格式。
        app = (Path(__file__).resolve().parents[1] / "frontend/src/App.jsx").read_text(encoding="utf-8")
        export = app.split("async function exportPackage()", 1)[1].split("async function importPackage", 1)[0]
        match = re.search(r"JSON\.stringify\(data(?:,\s*null(?:,\s*\d+)?)?\)", export)
        self.assertIsNotNone(match, "下载方式变化后需重新核对实际序列化合同")
        code = ("import {readFileSync} from 'node:fs';const data=JSON.parse(readFileSync(0,'utf8'));"
                "process.stdout.write(" + match.group() + ");")
        downloaded = subprocess.run(["node", "--input-type=module", "-e", code],
                                    input=compact, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    check=True, timeout=30).stdout
        self.assertLessEqual(len(compact), MAX_PACKAGE_BYTES)
        self.assertLessEqual(len(downloaded), MAX_PACKAGE_BYTES,
                             f"导出成功但实际下载格式超限：compact={len(compact)}, downloaded={len(downloaded)}")

    def test_default_local_precheck_project_can_export_its_real_coverage(self):
        checked = preliminary_review(Document("report", "虚构本地预检报告", "全部参与者都需要帮助。"))
        checked = json.loads(json.dumps(checked.to_dict()))
        p = self.store.create("虚构本地预检项目", checked["report"])
        p = self.store.reviewed(p["id"], p["version"], checked)
        package = export_package(self.store, p["id"])
        self.assertEqual(package["payload"]["project"]["result"]["coverage"], "expression_scan_only")
        with patch.object(server, "configured_completion") as complete:
            restored = import_package(self.store, package)
        complete.assert_not_called()
        self.assertEqual(restored["result"], checked)
        self.assertTrue(restored["needs_review"])

    def test_valid_local_precheck_with_over_200_marked_sentences_is_exportable(self):
        checked = preliminary_review(Document("report", "虚构较长预检报告", "\n".join("全部参与者都需要帮助。" for _ in range(250))))
        checked = json.loads(json.dumps(checked.to_dict()))
        self.assertEqual(len(checked["issues"]), 250)
        p = self.store.create("虚构250条预检位置", checked["report"])
        p = self.store.reviewed(p["id"], p["version"], checked)
        package = export_package(self.store, p["id"])
        self.assertEqual(len(package["payload"]["project"]["result"]["issues"]), 250)
        restored = import_package(self.store, package)
        self.assertEqual(len(restored["result"]["issues"]), 250)
        self.assertEqual(len(self.store.revision(restored["id"], restored["history"][0]["id"])["result"]["issues"]), 250)

    def completed_evidence(self):
        p = self.store.supplement(self.p["id"], self.p["version"], "i1",
                                  {"id": "m2", "name": "虚构补记", "text": "另一位受访者表示可以独立完成。",
                                   "enabled": True, "consent_status": "confirmed"})
        checked = copy.deepcopy(self.original)
        checked["used_material_ids"] = ["m1", "m2"]
        p = self.store.reviewed(p["id"], p["version"], checked)
        return self.store.task(p["id"], p["version"], p["tasks"][0]["id"], "done")

    def test_malformed_choices_have_controlled_error_and_no_partial_save(self):
        for invalid in ([], {}, None, True, 7):
            with self.subTest(choice=invalid):
                with self.assertRaises(ReviewError):
                    self.store.save(self.p["id"], self.p["version"],
                                    {"description": "这段文字不应部分保存", "choices": {"i1": invalid}})
                self.assertEqual(self.store.get(self.p["id"]), self.p)

    def test_material_removal_reopens_completed_evidence_and_keeps_confirmation_history(self):
        p = self.completed_evidence()
        task = copy.deepcopy(p["tasks"][0])
        p = self.store.create_task(p["id"], p["version"], "已经完成的独立实践分工")
        p = self.store.task(p["id"], p["version"], p["tasks"][-1]["id"], "done")
        p = self.store.save(p["id"], p["version"], {"materials": [m for m in p["materials"] if m["id"] != "m2"]})
        self.assertEqual(p["tasks"][0]["status"], "open")
        self.assertEqual(p["tasks"][0]["confirmed_at"], task["confirmed_at"])
        self.assertEqual(p["tasks"][0]["material_ids"], ["m2"])
        self.assertEqual(p["tasks"][-1]["status"], "done")
        self.assertTrue(p["needs_review"])
        self.assertTrue(any(a["action"] == "evidence_reopened" for a in p["activity"]))
        p = self.store.reviewed(p["id"], p["version"], copy.deepcopy(self.original))
        self.assertEqual(p["tasks"][0]["status"], "awaiting_confirmation")
        with self.assertRaises(ReviewError):
            self.store.task(p["id"], p["version"], task["id"], "done")

    def test_material_content_or_authorization_change_reopens_completed_evidence(self):
        for change in ({"text": "已经替换为另一份虚构记录。"}, {"consent_status": "unconfirmed"}, {"enabled": False}):
            with self.subTest(change=change):
                p = self.completed_evidence()
                materials = [dict(m, **change) if m["id"] == "m2" else m for m in p["materials"]]
                p = self.store.save(p["id"], p["version"], {"materials": materials})
                self.assertEqual(p["tasks"][0]["status"], "open")
                self.assertTrue(p["needs_review"])
                # 下一子用例使用新虚构项目，避免重复 m2 与上一个断言互相依赖。
                self.p = self.store.create("另一虚构范围", self.original["report"], [p["materials"][0]])
                self.p = self.store.reviewed(self.p["id"], self.p["version"], self.original)

    def test_tags_only_keep_completed_evidence_and_original_review_snapshot(self):
        p = self.completed_evidence()
        materials = [dict(m, tags=["社区", "访谈"]) if m["id"] == "m2" else m for m in p["materials"]]
        saved = self.store.save(p["id"], p["version"], {"materials": materials})
        self.assertFalse(saved["needs_review"])
        self.assertEqual(saved["tasks"], p["tasks"])
        self.assertEqual(saved["review_materials"], p["review_materials"])
        self.assertEqual(saved["result"], p["result"])

    def test_unreviewed_manual_edit_cannot_finish_evidence_and_restoring_original_can(self):
        p = self.completed_evidence()
        task_id = p["tasks"][0]["id"]
        p = self.store.task(p["id"], p["version"], task_id, "open")
        p = self.store.save(p["id"], p["version"], {"manual_text": "这是一段尚未复查的新正文。"})
        with self.assertRaises(ReviewError):
            self.store.task(p["id"], p["version"], task_id, "done")
        p = self.store.save(p["id"], p["version"], {"manual_text": p["result"]["report"]["text"]})
        p = self.store.task(p["id"], p["version"], task_id, "done")
        self.assertEqual(p["tasks"][0]["status"], "done")

    def test_concurrent_writers_with_same_version_cannot_silently_replace_each_other(self):
        ready = threading.Barrier(2)

        def update(label):
            other = ProjectStore(self.store.path)
            ready.wait(timeout=5)
            try:
                return other.save(self.p["id"], self.p["version"], {"description": label})
            except ProjectConflict as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(update, ("虚构窗口甲的新记录", "虚构窗口乙的新记录")))
        self.assertEqual(sum(isinstance(o, ProjectConflict) for o in outcomes), 1)
        saved = self.store.get(self.p["id"])
        successful = next(o for o in outcomes if isinstance(o, dict))
        self.assertEqual(saved, successful)
        self.assertEqual(saved["version"], self.p["version"] + 1)
        self.assertEqual(len(saved["activity"]), len(self.p["activity"]) + 1)

    def test_completed_evidence_package_without_author_edits_requires_fresh_confirmation(self):
        p = self.completed_evidence()
        restored = import_package(self.store, export_package(self.store, p["id"]))
        self.assertEqual(restored["tasks"][0]["status"], "awaiting_confirmation")
        self.assertEqual(restored["tasks"][0]["imported_status"], "done")
        self.assertEqual(restored["tasks"][0]["imported_confirmed_at"], p["tasks"][0]["confirmed_at"])
        self.assertNotIn("confirmed_at", restored["tasks"][0])
        with self.assertRaises(ReviewError):
            self.store.task(restored["id"], restored["version"], restored["tasks"][0]["id"], "done")

    def test_accepted_new_wording_reopens_completed_evidence_until_rechecked(self):
        p = self.completed_evidence()
        checked = copy.deepcopy(p["result"])
        checked["issues"][0]["suggested_text"] = "本次三位虚构受访者表示需要帮助。"
        p = self.store.reviewed(p["id"], p["version"], checked)
        p = self.store.task(p["id"], p["version"], p["tasks"][0]["id"], "done")
        p = self.store.save(p["id"], p["version"], {"choices": {"i1": "accepted"}})
        self.assertEqual(p["tasks"][0]["status"], "open")
        with self.assertRaises(ReviewError):
            self.store.task(p["id"], p["version"], p["tasks"][0]["id"], "done")

    def test_new_evidence_for_another_quote_also_invalidates_previous_completion(self):
        p = self.completed_evidence()
        checked = copy.deepcopy(p["result"])
        quote = "活动显著提高了服务成效。"
        start = len(checked["report"]["text"]) + 1
        checked["report"]["text"] += "\n" + quote
        issue = copy.deepcopy(checked["issues"][0])
        issue.update(id="i2", start=start, end=start + len(quote), quote=quote, category="成效依据")
        checked["issues"].append(issue)
        p = self.store.reviewed(p["id"], p["version"], checked)
        p = self.store.task(p["id"], p["version"], p["tasks"][0]["id"], "done")
        p = self.store.supplement(p["id"], p["version"], "i2", {"id": "m3", "name": "另一虚构新材料", "text": "活动完成记录。"})
        self.assertEqual(p["tasks"][0]["status"], "open")
        self.assertEqual(p["tasks"][-1]["status"], "material_added")
        self.assertTrue(p["needs_review"])

    def test_reopening_task_does_not_rewrite_its_previous_confirmation_time(self):
        p = self.completed_evidence()
        old_stamp = p["tasks"][0]["confirmed_at"]
        with patch("core.projects.now", return_value="2099-01-01T00:00:00+00:00"):
            p = self.store.task(p["id"], p["version"], p["tasks"][0]["id"], "open")
        self.assertEqual(p["tasks"][0]["confirmed_at"], old_stamp)
        self.assertEqual(p["activity"][-1]["created_at"], "2099-01-01T00:00:00+00:00")

    def test_material_role_and_task_action_discussions_keep_original_attachment(self):
        p = self.store.comment(self.p["id"], self.p["version"], "material", "m1", "讨论原来源身份。")
        original_snapshot = copy.deepcopy(p["comments"][0]["target_snapshot"])
        p = self.store.save(p["id"], p["version"], {"materials": [dict(m, source_role="工作人员说明") for m in p["materials"]]})
        self.assertEqual(p["comments"][0]["target_state"], "changed")
        self.assertEqual(p["comments"][0]["target_snapshot"], original_snapshot)
        p = self.store.create_task(p["id"], p["version"], "整理原始记录")
        task_id = p["tasks"][0]["id"]
        p = self.store.comment(p["id"], p["version"], "task", task_id, "讨论原任务。")
        p = self.store.task_detail(p["id"], p["version"], task_id, {"action": "重新开展访谈"})
        self.assertEqual(p["comments"][-1]["target_state"], "changed")
        self.assertEqual(p["comments"][-1]["target_snapshot"]["action"], "整理原始记录")

    def test_float_reading_size_cannot_create_project_that_its_own_backup_rejects(self):
        with self.assertRaises(ReviewError):
            self.store.save(self.p["id"], self.p["version"], {"reading_size": 16.0})
        self.assertEqual(self.store.get(self.p["id"]), self.p)

    def test_removed_evidence_can_be_explicitly_replaced_then_reviewed_and_confirmed(self):
        p = self.completed_evidence()
        task_id = p["tasks"][0]["id"]
        old_revision = p["history"][0]["id"]
        old_materials = copy.deepcopy(self.store.revision(p["id"], old_revision)["materials"])
        p = self.store.save(p["id"], p["version"], {"materials": [m for m in p["materials"] if m["id"] != "m2"]})
        p = self.store.supplement(p["id"], p["version"], "i1",
                                  {"id": "m3", "name": "虚构替代补记", "text": "替代记录保留了不同情况。",
                                   "consent_status": "confirmed", "enabled": True})
        self.assertEqual(p["tasks"][0]["material_ids"], ["m2", "m3"])
        with self.assertRaises(ReviewError):
            self.store.task(p["id"], p["version"], task_id, "done")
        p = self.store.task_detail(p["id"], p["version"], task_id, {"material_ids": ["m3"]}, actor="虚构核对同学")
        self.assertEqual(p["tasks"][0]["material_ids"], ["m3"])
        self.assertEqual(p["tasks"][0]["status"], "open")
        self.assertTrue(p["needs_review"])
        change = next(a for a in p["activity"] if a["action"] == "task_materials")
        self.assertIn("m2", change["detail"])
        self.assertIn("虚构替代补记", change["detail"])
        self.assertEqual(change["actor"], "虚构核对同学")
        with self.assertRaises(ReviewError):
            self.store.task(p["id"], p["version"], task_id, "done")
        checked = copy.deepcopy(self.original)
        checked["used_material_ids"] = ["m1", "m3"]
        p = self.store.reviewed(p["id"], p["version"], checked)
        p = self.store.task(p["id"], p["version"], task_id, "done")
        self.assertEqual(p["tasks"][0]["status"], "done")
        self.assertEqual(self.store.revision(p["id"], old_revision)["materials"], old_materials)
        self.assertTrue(any(m["id"] == "m2" for m in old_materials))

    def test_material_link_replacement_is_explicit_scoped_and_atomic(self):
        p = self.completed_evidence()
        task_id = p["tasks"][0]["id"]
        for mids in (None, "m2", ["m2", "m2"], ["m_absent"], [[]], ["m2"] * 9):
            with self.subTest(material_ids=mids):
                with self.assertRaises(ReviewError):
                    self.store.task_detail(p["id"], p["version"], task_id, {"notes": "不得部分保存", "material_ids": mids})
                self.assertEqual(self.store.get(p["id"]), p)
        unchanged = self.store.task_detail(p["id"], p["version"], task_id, {"material_ids": ["m2"]})
        self.assertEqual(unchanged, p)
        p = self.store.task_detail(p["id"], p["version"], task_id, {"material_ids": []})
        self.assertEqual(p["tasks"][0]["material_ids"], [])
        self.assertTrue(p["needs_review"])
        p = self.store.create_task(p["id"], p["version"], "独立分工不冒充证据任务")
        with self.assertRaises(ReviewError):
            self.store.task_detail(p["id"], p["version"], p["tasks"][-1]["id"], {"material_ids": []})

    def test_valid_review_with_full_reading_and_model_notices_remains_backupable(self):
        # PDF文字提取当前每份最多生成2条说明；8份材料+正文+20条合法模型说明+服务说明。
        notes = ["已提取PDF可复制文字，未读取图片。", "第2页没有提取到文字，本次不覆盖该页。"]
        report = dict(self.original["report"], notes=notes)
        materials = [{"id": f"m{i}", "name": f"虚构文字材料{i}", "text": f"第{i}份虚构记录。",
                      "enabled": True, "consent_status": "confirmed", "notes": notes} for i in range(1, 9)]
        p = self.store.create("虚构较多读取说明项目", report, materials)
        with patch.object(server, "configured_completion", return_value=json.dumps({"issues": [], "notices": [f"虚构模型说明{i}" for i in range(20)]})):
            p = server.project_action({"action": "review", "id": p["id"], "version": p["version"], "mode": "ai", "allow_external_processing": True})
        self.assertEqual(len(p["result"]["notices"]), 41)
        package = export_package(self.store, p["id"])
        restored = import_package(self.store, package)
        self.assertEqual(restored["result"]["notices"], p["result"]["notices"])

    def discussed_versions(self, same_quote=False):
        p = self.store.comment(self.p["id"], self.p["version"], "issue", "i1", "这是旧判断的讨论。", actor="旧版讨论同学")
        old_revision = p["history"][0]["id"]
        changed = result() if same_quote else result("活动显著提升了居民服务技能。", "成效依据")
        changed["issues"][0]["reason"] = "这是另一次核验的不同解释。"
        p = self.store.reviewed(p["id"], p["version"], changed)
        p = self.store.comment(p["id"], p["version"], "issue", "i1", "这是新判断的讨论。", actor="新版讨论同学")
        return p, old_revision

    def test_revision_discussions_restore_old_and_new_reused_issue_ids_separately(self):
        p, old_revision = self.discussed_versions()
        p = self.store.comment(p["id"], p["version"], "material", "m1", "材料讨论不应出现在结论讨论组。")
        current = self.store.revision(p["id"], p["history"][0]["id"])
        old = self.store.revision(p["id"], old_revision)
        self.assertEqual([c["body"] for c in current["discussions"]["current_review"]], ["这是新判断的讨论。"])
        self.assertEqual([c["body"] for c in current["discussions"]["previous_review"]], ["这是旧判断的讨论。"])
        self.assertEqual([c["body"] for c in old["discussions"]["current_review"]], ["这是旧判断的讨论。"])
        self.assertEqual(old["discussions"]["previous_review"], [])
        previous = current["discussions"]["previous_review"][0]
        self.assertEqual(previous["quote"], self.original["issues"][0]["quote"])
        self.assertEqual(previous["actor"], "旧版讨论同学")
        self.assertEqual(previous["target_snapshot"], p["comments"][0]["target_snapshot"])
        self.assertFalse(previous["unverified"])

    def test_revision_discussions_use_whole_judgment_even_for_same_id_quote_and_category(self):
        p, old_revision = self.discussed_versions(same_quote=True)
        current = self.store.revision(p["id"], p["history"][0]["id"])["discussions"]
        self.assertEqual([c["body"] for c in current["current_review"]], ["这是新判断的讨论。"])
        self.assertEqual([c["body"] for c in current["previous_review"]], ["这是旧判断的讨论。"])
        self.assertNotEqual(current["current_review"][0]["target_snapshot"]["result_fingerprint"],
                            current["previous_review"][0]["target_snapshot"]["result_fingerprint"])

    def test_revision_discussions_do_not_leak_other_projects_or_change_stored_package(self):
        p, _ = self.discussed_versions()
        other = self.store.create("其他虚构项目", p["result"]["report"], p["materials"])
        other = self.store.reviewed(other["id"], other["version"], p["result"])
        other = self.store.comment(other["id"], other["version"], "issue", "i1", "其他项目的同指纹讨论。")
        before = export_package(self.store, p["id"])
        revision_id = p["history"][0]["id"]
        with self.store.connect() as db:
            raw_before = db.execute("SELECT data FROM revisions WHERE id=?", (revision_id,)).fetchone()[0]
        db.close()
        shown = self.store.revision(p["id"], revision_id)
        self.assertNotIn("其他项目", json.dumps(shown["discussions"], ensure_ascii=False))
        with self.assertRaises(ReviewError):
            self.store.revision(other["id"], revision_id)
        after = export_package(self.store, p["id"])
        self.assertEqual(after["sha256"], before["sha256"])
        self.assertEqual(after["payload"], before["payload"])
        with self.store.connect() as db:
            raw_after = db.execute("SELECT data FROM revisions WHERE id=?", (revision_id,)).fetchone()[0]
        db.close()
        self.assertEqual(raw_after, raw_before)
        self.assertNotIn("discussions", raw_after)

    def test_imported_revision_discussions_keep_unverified_flag_after_local_recheck(self):
        p, _ = self.discussed_versions()
        restored = import_package(self.store, export_package(self.store, p["id"]))
        imported_revision = restored["history"][0]["id"]
        shown = self.store.revision(restored["id"], imported_revision)["discussions"]
        self.assertTrue(shown["current_review"][0]["unverified"])
        self.assertTrue(shown["previous_review"][0]["unverified"])
        changed = copy.deepcopy(restored["result"])
        changed["issues"][0]["reason"] = "这是在本机重新核验后的解释。"
        changed["used_material_ids"] = []
        restored = self.store.reviewed(restored["id"], restored["version"], changed)
        restored = self.store.comment(restored["id"], restored["version"], "issue", "i1", "本机复查后的新讨论。")
        shown = self.store.revision(restored["id"], restored["history"][0]["id"])["discussions"]
        self.assertFalse(shown["current_review"][0]["unverified"])
        self.assertTrue(shown["previous_review"][0]["unverified"])
        self.assertEqual(shown["previous_review"][0]["body"], "这是新判断的讨论。")


if __name__ == "__main__":
    unittest.main()
