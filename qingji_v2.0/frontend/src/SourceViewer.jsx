import {useEffect, useMemo, useRef, useState} from "react";
import {IconSearch, IconX} from "@tabler/icons-react";
import "./source-viewer.css";

function searchParts(text, query) {
  if (!query.trim()) return [{text, hit:false}];
  const parts = [], lowered = text.toLocaleLowerCase(), needle = query.trim().toLocaleLowerCase();
  let cursor = 0, count = 0, found;
  while ((found = lowered.indexOf(needle, cursor)) >= 0 && count < 500) {
    if (found > cursor) parts.push({text:text.slice(cursor,found),hit:false});
    parts.push({text:text.slice(found,found+needle.length),hit:true});
    cursor = found + needle.length; count++;
  }
  if (cursor < text.length) parts.push({text:text.slice(cursor),hit:false});
  return parts;
}

export function SourceViewer({document, citation, snapshot=false, onClose}) {
  const panel = useRef(null), close = useRef(null), textArea = useRef(null);
  const [query, setQuery] = useState("");
  const characters = useMemo(() => Array.from(document.text), [document.text]);
  const quoteMatches = !citation.quote || characters.slice(citation.start,citation.end).join("") === citation.quote;
  const parts = useMemo(() => searchParts(document.text,query), [document.text,query]);
  const hitCount = parts.filter(p=>p.hit).length;
  function scrollToMark() {
    const area = textArea.current, mark = area?.querySelector("mark");
    if (!mark) return;
    const areaRect = area.getBoundingClientRect(), markRect = mark.getBoundingClientRect();
    // Move only the text viewport; scrollIntoView can also scroll the fixed dialog's ancestors.
    area.scrollTo({top:Math.max(0, area.scrollTop + markRect.top - areaRect.top - (area.clientHeight - markRect.height) / 2)});
  }
  useEffect(() => {
    const trigger = window.document.activeElement; close.current?.focus({preventScroll:true});
    scrollToMark();
    return () => trigger?.focus({preventScroll:true});
  }, []);
  useEffect(scrollToMark, [query]);
  function keys(event) {
    if(event.key==="Escape") {event.preventDefault();event.stopPropagation();onClose();}
    if(event.key!=="Tab")return;
    const nodes=[...panel.current.querySelectorAll('button:not(:disabled), input:not(:disabled), summary')];
    if(event.shiftKey&&window.document.activeElement===nodes[0]){event.preventDefault();nodes.at(-1)?.focus();}
    else if(!event.shiftKey&&window.document.activeElement===nodes.at(-1)){event.preventDefault();nodes[0]?.focus();}
  }
  return <div className="modal-backdrop" onClick={onClose}>
    <section ref={panel} className="source-modal source-viewer" role="dialog" aria-modal="true" aria-labelledby="source-title" onClick={e=>e.stopPropagation()} onKeyDown={keys}>
      <header><div><small>{snapshot?"审阅时的依据原文":"当前材料原文"}</small><h2 id="source-title">{document.name}</h2></div>
        <button ref={close} id="close-source" className="icon-button" aria-label="关闭依据原文" onClick={onClose}><IconX size={20}/></button></header>
      <div className="source-search"><IconSearch size={17}/><label className="sr-only" htmlFor="source-query">查找原文</label>
        <input id="source-query" value={query} onChange={e=>setQuery(e.target.value)} placeholder="查找原文…" maxLength={200}/>
        {query&&<span role="status">{hitCount===500?"至少500":hitCount}处</span>}
        {query&&<button className="text-button" onClick={()=>setQuery("")}>{citation.quote && quoteMatches ? "回到引文" : "清除"}</button>}
      </div>
      <details className="source-context"><summary>来源与采集场景</summary><dl><dt>来源类型</dt><dd>{document.source_role||"待确认"}</dd><dt>采集时间</dt><dd>{document.collected_at||"未记录"}</dd><dt>对象与场景</dt><dd>{document.context||"未记录"}</dd></dl></details>
      {!quoteMatches&&<p className="source-notice" role="alert">这份原文无法对应旧引文的位置，请查看该次检查记录。</p>}
      <div ref={textArea} className="source-text">{query?parts.map((p,i)=>p.hit?<mark key={i}>{p.text}</mark>:p.text):quoteMatches&&citation.quote?
        <>{characters.slice(0,citation.start).join("")}<mark>{citation.quote}</mark>{characters.slice(citation.end).join("")}</>:document.text}</div>
      {!!document.notes?.length&&<details className="source-read-notes"><summary>读取说明</summary>{document.notes.map((n,i)=><p key={i}>{n}</p>)}</details>}
    </section>
  </div>;
}
