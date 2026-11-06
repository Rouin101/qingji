import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.question_synthesis import synthesis_context, validate_analysis
from core.review import ReviewError
from evaluation.synthesis import CASES, fixture, replay_reply, run_suite, render_report, write_report, compare_runs, digest


class EvaluationTests(unittest.TestCase):
    def test_default_replay_is_model_free_and_reproducible(self):
        with patch('core.review.configured_completion',side_effect=AssertionError('No model')):
            first, second = run_suite(), run_suite()
        self.assertEqual(first['model_calls'],0)
        self.assertEqual(first['suite_hash'],second['suite_hash'])
        self.assertEqual([r['input_hash'] for r in first['cases']],[r['input_hash'] for r in second['cases']])
        self.assertTrue(all(r['structural_status']=='passed' and r['semantic_review']=='pending' and r['project_unchanged'] for r in first['cases']))

    def test_scope_changed_source_and_fake_ids(self):
        cases = json.loads(CASES.read_text('utf-8'))['cases']
        scope,_ = synthesis_context(fixture(cases[-1]),'qmain')
        self.assertEqual(len(scope['records']),1)
        self.assertNotIn('哨兵',json.dumps(scope,ensure_ascii=False))
        changed,_ = synthesis_context(fixture(cases[3]),'qmain')
        self.assertTrue(changed['records'][0]['source_changed'])
        self.assertNotEqual(changed['records'][0]['team_finding'],changed['records'][0]['text'])

    def test_structural_guards_and_semantic_limit_are_distinct(self):
        case = json.loads(CASES.read_text('utf-8'))['cases'][0]
        context,_ = synthesis_context(fixture(case),'qmain')
        data = replay_reply(context)
        # A real quotation cannot make this sweeping conclusion correct.
        data['findings'][0]['text'] = '全体居民都已经独立掌握，满意率100%。'
        validate_analysis(copy.deepcopy(data),context)
        for mode in ('quote','record','material','no_cite','one_source_difference','limits'):
            invalid = copy.deepcopy(data)
            cite = invalid['findings'][0]['citations'][0]
            if mode=='quote': cite['quote']='不存在的引文'
            elif mode=='record': cite['observation_id']='other-question'
            elif mode=='material': cite['material_id']='unrelated'
            elif mode=='no_cite': invalid['findings'][0]['citations']=[]
            elif mode=='one_source_difference': invalid['differences']=[invalid['findings'][0]]
            else: invalid['limits']=[]
            with self.subTest(mode=mode),self.assertRaises(ReviewError):
                validate_analysis(invalid,context)

    def test_failure_is_retained_and_suite_continues_without_error_secrets(self):
        calls=[]
        def complete(messages):
            calls.append(messages)
            if len(calls)==1: raise RuntimeError('SECRET_TOKEN https://private.example')
            if len(calls)==2: return 'broken JSON'
            return json.dumps(replay_reply(json.loads(messages[1]['content'])))
        result = run_suite(complete)
        self.assertEqual(result['model_calls'],6)
        self.assertEqual([r['structural_status'] for r in result['cases']],['failed']*2+['passed']*4)
        self.assertNotIn('SECRET_TOKEN',json.dumps(result))
        self.assertEqual(result['cases'][1]['raw_response'],'broken JSON')

    def test_output_is_escaped_and_existing_run_not_overwritten(self):
        report = run_suite()
        report['cases'][0]['name']='<script>window.pwned=true</script>'
        page = render_report(report)
        self.assertNotIn('<script>window.pwned',page)
        self.assertIn('&lt;script&gt;',page)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'run'
            write_report(report,target)
            self.assertEqual(json.loads((target/'results.json').read_text('utf-8'))['run_hash'],report['run_hash'])
            with self.assertRaises(FileExistsError):write_report(report,target)

    def test_comparison_rejects_mixed_modes_changed_inputs_and_tampering(self):
        before, after = run_suite(), run_suite()
        self.assertTrue(all(row['semantic_review']=='pending' for row in compare_runs(before,after)['cases']))
        for field,value in [('mode','live'),('suite_hash','different')]:
            changed=copy.deepcopy(after);changed[field]=value
            changed['run_hash']=digest({k:v for k,v in changed.items() if k!='run_hash'})
            with self.assertRaises(ValueError):compare_runs(before,changed)
        changed=copy.deepcopy(after);changed['cases'][0]['input_hash']='different'
        with self.assertRaises(ValueError):compare_runs(before,changed)
        changed['run_hash']=digest({k:v for k,v in changed.items() if k!='run_hash'})
        with self.assertRaises(ValueError):compare_runs(before,changed)


if __name__=='__main__':unittest.main()
