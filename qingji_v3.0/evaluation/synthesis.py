"""Reproducible structural evaluation; semantic quality remains a human judgment."""
import copy
import hashlib
import html
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from core.lifecycle import empty_state, source_fingerprint
from core.question_synthesis import synthesize, synthesis_context

CASES = Path(__file__).with_name('synthesis_cases.json')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def fixture(case):
    """Stable identifiers, no SQLite connection and no real project input."""
    state = empty_state()
    state['brief'].update(topic='虚构评估', goal='了解有限记录中的情况与未解问题')
    state['questions'] = [{'id':'qmain','text':case['question']}, {'id':'qother','text':'其他问题'}]
    materials = []
    for index, record in enumerate(case['records']):
        material = {'id':f'm{index}', 'name':f'虚构材料{index+1}', 'text':record['text'],
                    'enabled':record.get('enabled',True), 'consent_status':record.get('consent_status','confirmed'),
                    'source_role':'虚构现场记录', 'context':'仅用于软件评估，非真实调查', 'collected_at':''}
        materials.append(material)
        state['observations'].append({'id':f'o{index}', 'material_id':material['id'],
            'question_id':record.get('question_id','qmain'), 'finding':record.get('finding',''),
            'uncertainty':'', 'source_fingerprint':'old' if record.get('changed') else source_fingerprint(material)})
    return {'id':'synthetic-'+case['id'], 'version':1, 'materials':materials, 'tasks':[], 'lifecycle':state}


def replay_reply(context):
    """A controlled echo, explicitly not an AI reasoning reference answer."""
    source = context['records'][0]
    return {'findings':[{'text':'这份记录保留了如下表述，尚待作者核对。', 'citations':[{
        'observation_id':source['observation_id'], 'material_id':source['material_id'], 'quote':source['text'][:600]}]}],
        'differences':[], 'questions':[], 'limits':['受控回放仅用于验证工具，不代表模型能力。']}


def run_suite(complete=None):
    suite = json.loads(CASES.read_text('utf-8'))
    report = {'schema':1, 'mode':'live' if complete else 'replay',
              'created_at':datetime.now(timezone.utc).isoformat(), 'suite_hash':digest(suite),
              'implementation_hash':hashlib.sha256((CASES.parent.parent/'core/question_synthesis.py').read_bytes()).hexdigest(),
              'cases':[], 'model_calls':0}
    for case in suite['cases']:
        project = fixture(case)
        context, fingerprint = synthesis_context(project, 'qmain')
        row = {'id':case['id'], 'name':case['name'], 'rubric':case['rubric'],
               'context':context, 'input_hash':fingerprint, 'semantic_review':'pending'}
        before = copy.deepcopy(project)
        start = time.monotonic()
        def provider(messages):
            if complete:
                report['model_calls'] += 1
                raw = complete(messages)
            else:
                raw = json.dumps(replay_reply(context), ensure_ascii=False)
            # Keep malformed short output for diagnosis too; no unbounded response dumps.
            if isinstance(raw,str):
                row['raw_response'] = raw[:24000]
                row['response_truncated'] = len(raw)>24000
            return raw
        try:
            row['result'] = synthesize(project, 'qmain', provider)
            row['structural_status'] = 'passed'
        except Exception as exc:
            row['structural_status'] = 'failed'
            # Provider exceptions may contain credentials/URLs; do not serialize their text.
            row['error_kind'] = type(exc).__name__
            row['error'] = '本例调用或输出校验失败；未生成可用分析。'
        row['project_unchanged'] = before == project
        row['elapsed_seconds'] = round(time.monotonic()-start,3)
        row['response_hash'] = digest(row.get('raw_response'))
        report['cases'].append(row)
    report['run_hash'] = digest(report)
    return report


