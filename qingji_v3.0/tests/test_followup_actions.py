import tempfile
import unittest
from pathlib import Path
from core.projects import ProjectStore,ProjectConflict
from core.lifecycle import save_brief,add_observation
from core.followup_actions import create_followup
from core.project_packages import export_package,import_package
from core.review import ReviewError


class FollowupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=ProjectStore(Path(temp.name)/'projects.sqlite3')
        p=self.store.create('虚构后续行动')
        p=save_brief(self.store,p['id'],p['version'],{'topic':'访谈','goal':'了解不同情况'},[{'id':'q1','text':'需要哪些帮助？'}],'field')
        self.p=add_observation(self.store,p['id'],p['version'],{'question_id':'q1','text':'甲说需要帮助。','uncertainty':'后来能否独立完成？','consent_status':'confirmed'})
        o=self.p['lifecycle']['observations'][0]
        self.body={'source_version':self.p['version'],'action_text':'联系甲了解后续经历','origin':{'kind':'record','question_id':'q1','text':'用户不可篡改原疑问','citations':[{'observation_id':o['id'],'material_id':o['material_id'],'quote':'甲说需要帮助。'}]}}

    def create(self,p=None,body=None):
        p=p or self.p
        return create_followup(self.store,p['id'],p['version'],body or self.body)

    def test_record_origin_uses_saved_uncertainty_and_preserves_relationships(self):
        p=self.create();t=p['tasks'][0]
        self.assertEqual(t['status'],'open');self.assertEqual(t['material_ids'],[])
        self.assertEqual(p['lifecycle']['task_links'][t['id']],'q1')
        self.assertIn('后来能否独立完成',t['notes']);self.assertNotIn('用户不可篡改',t['notes'])
        self.assertEqual(p['materials'],self.p['materials']);self.assertEqual(p['lifecycle']['observations'],self.p['lifecycle']['observations'])
        restored=import_package(self.store,export_package(self.store,p['id']))
        self.assertEqual(restored['tasks'][0]['notes'],t['notes'])
        self.assertEqual(restored['lifecycle']['task_links'][t['id']],'q1')

    def test_duplicate_and_stale_source_do_not_create_another_task(self):
        p=self.create()
        with self.assertRaises(ProjectConflict):self.create(p)
        with self.assertRaisesRegex(ReviewError,'已安排过'):self.create(p,{**self.body,'source_version':p['version']})
        self.assertEqual(len(self.store.get(p['id'])['tasks']),1)

    def test_ai_source_quotes_and_scope_checked(self):
        self.body['origin'].update(kind='analysis',text='不同场景是否也需要帮助？')
        p=self.create();self.assertIn('不同场景',p['tasks'][0]['notes'])
        self.body['origin']['citations'][0]['quote']='伪造原文'
        with self.assertRaises(ReviewError):self.create(p,{**self.body,'source_version':p['version']})
        self.assertEqual(len(self.store.get(p['id'])['tasks']),1)

    def test_bad_assignee_date_source_and_removed_material_fail_atomically(self):
        for change in ({'assignee_id':'missing'},{'due_date':'2026-02-31'},{'action_text':''}):
            with self.assertRaises(ReviewError):self.create(body={**self.body,**change})
        self.assertEqual(self.store.get(self.p['id'])['tasks'],[])
        p=self.store.save(self.p['id'],self.p['version'],{'materials':[]})
        with self.assertRaises(ReviewError):self.create(p,{**self.body,'source_version':p['version']})
