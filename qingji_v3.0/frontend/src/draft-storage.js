const prefix='qingji-v3.draft.v1:';
export function draftPrefix(project,kind){return prefix+encodeURIComponent(project)+':'+encodeURIComponent(kind)+':';}
export function readDrafts(storage,project,kind){
  const start=draftPrefix(project,kind),items=[];
  for(let i=0;i<storage.length;i++){
    const key=storage.key(i);if(!key?.startsWith(start))continue;
    try{const raw=storage.getItem(key);if(!raw||raw.length>200000)continue;const d=JSON.parse(raw);
      if(d.schema===1&&d.project===project&&d.kind===kind&&Number.isInteger(d.version)&&typeof d.savedAt==='number'&&d.value&&typeof d.value==='object'&&!Array.isArray(d.value))items.push({...d,key});
    }catch{}
  }
  return items.sort((a,b)=>b.savedAt-a.savedAt);
}
export function writeDraft(storage,project,kind,writer,version,value){
  const key=draftPrefix(project,kind)+writer;
  const item={schema:1,project,kind,version,savedAt:Date.now(),value};const raw=JSON.stringify(item);
  if(raw.length>200000)throw new Error('草稿过大');storage.setItem(key,raw);return {...item,key};
}
export function removeDraft(storage,item){
  if(!item)return;
  // A recovered copy may still be edited in its original window.
  const raw=storage.getItem(item.key);if(!raw)return;
  try{const current=JSON.parse(raw);if(current.savedAt===item.savedAt&&JSON.stringify(current.value)===JSON.stringify(item.value))storage.removeItem(item.key);}catch{}
}
export function draftText(value,key,fallback='',limit=48000){return typeof value?.[key]==='string'?value[key].slice(0,limit):fallback;}
