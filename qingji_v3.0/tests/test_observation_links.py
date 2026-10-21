import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from core import lifecycle as life
from core.projects import ProjectStore, ProjectConflict
from core.project_packages import export_package, import_package
from core.review import ReviewError


class ObservationLinkTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = ProjectStore(Path(self.folder.name)/'test.sqlite3')
        self.p = self.store.create('虚构流程', materials=[{'id':'m1','name':'虚构访谈',
            'text':'甲独立完成，乙需要帮助。','consent_status':'confirmed','enabled':True}])
        self.p = life.save_brief(self.store,self.p['id'],self.p['version'],
            {'topic':'虚构社区服务','goal':'了解不同操作经历'},
            [{'id':'q1','text':'操作遇到哪些困难？'},{'id':'q2','text':'哪些环节可独立完成？'}],'field')
        self.item = {'material_id':'m1','question_id':'q1','finding':'经历不同','uncertainty':'其他对象未知'}

    def save(self, item=None, oid=None):
        self.p = life.save_observation_link(self.store,self.p['id'],self.p['version'],item or self.item,oid)
        return self.p['lifecycle']['observations'][0]

    def test_link_reuses_source_and_enters_guidance_and_report(self):
        mats = copy.deepcopy(self.p['materials'])
        self.p=life.save_guidance(self.store,self.p['id'],self.p['version'],life.template_guidance(self.p))
        o=self.save()
        self.assertEqual(self.p['materials'],mats)
        self.assertFalse(life.guidance_current(self.p))
        self.assertEqual(life.context_of(self.p)['observations'][0]['material_id'],'m1')
        self.assertIn('甲独立完成',life.report_outline(self.p))
        self.assertEqual(life.practice_view(self.p)['questions'][0]['record_count'],1)
        package=export_package(self.store,self.p['id'])
        imported=import_package(self.store,package)
        self.assertEqual(imported['lifecycle']['observations'][0],o)

    def test_duplicate_pair_rejected_but_same_material_can_serve_another_question(self):
        self.save();version=self.p['version']
        with self.assertRaises(ReviewError):self.save()
        self.assertEqual(self.store.get(self.p['id'])['version'],version)
        self.save({**self.item,'question_id':'q2'})
        self.assertEqual(len(self.p['materials']),1)
        self.assertEqual(len(self.p['lifecycle']['observations']),2)

    def test_excluded_source_is_not_enabled_or_sent_by_linking(self):
        mats=copy.deepcopy(self.p['materials']);mats[0]['enabled']=False
        self.p=self.store.save(self.p['id'],self.p['version'],{'materials':mats})
        self.save({**self.item,'finding':'EXCLUDED_NOTE'})
        self.assertFalse(self.p['materials'][0]['enabled'])
        self.assertEqual(life.context_of(self.p)['observations'],[])
        self.assertNotIn('EXCLUDED_NOTE',life.report_outline(self.p))

    def test_edit_does_not_clear_changed_source_without_explicit_review(self):
        o=self.save();original=copy.deepcopy(o)
        mats=copy.deepcopy(self.p['materials']);mats[0]['text']='甲乙均独立完成。'
        self.p=self.store.save(self.p['id'],self.p['version'],{'materials':mats})
        self.save({**self.item,'finding':'重新整理后的发现'},o['id'])
        self.assertIn(o['id'],life.practice_view(self.p)['changed_observations'])
        self.save({**self.item,'finding':'两位均独立完成','source_reviewed':True},o['id'])
        self.assertEqual(life.practice_view(self.p)['changed_observations'],[])
        new=self.p['lifecycle']['observations'][0]
        self.assertEqual(new['created_at'],original['created_at'])
        self.assertEqual(new['material_id'],original['material_id'])
        self.assertEqual(self.p['materials'][0]['text'],'甲乙均独立完成。')

    def test_missing_source_notes_survive_but_cannot_be_confirmed(self):
        o=self.save()
        self.p=self.store.save(self.p['id'],self.p['version'],{'materials':[]})
        self.save({**self.item,'finding':'保留备注'},o['id'])
        with self.assertRaises(ReviewError):self.save({**self.item,'source_reviewed':True},o['id'])
        self.assertEqual(life.context_of(self.p)['observations'],[])

    def test_task_question_constraint_and_task_not_completed(self):
        self.p=life.save_guidance(self.store,self.p['id'],self.p['version'],life.template_guidance(self.p))
        g=self.p['lifecycle']['guidance']
        self.p=life.adopt_action(self.store,self.p['id'],self.p['version'],g['id'],'a1','了解不同经历')
        tid=self.p['tasks'][0]['id']
        with self.assertRaises(ReviewError):self.save({**self.item,'question_id':'q2','task_id':tid})
        self.save({**self.item,'task_id':tid})
        self.assertEqual(self.p['tasks'][0]['status'],'open')
        self.assertEqual(self.p['lifecycle']['observations'][0]['task_id'],tid)

    def test_invalid_values_and_source_replacement_do_not_mutate_project(self):
        o=self.save();version=self.p['version']
        for changes in [{'material_id':'other'},{'question_id':[]},{'source_reviewed':'yes'},
                        {'task_id':'missing'},{'finding':'x'*2001},{'text':'rewrite'}]:
            with self.assertRaises(ReviewError):self.save({**self.item,**changes},o['id'])
        self.assertEqual(self.store.get(self.p['id'])['version'],version)

    def test_stale_write_rejected_and_archived_api_rejected(self):
        version=self.p['version'];self.store.save(self.p['id'],version,{'description':'另一个窗口'})
        with self.assertRaises(ProjectConflict):self.save()
        self.p=self.store.get(self.p['id'])
        self.p=self.store.update(self.p['id'],self.p['version'],lambda p:p.update(archived=True))
        with patch.object(server,'STORE',self.store):
            with self.assertRaises(ReviewError):server.project_action({'action':'practice_link_material',
                'id':self.p['id'],'version':self.p['version'],'observation':self.item})

    def test_api_creates_and_edits_without_model_calls(self):
        with patch.object(server,'STORE',self.store),patch.object(server,'configured_completion') as model:
            self.p=server.project_action({'action':'practice_link_material','id':self.p['id'],
                'version':self.p['version'],'observation':self.item})
            self.p=server.project_action({'action':'practice_edit_observation','id':self.p['id'],
                'version':self.p['version'],'observation_id':self.p['lifecycle']['observations'][0]['id'],
                'observation':{**self.item,'finding':'补充后的发现'}})
            self.assertEqual(self.p['lifecycle']['observations'][0]['finding'],'补充后的发现')
            model.assert_not_called()
