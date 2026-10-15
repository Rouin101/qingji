import {useEffect, useState} from "react";
import {FieldworkArt} from "./FieldworkArt.jsx";

export function ReviewStart({project, materials, busy, onUpload, onSave, onStart, onDraftChange}) {
  const [selected, setSelected] = useState("");
  const [text, setText] = useState("");
  useEffect(()=>{onDraftChange?.(!!text.trim());return()=>onDraftChange?.(false);},[text,onDraftChange]);
  const ready = !!project.report?.text?.trim();
  return <main className="project-main review-start">
    <header className="review-start-heading"><div><p className="entry-kicker">结论核验</p><h1>从一份报告开始</h1><p>确定要核验的正文，再用实践材料核对其中的结论。</p></div><FieldworkArt kind="archive"/></header>
    <section className="project-card review-start-card">
      {ready ? <><h2>{project.report.name || "待核验正文"}</h2><p>正文已保存，可以开始核验。</p><button className="primary" disabled={busy} onClick={onStart}>{busy ? "正在核验…" : "用 AI 核对当前资料"}</button></> : <>
        <h2>选择待核验的正文</h2>
        <button className="primary" disabled={busy} onClick={onUpload}>上传报告</button>
        {materials.length>0 && <div className="review-source-choice"><label htmlFor="review-source">或使用已保存的材料</label><select id="review-source" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">选择一份报告材料</option>{materials.filter(m=>m.text?.trim()).map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select><p>原材料保留，并从本轮依据中排除，避免报告为自身作证。</p><button className="secondary" disabled={busy||!selected} onClick={()=>{const m=materials.find(m=>m.id===selected);onSave({report:{...m,id:"report"},materials:materials.map(item=>item.id===selected?{...item,enabled:false}:item)});}}>用作待核验报告</button></div>}
        <details className="review-source-choice"><summary>粘贴正文或一句结论</summary><label htmlFor="review-draft">待核验正文</label><textarea id="review-draft" rows={6} value={text} onChange={e=>setText(e.target.value)}/><button className="secondary" disabled={busy||!text.trim()} onClick={async()=>{if(await onSave({report:{id:"report",name:"待核验正文",text:text.trim()}}))setText("");}}>保存正文</button></details>
      </>}
      <p className="processing-note">默认使用 AI。仅发送待核验正文和纳入的材料；核验失败不会标记为完成。</p>
    </section>
  </main>;
}
