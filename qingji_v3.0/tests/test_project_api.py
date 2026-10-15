import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import server
from core.projects import ProjectStore


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(Path(self.temp.name)/"qa.sqlite3")
        self.store_patch=patch.object(server,"STORE",self.store)
        self.store_patch.start()
        self.http=server.LocalHTTPServer(("127.0.0.1",0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join(2)
        self.store_patch.stop();self.temp.cleanup()

    def call(self,path,body=None):
        req=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers={"Content-Type":"application/json"})
        try: response=urllib.request.urlopen(req,timeout=5)
        except urllib.error.HTTPError as exc: response=exc
        with response: return response.status,json.loads(response.read())

    def test_review_filters_materials_and_requires_ai_confirmation(self):
        report={"name":"虚构报告","text":"全部居民需要帮助。"}
        mats=[{"id":"m1","name":"已授权","text":"三人需要帮助。","consent_status":"confirmed"},
              {"id":"m2","name":"未授权","text":"不应发送的未授权内容。"},
              {"id":"m3","name":"已排除","text":"不应发送的排除内容。","enabled":False,"consent_status":"confirmed"}]
        _,p=self.call("/api/projects",{"action":"create","name":"虚构","report":report,"materials":mats})
        payload={"action":"review","id":p["id"],"version":p["version"],"mode":"ai"}
        with patch.object(server,"configured_completion",return_value='{"issues":[]}') as call:
            self.assertEqual(self.call("/api/projects",payload)[0],400)
            call.assert_not_called()
            status,p=self.call("/api/projects",dict(payload,allow_external_processing=True))
            self.assertEqual(status,200)
            sent=call.call_args.args[0][1]["content"]
            self.assertIn("三人需要帮助",sent)
            self.assertNotIn("不应发送",sent)
            self.assertEqual(len(p["materials"]),3)
            self.assertEqual(len(p["history"]),1)

    def test_failed_model_preserves_current_revision(self):
        _,p=self.call("/api/projects",{"action":"example"})
        with patch.object(server,"configured_completion",return_value='{"issues":[{"quote":"杜撰"}]}'):
            status,_=self.call("/api/projects",{"action":"review","id":p["id"],"version":p["version"],"mode":"ai","allow_external_processing":True})
        self.assertEqual(status,400)
        _,current=self.call("/api/project?id="+p["id"])
        self.assertEqual(current,p)

    def test_http_conflicts_and_revision_isolation(self):
        _,p=self.call("/api/projects",{"action":"example"})
        _,other=self.call("/api/projects",{"action":"create","name":"另一个虚构项目"})
        request={"action":"save","id":p["id"],"version":p["version"],"changes":{"name":"已保存的新名"}}
        self.assertEqual(self.call("/api/projects",request)[0],200)
        self.assertEqual(self.call("/api/projects",request)[0],409)
        self.assertEqual(self.call(f'/api/revision?id={other["id"]}&revision={p["history"][0]["id"]}')[0],404)

    def test_chat_uses_project_snapshot_and_blocks_changed_scope(self):
        _,p=self.call("/api/projects",{"action":"example"})
        payload={"project_id":p["id"],"version":p["version"],"issue":p["result"]["issues"][0],
                 "question":"为什么？","materials":[{"name":"恶意追加","text":"不应进入问答"}]}
        status,response=self.call("/api/chat",payload)
        self.assertEqual(status,200)
        self.assertIn("三位",response["answer"])
        self.store.save(p["id"],p["version"],{"materials":[dict(m,enabled=False) for m in p["materials"]]})
        self.assertEqual(self.call("/api/chat",payload)[0],400)

if __name__=="__main__": unittest.main()
