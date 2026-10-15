"""通过真实本地 HTTP 验证协作、交接与补证计划，不读取实际库或调用模型。"""
import copy
import http.client
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path
from unittest.mock import patch

import server
from core.projects import ProjectStore
from core.review import MAX_REPORT_CHARS, read_document


def plan_json():
    return json.dumps({"goal":"核对接触范围与不同情况。",
                       "questions":[{"question":"最近一次接触服务的经历是什么？未接触也可以说明。",
                                     "purpose":"记录实际经历，不预设人人参与。"}],
                       "observations":["保留独立完成、求助和未尝试的实际情况。"],
                       "record_fields":["匿名对象代码、日期、场景与授权"],
                       "limits":["未接触对象的情况仍未知。"]},ensure_ascii=False)


class HTTPWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=ProjectStore(Path(self.temp.name)/"fictional-http.sqlite3")
        self.store_patch=patch.object(server,"STORE",self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.model_patch=patch.object(server,"configured_completion",return_value=plan_json())
        self.model=self.model_patch.start()
        self.addCleanup(self.model_patch.stop)
        self.status_patch=patch.object(server,"ai_configured",return_value=False)
        self.status_patch.start()
        self.addCleanup(self.status_patch.stop)
        self.http=server.LocalHTTPServer(("127.0.0.1",0),server.Handler)
        # Finish in-flight fixture requests before unpatching STORE, even if setUp fails.
        self.http.daemon_threads=False
        self.addCleanup(self.http.server_close)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(lambda: self.thread.join(2))
        self.addCleanup(self.http.shutdown)
        self.base=f"http://127.0.0.1:{self.http.server_port}"
        status,self.p=self.call("/api/projects",{"action":"example","actor":"虚构同学甲"})
        self.assertEqual(status,200)

    def call(self,path,body=None,headers=None):
        headers=dict(headers or {})
        data=None
        if body is not None:
            data=json.dumps(body,ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type","application/json")
        request=urllib.request.Request(self.base+path,data=data,headers=headers)
        try:
            # Local fixture disk writes may be delayed by Windows scanning; this is not a latency test.
            response=urllib.request.urlopen(request,timeout=15)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:
            return response.status,json.loads(response.read())

    def action(self,action,**fields):
        body={"action":action,"id":self.p["id"],"version":self.p["version"],"actor":"虚构同学甲",**fields}
        status,value=self.call("/api/projects",body)
        if status==200:
            self.p=value
        return status,value

    def binary_call(self,path,body,headers=None):
        request=urllib.request.Request(self.base+path,data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
                                       headers={"Content-Type":"application/json",**(headers or {})})
        try:
            response=urllib.request.urlopen(request,timeout=5)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:
            return response.status,response.read(),dict(response.headers)

    def assert_unchanged(self,original):
        self.assertEqual(self.store.get(original["id"]),original)

    def test_team_task_discussion_archive_and_restore_flow_through_http(self):
        self.assertEqual(self.action("members",members=[{"name":"虚构同学甲","role":"访谈"},{"name":"虚构同学乙","role":"整理"}])[0],200)
        mid=self.p["members"][0]["id"]
        self.assertEqual(self.action("create_task",action_text="整理下一次访谈提纲",assignee_id=mid,due_date="2001-01-01",notes="先确认采访安排")[0],200)
        tid=self.p["tasks"][-1]["id"]
        self.assertEqual(self.action("task_detail",task_id=tid,changes={"notes":"已经确认采访安排","due_date":"2026-10-08"})[0],200)
        self.assertEqual(self.action("comment",target_type="task",target_id=tid,body="按实际接触对象补记不同情况")[0],200)
        self.assertEqual(self.action("task",task_id=tid,status="done")[0],200)
        before=copy.deepcopy(self.p)
        self.assertEqual(self.action("archive",archived=True)[0],200)
        self.assertEqual(self.p["tasks"],before["tasks"])
        self.assertEqual(self.p["comments"],before["comments"])
        self.assertTrue(self.p["archived"])
        self.assertEqual(self.action("archive",archived=False)[0],200)
        self.assertFalse(self.p["archived"])
        status,listed=self.call("/api/projects")
        self.assertEqual(status,200)
        self.assertEqual(listed["projects"][0]["team_count"],2)
        self.assertEqual(listed["projects"][0]["task_count"],0)
        self.assertEqual(self.p["tasks"][-1]["notes"],"已经确认采访安排")
        self.assertEqual(self.p["comments"][-1]["actor"],"虚构同学甲")
        self.model.assert_not_called()

    def test_every_team_mutation_checks_stale_version_without_overwriting(self):
        self.action("create_task",action_text="待分工实践任务")
        tid=self.p["tasks"][-1]["id"]
        stale=self.p["version"]
        self.action("save",changes={"description":"这次实际更新已保存"})
        current=copy.deepcopy(self.p)
        cases=[{"action":"members","members":[{"name":"旧请求成员"}]},
               {"action":"task_detail","task_id":tid,"changes":{"notes":"旧请求记录"}},
               {"action":"create_task","action_text":"旧请求任务"},
               {"action":"comment","target_type":"project","body":"旧请求讨论"},
               {"action":"archive","archived":True},
               {"action":"task","task_id":tid,"status":"done"}]
        for fields in cases:
            with self.subTest(action=fields["action"]):
                status,value=self.call("/api/projects",{"id":current["id"],"version":stale,**fields})
                self.assertEqual(status,409)
                self.assertIn("error",value)
        self.assert_unchanged(current)

    def test_assignment_membership_and_comment_target_are_project_scoped(self):
        _,other=self.call("/api/projects",{"action":"create","name":"另一个虚构实践项目"})
        _,other=self.call("/api/projects",{"action":"members","id":other["id"],"version":other["version"],"members":[{"name":"其他团队成员"}]})
        _,other=self.call("/api/projects",{"action":"create_task","id":other["id"],"version":other["version"],"action_text":"其他团队任务"})
        before=copy.deepcopy(self.p)
        self.assertEqual(self.action("create_task",action_text="不能错派",assignee_id=other["members"][0]["id"])[0],400)
        self.assertEqual(self.action("comment",target_type="task",target_id=other["tasks"][0]["id"],body="不能错挂")[0],400)
        self.assertEqual(self.action("comment",target_type="project",target_id=other["id"],body="不能错挂")[0],400)
        self.assert_unchanged(before)

    def test_removing_member_unassigns_without_deleting_task_or_comment(self):
        self.action("members",members=[{"name":"虚构同学甲","role":"访谈"}])
        self.action("create_task",action_text="整理提纲",assignee_id=self.p["members"][0]["id"])
        tid=self.p["tasks"][-1]["id"]
        self.action("comment",target_type="task",target_id=tid,body="这项任务仍需继续")
        self.assertEqual(self.action("members",members=[])[0],200)
        self.assertEqual(self.p["tasks"][-1]["assignee_id"],"")
        self.assertEqual(self.p["tasks"][-1]["id"],tid)
        self.assertEqual(self.p["comments"][-1]["target_state"],"current")
        self.assertTrue(any(a["action"]=="task_unassigned" for a in self.p["activity"]))

    def test_invalid_actor_member_due_date_and_archive_are_controlled_and_atomic(self):
        before=copy.deepcopy(self.p)
        invalid=[{"action":"members","members":[{"name":"虚构同学甲"}],"actor":"x"*61},
                 {"action":"members","members":[{"name":"同名"},{"name":"同名"}]},
                 {"action":"create_task","action_text":"不应写入","due_date":"2026-02-30"},
                 {"action":"archive","archived":"true"},
                 {"action":"comment","target_type":"project","body":""}]
        for fields in invalid:
            with self.subTest(action=fields["action"]):
                self.assertEqual(self.call("/api/projects",{"id":before["id"],"version":before["version"],**fields})[0],400)
        self.assert_unchanged(before)

    def test_export_import_is_an_independent_unreviewed_copy_and_keeps_original(self):
        self.action("members",members=[{"name":"虚构同学甲","role":"访谈"}])
        self.action("create_task",action_text="整理现场记录",assignee_id=self.p["members"][0]["id"])
        self.action("comment",target_type="project",body="团队交接说明")
        before=copy.deepcopy(self.p)
        status,package=self.call("/api/package?id="+before["id"])
        self.assertEqual(status,200)
        self.assertEqual(package["format"],"qingji-project")
        self.assertNotIn("QINGJI_V2_API_KEY",json.dumps(package))
        self.assertNotIn("ai-config",json.dumps(package))
        status,restored=self.call("/api/projects",{"action":"import","package":package,"actor":"虚构接收同学"})
        self.assertEqual(status,200)
        self.assertNotEqual(restored["id"],before["id"])
        self.assertTrue(restored["needs_review"])
        self.assertEqual(restored["report"],before["report"])
        self.assertEqual(len(restored["history"]),len(before["history"]))
        self.assertTrue(all(m["consent_status"]=="unconfirmed" for m in restored["materials"]))
        self.assertEqual(restored["members"],before["members"])
        self.assertEqual(restored["comments"][0]["target_id"],restored["id"])
        self.assertIn("未在本机复核",restored["imported_from"]["warning"])
        self.assert_unchanged(before)
        self.model.assert_not_called()

    def test_corrupted_package_import_is_rejected_without_partial_project(self):
        _,package=self.call("/api/package?id="+self.p["id"])
        package["payload"]["project"]["description"]="包已被改动"
        before_count=len(self.store.list())
        status,value=self.call("/api/projects",{"action":"import","package":package})
        self.assertEqual(status,400)
        self.assertIn("完整性",value["error"])
        self.assertEqual(len(self.store.list()),before_count)
        self.assertEqual(self.call("/api/projects",{"action":"import","package":[]})[0],400)
        self.assertEqual(self.call("/api/package?id=does-not-exist")[0],404)

    def test_template_plan_checks_current_version_without_model_or_data_write(self):
        original=copy.deepcopy(self.p)
        body={"project_id":original["id"],"version":original["version"],"issue_id":"i1","mode":"template"}
        status,plan=self.call("/api/plan",body)
        self.assertEqual(status,200)
        self.assertEqual(plan["mode"],"template")
        self.assertEqual(plan["issue_quote"],original["result"]["issues"][0]["quote"])
        self.assertIn("待执行",plan["notice"])
        self.assertEqual(self.call("/api/plan",dict(body,version=original["version"]-1))[0],409)
        self.assert_unchanged(original)
        self.model.assert_not_called()

    def test_ai_plan_requires_literal_current_authorization_and_filters_materials(self):
        mats=copy.deepcopy(self.p["materials"])
        mats.extend([{"name":"未授权访谈","text":"SECRET_UNAUTHORIZED_SOURCE"},
                     {"name":"排除访谈","text":"SECRET_EXCLUDED_SOURCE","consent_status":"confirmed","enabled":False}])
        self.action("save",changes={"materials":mats})
        self.action("review",mode="preliminary")
        body={"project_id":self.p["id"],"version":self.p["version"],"issue_id":self.p["result"]["issues"][0]["id"],"mode":"ai"}
        for consent in (None,False,1,"true"):
            with self.subTest(consent=consent):
                self.assertEqual(self.call("/api/plan",dict(body,allow_external_processing=consent))[0],400)
        self.model.assert_not_called()
        original=copy.deepcopy(self.p)
        status,value=self.call("/api/plan",dict(body,allow_external_processing=True))
        self.assertEqual(status,200)
        self.assertEqual(value["mode"],"ai")
        sent=self.model.call_args.args[0][1]["content"]
        self.assertNotIn("SECRET_UNAUTHORIZED_SOURCE",sent)
        self.assertNotIn("SECRET_EXCLUDED_SOURCE",sent)
        self.assert_unchanged(original)

    def test_float_and_boolean_plan_versions_are_conflicts_before_model_call(self):
        base={"project_id":self.p["id"],"issue_id":"i1","mode":"ai","allow_external_processing":True}
        for version in (float(self.p["version"]),True,False,str(self.p["version"])):
            with self.subTest(version=repr(version)):
                self.assertEqual(self.call("/api/plan",dict(base,version=version))[0],409)
        self.model.assert_not_called()

    def test_review_invalid_version_is_rejected_before_external_model_call(self):
        self.model.return_value='{"issues":[]}'
        status,_=self.call("/api/projects",{"action":"review","id":self.p["id"],"version":float(self.p["version"]),
                                             "mode":"ai","allow_external_processing":True})
        self.assertEqual(status,409)
        self.model.assert_not_called()

    def test_invalid_review_actor_is_rejected_before_external_model_call(self):
        self.model.return_value='{"issues":[]}'
        original=copy.deepcopy(self.p)
        for actor in ("x"*61,[],True):
            with self.subTest(actor=repr(actor)):
                status,_=self.call("/api/projects",{"action":"review","id":self.p["id"],"version":self.p["version"],
                                                     "mode":"ai","allow_external_processing":True,"actor":actor})
                self.assertEqual(status,400)
        self.assertEqual(self.model.call_count,0,"无效署名不应进入外部模型调用")
        self.assert_unchanged(original)

    def test_changed_material_keeps_old_citation_snapshot_and_blocks_old_chat_and_plan(self):
        original_materials=copy.deepcopy(self.p["materials"])
        mats=copy.deepcopy(original_materials)
        mats[0]["text"]="这一份正文已换成新的现场记录。"
        self.assertEqual(self.action("save",changes={"materials":mats})[0],200)
        status,current=self.call("/api/project?id="+self.p["id"])
        self.assertEqual(status,200)
        self.assertTrue(current["needs_review"])
        self.assertEqual(current["review_materials"],original_materials)
        self.assertNotEqual(current["review_materials"],current["materials"])
        citation=current["result"]["issues"][0]["citations"][0]
        source=next(m for m in current["review_materials"] if m["id"]==citation["document_id"])
        self.assertEqual(source["text"][citation["start"]:citation["end"]],citation["quote"])
        self.assertEqual(self.call("/api/chat",{"project_id":self.p["id"],"version":self.p["version"],
                                               "issue":self.p["result"]["issues"][0],"question":"为什么？"})[0],400)
        self.assertEqual(self.call("/api/plan",{"project_id":self.p["id"],"version":self.p["version"],"issue_id":"i1",
                                               "mode":"ai","allow_external_processing":True})[0],400)
        self.model.assert_not_called()

    def test_project_changed_during_plan_generation_returns_conflict_and_keeps_actual_save(self):
        original_version=self.p["version"]
        def completion(messages):
            self.store.save(self.p["id"],original_version,{"description":"另一项操作已保存"})
            return plan_json()
        self.model.side_effect=completion
        status,value=self.call("/api/plan",{"project_id":self.p["id"],"version":original_version,"issue_id":"i1",
                                            "mode":"ai","allow_external_processing":True})
        self.assertEqual(status,409)
        self.assertIn("生成期间",value["error"])
        current=self.store.get(self.p["id"])
        self.assertEqual(current["description"],"另一项操作已保存")
        self.assertEqual(current["version"],original_version+1)
        self.assertEqual(current["tasks"],self.p["tasks"])

    def test_invalid_plan_response_or_pending_edited_report_does_not_become_success(self):
        original=copy.deepcopy(self.p)
        self.model.return_value='{"goal":"核验通过","results":"已经访谈100人"}'
        payload={"project_id":self.p["id"],"version":self.p["version"],"issue_id":"i1","mode":"ai","allow_external_processing":True}
        self.assertEqual(self.call("/api/plan",payload)[0],400)
        self.assert_unchanged(original)
        self.action("save",changes={"choices":{"i1":"accepted"}})
        self.model.reset_mock()
        payload["version"]=self.p["version"]
        self.assertEqual(self.call("/api/plan",payload)[0],400)
        self.model.assert_not_called()

    def test_imported_project_refuses_old_plan_until_authorization_and_recheck(self):
        _,package=self.call("/api/package?id="+self.p["id"])
        _,restored=self.call("/api/projects",{"action":"import","package":package})
        status,value=self.call("/api/plan",{"project_id":restored["id"],"version":restored["version"],
                                            "issue_id":"i1","mode":"ai","allow_external_processing":True})
        self.assertEqual(status,400)
        self.assertIn("复查",value["error"])
        self.model.assert_not_called()

    def test_invalid_task_status_and_review_mode_are_bad_requests_not_server_errors(self):
        self.action("create_task",action_text="分工任务")
        before=copy.deepcopy(self.p)
        tid=self.p["tasks"][-1]["id"]
        for status in ({},[],True,None):
            with self.subTest(status=repr(status)):
                self.assertEqual(self.action("task",task_id=tid,status=status)[0],400)
        for mode in ({},[],True,None):
            with self.subTest(mode=repr(mode)):
                self.assertEqual(self.action("review",mode=mode)[0],400)
        self.assert_unchanged(before)

    def test_malformed_chat_project_and_issue_identity_are_controlled_bad_requests(self):
        for project_id in ([],{},True,None):
            with self.subTest(project_id=repr(project_id)):
                status,_=self.call("/api/chat",{"project_id":project_id,"version":self.p["version"],"issue":self.p["result"]["issues"][0],"question":"为什么？"})
                self.assertEqual(status,400)
        for issue in ("i1",[{"id":"i1"}],True):
            with self.subTest(issue=repr(issue)):
                status,_=self.call("/api/chat",{"project_id":self.p["id"],"version":self.p["version"],"issue":issue,"question":"为什么？"})
                self.assertEqual(status,400)
        self.model.assert_not_called()

    def test_chat_matches_whole_current_issue_not_only_reused_issue_id(self):
        issue=copy.deepcopy(self.p["result"]["issues"][0])
        payload={"project_id":self.p["id"],"version":self.p["version"],"issue":issue,"question":"为什么？"}
        self.assertEqual(self.call("/api/chat",payload)[0],200)
        for changes in ({"quote":"不同版本的原句"},{"start":0},{"end":1},{"category":"来源表述"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.call("/api/chat",dict(payload,issue={**issue,**changes}))[0],409)
        self.action("save",changes={"description":"项目实际更新"})
        self.assertEqual(self.call("/api/chat",payload)[0],409)
        self.model.assert_not_called()

    def test_ai_chat_version_conflict_during_answer_does_not_publish_old_answer(self):
        self.p=self.store.reviewed(self.p["id"],self.p["version"],{**self.p["result"],"mode":"ai"})
        version=self.p["version"]
        def completion(messages):
            self.store.save(self.p["id"],version,{"description":"回答期间有另一项保存"})
            return '{"answer":"旧范围的回答不能作为当前结果展示"}'
        self.model.side_effect=completion
        payload={"project_id":self.p["id"],"version":version,"issue":self.p["result"]["issues"][0],
                 "question":"为什么？","allow_external_processing":True}
        status,value=self.call("/api/chat",payload)
        self.assertEqual(status,409)
        self.assertIn("回答期间",value["error"])
        self.assertNotIn("answer",value)
        self.assertEqual(self.store.get(self.p["id"])["description"],"回答期间有另一项保存")

    def test_accepted_unreviewed_edit_blocks_chat_but_keep_original_allows_it(self):
        self.p=self.store.reviewed(self.p["id"],self.p["version"],{**self.p["result"],"mode":"ai"})
        issue=copy.deepcopy(self.p["result"]["issues"][0])
        self.action("save",changes={"choices":{issue["id"]:"accepted"}})
        payload={"project_id":self.p["id"],"version":self.p["version"],"issue":issue,
                 "question":"这些依据能支持到什么范围？","allow_external_processing":True}
        status,response=self.call("/api/chat",payload)
        self.assertEqual(status,400)
        self.assertIn("复查",response["error"])
        self.model.assert_not_called()
        self.action("save",changes={"choices":{issue["id"]:"kept"}})
        self.model.return_value='{"answer":"依据仅覆盖本次实际受访者。"}'
        status,response=self.call("/api/chat",{**payload,"version":self.p["version"]})
        self.assertEqual(status,200)
        self.assertEqual(response["mode"],"ai")
        self.assertEqual(self.model.call_count,1)

    def test_manual_unreviewed_edit_blocks_chat_and_restoring_current_report_allows_it(self):
        self.p=self.store.reviewed(self.p["id"],self.p["version"],{**self.p["result"],"mode":"ai"})
        issue=copy.deepcopy(self.p["result"]["issues"][0])
        self.action("save",changes={"manual_text":self.p["result"]["report"]["text"]+"\n新增虚构现场记录。"})
        payload={"project_id":self.p["id"],"version":self.p["version"],"issue":issue,
                 "question":"为什么？","allow_external_processing":True}
        status,response=self.call("/api/chat",payload)
        self.assertEqual(status,400)
        self.assertIn("复查",response["error"])
        self.model.assert_not_called()
        self.action("save",changes={"manual_text":None})
        self.model.return_value='{"answer":"当前结论仍应限于已提交的受访记录。"}'
        self.assertEqual(self.call("/api/chat",{**payload,"version":self.p["version"]})[0],200)
        self.assertEqual(self.model.call_count,1)

    def test_json_and_origin_errors_are_controlled_without_model_call(self):
        for data in (b"{",b"[]",b"null",b'"string"',b'{"action":NaN}'):
            connection=http.client.HTTPConnection("127.0.0.1",self.http.server_port,timeout=5)
            try:
                connection.request("POST","/api/projects",body=data,headers={"Content-Type":"application/json"})
                response=connection.getresponse()
                self.assertEqual(response.status,400)
                self.assertIn("error",json.loads(response.read()))
            finally:
                connection.close()
        self.assertEqual(self.call("/api/projects",{"action":"create"},headers={"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.call("/api/plan",{"project_id":self.p["id"]},headers={"Origin":"https://outside.example"})[0],403)
        self.assertEqual(self.call("/api/package?id="+self.p["id"],headers={"Origin":"https://outside.example"})[0],403)
        self.assertEqual(self.call("/api/status")[1]["ai_configured"],False)
        self.model.assert_not_called()

    def test_docx_endpoint_returns_current_unicode_report_as_a_binary_attachment(self):
        text="当前修改稿\n\n一、记录\n中文🙂与原样 < & > 字符。\n甲\t乙\n\n尾行\n"
        original=copy.deepcopy(self.p)
        status,content,headers=self.binary_call("/api/export-docx",{"name":"当前修改稿.docx","text":text})
        self.assertEqual(status,200)
        self.assertEqual(headers["Content-Type"],"application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(int(headers["Content-Length"]),len(content))
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertEqual(headers["X-Content-Type-Options"],"nosniff")
        self.assertIn('filename="qingji-report.docx"',headers["Content-Disposition"])
        self.assertIn("filename*=UTF-8''"+urllib.parse.quote("当前修改稿.docx",safe=""),headers["Content-Disposition"])
        self.assertEqual(read_document("下载稿.docx",content).text,text)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn("word/document.xml",archive.namelist())
        self.assert_unchanged(original)
        self.model.assert_not_called()

    def test_docx_endpoint_rejects_oversize_and_invalid_fields_as_json_errors(self):
        cases=[{"name":"报告","text":"甲"*(MAX_REPORT_CHARS+1)},
               {"name":"报告","text":""},{"name":"报告","text":None},{"name":"报告","text":{}},
               {"name":None,"text":"正文。"},{"name":[],"text":"正文。"},{"name":"x"*201,"text":"正文。"},
               {"name":"报告\r\nX-Injected: yes","text":"正文。"},
               {"name":"报告\t名称","text":"正文。"},{"name":"报告\x7f","text":"正文。"}]
        for body in cases:
            with self.subTest(body=str(body)[:50]):
                status,content,headers=self.binary_call("/api/export-docx",body)
                self.assertEqual(status,400)
                self.assertEqual(headers["Content-Type"],"application/json; charset=utf-8")
                self.assertIn("error",json.loads(content))
                self.assertNotIn("Content-Disposition",headers)
        self.model.assert_not_called()

    def test_docx_filename_paths_quotes_and_reserved_names_never_become_header_injection(self):
        cases={"../../当前稿.docx":"当前稿.docx","C:\\fakepath\\当前稿.txt":"当前稿.docx",
               '稿件"&?*.docx':'稿件_&__.docx',"CON.docx":"qingji-CON.docx"}
        for name,expected in cases.items():
            with self.subTest(name=name):
                status,content,headers=self.binary_call("/api/export-docx",{"name":name,"text":"正文原样。"})
                self.assertEqual(status,200)
                self.assertIn("filename*=UTF-8''"+urllib.parse.quote(expected,safe=""),headers["Content-Disposition"])
                self.assertEqual(read_document("下载.docx",content).text,"正文原样。")
                self.assertNotIn("X-Injected",headers)
        self.model.assert_not_called()

    def test_docx_endpoint_only_allows_local_json_requests(self):
        body={"name":"当前稿","text":"正文。","allow_external_processing":True}
        self.assertEqual(self.binary_call("/api/export-docx",body,headers={"Origin":"https://outside.example"})[0],403)
        self.assertEqual(self.binary_call("/api/export-docx",body,headers={"Host":"outside.example"})[0],403)
        self.assertEqual(self.binary_call("/api/export-docx",body,headers={"Content-Type":"text/plain"})[0],415)
        self.model.assert_not_called()


if __name__=="__main__":
    unittest.main()
