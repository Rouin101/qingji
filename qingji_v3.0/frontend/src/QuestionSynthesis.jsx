import {candidateBlock} from './synthesis-draft.js';
import {useEffect,useRef,useState} from 'react';

export default function QuestionSynthesis({project,questionId,busy,hasDraft,onRecords,onCandidate}){
  const [result,setResult]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const sequence=useRef(0),controller=useRef(null);
  useEffect(()=>{sequence.current++;controller.current?.abort();setResult(null);setError('');setLoading(false);},[project.id,project.version,questionId]);
  useEffect(()=>()=>{sequence.current++;controller.current?.abort();},[]);
  const eligible=new Set(project.materials.filter(m=>m.enabled&&m.consent_status==='confirmed').map(m=>m.id));
  const count=new Set((project.lifecycle?.observations||[]).filter(o=>o.question_id===questionId&&eligible.has(o.material_id)).map(o=>o.material_id)).size;
  const labels={findings:'已有记录提示什么',differences:'哪些反馈不同',questions:'还需要了解什么'};
  async function generate(){
    const current=++sequence.current;controller.current?.abort();controller.current=new AbortController();setLoading(true);setError('');setResult(null);
    try{
      const response=await fetch('/api/question-synthesis',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,version:project.version,question_id:questionId}),signal:controller.current.signal});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'阶段分析暂时失败，请重试。');
      if(sequence.current===current){if(data.version!==project.version||data.question_id!==questionId)throw new Error('项目范围已变化，请重新生成。');setResult(data);}
    }catch(e){if(sequence.current===current&&e.name!=='AbortError')setError(e.message);}
    finally{if(sequence.current===current)setLoading(false);}
  }
  async function stage(group,item){
    setError('');
    try{await onCandidate(candidateBlock(project,result,group,item),result.version);}catch(e){setError(e.message);}
  }
  function download(){
    const lines=['青迹 · AI阶段分析候选',project.lifecycle.questions.find(q=>q.id===questionId)?.text,'尚未写入项目；引用存在不等于判断成立。',`项目版本：${result.version}`];
    for(const [key,label]of Object.entries(labels)){lines.push('',label);for(const item of result.analysis[key]){lines.push(item.text);for(const c of item.citations)lines.push(`来源 ${c.material_id} / 记录 ${c.observation_id}：${c.quote}`);}}
    lines.push('','限制',...result.analysis.limits);
    const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='青迹-阶段分析候选.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <section className="question-synthesis" aria-label="AI阶段分析">
    <h3>把记录放在一起看</h3>
    <p className="compact-note">仅发送这个问题的目标与 {count} 份纳入的关联材料、阶段发现和疑问。分析是待核对的理解，不自动写入报告。</p>
    <button className="secondary" disabled={busy||loading||hasDraft||!count} onClick={generate}>{loading?'正在分析记录…':'用 AI 整理阶段发现'}</button>
    {hasDraft&&<p role="status">请先保存当前输入，再分析已提交的记录。</p>}
    {!count&&<p>先为这个问题保存实际记录，或检查材料是否纳入。</p>}
    {error&&<p role="alert">{error}</p>}
    {result&&<div className="synthesis-result">
      <p className="compact-note">AI 候选理解 · 引文已核对是否存在，含义仍需人工核对。结果仅在本页面暂存，刷新或切换问题后清空，可先下载留存。</p>
      {result.changed_sources&&<p role="status">部分来源后来有修改，原阶段发现需重新核对。</p>}
      {Object.entries(labels).map(([key,label])=><details key={key} open><summary>{label}</summary>{!result.analysis[key].length&&<p>本次未形成有引用的条目，不代表没有其他情况。</p>}{result.analysis[key].map((item,i)=><article key={i}><p>{item.text}</p>{item.citations.map((c,j)=><blockquote key={j}><p>{c.quote}</p><button className="text-button" onClick={()=>onRecords({observationId:c.observation_id})}>核对原始记录</button></blockquote>)}<button className="secondary" disabled={busy||hasDraft} onClick={()=>stage(key,item)}>带入报告草稿</button></article>)}</details>)}
      <h4>本次分析的限制</h4><ul>{result.analysis.limits.map((x,i)=><li key={i}>{x}</li>)}</ul><button className="text-button" disabled={hasDraft||busy} onClick={download}>下载分析候选</button>
    </div>}
  </section>;
}
