"""Shared test-only isolation and fixture checks. Never points at the live store."""
from pathlib import Path
from copy import deepcopy
from core.projects import ProjectStore
from core.review import CATEGORIES

ROOT = Path(__file__).resolve().parent.parent

def qa_database(value, *, existing=False):
    target = Path(value).resolve()
    target.relative_to((ROOT / '.browser-test-output').resolve())
    if target.name != 'projects.sqlite3' or target.parent == ROOT / '.browser-test-output':
        raise ValueError('Use a named isolated QA run directory')
    if target.exists() != existing:
        raise ValueError('QA database existence does not match the requested operation')
    return target

def validate_fixture_result(result, materials):
    assert result['mode'] == 'example', 'Controlled judgments must be fictional examples'
    documents = {'report':result['report'], **{m['id']:m for m in materials}}
    for issue in result['issues']:
        assert issue['category'] in CATEGORIES, 'Use the product category vocabulary'
        assert result['report']['text'][issue['start']:issue['end']] == issue['quote']
        for citation in issue.get('citations', []):
            doc = documents[citation['document_id']]
            assert doc['text'][citation['start']:citation['end']] == citation['quote']

def prepare_fixture_result(result, materials):
    """Locate historical fictional quotes exactly; reject missing sources/quotes."""
    result = deepcopy(result)
    result['mode'] = 'example'
    notice = '人工构造的虚构验收记录，不是AI输出。'
    result['notices'] = [*result.get('notices', []), notice]
    documents = {'report': result['report'], **{m['id']: m for m in materials}}
    cursors = {}
    def locate(record, document_id):
        text, quote = documents[document_id]['text'], record['quote']
        start, end = record.get('start'), record.get('end')
        if not (isinstance(start, int) and isinstance(end, int) and
                0 <= start < end <= len(text) and text[start:end] == quote):
            start = text.find(quote, cursors.get((document_id, quote), 0))
            if not quote or start < 0:
                raise ValueError('Fictional quote must occur in its source document')
            end = start + len(quote)
            record.update(start=start, end=end)
        cursors[document_id, quote] = end
    for issue in result['issues']:
        locate(issue, 'report')
        for citation in issue.get('citations', []):
            locate(citation, citation['document_id'])
    validate_fixture_result(result, materials)
    return result

class FixtureStore(ProjectStore):
    """Historical fixture writers share the same database boundary and checks."""
    def __init__(self, database):
        super().__init__(qa_database(database, existing=True))

    def reviewed(self, project_id, version, result, **kwargs):
        project = self.get(project_id)
        prepared = prepare_fixture_result(result, project['materials'])
        return super().reviewed(project_id, version, prepared, **kwargs)
