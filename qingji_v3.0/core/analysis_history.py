"""Durable, source-snapshotted AI notes. Imported notes never become current automatically."""
import copy
import hashlib
import json
import re
import uuid
from contextlib import closing
from datetime import datetime
from core.projects import now, ProjectConflict
from core.question_synthesis import synthesis_context,validate_analysis
from core.review import ReviewError

MAX_ANALYSES=20


def validate_snapshot(value):
    v=copy.deepcopy(value)
    if not isinstance(v,dict) or set(v)!={'id','created_at','imported','context','result'}:
        raise ReviewError('阶段分析历史结构不完整。')
    if not isinstance(v['id'],str) or not re.fullmatch('[a-f0-9]{32}',v['id']) or type(v['imported']) is not bool:
        raise ReviewError('阶段分析历史标识无效。')
    try:
        if not isinstance(v['created_at'],str) or datetime.fromisoformat(v['created_at']).tzinfo is None:raise ValueError()
    except (TypeError,ValueError):raise ReviewError('阶段分析历史时间无效。')
    c=v['context'];r=v['result']
    if not isinstance(c,dict) or set(c)!={'question','goal','records'} or not isinstance(c['records'],list) or not 1<=len(c['records'])<=100:
        raise ReviewError('阶段分析历史缺少原始范围快照。')
    for key,limit in [('question',400),('goal',800)]:
        if not isinstance(c[key],str) or len(c[key])>limit:raise ReviewError('阶段分析历史范围无效。')
    fields={'observation_id':80,'material_id':80,'name':200,'text':48000,'source_role':40,'context':1000,'collected_at':100,'team_finding':2000,'uncertainty':2000}
    ids=set()
    for record in c['records']:
        if not isinstance(record,dict) or set(record)!=set(fields)|{'source_changed'}:raise ReviewError('阶段分析来源快照结构无效。')
        if any(not isinstance(record[k],str) or len(record[k])>limit for k,limit in fields.items()) or type(record['source_changed']) is not bool:raise ReviewError('阶段分析来源快照无效。')
        if record['observation_id'] in ids or not record['observation_id'] or not record['material_id']:raise ReviewError('阶段分析来源标识重复或缺失。')
        ids.add(record['observation_id'])
    from core.material_limits import validate_scope
    unique={}
    for record in c['records']:
        if record['material_id'] in unique and unique[record['material_id']]['text']!=record['text']:raise ReviewError('同份材料的快照原文不一致。')
        unique[record['material_id']]={'text':record['text']}
    validate_scope(list(unique.values()))
    encoded=json.dumps(c,ensure_ascii=False,sort_keys=True)
    if len(encoded)>60000:raise ReviewError('阶段分析历史来源快照过长。')
    if not isinstance(r,dict) or set(r)!={'mode','question_id','version','fingerprint','analysis','material_count','changed_sources'}:raise ReviewError('阶段分析历史结果结构无效。')
    if r['mode']!='ai' or not isinstance(r['question_id'],str) or not re.fullmatch(r'q[A-Za-z0-9_-]{1,79}',r['question_id']) or type(r['version']) is not int or r['version']<1:raise ReviewError('阶段分析历史版本无效。')
    if r['fingerprint']!=hashlib.sha256(encoded.encode()).hexdigest():raise ReviewError('阶段分析历史输入指纹不匹配。')
    if type(r['material_count']) is not int or r['material_count']!=len({x['material_id'] for x in c['records']}) or type(r['changed_sources']) is not bool or r['changed_sources']!=any(x['source_changed'] for x in c['records']):raise ReviewError('阶段分析历史来源范围不匹配。')
    if len(json.dumps(r['analysis'],ensure_ascii=False))>24000:raise ReviewError('阶段分析历史结果过长。')
    r['analysis']=validate_analysis(r['analysis'],c)
    return v


def ensure_capacity(store,project_id):
    with closing(store.connect()) as db:
        if db.execute('SELECT COUNT(*) FROM analyses WHERE project_id=?',(project_id,)).fetchone()[0]>=MAX_ANALYSES:
            raise ReviewError('项目已保存 20 次阶段分析，请先下载并删除不再需要的历史；不会自动淘汰。')


def save_analysis(store,project,result):
    context,_=synthesis_context(project,result['question_id'])
    snapshot=validate_snapshot({'id':uuid.uuid4().hex,'created_at':now(),'imported':False,'context':context,'result':result})
    with closing(store.connect()) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT data FROM projects WHERE id=?',(project['id'],)).fetchone()
        if not row or json.loads(row[0])['version']!=project['version']:raise ProjectConflict('保存分析时项目已更新，请重新生成。')
        if db.execute('SELECT COUNT(*) FROM analyses WHERE project_id=?',(project['id'],)).fetchone()[0]>=MAX_ANALYSES:raise ReviewError('分析历史已满，本次未保存；请先整理历史。')
        db.execute('INSERT INTO analyses VALUES (?,?,?)',(snapshot['id'],project['id'],json.dumps(snapshot,ensure_ascii=False)))
    return {**result,'history_id':snapshot['id'],'created_at':snapshot['created_at'],'current':True}


def history(store,project_id,question_id):
    with closing(store.connect()) as db:
        db.execute('BEGIN')
        row=db.execute('SELECT data FROM projects WHERE id=?',(project_id,)).fetchone()
        if not row:raise ReviewError('找不到这个实践项目。')
        p=json.loads(row[0]);rows=db.execute('SELECT data FROM analyses WHERE project_id=? ORDER BY rowid DESC',(project_id,)).fetchall()
    try:_,fingerprint=synthesis_context(p,question_id)
    except ReviewError:fingerprint=None
    result=[]
    for row in rows:
        snapshot=validate_snapshot(json.loads(row[0]));r=snapshot['result']
        if r['question_id']!=question_id:continue
        current=not snapshot['imported'] and r['fingerprint']==fingerprint
        result.append({**r,'version':p['version'] if current else r['version'],'source_version':r['version'],
                       'history_id':snapshot['id'],'created_at':snapshot['created_at'],'current':current,
                       'imported':snapshot['imported'],'source_question':snapshot['context']['question'],
                       'source_records':snapshot['context']['records']})
    return {'version':p['version'],'history':result}


def delete_analysis(store,project_id,history_id):
    if not isinstance(history_id,str):raise ReviewError('请选择要删除的历史分析。')
    with closing(store.connect()) as db,db:
        if not db.execute('DELETE FROM analyses WHERE project_id=? AND id=?',(project_id,history_id)).rowcount:raise ReviewError('这份历史分析已不存在，请刷新列表。')
    return {'deleted':True}
