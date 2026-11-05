import {useState} from 'react';

export function materialBudget(materials){
  const included=materials.filter(m=>m.enabled!==false);
  const chars=included.reduce((n,m)=>n+Array.from(m.text||'').length,0);
  return {count:included.length,chars,over:included.length>8||chars>48000};
}

export function MaterialScope({materials,lifecycle,onSelect,busy}){
  const [question,setQuestion]=useState('');
  const budget=materialBudget(materials);
  const ids=new Set((lifecycle?.observations||[]).filter(o=>o.question_id===question).map(o=>o.material_id));
  return <section className="material-scope-panel" aria-label="本轮 AI 材料范围">
    <strong>项目保存 {materials.length} / 100 份 · 本轮纳入 {budget.count} / 8 份</strong>
    <p className="compact-note">本轮材料 {budget.chars.toLocaleString()} / 48,000 字。保存与 AI 处理范围分开，范围调整后请保存；不会自动发起 AI。</p>
    {budget.over&&<p role="alert" className="inline-error">本轮范围超限，材料可以继续保存。请减少纳入数量或字数后再调用 AI，不必删除原始记录。</p>}
    {!!lifecycle?.questions?.length&&<div className="observation-actions"><label>按实践问题选择<select aria-label="选择本轮实践问题" value={question} disabled={busy} onChange={e=>setQuestion(e.target.value)}><option value="">选择问题</option>{lifecycle.questions.map(q=><option key={q.id} value={q.id}>{q.text}</option>)}</select></label><button className="secondary" type="button" disabled={busy||!question||!materials.some(m=>ids.has(m.id))} onClick={()=>onSelect(ids)}>仅纳入这个问题的材料</button></div>}
    <button className="text-button" type="button" disabled={busy||!budget.count} onClick={()=>onSelect(new Set())}>清空本轮纳入，保留全部材料</button>
  </section>;
}
