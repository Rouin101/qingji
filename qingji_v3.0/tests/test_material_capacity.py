import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import server
from core.projects import ProjectStore, material_list
from core.review import ReviewError
from core.lifecycle import add_observation, save_brief, generate_guidance
from core.project_packages import export_package, import_package
from core.practice_assistant import _eligible_materials


def material(i, size=6000, enabled=True):
    return {'id':f'm{i}','name':f'虚构材料{i}','text':'甲'*size,'enabled':enabled,'consent_status':'confirmed'}


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=ProjectStore(Path(self.temp.name)/'test.sqlite3')

    def test_storage_limits_are_independent_and_do_not_truncate(self):
        self.assertEqual(len(material_list([material(i,4800) for i in range(100)])),100)
        with self.assertRaises(ReviewError):material_list([material(i,1) for i in range(101)])
        with self.assertRaises(ReviewError):material_list([material(i,48000) for i in range(11)])
        self.assertEqual(sum(len(m['text']) for m in material_list([material(i) for i in range(9)])),54000)

    def test_ninth_record_and_package_keep_all_relations(self):
        p=self.store.create('虚构容量项目')
        p=save_brief(self.store,p['id'],p['version'],{'topic':'虚构主题','goal':'了解实际情况'},[{'id':'q1','text':'遇到了什么？'}],'field')
        for i in range(9):
            p=add_observation(self.store,p['id'],p['version'],{'question_id':'q1','text':f'实际记录{i}','consent_status':'confirmed'})
        self.assertEqual(len(p['materials']),9)
        q=import_package(self.store,export_package(self.store,p['id']))
        self.assertEqual(len(q['materials']),9)
        self.assertEqual([o['material_id'] for o in q['lifecycle']['observations']],[o['material_id'] for o in p['lifecycle']['observations']])
        complete=Mock()
        with self.assertRaises(ReviewError):generate_guidance(p,'ai',complete)
        complete.assert_not_called()

    def test_review_rejects_over_scope_before_model_then_uses_exact_selection(self):
        p=self.store.create('虚构报告',{'text':'本次现场观察。'},[material(i) for i in range(9)])
        complete=Mock(return_value='{"issues":[]}')
        with patch.object(server,'STORE',self.store),patch.object(server,'configured_completion',complete):
            with self.assertRaises(ReviewError):server.project_action({'action':'review','id':p['id'],'version':p['version'],'mode':'ai','allow_external_processing':True})
            complete.assert_not_called()
            self.assertEqual(self.store.get(p['id'])['version'],p['version'])
            p=self.store.save(p['id'],p['version'],{'materials':[{**m,'enabled':i<7} for i,m in enumerate(p['materials'])]})
            result=server.project_action({'action':'review','id':p['id'],'version':p['version'],'mode':'ai','allow_external_processing':True})
        self.assertEqual(len(result['materials']),9)
        self.assertEqual(result['result']['used_material_ids'],[f'm{i}' for i in range(7)])
        self.assertEqual(len(_eligible_materials(p)),7)
        self.assertEqual(complete.call_count,1)

    def test_character_budget_still_blocks_even_with_fewer_materials(self):
        p=self.store.create('虚构大材料',materials=[material(1,30000),material(2,30000)])
        with self.assertRaises(ReviewError):_eligible_materials(p)
        with self.assertRaises(ReviewError):server.input_documents({'report':{'text':'待核对正文'},'materials':p['materials']})
