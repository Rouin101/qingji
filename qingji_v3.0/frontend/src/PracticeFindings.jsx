import {useEffect, useRef, useState} from 'react';

export function PracticeFindings({project, view, busy, onEdit, onMaterials, request}) {
  const s=project.lifecycle;
  const [question,setQuestion]=useState('');
  const [task,setTask]=useState('');
  const [query,setQuery]=useState('');
  const details=useRef(null), heading=useRef(null);
  useEffect(()=>{
    if(!request)return;
    setQuestion('');setTask(request.taskId);setQuery('');
    if(details.current)details.current.open=true;
    const frame=requestAnimationFrame(()=>{heading.current?.focus({preventScroll:true});heading.current?.scrollIntoView({block:'center'});});
    return()=>cancelAnimationFrame(frame);
  },[request]);
  const sourceById=new Map(project.materials.map(m=>[m.id,m]));
  const normalized=query.trim().toLocaleLowerCase();
  const visible=s.observations.filter(o=>{
    const m=sourceById.get(o.material_id);
    return (!question||o.question_id===question) && (!task||(task==='unlinked'?!o.task_id:o.task_id===task)) &&
      (!normalized||[o.finding,o.uncertainty,m?.name,m?.text,m?.context].filter(Boolean).join(' ').toLocaleLowerCase().includes(normalized));
  });
  const tasks=project.tasks.filter(t=>t.kind==='practice'&&(!question||s.task_links[t.id]===question));
  return <details className="practice-findings" ref={details}>
    <summary ref={heading}>查看 {s.observations.length} 条阶段记录</summary>
    <div className="finding-filters">
      <label>实践问题<select aria-label="筛选记录问题" value={question} onChange={e=>{setQuestion(e.target.value);setTask('');}}><option value="">全部问题</option>{s.questions.map(q=><option key={q.id} value={q.id}>{q.text}</option>)}</select></label>
      <label>对应行动<select aria-label="筛选记录行动" value={task} onChange={e=>setTask(e.target.value)}><option value="">全部行动</option><option value="unlinked">未关联行动</option>{tasks.map(t=><option key={t.id} value={t.id}>{t.action}</option>)}</select></label>
      <label className="finding-search">搜索记录<input type="search" aria-label="搜索阶段记录" value={query} onChange={e=>setQuery(e.target.value)} placeholder="发现、原文或材料名称"/></label>
    </div>
    <div className="finding-filter-result"><span role="status">显示 {visible.length} / {s.observations.length} 条记录</span>{(question||task||query)&&<button className="text-button" onClick={()=>{setQuestion('');setTask('');setQuery('');}}>清除筛选</button>}</div>
    {!visible.length&&<p className="compact-note">没有符合当前筛选的记录，试试其他问题或关键词。</p>}
    {visible.map(o=>{const material=sourceById.get(o.material_id);const action=project.tasks.find(t=>t.id===o.task_id);return <article key={o.id} data-observation-id={o.id}>
      <strong>{s.questions.find(q=>q.id===o.question_id)?.text}</strong>
      <p className="compact-note">{action?`对应行动：${action.action}`:'未关联具体行动'}{material?.enabled===false?' · 材料已排除':''}</p>
      <p>{o.finding||'尚未整理阶段发现。'}</p>
      {view?.changed_observations?.includes(o.id)&&<p className="practice-stale">关联材料已修改，阶段发现需重新核对。</p>}
      {o.uncertainty&&<p className="subtle">仍不确定：{o.uncertainty}</p>}
      {material?<details className="observation-source"><summary>查看原始记录 · {material.name}</summary><p className="compact-note">{material.source_role} · {material.collected_at||'时间未记录'}{material.context&&` · ${material.context}`}</p><pre>{material.text}</pre><small>当前保存的原文；阶段发现是团队的理解，仍需结合来源核对。</small></details>:<p className="compact-note">关联材料已移除，仅保留记录备注，不能查看或据此还原原文。</p>}
      <button className="text-button" disabled={busy} onClick={()=>onEdit(o.id)}>编辑阶段记录</button>
    </article>;})}
    <button className="text-button" onClick={onMaterials}>查看材料与来源 →</button>
  </details>;
}
