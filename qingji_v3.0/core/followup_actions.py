"""Explicit author-confirmed actions from unanswered questions, not evidence."""
import uuid
from core.projects import now, ProjectConflict
from core.collaboration import MAX_TASKS, assignee, due_date, short_text
from core.lifecycle import assign_task_question, state_of
from core.privacy import redacted
from core.review import ReviewError


def create_followup(store, project_id, version, body, actor=''):
    def mutate(p):
        if p.get('archived'):raise ReviewError('已归档项目请先恢复后再安排行动。')
        if type(body.get('source_version')) is not int or body['source_version']!=p['version']:
            raise ProjectConflict('起草后项目已有更新，请重新核对来源并起草行动；输入仍保留。')
        origin=body.get('origin')
        if not isinstance(origin,dict) or origin.get('kind') not in ('record','analysis'):
            raise ReviewError('请选择行动对应的待了解事项。')
        s=state_of(p);qid=origin.get('question_id')
        if not any(q['id']==qid for q in s['questions']):raise ReviewError('关联实践问题已变化。')
        citations=origin.get('citations')
        if not isinstance(citations,list) or not 1<=len(citations)<=4:raise ReviewError('行动来源不完整。')
        refs=[];observations=[]
        for c in citations:
            if not isinstance(c,dict):raise ReviewError('行动来源不完整。')
            o=next((o for o in s['observations'] if o['id']==c.get('observation_id') and o['question_id']==qid and o['material_id']==c.get('material_id')),None)
            m=next((m for m in p['materials'] if m['id']==c.get('material_id')),None)
            if not o or not m:raise ReviewError('行动来源已移除或关联变化，请重新选择。')
            if origin['kind']=='analysis':
                quote=c.get('quote')
                if not m['enabled'] or m['consent_status']!='confirmed' or not isinstance(quote,str) or not quote.strip() or quote not in redacted(m['text']):
                    raise ReviewError('分析来源已变化，请重新生成后安排。')
            observations.append(o);refs.append(f"材料 {m['id']} / 记录 {o['id']}")
        if origin['kind']=='record':
            if len(observations)!=1:raise ReviewError('请选择一条团队记录中的疑问。')
            source_text=short_text(observations[0]['uncertainty'],'待了解事项',2000,True)
        else:
            source_text=short_text(origin.get('text'),'分析待了解事项',800,True)
        source_note='\n'.join(['待了解事项（不是已取得依据）：'+source_text,*dict.fromkeys(refs)])
        if any(s['task_links'].get(t['id'])==qid and (t.get('notes','')==source_note or t.get('notes','').startswith(source_note+'\n')) for t in p['tasks']):
            raise ReviewError('这条待了解事项已安排过行动，请查看相关行动，避免重复添加。')
        notes=source_note+'\n'+short_text(body.get('notes',''),'行动补充说明',500)
        notes=short_text(notes,'行动来源备注',3000)
        if len(p['tasks'])>=MAX_TASKS:raise ReviewError('项目任务已达到上限。')
        task={'id':uuid.uuid4().hex,'kind':'practice','action':short_text(body.get('action_text'),'行动安排',1000,True),
              'assignee_id':assignee(p,body.get('assignee_id','')),'due_date':due_date(body.get('due_date','')),
              'notes':notes,'status':'open','created_at':now(),'quote':'','category':'实践任务','material_ids':[]}
        p['tasks'].append(task);assign_task_question(p,task,qid)
    return store.update(project_id,version,mutate,actor=actor,action='task_created',detail='将待了解事项确认为实践行动')
