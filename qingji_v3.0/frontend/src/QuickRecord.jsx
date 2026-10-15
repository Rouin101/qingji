import {useEffect, useRef, useState} from "react";
import {IconCheck, IconLoader2, IconX} from "@tabler/icons-react";
import "./record-dialog.css";

const sources = ["待确认", "受访者陈述", "工作人员说明", "现场观察", "正式记录", "团队分析"];

export function QuickRecord({onSave, onClose, busy, initial=null}) {
  const dialog = useRef(null);
  const titleInput = useRef(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submission = useRef(false);
  const form = useRef(null), baseline = useRef(""), continueButton = useRef(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  function formSnapshot() {
    return JSON.stringify([...new FormData(form.current).entries()]);
  }
  useEffect(() => {
    const trigger = document.activeElement;
    baseline.current = formSnapshot();
    titleInput.current?.focus();
    return () => trigger?.focus();
  }, []);
  useEffect(() => {if(confirmDiscard)continueButton.current?.focus();}, [confirmDiscard]);
  useEffect(() => {if(error&&!submitting)titleInput.current?.focus();}, [error,submitting]);
  function requestClose() {
    if(submitting||busy)return;
    if(formSnapshot()!==baseline.current)setConfirmDiscard(true);
    else onClose();
  }

  async function submit(event) {
    event.preventDefault();
    if (submission.current || busy) return;
    const form = new FormData(event.currentTarget);
    submission.current=true;setSubmitting(true); setError("");
    try {
      await onSave({id: initial?.id||"m" + crypto.randomUUID(), name: form.get("name").trim(),
        text: form.get("text"), source_role: form.get("source_role"),
        context: form.get("context").trim(), collected_at: form.get("collected_at"),
        tags: form.get("tags").split(/[，,、]/).map(s => s.trim()).filter(Boolean),
        notes: initial?[...new Set([...(initial.notes||[]),"由作者编辑读取后的文字；原文件未改动。"])]:[], enabled: initial?.enabled??true, consent_status: form.get("consent") ? "confirmed" : "unconfirmed"});
      onClose();
    } catch (e) { setError(e.message); }
    finally { submission.current=false;setSubmitting(false); }
  }

  function keys(event) {
    if (event.key === "Escape" && !submitting && !busy) {
      event.preventDefault();event.stopPropagation();
      if(confirmDiscard){setConfirmDiscard(false);titleInput.current?.focus();}
      else requestClose();
    }
    if (event.key !== "Tab") return;
    const nodes = [...dialog.current.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')];
    const first = nodes[0], last = nodes.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }

  return <div className="modal-backdrop" onClick={requestClose}>
    <section ref={dialog} className="record-dialog" role="dialog" aria-modal="true" aria-labelledby="record-title" onClick={e => e.stopPropagation()} onKeyDown={keys}>
      <header><div><span className="eyebrow">实践材料</span><h2 id="record-title">{initial?"编辑材料文字":"快速记录"}</h2></div>
        <button type="button" className="icon-button" aria-label="关闭快速记录" onClick={requestClose} disabled={busy || submitting}><IconX size={20}/></button>
      </header>
      {confirmDiscard&&<div className="record-discard" role="alert">
        <p>这份记录还未保存。</p><div><button ref={continueButton} type="button" className="secondary" onClick={()=>{setConfirmDiscard(false);titleInput.current?.focus();}}>继续填写</button><button type="button" className="text-button" onClick={onClose}>放弃草稿</button></div>
      </div>}
      <form ref={form} onSubmit={submit}>
        {error && <p className="form-error" role="alert">{error}</p>}
        <label>记录名称<input ref={titleInput} name="name" aria-label="记录名称" defaultValue={initial?.name||""} placeholder="例如：社区大厅访谈摘记" maxLength={200} required disabled={submitting}/></label>
        <label>记录内容<textarea name="text" aria-label="记录内容" defaultValue={initial?.text||""} placeholder="写下实际观察或受访者原话，区分记录与自己的分析。" rows={7} maxLength={48000} required disabled={submitting}/></label>
        <div className="record-fields"><label>来源类型<select name="source_role" aria-label="来源类型" defaultValue={initial?.source_role||"待确认"} disabled={submitting}>{sources.map(s => <option key={s}>{s}</option>)}</select></label>
          <label>采集时间<input name="collected_at" aria-label="采集时间" type={initial?"text":"date"} defaultValue={initial?.collected_at||""} maxLength={100} disabled={submitting}/></label></div>
        <details className="record-more"><summary>补充场景与标签</summary>
          <label>对象与采集场景<input name="context" aria-label="对象与采集场景" defaultValue={initial?.context||""} placeholder="地点、对象和记录方式" maxLength={1000} disabled={submitting}/></label>
          <label>标签<input name="tags" aria-label="标签" defaultValue={initial?.tags?.join("，")||""} placeholder="用逗号分隔，例如：访谈、数字服务" maxLength={320} disabled={submitting}/></label>
        </details>
        <label className="processing-choice"><input name="consent" type="checkbox" disabled={submitting}/>已获得本项目引用及所选 AI 处理授权</label>
        <div className="record-footer"><span>{initial?"修改后的材料需重新确认授权。":"保存不会自动调用AI。"}</span><button className="primary" disabled={busy || submitting}>
          {submitting ? <IconLoader2 size={18} className="spin"/> : <IconCheck size={18}/>}保存记录</button></div>
      </form>
    </section>
  </div>;
}
