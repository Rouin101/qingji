import {useEffect, useRef, useState} from 'react';

export function ObservationLink({project, observation, changed, busy, onSave, onCancel, onDirty}) {
  const s = project.lifecycle;
  const [qid, setQid] = useState(observation?.question_id || s.questions[0].id);
  const [mid, setMid] = useState(observation?.material_id || '');
  const [taskId, setTaskId] = useState(observation?.task_id || '');
  const [finding, setFinding] = useState(observation?.finding || '');
  const [uncertainty, setUncertainty] = useState(observation?.uncertainty || '');
  const first = useRef(null);
  useEffect(()=>{first.current?.focus();},[]);
  const material = project.materials.find(m=>m.id===mid);
  const linked = id => s.observations.some(o=>o.id!==observation?.id && o.question_id===qid && o.material_id===id);
  const submit = reviewed => onSave({material_id:mid, question_id:qid, task_id:taskId, finding, uncertainty, source_reviewed:reviewed});
  return <form className="observation-link-form" aria-label={observation?'编辑阶段记录':'关联已有材料'} onChange={()=>onDirty(true)} onSubmit={e=>{e.preventDefault();submit(false);}}>
    <fieldset disabled={busy}>
      <legend>{observation?'编辑阶段记录':'把已有材料接到实践问题'}</legend>
      <div className="practice-form-grid">
        <label>关联问题<select aria-label="关联问题" ref={first} value={qid} onChange={e=>{setQid(e.target.value);setTaskId('');if(!observation)setMid('');}}>{s.questions.map(q=><option value={q.id} key={q.id}>{q.text}</option>)}</select></label>
        <label>对应行动<select aria-label="对应行动" value={taskId} onChange={e=>setTaskId(e.target.value)}><option value="">暂不关联行动</option>{project.tasks.filter(t=>s.task_links[t.id]===qid).map(t=><option key={t.id} value={t.id}>{t.action}</option>)}</select></label>
      </div>
      {observation ? <p className="compact-note">原始来源：{material?.name || '材料已移除，记录备注仍保留'}</p> : <label>已有材料<select aria-label="已有材料" value={mid} required onChange={e=>setMid(e.target.value)}><option value="">选择一份已保存材料</option>{project.materials.map(m=><option key={m.id} value={m.id} disabled={linked(m.id)}>{m.name}{linked(m.id)?' · 已关联':m.enabled===false?' · 已排除':''}</option>)}</select></label>}
      {material && <details className="observation-source" open><summary>核对原始记录 · {material.name}</summary><p className="compact-note">{material.source_role} · {material.collected_at || '时间未记录'}{material.context && ' · '+material.context}</p><pre>{material.text}</pre></details>}
      {material?.enabled===false && <p className="compact-note">这份材料已排除。建立关联不会将它纳入 AI 指导或报告初稿。</p>}
      {changed && <p className="practice-stale">原材料已修改。请对照当前原文调整发现；普通保存会保留“需重新核对”提示。</p>}
      <label>团队的阶段发现<textarea rows={3} maxLength={2000} value={finding} onChange={e=>setFinding(e.target.value)} placeholder="区分实际记录与团队的理解，可暂时留空。"/></label>
      <label>仍不确定什么<textarea rows={2} maxLength={2000} value={uncertainty} onChange={e=>setUncertainty(e.target.value)}/></label>
      <div className="observation-actions"><button className="primary" disabled={!mid || linked(mid)}>{observation?'保存阶段记录':'保存材料关联'}</button>{observation && changed && material && <button type="button" className="secondary" disabled={linked(mid)} onClick={()=>submit(true)}>保存并确认已核对原文</button>}<button type="button" className="text-button" onClick={onCancel}>取消</button></div>
      <p className="compact-note">保留原材料，不复制正文；保存发现不会自动完成行动或改变结论支持状态。</p>
    </fieldset>
  </form>;
}
