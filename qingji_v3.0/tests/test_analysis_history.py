import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import server
from core.projects import ProjectStore,ProjectConflict
from core.lifecycle import save_brief,add_observation
from core.question_synthesis import synthesize
from core.analysis_history import save_analysis,history,delete_analysis,validate_snapshot
from core.project_packages import export_package,import_package,_json_bytes
from core.project_backups import create_backup,restore_backup
from core.review import ReviewError


class AnalysisHistoryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=ProjectStore(Path(temp.name)/'projects.sqlite3')
        p=self.store.create('虚构分析历史')
        p=save_brief(self.store,p['id'],p['version'],{'topic':'访谈','goal':'了解实际情况'},[{'id':'q1','text':'遇到哪些困难？'}],'field')
        self.p=add_observation(self.store,p['id'],p['version'],{'question_id':'q1','text':'甲说需要帮助。','consent_status':'confirmed'})
        o=self.p['lifecycle']['observations'][0]
        self.reply={'findings':[{'text':'甲报告需要帮助','citations':[{'observation_id':o['id'],'material_id':o['material_id'],'quote':'甲说需要帮助。'}]}],'differences':[],'questions':[],'limits':['仅一次记录']}
    def save(self):
        r=synthesize(self.p,'q1',lambda _:json.dumps(self.reply))
        return save_analysis(self.store,self.p,r)
    def test_persistent_history_without_mutating_project(self):
        with patch.object(server,'STORE',self.store),patch.object(server,'configured_completion',return_value=json.dumps(self.reply)):
            r=server.question_analysis({'project_id':self.p['id'],'version':self.p['version'],'question_id':'q1'})
        again=ProjectStore(self.store.path)
        rows=history(again,self.p['id'],'q1')['history']
        self.assertEqual(rows[0]['history_id'],r['history_id']);self.assertTrue(rows[0]['current'])
        self.assertEqual(rows[0]['source_records'][0]['text'],'甲说需要帮助。')
        self.assertEqual(again.get(self.p['id']),self.p)
    def test_unrelated_update_remaps_action_version_but_source_changes_expire(self):
        self.save();p=self.store.save(self.p['id'],self.p['version'],{'description':'项目简介'})
        row=history(self.store,p['id'],'q1')['history'][0]
        self.assertTrue(row['current']);self.assertEqual(row['version'],p['version']);self.assertEqual(row['source_version'],self.p['version'])
        mats=copy.deepcopy(p['materials']);mats[0]['text']='新的原文'
        p=self.store.save(p['id'],p['version'],{'materials':mats})
        row=history(self.store,p['id'],'q1')['history'][0];self.assertFalse(row['current']);self.assertEqual(row['source_records'][0]['text'],'甲说需要帮助。')
    def test_package_and_backup_keep_history_imported_unverified(self):
        old=create_backup(self.store,self.p['id'],self.p['version'])
        self.save();package=export_package(self.store,self.p['id']);self.assertEqual(package['schema_version'],3)
        restored=import_package(self.store,package);row=history(self.store,restored['id'],'q1')['history'][0]
        self.assertTrue(row['imported']);self.assertFalse(row['current'])
        backups=create_backup(self.store,self.p['id'],self.p['version']);self.assertEqual(len(backups),len(old)+1)
        restored=restore_backup(self.store,self.p['id'],backups[0]['id'])
        self.assertEqual(len(history(self.store,restored['id'],'q1')['history']),1)
    def test_capacity_rejects_before_model_and_does_not_evict(self):
        r=self.save();complete=Mock()
        with patch('core.analysis_history.MAX_ANALYSES',1),patch.object(server,'STORE',self.store),patch.object(server,'configured_completion',complete):
            with self.assertRaises(ReviewError):server.question_analysis({'project_id':self.p['id'],'version':self.p['version'],'question_id':'q1'})
        complete.assert_not_called();self.assertEqual(history(self.store,self.p['id'],'q1')['history'][0]['history_id'],r['history_id'])
    def test_deleted_selected_history_only_and_cross_project_rejected(self):
        a=self.save();b=self.save();other=self.store.create('其他项目')
        with self.assertRaises(ReviewError):delete_analysis(self.store,other['id'],a['history_id'])
        delete_analysis(self.store,self.p['id'],a['history_id'])
        self.assertEqual([r['history_id'] for r in history(self.store,self.p['id'],'q1')['history']],[b['history_id']])
        self.assertEqual(self.store.get(self.p['id']),self.p)
    def test_tampered_snapshot_and_wrong_package_version_rejected(self):
        self.save();package=export_package(self.store,self.p['id'])
        corrupted=copy.deepcopy(package);corrupted['payload']['analyses'][0]['result']['analysis']['findings'][0]['citations'][0]['quote']='伪造引文'
        corrupted['sha256']=hashlib.sha256(_json_bytes(corrupted['payload'])).hexdigest()
        with self.assertRaises(ReviewError):import_package(self.store,corrupted)
        package['schema_version']=2
        with self.assertRaises(ReviewError):import_package(self.store,package)
        self.assertEqual(len(self.store.list()),1)
    def test_atomic_save_rejects_changed_project(self):
        r=synthesize(self.p,'q1',lambda _:json.dumps(self.reply))
        self.store.save(self.p['id'],self.p['version'],{'description':'并发更新'})
        with self.assertRaises(ProjectConflict):save_analysis(self.store,self.p,r)
        self.assertEqual(history(self.store,self.p['id'],'q1')['history'],[])
