import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
from core import lifecycle as life
from core.projects import ProjectStore, ProjectConflict
from core.review import ReviewError
from core.project_packages import export_package, import_package


class TaskQuestionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=ProjectStore(Path(self.temp.name)/'test.sqlite3')
        self.p=self.store.create('虚构实践')
        self.p=life.save_brief(self.store,self.p['id'],self.p['version'],
            {'topic':'社区走访','goal':'了解不同经历'},[{'id':'q1','text':'哪里需要帮助？'},
            {'id':'q2','text':'哪些环节可独立完成？'}],'field')

    def create(self, qid='q1'):
        self.p=self.store.create_task(self.p['id'],self.p['version'],'访谈两位居民',question_id=qid)
        return self.p['tasks'][-1]['id']

    def edit(self, tid, qid):
        self.p=self.store.task_detail(self.p['id'],self.p['version'],tid,{'question_id':qid})

    def test_create_connects_question_guidance_record_and_package(self):
        tid=self.create()
        self.assertEqual(self.p['lifecycle']['task_links'][tid],'q1')
        self.assertEqual(life.context_of(self.p)['tasks'][0]['question_id'],'q1')
        self.assertEqual(life.practice_view(self.p)['questions'][0]['task_count'],1)
        self.p=life.add_observation(self.store,self.p['id'],self.p['version'],
            {'question_id':'q1','task_id':tid,'text':'虚构：甲需要帮助。','consent_status':'confirmed'})
        self.assertEqual(self.p['tasks'][0]['status'],'open')
        restored=import_package(self.store,export_package(self.store,self.p['id']))
        self.assertEqual(restored['lifecycle']['task_links'],self.p['lifecycle']['task_links'])
        self.assertEqual(restored['lifecycle']['observations'][0]['task_id'],tid)

    def test_unlinked_task_can_link_change_and_unlink_without_changing_status(self):
        tid=self.create('');self.edit(tid,'q1')
        self.p=self.store.task(self.p['id'],self.p['version'],tid,'done')
        self.edit(tid,'q2');self.assertEqual(self.p['tasks'][0]['status'],'done')
        self.assertEqual(life.practice_view(self.p)['questions'][1]['done_count'],1)
        self.edit(tid,'');self.assertNotIn(tid,self.p['lifecycle']['task_links'])
        self.assertEqual(self.p['materials'],[])

    def test_link_change_invalidates_guidance_and_prevents_deleting_question(self):
        tid=self.create('')
        self.p=life.save_guidance(self.store,self.p['id'],self.p['version'],life.template_guidance(self.p))
        self.edit(tid,'q1');self.assertFalse(life.guidance_current(self.p))
        with self.assertRaises(ReviewError):life.save_brief(self.store,self.p['id'],self.p['version'],
            self.p['lifecycle']['brief'],[{'id':'q2','text':'哪些环节可独立完成？'}],'field')

    def test_existing_records_block_move_until_explicitly_detached(self):
        tid=self.create()
        self.p=life.add_observation(self.store,self.p['id'],self.p['version'],
            {'question_id':'q1','task_id':tid,'text':'虚构现场记录'})
        for qid in ['q2','']:
            with self.assertRaisesRegex(ReviewError,'已有阶段记录'):self.edit(tid,qid)
        self.edit(tid,'q1')
        o=self.p['lifecycle']['observations'][0]
        self.p=life.save_observation_link(self.store,self.p['id'],self.p['version'],
            {'question_id':'q1','task_id':'','material_id':o['material_id'],'finding':'原发现'},o['id'])
        self.edit(tid,'q2')
        self.assertEqual(self.p['lifecycle']['observations'][0]['question_id'],'q1')
        self.assertEqual(self.p['lifecycle']['observations'][0]['finding'],'原发现')

    def test_invalid_create_is_atomic_and_stale_edit_rejected(self):
        version=self.p['version']
        for qid in ['foreign',None,[],123]:
            with self.assertRaises(ReviewError):self.create(qid)
        self.assertEqual(self.store.get(self.p['id'])['version'],version)
        self.assertEqual(self.store.get(self.p['id'])['tasks'],[])
        tid=self.create()
        self.store.save(self.p['id'],self.p['version'],{'description':'另一窗口修改'})
        with self.assertRaises(ProjectConflict):self.edit(tid,'q2')

    def test_evidence_task_cannot_change_semantics(self):
        tid=self.create()
        self.p=self.store.update(self.p['id'],self.p['version'],lambda p:p['tasks'][0].update(kind='evidence'))
        with self.assertRaises(ReviewError):self.edit(tid,'q2')

    def test_old_project_without_questions_still_creates_tasks(self):
        p=self.store.create('旧项目')
        p=self.store.create_task(p['id'],p['version'],'独立行动')
        self.assertEqual(life.state_of(p)['task_links'],{})

    def test_api_passes_question_and_preserves_other_fields(self):
        with patch.object(server,'STORE',self.store):
            p=server.project_action({'action':'create_task','id':self.p['id'],'version':self.p['version'],
                'action_text':'走访','question_id':'q2','due_date':'2026-11-01','notes':'保留原话'})
            self.assertEqual(p['lifecycle']['task_links'][p['tasks'][0]['id']],'q2')
            self.assertEqual(p['tasks'][0]['due_date'],'2026-11-01')
            self.assertEqual(p['tasks'][0]['notes'],'保留原话')
