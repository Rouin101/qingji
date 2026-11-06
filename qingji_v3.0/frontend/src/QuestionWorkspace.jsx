import QuestionSynthesis from './QuestionSynthesis.jsx';
import {useEffect,useState} from 'react';
import {PracticeReport} from './PracticeReport.jsx';
import './question-workspace.css';

export default function QuestionWorkspace({project,busy,hasDraft,onRecords,onRecord}){
  const state=project.lifecycle;
  const [selected,setSelected]=useState('');
  const [view,setView]=useState(null),[error,setError]=useState('');
  useEffect(()=>{let cancelled=false;setView(null);setError('');
    fetch('/api/practice?id='+encodeURIComponent(project.id)).then(async r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{if(!cancelled){if(data.version!==project.version)throw new Error();setView(data);}}).catch(()=>{if(!cancelled)setError('来源状态暂时无法确认，请重新打开项目后核对。');});
    return()=>{cancelled=true;};
  },[project.id,project.version]);
  if(!state?.questions.length)return null;
  const question=state.questions.find(q=>q.id===selected)||state.questions[0];
  const tasks=project.tasks.filter(t=>state.task_links[t.id]===question.id);
  const records=state.observations.filter(o=>o.question_id===question.id);
  const materials=new Map(project.materials.map(m=>[m.id,m]));
  const changed=new Set(view?.changed_observations||[]);
  const status=o=>!materials.has(o.material_id)?'来源已移除':changed.has(o.id)?'来源已修改，需核对':materials.get(o.material_id).enabled===false?'材料已排除':!view?'来源状态待确认':'阶段发现，需结合原文核对';
  return <section className="question-workspace" aria-label="问题工作区">
    <h2>沿着问题推进</h2>
    <label>当前实践问题<select aria-label="当前实践问题" value={question.id} onChange={e=>setSelected(e.target.value)}>{state.questions.map(q=><option key={q.id} value={q.id}>{q.text}</option>)}</select></label>
    {error&&<p role="alert">{error}</p>}
    <div className="question-actions"><button className="secondary" disabled={busy} onClick={()=>onRecord({questionId:question.id})}>为这个问题记记录</button><button className="text-button" onClick={()=>onRecords({questionId:question.id})}>查看这个问题的全部记录</button></div>
    <details><summary>相关行动 · {tasks.length} 项</summary>{!tasks.length&&<p>尚未安排相关行动，可在行动与记录中添加并关联这个问题。</p>}<ul>{tasks.map(t=><li key={t.id}><p>{t.action}</p><small>{t.status==='done'?'团队已确认行动完成':'行动待推进'} · 行动状态不代表结论成立</small><div className="question-actions"><button className="text-button" disabled={busy} onClick={()=>onRecord({taskId:t.id})}>记下这项行动的记录</button><button className="text-button" onClick={()=>onRecords({taskId:t.id})}>查看行动记录</button></div></li>)}</ul></details>
    <details><summary>阶段发现与来源 · {records.length} 条</summary>{!records.length&&<p>尚无关联记录，暂不能据此判断这个问题。</p>}<ul>{records.map(o=><li key={o.id}><p>{o.finding||'尚未整理阶段发现'}</p><small>{status(o)}</small><div><button className="text-button" onClick={()=>onRecords({observationId:o.id})}>查看记录与原始来源</button></div></li>)}</ul></details>
    <details><summary>仍需了解的情况 · {records.filter(o=>o.uncertainty?.trim()).length} 条</summary><p className="compact-note">来自团队记录的疑问；没有填写不代表问题已经解决。</p><ul>{records.filter(o=>o.uncertainty?.trim()).map(o=><li key={o.id}><p>{o.uncertainty}</p><small>{status(o)}</small><div><button className="text-button" onClick={()=>onRecords({observationId:o.id})}>回到这条记录</button></div></li>)}</ul></details>
    <QuestionSynthesis project={project} questionId={question.id} busy={busy} hasDraft={hasDraft} onRecords={onRecords}/>
    <PracticeReport project={project} busy={busy} hasDraft={hasDraft} questionId={question.id}/>
  </section>;
}
