import {changedText} from "./review-state.js";
import {changedProjectFields} from "./project-state.js";

export function same(a,b) {
  if(a===b)return true;
  if(!a||!b||typeof a!=="object"||typeof b!=="object")return false;
  if(Array.isArray(a)!==Array.isArray(b))return false;
  const keys=Object.keys(a);
  return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&same(a[k],b[k]));
}

// A save from another window may change an unrelated field. Preserve both edits
// when they are independent; ask the author when the same value changed twice.
function merge(base,local,remote,path,conflicts,preferLocal=false) {
  if(same(local,base))return remote;
  if(same(remote,base)||same(local,remote))return local;
  const objects=[base,local,remote].every(v=>v&&typeof v==="object"&&!Array.isArray(v));
  if(objects){
    const value={};
    for(const key of new Set([...Object.keys(base),...Object.keys(local),...Object.keys(remote)])){
      const next=merge(base[key],local[key],remote[key],`${path}.${key}`,conflicts,preferLocal);
      if(next!==undefined)value[key]=next;
    }
    return value;
  }
  const keyed=[base,local,remote].every(v=>Array.isArray(v)&&v.every(i=>i&&typeof i.id==="string")&&new Set(v.map(i=>i.id)).size===v.length);
  if(keyed){
    const maps=[base,local,remote].map(a=>Object.fromEntries(a.map(i=>[i.id,i]))),result=[];
    for(const id of new Set([...remote.map(i=>i.id),...local.map(i=>i.id)])){
      const item=merge(maps[0][id],maps[1][id],maps[2][id],`${path}.${id}`,conflicts,preferLocal);
      if(item!==undefined)result.push(item);
    }
    return result;
  }
  conflicts.push(path);return preferLocal?local:remote;
}

export function reconcileProjectChanges(base,requested,remote,preferLocal=false) {
  const conflicts=[],merged={};
  const newResult=!same(base.result,remote.result);
  let localAuthorChanged=false;
  for(const key of Object.keys(requested)){
    if((key==="choices"||key==="manual_text")&&newResult&&!same(requested[key],base[key])){
      localAuthorChanged=true;continue;
    }
    // A report is one document. Combining its text and metadata from two authors
    // could hide an incorrect attribution, so a concurrent replacement is explicit.
    if(key==="report"&&!same(base.report,requested.report)&&!same(base.report,remote.report)&&!same(requested.report,remote.report)){
      conflicts.push("report");merged.report=preferLocal?requested.report:remote.report;
    }else merged[key]=merge(base[key],requested[key],remote[key],key,conflicts,preferLocal);
  }
  if(localAuthorChanged){
    conflicts.push("author_text");
    if(preferLocal){
      const choices=requested.choices??base.choices;
      merged.manual_text=requested.manual_text??changedText(base.result?.report?.text||base.report.text,base.result?.issues||[],choices);
      merged.choices={};
    }else{merged.manual_text=remote.manual_text;merged.choices=remote.choices;}
  }
  return {changes:changedProjectFields(remote,merged),conflicts:[...new Set(conflicts)]};
}
