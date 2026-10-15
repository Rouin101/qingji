import {useRef,useState} from "react";
import {IconClipboardCheck, IconDownload, IconLoader2, IconRefresh} from "@tabler/icons-react";
import {downloadText} from "./review-state.js";
import "./delivery-check.css";

export function DeliveryCheck({version,hasEdits,busy,onCheck,onNavigate}) {
  const [data,setData]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const active=useRef(false);
  const stale=!!data&&(data.check.version!==version||hasEdits);
  async function load() {
    if(active.current||busy)return;
    active.current=true;
    setLoading(true);setError("");
    try {setData(await onCheck());}
    catch(e){setError(e.message||"暂时无法整理交付状态，请重试。");}
    finally{active.current=false;setLoading(false);}
  }
  return <details className="delivery-check surface-disclosure" onToggle={event=>{
    if(event.currentTarget.open&&(!data||stale))load();
  }}>
    <summary><span><IconClipboardCheck size={18}/>交付前检查</span><small>{loading?"正在整理…":stale?"内容已变化":data?`${data.check.counts.attention_items}项待查看`:"核对范围与遗留事项"}</small></summary>
    <div className="delivery-body">
      {error&&<p role="alert" className="inline-error">{error}</p>}
      {loading&&<p className="delivery-loading"><IconLoader2 size={17} className="spin"/>正在整理已保存的项目状态…</p>}
      {stale&&<p className="delivery-stale">项目内容已变化，下面是上次整理的状态。</p>}
      {data&&<>
        <div className="delivery-scope"><strong>{data.check.review.label}</strong><span>{data.check.review.current?"对应当前保存内容":"尚未核对或需复查"}</span></div>
        <p className="delivery-material-scope">已保存{data.check.materials.total}份材料 · 当前准备纳入{data.check.materials.eligible_current}份
          {data.check.review.last_used_material_count===null?" · 上次纳入范围未记录":` · 上次核对纳入${data.check.review.last_used_material_count}份`}</p>
        <p className="compact-note">{data.check.notice}</p>
        {!data.check.review.current&&<p className="delivery-stale">以下判断和作者选择属于已保存记录，需复查后再用于当前正文。</p>}
        <div className="delivery-sections">{data.check.sections.map(section=><details key={section.id} className="delivery-section">
          <summary>{section.title}<span>{section.items.length}</span></summary>
          {section.items.length?<><ul>{section.items.map((item,index)=><li key={index}><p>{item.label}</p>{item.detail&&<small>{item.detail}</small>}</li>)}</ul>
            <button className="text-button" type="button" disabled={busy||loading} onClick={()=>onNavigate(section.target)}>去查看</button></>:
            <p className="compact-note">当前没有此类待处理项。</p>}
        </details>)}</div>
      </>}
      <div className="delivery-actions"><button className="secondary" type="button" disabled={busy||loading} onClick={load}><IconRefresh size={16}/>更新检查</button>
        {data&&<button className="text-button" type="button" disabled={busy||loading||stale} onClick={()=>downloadText(`${data.check.project_name}_交付前检查.md`,data.markdown,"text/markdown;charset=utf-8")}><IconDownload size={16}/>下载核对摘要</button>}
      </div>
    </div>
  </details>;
}
