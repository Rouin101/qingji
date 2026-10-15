import {useEffect, useRef, useState} from "react";
import {IconClipboardList, IconDownload, IconLoader2} from "@tabler/icons-react";
import "./practice-plan.css";

function blankRecordText(plan) {
  return [
    "# 青迹空白补证记录表",
    "空白模板·尚未采集",
    "本表的问题、观察与记录项目均待执行，不能作为已取得的依据。",
    "\n待核对原句", plan.issue_quote,
    "\n补证目标", plan.goal,
    "\n一、采集信息",
    "对象代号：[待填写]", "采集时间：[待填写]", "采集场景：[待填写]",
    "来源角色与记录出处：[待填写]", "记录人：[待填写]",
    "采集与引用授权：待确认 [待填写]", "AI 处理授权：待确认 [待填写]",
    "\n二、访谈问题",
    ...plan.questions.map((question, index) => `${index + 1}. ${question.question}\n核对目的：${question.purpose}\n答复原文：[待填写]\n未回应或无法判断：[待填写]`),
    "\n三、观察要点",
    ...plan.observations.map((observation, index) => `${index + 1}. ${observation}\n实际观察记录：[待填写]`),
    "\n四、记录字段",
    ...plan.record_fields.map(field => `${field}：[待填写]`),
    "\n五、限制与未知",
    ...plan.limits.map(limit => `待核对边界：${limit}`),
    "不同情况与尚未知的部分：[待填写]", "无法接触的对象或场景：[待填写]",
    "后续核对安排：[待填写]",
    "\n填写后可作为实践材料导回青迹；来源、授权及是否纳入核对仍需逐项确认。",
  ].join("\n\n");
}

export function PracticePlan({issue,plan,onGenerate,onCreateTask,generating,busy,aiSelected}) {
  const [action,setAction]=useState("");
  const [notes,setNotes]=useState("");
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [exporting,setExporting]=useState(false);
  const [exportError,setExportError]=useState("");
  const exportLock=useRef(false);
  useEffect(()=>{
    setAction(plan?.goal||"");setError("");setExportError("");
    setNotes(plan ? [
      "待执行的补证计划；尚未取得新依据。",
      ...plan.questions.map(q=>`提问：${q.question}\n目的：${q.purpose}`),
      ...plan.observations.map(v=>`观察：${v}`),
      `记录字段：${plan.record_fields.join("；")}`,
      ...plan.limits.map(v=>`边界：${v}`),
    ].join("\n\n") : "");
  },[plan]);
  async function exportBlankRecord() {
    if(!plan||busy||saving||exportLock.current)return;
    exportLock.current=true;setExporting(true);setExportError("");
    try {
      const name="青迹_空白补证记录表.docx", text=blankRecordText(plan);
      if(name.length>200||text.length>24000)throw new Error("空白记录表超过当前 Word 导出范围，请精简计划后重试；内容未被截断。");
      const response=await fetch("/api/export-docx", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,text})});
      if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"空白记录表未导出，请重试。");}
      const blob=await response.blob(),url=URL.createObjectURL(blob),anchor=document.createElement("a");
      anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    } catch(error) {
      setExportError(error.message||"空白记录表未导出，请重试。");
    } finally {exportLock.current=false;setExporting(false);}
  }
  async function submit(event) {
    event.preventDefault();if(saving||exporting||busy||!action.trim())return;
    setSaving(true);setError("");
    try {await onCreateTask({action:action.trim(),notes:notes.trim()});}
    catch(e){setError(e.message);}
    finally {setSaving(false);}
  }
  return <section className="practice-plan" aria-label="这条结论的补证计划">
    {!plan ? <button className="text-button plan-generate" onClick={()=>onGenerate(issue)} disabled={busy||generating}>
      {generating?<IconLoader2 className="spin" size={18}/>:<IconClipboardList size={18}/>}
      {generating?"正在整理补证计划…":aiSelected?"生成补证计划":"查看补证模板"}
    </button> : <details open className="plan-content">
      <summary>{plan.mode==="ai"?"AI 补证建议":"补证模板"}<span>待执行</span></summary>
      <p className="plan-notice">{plan.notice||"计划是待执行建议，不能当已有依据。"}</p>
      <div className="plan-sections">
        <details><summary>访谈问题 · {plan.questions.length}</summary><ol>{plan.questions.map((q,i)=><li key={i}><p>{q.question}</p><small>{q.purpose}</small></li>)}</ol></details>
        <details><summary>观察与记录</summary><ul>{plan.observations.map((v,i)=><li key={i}>{v}</li>)}</ul><p className="plan-fields">{plan.record_fields.join(" · ")}</p></details>
        <details><summary>仍需注意的边界</summary><ul>{plan.limits.map((v,i)=><li key={i}>{v}</li>)}</ul></details>
      </div>
      <div className="plan-export">
        <button className="text-button" type="button" onClick={exportBlankRecord} disabled={busy||saving||exporting}><IconDownload size={16}/>{exporting?"正在导出…":"导出空白记录表"}</button>
        <span>Word · 尚未采集</span>
      </div>
      {exportError&&<p className="inline-error" role="alert">{exportError}</p>}
      <form onSubmit={submit}>
        <label>行动名称<input aria-label="补证计划行动名称" value={action} maxLength={1000} onChange={e=>setAction(e.target.value)} disabled={busy||saving}/></label>
        <details><summary>编辑任务内容</summary><textarea aria-label="补证计划任务内容" value={notes} maxLength={3000} rows={8} onChange={e=>setNotes(e.target.value)} disabled={busy||saving}/><small>{notes.length}/3000</small>{notes.length>3000&&<p role="alert">内容超过任务上限，请精简到3000字再保存。</p>}</details>
        {error&&<p className="inline-error" role="alert">{error}</p>}
        <div className="plan-actions"><button className="outline-button" type="submit" disabled={busy||saving||exporting||!action.trim()||notes.length>3000}>{saving?"保存中…":"加入团队行动"}</button><span>保存后可分配负责人和日期</span></div>
      </form>
    </details>}
  </section>;
}
