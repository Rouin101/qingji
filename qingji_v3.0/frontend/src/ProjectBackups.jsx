import {useState} from 'react';
import './project-backups.css';

export default function ProjectBackups({onAction, busy, dirty}) {
  const [open,setOpen]=useState(false),[items,setItems]=useState([]),[working,setWorking]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  async function run(action, item) {
    if(working||busy)return;
    if(action==='restore'&&!window.confirm('将恢复为独立的交接副本，保留原项目。历史判断需重新复查。继续？'))return;
    if(action==='delete'&&!window.confirm('删除这份本机备份？原项目和其他备份会保留；建议先下载留存。'))return;
    setWorking(true);setError('');setMessage('');
    try {
      const data=await onAction(action,item);
      if(data?.backups)setItems(data.backups);
      if(action==='create')setMessage('已保存当前项目版本的本机备份。');
      if(action==='delete')setMessage('已删除这份本机备份。');
    } catch(e){setError(e.message);} finally{setWorking(false);}
  }
  return <section className="project-backups">
    <button className="text-button" aria-expanded={open} onClick={()=>{setOpen(!open);if(!open)run('list');}}>项目备份与恢复</button>
    {open&&<div>
      <p>保存已提交的材料、行动、记录关联与核验历史。恢复会创建独立副本。</p>
      <p className="muted">本机备份与项目库分开保存，但仍在同一设备。建议下载到其他位置；不包含未保存草稿、原上传文件或模型配置。</p>
      {dirty&&<p role="status">请先保存当前输入，再创建备份或恢复副本。</p>}
      <div className="backup-actions"><button className="secondary" disabled={busy||working||dirty} onClick={()=>run('create')}>保存当前版本备份</button><button className="text-button" disabled={busy||working} onClick={()=>run('list')}>刷新备份列表</button><span>{items.length} / 20 份</span></div>
      {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
      {!working&&!items.length&&<p>还没有本机备份。保存一份后，可以随时下载或恢复。</p>}
      {working&&<p role="status">正在处理备份…</p>}
      <ul>{items.map(item=><li key={item.id}><div><strong>{item.name}</strong><p>版本 {item.version} · {new Date(item.created_at).toLocaleString()} · {Math.max(1,Math.ceil(item.size/1024))} KB</p></div><div className="backup-actions"><button className="text-button" disabled={busy||working} onClick={()=>run('download',item)}>下载备份</button><button className="secondary" disabled={busy||working||dirty} onClick={()=>run('restore',item)}>恢复为副本</button><button className="text-button" disabled={busy||working} onClick={()=>run('delete',item)}>删除备份</button></div></li>)}</ul>
    </div>}
  </section>;
}
