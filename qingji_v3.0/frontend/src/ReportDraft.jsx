import {useEffect,useState} from 'react';

export function ReportDraft({report,text,busy,onSave,onDirty}){
  const [draft,setDraft]=useState(text),[base,setBase]=useState(text),[error,setError]=useState('');
  const dirty=draft!==base;
  const changed=text!==base;
  useEffect(()=>{if(!dirty){setDraft(text);setBase(text);}},[text,dirty]);
  useEffect(()=>{onDirty(dirty);},[dirty,onDirty]);
  useEffect(()=>()=>onDirty(false),[onDirty]);
  useEffect(()=>{if(!dirty)return;const warn=e=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);
  function discard(){if(dirty&&!window.confirm('放弃尚未保存的报告修改，恢复当前已保存正文？'))return;setDraft(text);setBase(text);setError('');}
  async function save(e){
    e.preventDefault();if(busy||changed)return;setError('');
    try{if(await onSave({report:{...report,id:'report',name:report.name||'结论草稿',text:draft,notes:[]}})){setBase(draft);}else setError('未能保存，输入已保留，请处理页面提示后重试。');}
    catch{setError('未能保存，输入已保留，请重试。');}
  }
  return <details className="quick-claim"><summary>编辑报告正文或补充结论{dirty?' · 尚未保存':''}</summary>
    <form onSubmit={save}><label>待核对文字<textarea name="text" value={draft} onChange={e=>setDraft(e.target.value)} rows={8} maxLength={24000} required disabled={busy}/></label>
      <p className="compact-note">接续当前正文与已采纳改写；保存后需再次核对，历史复核记录保留。</p>
      {changed&&dirty&&<p role="alert" className="inline-error">已保存正文发生变化。请先复制保留本次输入，再恢复当前正文重新编辑。</p>}
      {error&&<p role="alert" className="inline-error">{error}</p>}
      <div className="observation-actions"><button className="secondary" disabled={busy||!dirty||changed||!draft.trim()}>保存待核对文字</button>{dirty&&<button type="button" className="text-button" disabled={busy} onClick={discard}>放弃本次修改</button>}</div>
    </form>
  </details>;
}
