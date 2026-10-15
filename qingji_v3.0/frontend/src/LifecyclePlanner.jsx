import {useEffect, useState} from 'react';
import {IconArrowRight, IconCheck, IconPlus, IconCompass, IconNotes} from '@tabler/icons-react';
import './lifecycle.css';

const stages=[['prepare','出发前'],['field','实践中'],['report','整理与复核']];
const labels={topic:'实践主题',goal:'希望弄清楚什么',audience:'对象',location:'地点',timeframe:'时间安排',resources:'人员与现实条件'};
const fresh={topic:'',goal:'',audience:'',location:'',timeframe:'',resources:''};

function BriefForm({state,onSave,busy}){
  const [brief,setBrief]=useState(state?.brief||fresh);
  const [questions,setQuestions]=useState(state?.questions?.length?state.questions:[{id:'q'+crypto.randomUUID(),text:''}]);
  const [stage,setStage]=useState(state?.stage||'prepare');
  const linked=new Set([...Object.values(state?.task_links||{}),...(state?.observations||[]).map(o=>o.question_id)]);
  return <form className="practice-brief" onSubmit={e=>{e.preventDefault();onSave({brief,questions,stage});}}>
    <div className="practice-form-grid">{['topic','goal'].map(key=><label key={key} className="wide">{labels[key]}{key==='goal'?<textarea required maxLength={800} rows={2} value={brief[key]} onChange={e=>setBrief({...brief,[key]:e.target.value})}/>:<input required maxLength={800} value={brief[key]} onChange={e=>setBrief({...brief,[key]:e.target.value})}/>}</label>)}</div>
    <fieldset className="practice-question-fields"><legend>先带着哪些问题出发</legend><p className="compact-note">写开放的问题，给不同反馈留出空间。保留1至8个，可以继续调整。</p>{questions.map((q,i)=><div key={q.id}><label>实践问题 {i+1}<input value={q.text} required maxLength={400} placeholder="如：哪些操作环节容易遇到困难？" onChange={e=>setQuestions(questions.map(item=>item.id===q.id?{...item,text:e.target.value}:item))}/></label>{questions.length>1&&<button type="button" className="text-button" disabled={linked.has(q.id)} title={linked.has(q.id)?'已有行动或记录关联，可修改文字，保留关联':''} onClick={()=>setQuestions(questions.filter(item=>item.id!==q.id))}>移除</button>}</div>)}<button type="button" className="text-button" disabled={questions.length>=8||busy} onClick={()=>setQuestions([...questions,{id:'q'+crypto.randomUUID(),text:''}])}><IconPlus size={16}/>再加一个问题</button></fieldset>
    <details className="practice-optional"><summary>对象、地点与团队条件 <span>可后补</span></summary><div className="practice-form-grid">{['audience','location','timeframe','resources'].map(key=><label key={key}>{labels[key]}<input maxLength={800} value={brief[key]} placeholder="可以稍后补充" onChange={e=>setBrief({...brief,[key]:e.target.value})}/></label>)}</div></details>
    <label>目前进展<select aria-label="目前进展" value={stage} onChange={e=>setStage(e.target.value)}>{stages.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><button className="primary" disabled={busy}>保存方向与问题 <IconArrowRight size={17}/></button>
  </form>;
}

function ObservationForm({project,onSubmit,busy}){
  const s=project.lifecycle;const [qid,setQid]=useState(s.questions[0].id);
  return <form className="practice-record-form" onSubmit={e=>{e.preventDefault();const fields=new FormData(e.currentTarget);onSubmit(Object.fromEntries(fields));}}>
    <div className="practice-form-grid"><label>关联问题<select aria-label="关联问题" name="question_id" value={qid} onChange={e=>setQid(e.target.value)}>{s.questions.map(q=><option key={q.id} value={q.id}>{q.text}</option>)}</select></label><label>对应行动<select aria-label="对应行动" name="task_id" key={qid}><option value="">暂不关联行动</option>{project.tasks.filter(t=>s.task_links[t.id]===qid).map(t=><option key={t.id} value={t.id}>{t.action}</option>)}</select></label></div>
    <label>实际留下的原始记录<textarea name="text" rows={4} maxLength={12000} required placeholder="记录实际听到、看到的情况，保留不同反馈。"/></label>
    <div className="practice-form-grid"><label>来源类型<select aria-label="来源类型" name="source_role" defaultValue="受访者陈述">{['待确认','受访者陈述','工作人员说明','现场观察','正式记录','团队分析'].map(r=><option key={r}>{r}</option>)}</select></label><label>采集时间<input name="collected_at" type="date"/></label><label className="wide">对象与场景<input name="context" maxLength={1000} placeholder="如：某社区便民服务点，一次现场访谈"/></label></div>
    <label>团队的阶段发现<textarea name="finding" rows={2} maxLength={2000} placeholder="可以暂时留空，后续结合记录核对。"/></label><label>仍不确定什么<textarea name="uncertainty" rows={2} maxLength={2000} placeholder="哪些人、环节或不同情况还没了解？"/></label>
    <input type="hidden" name="consent_status" value="confirmed"/><button className="primary" disabled={busy}>保存实际记录</button><p className="compact-note">保存后进入实践材料；行动是否完成由团队另行确认。</p>
  </form>;
}

function ActionSuggestion({action,guide,onAdopt,disabled,onDirty}){
  const [text,setText]=useState(action.action);const adopted=guide.adopted[action.id];
  return <article className="practice-suggestion"><span className="practice-method">{action.method}</span><textarea aria-label={'行动安排 '+action.id.slice(1)} rows={2} value={text} maxLength={4000} onChange={e=>{setText(e.target.value);onDirty(e.target.value!==action.action);}} disabled={disabled||!!adopted}/><details><summary>为什么建议这样做</summary><p>{action.why}</p><p>执行时留下：{action.record_hint}</p><small>{action.basis_material_ids.length?`参考 ${action.basis_material_ids.length} 份纳入的关联材料`:'尚无关联材料；这是待执行的探索安排。'}</small></details><button className="secondary" disabled={disabled||!!adopted||!text.trim()} onClick={()=>onAdopt(action.id,text)}>{adopted?<><IconCheck size={16}/>已加入行动</>:'加入行动安排'}</button></article>;
}

export function LifecyclePlanner({project,onAction,busy,aiConfigured,onMaterials,section="guidance",onDraftChange}){
  const s=project.lifecycle, ready=!!s?.questions?.length;
  const [editing,setEditing]=useState(!ready),[recording,setRecording]=useState(false),[error,setError]=useState(''),[view,setView]=useState(null);
  const [dirty,setDirty]=useState({});
  const [recordVersion,setRecordVersion]=useState(0);
  const hasDraft=Object.values(dirty).some(Boolean);
  const mark=(key,value)=>setDirty(current=>({...current,[key]:value}));
  useEffect(()=>{onDraftChange?.(hasDraft);},[hasDraft,onDraftChange]);
  useEffect(()=>()=>onDraftChange?.(false),[onDraftChange]);
  useEffect(()=>{if(!hasDraft)return;const warn=e=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[hasDraft]);
  useEffect(()=>{let cancelled=false;setView(null);fetch('/api/practice?id='+encodeURIComponent(project.id)).then(r=>r.ok?r.json():Promise.reject()).then(data=>{if(!cancelled&&data.version===project.version)setView(data);}).catch(()=>{if(!cancelled)setError('暂时无法读取指导状态，请刷新项目后重试。');});return()=>{cancelled=true;};},[project.id,project.version]);
  async function act(action,values={}){if(action==='practice_guidance'&&Object.keys(dirty).some(k=>k.startsWith('suggestion:')&&dirty[k])&&!window.confirm('行动建议有未采纳的修改，更新建议会替换它们。继续更新？'))return null;setError('');try{const p=await onAction(action,values);if(action==='practice_guidance')setDirty(current=>Object.fromEntries(Object.entries(current).filter(([k])=>!k.startsWith('suggestion:'))));return p;}catch(e){setError(e.message);return null;}}
  const guide=s?.guidance, isCurrent=!!view?.guidance_current;
  return <section className="lifecycle-planner" aria-label="实践指导">
    {error&&<p className="inline-error" role="alert">{error}</p>}
    <div hidden={section!=="guidance"}>
    <div className="practice-section-heading"><div><p className="eyebrow"><IconCompass size={17}/>青迹 3.0 · 实践指导</p><h2>{ready?'沿着问题，推进这次实践':'从一个想法开始'}</h2></div>{ready&&<button className="text-button" onClick={()=>setEditing(!editing)} disabled={busy}>{editing?'收起':'调整方向'}</button>}</div>
    {ready&&<div className="practice-stages" aria-label="实践阶段">{stages.map(([id,label],i)=><span key={id} className={s.stage===id?'current':''} aria-current={s.stage===id?'step':undefined}><small>{i+1}</small>{label}</span>)}</div>}
    <div hidden={!editing} onChangeCapture={()=>mark('brief',true)}><BriefForm key={project.id} state={s} busy={busy} onSave={async values=>{if(await act('practice_brief',values)){mark('brief',false);setEditing(false);}}}/></div>
    <div hidden={editing}>{ready&&<>
      <p className="practice-goal">{s.brief.goal}</p><div className="practice-question-summary">{s.questions.map(q=>{const row=view?.questions.find(item=>item.id===q.id);return <div key={q.id}><strong>{q.text}</strong><small>{row?`${row.record_count} 条记录 · ${row.eligible_count} 条纳入 · ${row.done_count}/${row.task_count} 项行动完成`:'正在整理记录…'}</small></div>;})}</div>
      <div className="practice-next-heading"><h3>下一步怎么做</h3><button className="secondary" disabled={busy||!view} onClick={()=>act('practice_guidance',{mode:'ai',allow_external_processing:true})}>{busy?'正在处理…':guide?'更新下一步建议':'生成行动建议'}</button></div>
      {aiConfigured&&<details className="practice-processing"><summary>本次处理范围</summary><p>发送目标、问题、实践行动及已纳入的关联记录；不发送排除的材料、报告和团队讨论。普通手机号等会先遮盖。</p></details>}
      {guide&&<div className="practice-guidance"><span className="mode-pill">{guide.mode==='ai'?'AI实践建议':'本地行动模板'}</span><p>{guide.summary}</p>{view&&!isCurrent&&<p className="practice-stale" role="status">项目输入已变化或建议来自交接副本，请更新建议后再采纳。</p>}<div className="practice-suggestions">{guide.actions.map(a=><ActionSuggestion key={guide.id+a.id} action={a} guide={guide} disabled={busy||!isCurrent} onDirty={value=>mark('suggestion:'+a.id,value)} onAdopt={async(id,text)=>{if(await act('practice_adopt',{guidance_id:guide.id,action_id:id,action_text:text}))mark('suggestion:'+id,false);}}/>)}</div>{!guide.actions.length&&<p className="compact-note">先推进已有行动，再记录收获与困难，青迹会据此更新建议。</p>}<details className="practice-reference-hints"><summary>查找哪些材料 · 当前限制</summary>{guide.material_hints.map((h,i)=><p key={'h'+i}>{h}</p>)}{guide.limits.map((h,i)=><p key={'l'+i}>{h}</p>)}</details></div>}
      {!!s.guidance_history.length&&<details className="practice-guide-history"><summary>之前的 {s.guidance_history.length} 次建议</summary>{[...s.guidance_history].reverse().map(g=><article key={g.id}><small>{new Date(g.created_at).toLocaleString('zh-CN')} · {g.mode==='ai'?'AI实践建议':'本地行动模板'}</small><p>{g.summary}</p><ul>{g.actions.map(a=><li key={a.id}>{a.action}</li>)}</ul></article>)}</details>}
    </>}</div>
    </div>
    <div hidden={section!=="actions"}>
      {!ready&&<p className="compact-note">可以先安排实践任务；在实践指导中保存问题后，可记录关联发现。</p>}
      {ready&&<>
      <div className="practice-record-heading"><h3>实际发现了什么</h3><button className="text-button" disabled={busy} onClick={()=>setRecording(!recording)}><IconNotes size={16}/>{recording?'收起记录':'记下实际发现'}</button></div>
      <div hidden={!recording} onChangeCapture={()=>mark('record',true)}><ObservationForm key={recordVersion} project={project} busy={busy} onSubmit={async observation=>{if(await act('practice_observation',{observation})){mark('record',false);setRecording(false);setRecordVersion(v=>v+1);}}}/></div>
      {!s.observations.length&&!recording&&<p className="compact-note">保留实际经历、不同反馈和仍不确定的地方，指导会随记录更新。</p>}
      {s.observations.length>0&&<details className="practice-findings"><summary>查看 {s.observations.length} 条阶段记录</summary>{s.observations.map(o=><article key={o.id}><strong>{s.questions.find(q=>q.id===o.question_id)?.text}</strong><p>{o.finding||'尚未整理阶段发现。'}</p>{view?.changed_observations?.includes(o.id)&&<p className="practice-stale">关联材料已修改，阶段发现需重新核对。</p>}{o.uncertainty&&<p className="subtle">仍不确定：{o.uncertainty}</p>}<small>{project.materials.some(m=>m.id===o.material_id)?'原始记录保存在实践材料':'关联材料已移除，保留此处的记录备注。'}</small></article>)}<button className="text-button" onClick={onMaterials}>查看材料与来源 <IconArrowRight size={15}/></button></details>}
      <div className="practice-report-bridge"><div><strong>把实践接到报告</strong><p>按问题整理纳入的记录与团队发现，保留待撰写的结论和限制。</p></div><button className="secondary" disabled={busy||!!project.report.text.trim()||!!project.manual_text} onClick={()=>act('practice_report')}>{project.report.text.trim()?'报告已准备，可在项目概览核对':'整理为报告初稿'}</button></div>

    </>}
    </div>
  </section>;
}
