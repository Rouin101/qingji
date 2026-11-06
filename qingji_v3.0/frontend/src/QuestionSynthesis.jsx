import {candidateBlock} from './synthesis-draft.js';
import {useEffect,useRef,useState} from 'react';

export default function QuestionSynthesis({project,questionId,busy,hasDraft,onRecords,onCandidate,onFollowup}){
  const [result,setResult]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const [history,setHistory]=useState([]),[historyBusy,setHistoryBusy]=useState(false);
  const sequence=useRef(0),controller=useRef(null);
  useEffect(()=>{sequence.current++;controller.current?.abort();setResult(null);setHistory([]);setError('');setLoading(false);loadHistory(true);},[project.id,project.version,questionId]);
  useEffect(()=>()=>{sequence.current++;controller.current?.abort();},[]);
  const eligible=new Set(project.materials.filter(m=>m.enabled&&m.consent_status==='confirmed').map(m=>m.id));
  const count=new Set((project.lifecycle?.observations||[]).filter(o=>o.question_id===questionId&&eligible.has(o.material_id)).map(o=>o.material_id)).size;
  const labels={findings:'已有记录提示什么',differences:'哪些反馈不同',questions:'还需要了解什么'};
  async function loadHistory(restore=false){
    const current=sequence.current;setHistoryBusy(true);
    try{const response=await fetch('/api/analyses?project_id='+encodeURIComponent(project.id)+'&id='+encodeURIComponent(project.id)+'&question_id='+encodeURIComponent(questionId));const data=await response.json();
      if(!response.ok)throw new Error(data.error||'无法读取分析历史。');
      if(current===sequence.current){if(data.version!==project.version)throw new Error('项目已更新，请重新打开后查看历史。');setHistory(data.history);if(restore)setResult(data.history[0]||null);}
    }catch(e){if(current===sequence.current)setError(e.message);}finally{if(current===sequence.current)setHistoryBusy(false);}
  }
  async function removeHistory(item){
    if(!window.confirm('删除这次分析及其来源快照？已有报告、行动和下载文件会保留。'))return;
    const current=sequence.current;setHistoryBusy(true);setError('');
    try{const response=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'analysis_delete',id:project.id,history_id:item.history_id})});const data=await response.json();if(!response.ok)throw new Error(data.error||'删除失败');
      if(current===sequence.current){if(result?.history_id===item.history_id)setResult(null);await loadHistory();}
    }catch(e){if(current===sequence.current)setError(e.message);}finally{if(current===sequence.current)setHistoryBusy(false);}
  }
  async function generate(){
    const current=++sequence.current;controller.current?.abort();controller.current=new AbortController();setLoading(true);setHistoryBusy(false);setError('');setResult(null);
    try{
      const response=await fetch('/api/question-synthesis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,version:project.version,question_id:questionId}),signal:controller.current.signal});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'阶段分析暂时失败，请重试。');
      if(sequence.current===current){if(data.version!==project.version||data.question_id!==questionId)throw new Error('项目范围已变化，请重新生成。');setResult(data);loadHistory();}
    }catch(e){if(sequence.current===current&&e.name!=='AbortError')setError(e.message);}
    finally{if(sequence.current===current)setLoading(false);}
  }
  async function stage(group,item){
    setError('');
    try{await onCandidate(candidateBlock(project,result,group,item),result.version);}catch(e){setError(e.message);}
  }
  function download(){
    const lines=['青迹 · AI阶段分析候选',project.lifecycle.questions.find(q=>q.id===questionId)?.text,'已保存为分析历史，尚未采纳为报告结论；引用存在不等于判断成立。',result.current===false?'历史范围已变化或为导入副本，请重新生成。':'当前来源范围',result.source_question||'',`项目版本：${result.version}`];
    for(const [key,label]of Object.entries(labels)){lines.push('',label);for(const item of result.analysis[key]){lines.push(item.text);for(const c of item.citations)lines.push(`来源 ${c.material_id} / 记录 ${c.observation_id}：${c.quote}`);}}
    lines.push('','限制',...result.analysis.limits);
    const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='青迹-阶段分析候选.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <section className="question-synthesis" aria-label="AI阶段分析">
    <h3>把记录放在一起看</h3>
    <p className="compact-note">仅发送这个问题的目标与 {count} 份纳入的关联材料、阶段发现和疑问。分析是待核对的理解，不自动写入报告。</p>
    <button className="secondary" disabled={busy||loading||historyBusy||hasDraft||!count} onClick={generate}>{loading?'正在分析记录…':'用 AI 整理阶段发现'}</button>
    {hasDraft&&<p role="status">请先保存当前输入，再分析已提交的记录。</p>}
    {!count&&<p>先为这个问题保存实际记录，或检查材料是否纳入。</p>}
    {error&&<p role="alert">{error}</p>}
    <details className="synthesis-history"><summary>分析历史 · {history.length} 次</summary><p className="compact-note">每项目最多保留 20 次分析。下载留存后可删除指定历史；旧版本应用不能导入包含分析历史的新项目包。</p>
      <button className="text-button" disabled={historyBusy||loading||busy} onClick={()=>loadHistory()}>刷新分析历史</button>
      {history.map(item=><div key={item.history_id}><p>{new Date(item.created_at).toLocaleString()} · 来源版本 {item.source_version} · {item.imported?'外部历史，未在本机复核':item.current?'来源范围未变化':'来源范围已变化'}</p><button className="text-button" disabled={loading||historyBusy} onClick={()=>setResult(item)}>查看这次分析</button><button className="text-button" disabled={busy||loading||historyBusy} onClick={()=>removeHistory(item)}>删除这次分析</button></div>)}
    </details>
    {result&&<div className="synthesis-result">
      <p className="compact-note">AI 候选理解 · 引文已核对是否存在，含义仍需人工核对。成功分析已保存在本机历史中，可随项目包和备份保留。</p>
      {result.current===false&&<p role="status">这份分析的来源范围已变化，或来自交接副本；仅供回看，请重新生成后再带入报告或安排新行动。</p>}
      {result.source_records&&<details><summary>查看分析时的来源快照</summary><p>{result.source_question}</p>{result.source_records.map(r=><article key={r.observation_id}><strong>{r.name}</strong><p>{r.text}</p></article>)}</details>}
      {result.changed_sources&&<p role="status">部分来源后来有修改，原阶段发现需重新核对。</p>}
      {Object.entries(labels).map(([key,label])=><details key={key} open><summary>{label}</summary>{!result.analysis[key].length&&<p>本次未形成有引用的条目，不代表没有其他情况。</p>}{result.analysis[key].map((item,i)=><article key={i}><p>{item.text}</p>{item.citations.map((c,j)=><blockquote key={j}><p>{c.quote}</p><button className="text-button" onClick={()=>onRecords({observationId:c.observation_id})}>核对原始记录</button></blockquote>)}<button className="secondary" disabled={busy||hasDraft||result.current===false} onClick={()=>stage(key,item)}>带入报告草稿</button>{key==='questions'&&<button className="text-button" disabled={busy||hasDraft||result.current===false} onClick={()=>onFollowup({kind:"analysis",question_id:questionId,text:item.text,citations:item.citations})}>据此起草后续行动</button>}</article>)}</details>)}
      <h4>本次分析的限制</h4><ul>{result.analysis.limits.map((x,i)=><li key={i}>{x}</li>)}</ul><button className="text-button" disabled={hasDraft||busy} onClick={download}>下载分析候选</button>
    </div>}
  </section>;
}
