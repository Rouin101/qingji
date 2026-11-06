import {useEffect,useRef,useState} from 'react';
import './backup-library.css';

export default function BackupLibrary({busy,onAction}){
  const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[search,setSearch]=useState('');
  const [data,setData]=useState({backups:[],total:0,page:0,page_size:20}),[selected,setSelected]=useState(null),[preview,setPreview]=useState(null);
  const [working,setWorking]=useState(false),[error,setError]=useState('');const sequence=useRef(0),lock=useRef(false);
  useEffect(()=>()=>{sequence.current++;},[]);
  async function read(url){const r=await fetch(url);const value=await r.json();if(!r.ok)throw new Error(value.error||'无法读取备份，请重试。');return value;}
  async function list(q=query,page=0){
    const seq=++sequence.current;setWorking(true);setError('');setSelected(null);setPreview(null);
    try{const value=await read('/api/backup-library?q='+encodeURIComponent(q)+'&page='+page);if(seq===sequence.current){setData(value);setSearch(q);}}
    catch(e){if(seq===sequence.current)setError(e.message);}finally{if(seq===sequence.current)setWorking(false);}
  }
  async function inspect(item){
    const seq=++sequence.current;setWorking(true);setError('');setSelected(item);setPreview(null);
    try{const value=await read('/api/backup-preview?id='+encodeURIComponent(item.project_id)+'&backup_id='+encodeURIComponent(item.id));if(seq===sequence.current)setPreview(value);}
    catch(e){if(seq===sequence.current)setError(e.message);}finally{if(seq===sequence.current)setWorking(false);}
  }
  async function act(action,item){
    if(lock.current||busy||working)return;
    if(action==='restore'&&!window.confirm('按这份备份恢复为独立副本？现有项目会保留，历史判断需重新复查。'))return;
    if(action==='delete'&&!window.confirm('删除这份本机备份？建议先下载留存，原项目和其他备份不会删除。'))return;
    lock.current=true;setWorking(true);setError('');
    try{await onAction(action,item);if(action==='delete')await list(search,0);}
    catch(e){setError(e.message);}finally{lock.current=false;setWorking(false);}
  }
  return <section className="backup-library" aria-label="本机备份库">
    <button className="text-button" aria-expanded={open} disabled={busy||working} onClick={()=>{setOpen(!open);if(!open)list();}}>本机备份库</button>
    {open&&<div>
      <p>查看所有项目已保存的本机备份。原项目不在列表中时，也可从这里恢复副本。</p>
      <p className="compact-note">这里显示主动保存过的备份；不是自动或异地备份，不包含未保存草稿与原上传文件。</p>
      <form className="backup-library-search" onSubmit={e=>{e.preventDefault();list(query,0);}}><label>搜索备份项目<input type="search" maxLength={200} value={query} onChange={e=>setQuery(e.target.value)}/></label><button className="secondary" disabled={busy||working}>搜索备份</button></form>
      {error&&<p role="alert">{error}</p>}{working&&<p role="status">正在处理备份…</p>}
      <p role="status">找到 {data.total} 份备份 · 第 {data.page+1} 页</p>
      {!working&&!data.backups.length&&<p>没有找到匹配的本机备份。可以在项目内保存备份，或从首页导入之前下载的项目包。</p>}
      <ul>{data.backups.map(item=><li key={item.id}><strong>{item.name}</strong><p>版本 {item.version} · {new Date(item.created_at).toLocaleString()} · {Math.max(1,Math.ceil(item.size/1024))} KB</p><div className="backup-library-actions"><button className="secondary" disabled={busy||working} onClick={()=>inspect(item)}>预览备份内容</button><button className="text-button" disabled={busy||working} onClick={()=>act('download',item)}>下载备份文件</button><button className="text-button" disabled={busy||working} onClick={()=>act('delete',item)}>删除这份备份</button></div>
      {selected?.id===item.id&&preview&&<section className="backup-library-preview" aria-label="备份内容预览"><h3>{preview.saved.name}</h3><p>保存于 {new Date(preview.exported_at).toLocaleString()} · 包版本 {preview.package_version}</p><p>{preview.saved.materials} 份材料 · {preview.saved.tasks} 项行动 · {preview.saved.observations} 条阶段记录 · {preview.saved.reviews} 次报告复核 · {preview.saved.analyses} 次阶段分析</p><p>报告：{preview.saved.report_name} · {preview.saved.report_chars} 字符</p>{preview.saved.questions.length>0&&<details><summary>备份中的实践问题</summary><ul>{preview.saved.questions.map((q,i)=><li key={i}>{q}</li>)}</ul></details>}
        {preview.current?<p>当前项目：{preview.current.name} · 版本 {preview.current.version} · {preview.current.materials} 份材料。恢复会另建副本。</p>:<p>{preview.availability==='unreadable'?'当前项目库暂不可读，请先下载备份留存；此处不会覆盖或修复工作库。':'当前项目库中没有原项目；这份备份仍可恢复为副本。'}</p>}
        <p className="compact-note">备份结构与完整性校验通过，不代表材料或历史判断已被认证。恢复后请重新检查处理范围并复查。</p><button className="primary" disabled={busy||working||preview.availability==='unreadable'} onClick={()=>act('restore',item)}>按此备份恢复副本</button>
      </section>}</li>)}</ul>
      <nav className="backup-library-actions" aria-label="备份分页"><button className="text-button" disabled={busy||working||data.page===0} onClick={()=>list(search,data.page-1)}>上一页备份</button><button className="text-button" disabled={busy||working||(data.page+1)*data.page_size>=data.total} onClick={()=>list(search,data.page+1)}>下一页备份</button></nav>
    </div>}
  </section>;
}
