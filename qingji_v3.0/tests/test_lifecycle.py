import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server
from core.projects import ProjectStore, ProjectConflict
from core.review import ReviewError
from core import lifecycle as life
from core.project_packages import export_package, import_package

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.store=ProjectStore(Path(self.folder.name)/'fictional.sqlite3')
        self.p=self.store.create('新的社会实践项目')
        self.brief={'topic':'虚构社区数字服务','goal':'了解实际困难和不同经历','audience':'社区居民','location':'虚构社区','timeframe':'一周','resources':'两位成员'}
        self.questions=[{'id':'q1','text':'哪些操作环节遇到困难？'},{'id':'q2','text':'未使用者有哪些不同经历？'}]
        self.p=life.save_brief(self.store,self.p['id'],self.p['version'],self.brief,self.questions,'prepare')

    def guide(self,mode='template',complete=None):
        generated=life.generate_guidance(self.p,mode,complete)
        self.p=life.save_guidance(self.store,self.p['id'],self.p['version'],generated)
        return self.p['lifecycle']['guidance']

    def observe(self,consent='unconfirmed',question='q1',finding='有对象需要求助，尚不能概括全部居民。'):
        self.p=life.add_observation(self.store,self.p['id'],self.p['version'],{
            'question_id':question,'text':'虚构：一位居民求助，一位独立完成。','source_role':'受访者陈述',
            'context':'虚构社区访谈','finding':finding,'uncertainty':'未接触的对象情况未知。','consent_status':consent})

    def ai_result(self,mid=None):
        return json.dumps({'summary':'仅据输入安排下一步。','actions':[{'question_id':'q1','action':'了解不同使用经历。','method':'访谈','why':'覆盖不同情况。','record_hint':'保留范围和原话。','basis_material_ids':[] if mid is None else [mid]}],'material_hints':['查看发布机构原文。'],'limits':['尚未接触所有对象。']})

    def test_start_without_report_and_persist_project_direction(self):
        self.assertEqual(self.p['name'],self.brief['topic']);self.assertEqual(self.p['report']['text'],'')
        other=ProjectStore(self.store.path).get(self.p['id'])
        self.assertEqual(other['lifecycle']['questions'],self.questions)
        self.assertIsNone(other['result'])

    def test_guidance_is_suggestion_until_author_adopts_and_is_idempotent(self):
        g=self.guide();self.assertEqual(self.p['tasks'],[])
        self.p=life.adopt_action(self.store,self.p['id'],self.p['version'],g['id'],'a1','团队修改后的访谈安排')
        self.assertEqual(len(self.p['tasks']),1);self.assertEqual(self.p['tasks'][0]['status'],'open')
        self.assertEqual(self.p['lifecycle']['task_links'][self.p['tasks'][0]['id']],'q1')
        version=self.p['version'];self.p=life.adopt_action(self.store,self.p['id'],version,g['id'],'a1','另一段文字')
        self.assertEqual(self.p['version'],version);self.assertEqual(len(self.p['tasks']),1)

    def test_task_completion_does_not_invent_a_record_and_invalidates_guidance(self):
        g=self.guide();self.p=life.adopt_action(self.store,self.p['id'],self.p['version'],g['id'],'a1','了解实际经历')
        self.p=self.store.task(self.p['id'],self.p['version'],self.p['tasks'][0]['id'],'done')
        self.assertFalse(life.guidance_current(self.p));self.assertEqual(self.p['materials'],[])
        self.assertEqual(life.practice_view(self.p)['questions'][0]['record_count'],0)

    def test_goal_change_retains_history_and_rejects_stale_adoption(self):
        g=self.guide();self.p=life.save_brief(self.store,self.p['id'],self.p['version'],{**self.brief,'goal':'调整为了解求助路径'},self.questions,'field')
        with self.assertRaises(ReviewError):life.adopt_action(self.store,self.p['id'],self.p['version'],g['id'],'a1','新行动')
        self.guide();self.assertEqual(self.p['lifecycle']['guidance_history'][0]['id'],g['id'])

    def test_record_requires_valid_question_and_action_and_does_not_finish_task(self):
        g=self.guide();self.p=life.adopt_action(self.store,self.p['id'],self.p['version'],g['id'],'a1','访谈')
        version=self.p['version']
        for item in [{'question_id':'bad','text':'实际记录'},{'question_id':'q2','task_id':self.p['tasks'][0]['id'],'text':'实际记录'}]:
            with self.assertRaises(ReviewError):life.add_observation(self.store,self.p['id'],version,item)
        self.assertEqual(self.store.get(self.p['id'])['version'],version)
        self.observe();self.assertEqual(self.p['tasks'][0]['status'],'open')
        self.assertEqual(self.p['materials'][0]['consent_status'],'unconfirmed')

    def test_unconsented_and_excluded_records_and_private_notes_never_enter_prompt(self):
        self.guide()
        self.observe(finding='SECRET-unconfirmed')
        self.assertFalse(life.guidance_current(self.p))
        model=Mock(return_value=self.ai_result());life.generate_guidance(self.p,'ai',model)
        prompt=model.call_args[0][0][-1]['content'];self.assertNotIn('SECRET-unconfirmed',prompt)
        mats=copy.deepcopy(self.p['materials']);mats[0].update(consent_status='confirmed',enabled=False)
        self.p=self.store.save(self.p['id'],self.p['version'],{'materials':mats})
        life.generate_guidance(self.p,'ai',model);self.assertNotIn('SECRET-unconfirmed',model.call_args[0][0][-1]['content'])

    def test_ai_cannot_reference_nonexistent_or_other_question_material(self):
        self.observe('confirmed',question='q2');mid=self.p['materials'][0]['id']
        for referenced in ['invented',mid]:
            with self.assertRaises(ReviewError):life.generate_guidance(self.p,'ai',lambda _:self.ai_result(referenced))
        self.assertEqual(self.p['lifecycle']['guidance'],None)

    def test_ai_failure_does_not_become_local_template_and_late_result_does_not_commit(self):
        with self.assertRaises(ReviewError):life.generate_guidance(self.p,'ai',lambda _:'invalid')
        version=self.p['version'];generated=life.generate_guidance(self.p)
        self.store.save(self.p['id'],version,{'description':'并发窗口保存'})
        with self.assertRaises(ProjectConflict):life.save_guidance(self.store,self.p['id'],version,generated)
        self.assertIsNone(self.store.get(self.p['id'])['lifecycle']['guidance'])

    def test_changed_source_is_marked_and_never_merged_into_old_finding(self):
        self.observe('confirmed');mats=copy.deepcopy(self.p['materials']);mats[0]['text']='修改后不同的记录'
        self.p=self.store.save(self.p['id'],self.p['version'],{'materials':mats})
        self.assertTrue(life.practice_view(self.p)['changed_observations'])
        self.assertTrue(life.context_of(self.p)['observations'][0]['source_changed'])
        self.assertIn('需要重新核对',life.report_outline(self.p))

    def test_package_preserves_flow_and_resets_consent_and_old_guidance(self):
        self.observe('confirmed');g=self.guide()
        self.p=life.adopt_action(self.store,self.p['id'],self.p['version'],g['id'],'a1','整理不同经历')
        package=export_package(self.store,self.p['id']);self.assertEqual(package['schema_version'],2)
        imported=import_package(self.store,package)
        self.assertNotEqual(imported['id'],self.p['id'])
        self.assertEqual(imported['lifecycle']['observations'],self.p['lifecycle']['observations'])
        self.assertFalse(life.guidance_current(imported));self.assertEqual(imported['materials'][0]['consent_status'],'unconfirmed')
        export_package(self.store,imported['id'])

    def test_unknown_nested_package_fields_cannot_enter_guidance_snapshots(self):
        self.guide();package=export_package(self.store,self.p['id'])
        package['payload']['project']['lifecycle']['guidance']['basis']['brief']['api_key']='not-permitted'
        from core.project_packages import _json_bytes
        import hashlib
        package['sha256']=hashlib.sha256(_json_bytes(package['payload'])).hexdigest()
        with self.assertRaises(ReviewError):import_package(self.store,package)

    def test_v2_package_imports_as_independent_project_without_invented_flow(self):
        old=self.store.create('虚构旧版项目')
        package=export_package(self.store,old['id']);package['schema_version']=1
        imported=import_package(self.store,package)
        self.assertEqual(life.state_of(imported),life.empty_state())

    def test_brief_cannot_remove_question_with_linked_record(self):
        self.observe()
        with self.assertRaises(ReviewError):life.save_brief(self.store,self.p['id'],self.p['version'],self.brief,[self.questions[1]],'field')

    def test_report_uses_actual_authorized_records_and_refuses_overwrite(self):
        self.observe('confirmed');outline=life.report_outline(self.p)
        self.assertIn('一位独立完成',outline);self.assertIn('阶段发现（待核对）',outline)
        with patch.object(server,'STORE',self.store),patch.object(server,'configured_completion') as model:
            self.p=server.project_action({'action':'practice_report','id':self.p['id'],'version':self.p['version']})
            with self.assertRaises(ReviewError):server.project_action({'action':'practice_report','id':self.p['id'],'version':self.p['version']})
            with self.assertRaises(ReviewError):server.project_action({'action':'practice_guidance','id':self.p['id'],'version':self.p['version'],'mode':'ai','allow_external_processing':False})
            model.assert_not_called()
