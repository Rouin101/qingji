import {useEffect,useRef,useState} from 'react';

export function PracticeReport({project,busy,hasDraft,onCreate}){
  const [preview,setPreview]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const request=useRef(0);
  useEffect(()=>{request.current++;setPreview(null);setLoading(false);setError('');},[project.id,project.version]);
  useEffect(()=>()=>{request.current++;},[]);
  const existing=!!(project.report.text.trim()||project.manual_text||project.result);
  async function show(){
    const id=++request.current;setLoading(true);setError('');setPreview(null);
    try{
      const response=await fetch('/api/practice-report?id='+encodeURIComponent(project.id)+'&version='+project.version);
      const data=await response.json();if(!response.ok)throw new Error(data.error||'整理暂时失败，请重试。');
      if(id===request.current){if(data.version!==project.version)throw new Error('项目已更新，请重新整理。');setPreview(data);}
    }catch(e){if(id===request.current)setError(e.message);}
    finally{if(id===request.current)setLoading(false);}
  }
  function download(){
    const url=URL.createObjectURL(new Blob([preview.text],{type:'text/plain;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='青迹-实践整理稿.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <div className="practice-report-workspace">
    <div className="practice-report-bridge"><div><strong>把实践接到报告</strong><p>{existing?'按最新记录整理，供你补充现有报告。':'按问题整理记录与阶段发现，再继续撰写报告。'}</p></div><div className="observation-actions"><button className="secondary" disabled={busy||loading||hasDraft} onClick={show}>{loading?'正在整理…':'查看最新整理稿'}</button>{!existing&&<button className="secondary" disabled={busy||hasDraft} onClick={onCreate}>整理为报告初稿</button>}</div></div>
    {hasDraft&&<p className="compact-note">请先保存正在编辑的实践内容，再整理报告。</p>}
    {error&&<p role="alert" className="inline-error">{error}</p>}
    {preview&&<section className="practice-report-preview" aria-label="最新实践整理稿"><div className="practice-record-heading"><h3>最新实践整理稿</h3><div className="observation-actions"><button className="secondary" disabled={busy||hasDraft} onClick={download}>下载整理稿</button><button className="text-button" onClick={()=>setPreview(null)}>收起整理稿</button></div></div><p className="compact-note">来自已保存且纳入的关联记录；已有报告和复核结果保持原样。阶段发现仍需核对。</p><pre>{preview.text}</pre></section>}
  </div>;
}
