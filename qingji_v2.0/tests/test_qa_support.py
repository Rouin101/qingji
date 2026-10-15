import tempfile
import unittest
from pathlib import Path

from scripts.qa_support import ROOT, qa_database, prepare_fixture_result


class QaSupportTests(unittest.TestCase):
    def test_database_rejects_formal_and_prefix_sibling_paths(self):
        for target in (ROOT / 'data/projects.sqlite3',
                       ROOT / '.browser-test-output-sibling/run/projects.sqlite3',
                       ROOT / '.browser-test-output/projects.sqlite3'):
            with self.assertRaises(ValueError):
                qa_database(target)

    def test_named_qa_database_checks_create_and_existing_operations(self):
        qa_root = ROOT / '.browser-test-output'
        qa_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='guard-test-', dir=qa_root) as folder:
            target = Path(folder) / 'projects.sqlite3'
            self.assertEqual(qa_database(target), target.resolve())
            with self.assertRaises(ValueError):
                qa_database(target, existing=True)
            target.touch()
            self.assertEqual(qa_database(target, existing=True), target.resolve())
            with self.assertRaises(ValueError):
                qa_database(target)

    def test_fixture_offsets_are_exact_and_missing_quotes_are_rejected(self):
        result = {'mode': 'example', 'report': {'text': '甲说改善。甲说改善。'},
                  'issues': [{'id': 'a', 'quote': '甲说改善。', 'category': '范围外推'},
                             {'id': 'b', 'quote': '甲说改善。', 'category': '范围外推',
                              'citations': [{'document_id': 'm', 'quote': '仅一人'}]}]}
        material = {'id': 'm', 'text': '访谈仅一人，范围有限。'}
        prepared = prepare_fixture_result(result, [material])
        self.assertEqual([(i['start'], i['end']) for i in prepared['issues']], [(0, 5), (5, 10)])
        self.assertEqual(prepared['issues'][1]['citations'][0]['start'], 2)
        self.assertNotIn('start', result['issues'][0])
        result['issues'][0]['quote'] = '不存在的引文'
        with self.assertRaises(ValueError):
            prepare_fixture_result(result, [material])
