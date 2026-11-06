import tempfile
import unittest
from pathlib import Path
from core.projects import ProjectStore
from core.lifecycle import save_brief, add_observation, report_outline
from core.review import ReviewError


class QuestionReportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=ProjectStore(Path(temp.name)/'projects.sqlite3')
        p=self.store.create('虚构问题整理')
        p=save_brief(self.store,p['id'],p['version'],{'topic':'走访','goal':'了解不同环节'},[{'id':'q1','text':'线下有哪些困难？'},{'id':'q2','text':'线上有哪些困难？'}],'field')
        for q,text in [('q1','甲窗口原文'),('q2','乙线上原文')]:
            p=add_observation(self.store,p['id'],p['version'],{'question_id':q,'text':text,'finding':text+'发现','uncertainty':text+'疑问','consent_status':'confirmed'})
        self.p=p

    def test_scope_keeps_sources_findings_uncertainty_without_mutation(self):
        result=report_outline(self.p,'q2')
        self.assertIn(' · 问题整理稿',result)
        self.assertIn('乙线上原文',result);self.assertIn('乙线上原文疑问',result)
        self.assertNotIn('甲窗口原文',result);self.assertNotIn('线下有哪些困难',result)
        self.assertEqual(self.store.get(self.p['id']),self.p)
        self.assertIn('行动安排与完成状态不作为成效证据',result)

    def test_full_report_unchanged_and_unknown_question_rejected(self):
        result=report_outline(self.p)
        self.assertIn('甲窗口原文',result);self.assertIn('乙线上原文',result)
        with self.assertRaises(ReviewError):report_outline(self.p,'deleted-question')

    def test_excluded_records_not_leaked_and_changed_sources_warn(self):
        materials=self.p['materials']
        materials[1]['enabled']=False
        p=self.store.save(self.p['id'],self.p['version'],{'materials':materials})
        result=report_outline(p,'q2');self.assertNotIn('乙线上原文',result)
        self.assertIn('暂不能据此作出结论',result)
        materials[1]['enabled']=True;materials[1]['text']='改过的记录'
        p=self.store.save(p['id'],p['version'],{'materials':materials})
        result=report_outline(p,'q2');self.assertIn('关联材料后来有修改',result)
        self.assertIn('改过的记录',result)
