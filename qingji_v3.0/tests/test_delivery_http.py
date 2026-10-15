import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
import server
from core.projects import ProjectStore
from core.review import Document, preliminary_review


class DeliveryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(Path(self.temp.name)/'delivery.sqlite3')
        self.p=self.store.create('虚构交付项目',{'name':'虚构正文','text':'所有居民都需要帮助。'},
            [{'id':'m1','name':'虚构记录','text':'只访问了三位居民。','enabled':True,'consent_status':'unconfirmed'}])
        self.p=self.store.reviewed(self.p['id'],self.p['version'],preliminary_review(Document('report','虚构正文',self.p['report']['text']),[]).to_dict())
        self.store_patch=patch.object(server,'STORE',self.store);self.store_patch.start()
        self.http=server.LocalHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown();self.thread.join();self.http.server_close();self.store_patch.stop();self.temp.cleanup()

    def get(self,version,project_id=None):
        url=f"{self.base}/api/delivery?id={project_id or self.p['id']}&version={version}"
        try:
            with urllib.request.urlopen(url) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)

    def test_check_has_no_model_call_or_project_write_and_keeps_unconfirmed_scope(self):
        before=copy.deepcopy(self.store.get(self.p['id']))
        with patch.object(server,'configured_completion',side_effect=AssertionError('must not call model')):
            code,data=self.get(self.p['version'])
        self.assertEqual(code,200)
        self.assertEqual(data['check']['materials']['eligible_current'],0)
        self.assertEqual(data['check']['materials']['unconfirmed_included'],1)
        self.assertIn('本地预检',data['markdown'])
        self.assertEqual(self.store.get(self.p['id']),before)

    def test_stale_check_cannot_be_presented_as_current_version(self):
        changed=self.store.save(self.p['id'],self.p['version'],{'name':'新虚构名称'})
        self.assertEqual(self.get(self.p['version'])[0],409)
        code,data=self.get(changed['version'])
        self.assertEqual(code,200);self.assertEqual(data['check']['project_name'],'新虚构名称')

    def test_malformed_version_and_unknown_project_have_controlled_errors(self):
        for invalid in ['', '1.0', '-1', 'true','9'*13]:
            self.assertEqual(self.get(invalid)[0],400)
        self.assertEqual(self.get(1,'missing')[0],404)