def render_report(report):
    """Self-contained offline review page. All model/source text is escaped."""
    escape = lambda value: html.escape(str(value), quote=True)
    sections = []
    for row in report['cases']:
        rubrics = ''.join(f'<li>{escape(x)}</li>' for x in row['rubric'])
        content = json.dumps(row.get('result', {'error':row.get('error'), 'raw_response':row.get('raw_response')}),ensure_ascii=False,indent=2)
        sources = ''.join(f'<h3>{escape(r["name"])}</h3><p>{escape(r["text"])}</p>'
                          + (f'<p>团队旧发现：{escape(r["team_finding"])}</p>' if r['team_finding'] else '')
                          + ('<p>来源已改变，团队发现需核对。</p>' if r['source_changed'] else '')
                          for r in row['context']['records'])
        readable = ''
        if row.get('result'):
            analysis = row['result']['analysis']
            for group, label in [('findings','候选理解'),('differences','不同反馈'),('questions','待了解事项')]:
                readable += f'<h3>{label}</h3>'
                if not analysis[group]:readable += '<p>本轮未返回条目。</p>'
                for item in analysis[group]:
                    readable += f'<p>{escape(item["text"])}</p>'
                    readable += ''.join(f'<blockquote>{escape(c["quote"])}<br><small>材料 {escape(c["material_id"])} · 记录 {escape(c["observation_id"])}</small></blockquote>' for c in item['citations'])
            readable += '<h3>分析限制</h3><ul>'+''.join(f'<li>{escape(x)}</li>' for x in analysis['limits'])+'</ul>'
        else:readable = f'<p>{escape(row.get("error","本例未生成可用分析。"))}</p>'
        disabled = ' disabled' if row['structural_status']!='passed' else ''
        sections.append(f'''<section data-id="{escape(row['id'])}" data-response="{escape(row['response_hash'])}">
<h2>{escape(row['name'])}</h2><p>结构与引文校验：{escape(row['structural_status'])} · 语义判断：待人工复核</p>
<h3>逐条检查</h3><ul>{rubrics}</ul><details><summary>本次发送的虚构来源</summary><p>问题：{escape(row['context']['question'])}</p>{sources}</details>
{readable}<details><summary>完整输出数据</summary><pre>{escape(content)}</pre></details>
<label>人工结论 <select{disabled}><option value="pending">待复核</option><option value="pass">符合本例检查要点</option><option value="fail">存在问题</option><option value="uncertain">无法判断</option></select></label>
<label>依据与问题 <textarea rows="3" placeholder="写明对应表述、原文和判断理由"></textarea></label></section>''')
    metadata = escape(json.dumps({k:report[k] for k in ('run_hash','mode','suite_hash','implementation_hash')},ensure_ascii=False))
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>青迹 · 阶段分析评估</title><style>
*{box-sizing:border-box}body{margin:0;background:#faf8fd;color:#292036;font:16px/1.65 system-ui,sans-serif}main{max-width:960px;margin:auto;padding:24px}h1{color:#653699}h2{font-size:22px}h3{font-size:17px}section{background:white;border:1px solid #e1d7ef;border-radius:12px;padding:24px;margin:24px 0;overflow-wrap:anywhere}blockquote{margin:12px 0;padding:8px 16px;border-left:3px solid #b9a4d3;background:#faf8fd}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.7 system-ui}label{display:block;margin:16px 0}select,textarea,input,button{font:inherit;max-width:100%;padding:8px;border:1px solid #b9a4d3;border-radius:6px}textarea{display:block;width:100%}button{background:#653699;color:white;cursor:pointer}summary{cursor:pointer;color:#653699}#notice{color:#653699}@media(max-width:480px){main{padding:16px}section{padding:16px}}
</style><main><h1>阶段分析评估</h1>''' + f'''<p>运行方式：<strong>{escape(report['mode'])}</strong> · 模型调用 {report['model_calls']} 次</p>
<p>结构与引文匹配通过不代表语义正确。replay 是受控回放，不是模型评测。所有案例均为虚构；本页不连接项目库或外部服务。</p>
<p>人工选择仅暂存在当前页面，请下载复核记录后再关闭。未完成的项目保留“待复核”，不自动计算准确率。</p>
<label>复核人（可填代号） <input id="reviewer" maxlength="80"></label>
<div id="metadata" hidden>{metadata}</div>''' + ''.join(sections) + '''
<button id="download">下载人工复核记录</button><p id="notice" role="status"></p></main>
<script>
let dirty=false;document.addEventListener('input',()=>{dirty=true});document.addEventListener('change',()=>{dirty=true});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
document.querySelector('#download').onclick=()=>{
const cases=[...document.querySelectorAll('section')].map(s=>({id:s.dataset.id,response_hash:s.dataset.response,verdict:s.querySelector('select').value,notes:s.querySelector('textarea').value.trim()}));
if(cases.some(c=>c.verdict!=='pending'&&!c.notes)){document.querySelector('#notice').textContent='已作判断的条目请填写依据，再下载。';return}
const data={schema:1,...JSON.parse(document.querySelector('#metadata').textContent),reviewer:document.querySelector('#reviewer').value.trim(),reviewed_at:new Date().toISOString(),cases};
const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='qingji-evaluation-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);dirty=false;
document.querySelector('#notice').textContent='已发起下载，请确认文件已保存。未完成项目仍为待复核。';
};</script></html>'''


def write_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (directory/'review.html').write_text(render_report(report),encoding='utf-8')


def compare_runs(before, after):
    """Compare identical inputs only; never manufacture a semantic score."""
    for report in (before,after):
        payload = {k:v for k,v in report.items() if k!='run_hash'}
        if report.get('schema')!=1 or digest(payload)!=report.get('run_hash'):
            raise ValueError('评估文件不完整或已修改，请使用原始 results.json。')
    if before['mode']!=after['mode'] or before['suite_hash']!=after['suite_hash']:
        raise ValueError('运行方式或案例集不同，不能作为同一基线比较。')
    old = {row['id']:row for row in before['cases']}
    new = {row['id']:row for row in after['cases']}
    if set(old)!=set(new) or len(old)!=len(before['cases']) or len(new)!=len(after['cases']):
        raise ValueError('案例集合不一致或存在重复标识。')
    rows = []
    for ident, row in new.items():
        previous = old[ident]
        if previous['input_hash']!=row['input_hash']:
            raise ValueError('案例输入不同，不能直接比较。')
        rows.append({'id':ident,'before':previous['structural_status'],'after':row['structural_status'],
                     'response_changed':previous['response_hash']!=row['response_hash'],
                     'semantic_review':'pending'})
    return {'before':before['run_hash'],'after':after['run_hash'],
            'implementation_changed':before['implementation_hash']!=after['implementation_hash'],
            'cases':rows,'note':'仅比较结构校验和输出变化；不据此判断语义变好或变差。'}
