import copy
import unittest
from core.delivery_check import delivery_check, delivery_markdown


def project():
    quote="所有居民都需要帮助。"
    return {"id":"p1", "name":"虚构交付检查", "version":7, "report":{"text":quote}, "needs_review":False,
            "manual_text":None, "choices":{}, "materials":[{"id":"m1", "name":"虚构访谈", "enabled":True, "consent_status":"confirmed"}],
            "result":{"mode":"ai", "report":{"text":quote}, "used_material_ids":["m1"], "issues":[
                {"id":"i1", "quote":quote, "support_status":"unsupported", "suggested_text":"本次受访者提出帮助需求。"}]},
            "tasks":[], "history":[{"created_at":"2026-10-03T00:00:00+00:00"}]}


class DeliveryCheckTests(unittest.TestCase):
    def test_kept_original_does_not_turn_insufficient_evidence_into_support(self):
        p=project();p['choices']={'i1':'kept'}
        c=delivery_check(p)
        self.assertEqual(c['counts']['undecided_claims'],0)
        self.assertEqual(c['review']['support_counts']['unsupported'],1)
        self.assertNotIn('passed',c)

    def test_author_adopted_edit_requires_recheck_even_if_scope_flag_is_false(self):
        p=project();p['choices']={'i1':'accepted'}
        c=delivery_check(p)
        self.assertFalse(c['review']['current'])
        self.assertTrue(c['review']['pending_author_edits'])
        self.assertIn('待复查',c['sections'][0]['items'][0]['label'])

    def test_manual_text_equal_to_review_is_current_but_new_text_is_not(self):
        p=project();p['manual_text']=p['report']['text']
        self.assertTrue(delivery_check(p)['review']['current'])
        p['manual_text']+='新增未知场景。'
        self.assertFalse(delivery_check(p)['review']['current'])

    def test_precheck_zero_issues_is_still_not_an_ai_judgment(self):
        p=project();p['result'].update(mode='preliminary',issues=[])
        c=delivery_check(p)
        self.assertIn('本地预检',c['sections'][0]['items'][0]['label'])
        self.assertEqual(c['counts']['undecided_claims'],0)
        self.assertNotIn('ready',c)

    def test_unconfirmed_material_is_not_hidden_by_false_needs_review(self):
        p=project();p['materials'][0]['consent_status']='unconfirmed';p['result']['used_material_ids']=[]
        c=delivery_check(p)
        self.assertEqual(c['materials']['total'],1)
        self.assertEqual(c['materials']['eligible_current'],0)
        self.assertEqual(c['review']['last_used_material_count'],0)
        self.assertEqual(c['sections'][1]['items'][0]['material_id'],'m1')

    def test_explicit_exclusion_is_not_a_request_to_authorize_or_a_missing_link(self):
        p=project();p['materials'][0].update(enabled=False,consent_status='unconfirmed')
        p['tasks']=[{'id':'t1','action':'核对记录','kind':'evidence','status':'done','material_ids':['m1']}]
        c=delivery_check(p)
        self.assertEqual(c['materials']['excluded'],1)
        self.assertEqual(c['sections'][1]['items'],[])
        self.assertEqual(c['counts']['missing_material_links'],0)

    def test_unknown_old_scope_is_not_made_zero_or_all_current_materials(self):
        p=project();p['result'].pop('used_material_ids')
        c=delivery_check(p)
        self.assertIsNone(c['review']['last_used_material_count'])
        self.assertIn('未知（旧记录未保存纳入范围）',delivery_markdown(c))

    def test_supported_claim_does_not_require_a_keep_click(self):
        p=project();p['result']['issues'][0].update(support_status='supported',suggested_text=None)
        self.assertEqual(delivery_check(p)['counts']['undecided_claims'],0)

    def test_missing_links_and_practice_tasks_are_separate_and_never_auto_completed(self):
        p=project();p['tasks']=[{'id':'t1','action':'补访','kind':'evidence','status':'awaiting_confirmation','material_ids':['m2']},
                             {'id':'t2','action':'安排交通','kind':'practice','status':'open','material_ids':[]}]
        before=copy.deepcopy(p);c=delivery_check(p)
        self.assertEqual(c['counts']['open_evidence_tasks'],1)
        self.assertEqual(c['counts']['open_practice_tasks'],1)
        self.assertEqual(c['counts']['missing_material_links'],1)
        self.assertEqual(p,before)

    def test_empty_project_and_no_result_are_explicit_not_success(self):
        p=project();p.update(result=None,report={'text':''},history=[])
        c=delivery_check(p)
        self.assertFalse(c['review']['current'])
        self.assertEqual(len(c['sections'][0]['items']),2)
        self.assertIsNone(c['review']['last_used_material_count'])

    def test_export_preserves_all_action_items_and_marks_old_assessment(self):
        p=project();p['needs_review']=True
        p['tasks']=[{'id':f't{i}','action':f'虚构行动{i}','kind':'practice','status':'open','material_ids':[]} for i in range(30)]
        output=delivery_markdown(delivery_check(p))
        self.assertIn('虚构行动29',output)
        self.assertIn('不能代替对最新正文和材料的复查',output)

    def test_input_and_model_config_are_never_exported_wholesale(self):
        p=project();p['private_unknown_field']='synthetic-secret-marker'
        before=copy.deepcopy(p);c=delivery_check(p)
        self.assertEqual(p,before)
        self.assertNotIn('synthetic-secret-marker',str(c)+delivery_markdown(c))
