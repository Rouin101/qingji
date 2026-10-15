import {useEffect,useRef,useState} from "react";
import "./project-conflicts.css";

const labels={materials:"实践材料",choices:"作者取舍",manual_text:"正文编辑",reading_size:"阅读字号",name:"项目名称",description:"项目简介",report:"报告文件",author_text:"正文与结论取舍"};
export function ConflictDialog({conflict,onResolve,onBackup,busy}){
  const panel=useRef(null),first=useRef(null),[error,setError]=useState("");
  useEffect(()=>{const trigger=document.activeElement;first.current?.focus();return()=>trigger?.focus();},[]);
  const fields=[...new Set(conflict.paths.map(v=>labels[v.split(".")[0]]||"项目内容"))];
  async function resolve(preferLocal){setError("");try{await onResolve(preferLocal);}catch(e){setError(e.message);}}
  function trap(event){if(event.key!=="Tab")return;const nodes=[...panel.current.querySelectorAll("button:not(:disabled)")];if(event.shiftKey&&document.activeElement===nodes[0]){event.preventDefault();nodes.at(-1)?.focus();}else if(!event.shiftKey&&document.activeElement===nodes.at(-1)){event.preventDefault();nodes[0]?.focus();}}
  return <div className="modal-backdrop"><section className="conflict-dialog" role="dialog" aria-modal="true" aria-labelledby="conflict-title" ref={panel} onKeyDown={trap}>
    <h2 id="conflict-title">项目在另一个窗口更新了</h2><p>同时改动了{fields.join("、")}。本页未保存的内容仍在，请选择这些重叠改动使用哪个版本。</p>
    {conflict.paths.includes("author_text")&&<p className="conflict-note">结论记录已变化。保留本页正文时，会保存为待复查的编辑，不沿用旧结论的取舍。</p>}
    <p className="conflict-note">其他不冲突的改动会合并保留。</p>
    {error&&<p role="alert" className="inline-error">{error}</p>}
    <div className="conflict-actions"><button className="primary" ref={first} onClick={()=>resolve(true)} disabled={busy}>重叠部分保留本页</button><button className="outline-button" onClick={()=>resolve(false)} disabled={busy}>重叠部分使用最新</button></div>
    <button className="text-button" onClick={onBackup}>下载本页草稿</button>
  </section></div>;
}
