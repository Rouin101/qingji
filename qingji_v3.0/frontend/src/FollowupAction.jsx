import {useEffect,useState,useRef} from 'react';
import {useLocalDraft,DraftRecovery} from './LocalDraft.jsx';
import {draftText} from './draft-storage.js';

export default function FollowupAction({project,origin,busy,onSave,onClose,onDirty}){
  const [fields,setFields]=useState({action_text:origin.text.length<=990?'进一步了解：'+origin.text:'',assignee_id:'',due_date:'',notes:'',source_version:project.version});
  const [saving,setSaving]=useState(false),[error,setError]=useState('');const lock=useRef(false),area=useRef(null);
  const backup=useLocalDraft({projectId:project.id,kind:'followup:'+origin.kind+':'+origin.question_id+':'+origin.text,version:fields.source_version,value:fields,dirty:true,onRestore:v=>setFields({action_text:draftText(v,'action_text','',1000),assignee_id:draftText(v,'assignee_id','',80),due_date:draftText(v,'due_date','',20),notes:draftText(v,'notes','',500),source_version:Number.isInteger(v.source_version)?v.source_version:0})});
  useEffect(()=>{onDirty(true);area.current?.focus();area.current?.scrollIntoView({block:'center'});const warn=e=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>{onDirty(false);window.removeEventListener('beforeunload',warn);};},[onDirty]);
  async function save(e){e.preventDefault();if(lock.current||busy)return;lock.current=true;setSaving(true);setError('');
    try{await onSave({...fields,origin});backup.clear();onClose();}catch(e){setError(e.message);}finally{lock.current=false;setSaving(false);}}
  function close(){if(window.confirm('放弃这份未保存的行动安排？')){backup.clear();onClose();}}
  return <form className="followup-action practice-record-form" aria-label="确认后续行动" onSubmit={save}>
    <h3>把疑问变成下一步行动</h3><p>关联问题：{project.lifecycle.questions.find(q=>q.id===origin.question_id)?.text}</p>
    <p className="compact-note">来源：{origin.kind==='analysis'?'AI 提出的待了解事项':'团队记录的疑问'}。请改写成可执行安排；创建任务不会解决疑问或形成新证据。</p>
    <DraftRecovery draft={backup} busy={busy||saving}/>
    <fieldset disabled={busy||saving}>
      <label>后续行动安排<textarea ref={area} required maxLength={1000} rows={3} value={fields.action_text} onChange={e=>setFields({...fields,action_text:e.target.value})}/></label>
      <label>行动负责人<select aria-label="行动负责人" value={fields.assignee_id} onChange={e=>setFields({...fields,assignee_id:e.target.value})}><option value="">未指派</option>{project.members.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
      <label>行动截止日期<input type="date" value={fields.due_date} onChange={e=>setFields({...fields,due_date:e.target.value})}/></label>
      <label>行动补充说明<textarea maxLength={500} rows={2} value={fields.notes} onChange={e=>setFields({...fields,notes:e.target.value})}/></label>
      <details><summary>保留的来源备注</summary><p>{origin.text}</p>{origin.citations.map((c,i)=><p key={i}>材料 {c.material_id} · 记录 {c.observation_id}{c.quote&&'：'+c.quote}</p>)}</details>
      {fields.source_version!==project.version&&<p role="alert">项目版本已变化，请先保留输入，重新核对来源后起草。</p>}
      {error&&<p role="alert">{error}</p>}
      <div className="question-actions"><button className="primary" disabled={fields.source_version!==project.version||!fields.action_text.trim()}>确认创建后续行动</button><button type="button" className="text-button" onClick={close}>放弃这份行动草稿</button></div>
    </fieldset>
  </form>;
}
