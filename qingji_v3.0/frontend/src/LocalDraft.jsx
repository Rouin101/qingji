import {useEffect,useRef,useState} from 'react';
import {readDrafts,writeDraft,removeDraft} from './draft-storage.js';
import './local-draft.css';

export function useLocalDraft({projectId,kind,version,value,dirty,onRestore}){
  const writer=useRef(crypto.randomUUID()),own=useRef(null),restored=useRef(null),cleared=useRef(null);
  const [candidates,setCandidates]=useState([]),[error,setError]=useState(''),[saved,setSaved]=useState(false),[restoredVersion,setRestoredVersion]=useState(null);
  const serialized=JSON.stringify(value);
  function refresh(){try{setCandidates(projectId?readDrafts(localStorage,projectId,kind).filter(d=>d.key!==own.current?.key&&d.key!==restored.current?.key):[]);}catch{setError('浏览器无法读取草稿，请主动保存项目。');}}
  useEffect(()=>{own.current=null;restored.current=null;cleared.current=null;setSaved(false);refresh();const change=()=>refresh();window.addEventListener('storage',change);return()=>window.removeEventListener('storage',change);},[projectId,kind]);
  useEffect(()=>{
    if(!dirty){cleared.current=null;return;}
    if(!projectId||cleared.current===serialized)return;
    try{own.current=writeDraft(localStorage,projectId,kind,writer.current,own.current?.version??restored.current?.version??version,JSON.parse(serialized));setSaved(true);setError('');}
    catch{setSaved(false);setError('草稿未能备份到浏览器，请先保存项目，暂勿刷新或关闭。');}
  },[projectId,kind,version,serialized,dirty]);
  function clear(){cleared.current=serialized;setRestoredVersion(null);try{removeDraft(localStorage,own.current);removeDraft(localStorage,restored.current);own.current=null;restored.current=null;setSaved(false);refresh();}catch{setError('浏览器草稿未清除，请稍后重试。');}}
  function restore(item){if(dirty&&!window.confirm('当前表单还有未保存内容。用选中的备份替换当前输入？'))return;
    restored.current=item;setRestoredVersion(item.version);onRestore(item.value);setCandidates(items=>items.filter(d=>d.key!==item.key));
  }
  function discard(item){if(!window.confirm('删除这份浏览器草稿备份？已保存项目不受影响。'))return;try{removeDraft(localStorage,item);refresh();}catch{setError('草稿未能删除，请重试。');}}
  return {candidates,error,saved,version,restoredVersion,restore,discard,clear};
}

function preview(value){const text=value.text||value.finding||value.brief?.goal||value.name;return typeof text==='string'?text.slice(0,80):'表单输入备份';}
export function DraftRecovery({draft,busy}){
  return <div className="local-draft" aria-label="浏览器草稿备份">
    {draft.error&&<p className="inline-error" role="alert">{draft.error}</p>}
    {!!draft.candidates.length&&<details open><summary>发现 {draft.candidates.length} 份未保存草稿</summary>{draft.candidates.map(item=><div key={item.key} className="local-draft-choice"><p>{new Date(item.savedAt).toLocaleString('zh-CN')}{item.version!==draft.version?' · 项目版本已变化，恢复后请对照当前内容核对':''}</p><p>{preview(item.value)}</p><button type="button" className="secondary" disabled={busy} onClick={()=>draft.restore(item)}>恢复这份草稿</button><button type="button" className="text-button" disabled={busy} onClick={()=>draft.discard(item)}>删除这份备份</button></div>)}</details>}
    {draft.restoredVersion!==null&&draft.restoredVersion!==draft.version&&<p className="compact-note">已恢复旧版本草稿，请核对当前问题、行动与正文后再保存。</p>}
    {draft.saved&&<p className="compact-note" role="status">草稿已备份到此浏览器，尚未保存到项目。恢复不会自动调用 AI。</p>}
  </div>;
}
