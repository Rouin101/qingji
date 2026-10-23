import {ReviewStart} from "./ReviewStart.jsx";
import {FieldworkArt} from "./FieldworkArt.jsx";
import {useEffect, useMemo, useRef, useState} from "react";
import {IconArrowLeft, IconArrowUpRight, IconCheck, IconChevronDown, IconChevronUp,
  IconFileText, IconFileUpload, IconHelpCircle, IconLoader2, IconMessageCircle,
  IconPencil, IconPlus, IconRefresh, IconSend, IconUpload, IconX} from "@tabler/icons-react";
import {changedText, downloadText, highlightedLines} from "./review-state.js";
import {ProjectSidebar, ProjectCards, ProjectOverview, MaterialsPanel, supportLabels, taskLabels} from "./ProjectPanels.jsx";
import {editableProjectState, changedProjectFields} from "./project-state.js";
import {QuickRecord} from "./QuickRecord.jsx";
import {SourceViewer} from "./SourceViewer.jsx";
import {CommentThread} from "./TeamPanel.jsx";
import {PracticePlan} from "./PracticePlan.jsx";
import {reconcileProjectChanges} from "./project-conflicts.js";
import {ConflictDialog} from "./ConflictDialog.jsx";
import {DeliveryCheck} from "./DeliveryCheck.jsx";
import {ExportMenu} from "./ExportMenu.jsx";
import {isImportedUnverified} from "./export-status-helpers.js";
import {ReviewToolbar} from "./ReviewToolbar.jsx";
import {filterIssues, getNavPosition, computeFilterCounts, isIssueVisible, reconcileIssueSelection} from "./review-filter-helpers.js";
import {matchTaskIssue} from "./evidence-feedback-helpers.js";
import "./export-menu.css";
import "./review-toolbar.css";

const Icon = ({as: Component, ...props}) => <Component size={20} stroke={1.65} aria-hidden="true" {...props}/>;
const titles = {"范围外推": "结论范围与访谈样本需要核对", "成效依据": "活动完成与成效需要区分", "数字口径": "统计对象与数字口径需要核对", "来源表述": "观点来源与事实判断需要区分", "其他": "这处表述需要进一步核对"};

async function request(path, body) {
  let response;
  try {
    response = await fetch(path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  } catch { throw new Error("暂时无法连接检查服务，请稍后重试。"); }
  const data = await response.json().catch(() => ({error: "服务没有返回完整结果，请重试。"}));
  if (!response.ok) {const error=new Error(data.error || "本次处理未完成，请重试。");error.status=response.status;throw error;}
  return data;
}

async function readFile(file) {
  if (file.size > 5 * 1024 * 1024) throw new Error("单个文件请控制在5 MB以内。");
  if (!/\.(docx|pdf|txt|md)$/i.test(file.name)) throw new Error("当前支持 DOCX、文字PDF、TXT 和 Markdown，也可以直接粘贴文字。");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return request("/api/document", {name: file.name, content: btoa(binary)});
}

export function App() {
  const [reportRequest,setReportRequest] = useState(null);
  const [practiceDraft, setPracticeDraft] = useState(false);
  const mayLeavePractice = () => !practiceDraft || window.confirm("还有未保存的报告或实践内容。离开将丢失这些输入，确定离开？");
  const [screen, setScreen] = useState("home");
  const [project, setProject] = useState(null);
  const [projects, setProjects] = useState([]);
  const [revision, setRevision] = useState(null);
  const [revisionLoading, setRevisionLoading] = useState(false);
  const revisionRequest = useRef(0);
  const [saving, setSaving] = useState(false);
  const [actorId, setActorId] = useState("");
  const [quickRecordOpen, setQuickRecordOpen] = useState(false);
  const [recordToEdit,setRecordToEdit] = useState(null);
  const [exporting,setExporting] = useState(false);
  const mutationOperation=useRef(false);
  const latestWorkingState=useRef(null);
  const [practicePlan, setPracticePlan] = useState(null);
  const [planningIssue, setPlanningIssue] = useState(null);
  const [conflict,setConflict] = useState(null);
  const conflictRef = useRef(null);
  const planOperation = useRef(false);
  const projectRef = useRef(null);
  const projectQueue = useRef(Promise.resolve());
  const savedState = useRef("");
  const supplementTarget = useRef(null);
  const supplementInput = useRef(null);
  const [readingSize, setReadingSize] = useState(16);
  const [status, setStatus] = useState(null);
  const [report, setReport] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [paste, setPaste] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  const allowAI = true;
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reviewSeconds, setReviewSeconds] = useState(0);
  const [focusMaterial, setFocusMaterial] = useState(null);
  const operationRef = useRef(false);
  const chatOperationRef = useRef(false);
  const reviewConsent = useRef(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [activeId, setActiveId] = useState(null);
  const [choices, setChoices] = useState({});
  const [tab, setTab] = useState("feedback");
  const [mobilePane, setMobilePane] = useState("feedback");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [recoverableDraft,setRecoverableDraft] = useState(null);
  const [manualText, setManualText] = useState(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [citation, setCitation] = useState(null);
  const [question, setQuestion] = useState("");
  const [chat, setChat] = useState([]);
  const [chatBusy, setChatBusy] = useState(false);
  const editingRef = useRef(false);
  editingRef.current = editing;
  const draftRef = useRef("");
  draftRef.current = draft;
  const exportOpenRef = useRef(false);
  exportOpenRef.current = exportOpen;
  const exportSessionRef = useRef(0);
  const deliveryReqSeqRef = useRef(0);
  const exportWrapRef = useRef(null);
  const exportButtonRef = useRef(null);
  const reportInput = useRef(null);
  const materialsInput = useRef(null);
  const packageInput = useRef(null);
  const [issueFilter, setIssueFilter] = useState("all");
  const [taskCandidates, setTaskCandidates] = useState([]);
  const visibleIssues = useMemo(() => {
    return filterIssues(result?.issues || [], issueFilter, choices);
  }, [result?.issues, issueFilter, choices]);
  const previousVisibleIssues = useRef(visibleIssues);
  const lastLocated = useRef(null);
  useEffect(() => {
    const next = reconcileIssueSelection(previousVisibleIssues.current, visibleIssues, activeId);
    previousVisibleIssues.current = visibleIssues;
    if (next !== activeId) {
      setActiveId(next);
      if (next === null) setQuestion("");
    }
  }, [visibleIssues, activeId]);
  useEffect(() => {
    if (screen !== "review" || tab !== "feedback" || !activeId) {
      lastLocated.current = null;
      return;
    }
    if (!visibleIssues.some(i => i.id === activeId)) return;
    const identity = `${project?.id}:${activeId}:${mobilePane}`;
    if (lastLocated.current === identity) return;
    const frame = requestAnimationFrame(() => {
      const card = document.getElementById(`issue-${activeId}`);
      if (!card || !card.getClientRects().length) return;
      lastLocated.current = identity;
      const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
      const mark = document.getElementById(`mark-${activeId}`);
      if (mark?.getClientRects().length) mark.scrollIntoView({behavior, block: "center"});
      const pane = card.closest(".feedback-scroll");
      const header = card.querySelector(".issue-header");
      const bounds = pane.getBoundingClientRect(), target = header.getBoundingClientRect();
      const toolbarHeight = pane.querySelector(".review-toolbar")?.getBoundingClientRect().height || 0;
      if (target.top < bounds.top + toolbarHeight + 12 || target.bottom > bounds.bottom) {
        pane.scrollTo({top: pane.scrollTop + target.top - bounds.top - toolbarHeight - 12, behavior});
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [screen, tab, project?.id, activeId, visibleIssues, mobilePane]);
  const navInfo = useMemo(() => {
    return getNavPosition(visibleIssues, activeId);
  }, [visibleIssues, activeId]);
  const filterCounts = useMemo(() => {
    return computeFilterCounts(result?.issues || [], choices);
  }, [result?.issues, choices]);

  const selectedIssue = result?.issues.find((issue) => issue.id === activeId);
  const displayText = useMemo(() => !result ? "" : manualText ?? changedText(result.report.text, result.issues, choices), [result, choices, manualText]);
  const hasEdits = !!result && displayText !== result.report.text;
  const currentReport = result ? {...result.report, text: displayText} : report;
  const actorName = project?.members?.find(m=>m.id===actorId)?.name || "";
  const reportName = (result?.report.name || report?.name || "社会实践报告").replace(/\.(docx|pdf|txt|md)$/i, "");

  useEffect(() => { request("/api/status").then(setStatus).catch((e) => setError(e.message)); }, []);
  useEffect(() => { request("/api/projects").then(data=>setProjects(data.projects)).catch(e=>setError(e.message)); }, []);
  useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(""), 3500); return () => clearTimeout(timer); }, [toast]);
  useEffect(()=>{
    if(!reviewing)return;
    const started=Date.now();setReviewSeconds(0);
    const timer=setInterval(()=>setReviewSeconds(Math.floor((Date.now()-started)/1000)),1000);
    return ()=>clearInterval(timer);
  },[reviewing]);
  useEffect(()=>{
    if(screen!=="materials"||!focusMaterial)return;
    const card=document.getElementById(`material-${focusMaterial}`);
    if(card){const details=card.querySelector(".material-source-details");if(details)details.open=true;card.scrollIntoView({block:"center"});card.querySelector("select")?.focus();setFocusMaterial(null);}
  },[screen,focusMaterial,materials]);
  useEffect(() => {
    const onEscape = (event) => {
      if (event.key === "Escape") {
        setCitation(null);
        if (exportOpen) {
          setExportOpen(false);
          exportButtonRef.current?.focus();
        }
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [exportOpen]);
  useEffect(() => {
    if (!exportOpen) return;
    function handlePointer(event) {
      if (exportWrapRef.current && !exportWrapRef.current.contains(event.target)) {
        setExportOpen(false);
      }
    }
    document.addEventListener("pointerdown", handlePointer);
    return () => document.removeEventListener("pointerdown", handlePointer);
  }, [exportOpen]);
  function workingState() {
    return {choices:Object.fromEntries(Object.entries(choices).filter(([,v])=>v)),manual_text:manualText,reading_size:readingSize,materials};
  }
  latestWorkingState.current=workingState();

  function keepProject(p) {projectRef.current=p;setProject(p);}

  function cacheEditorDraft(text){
    setDraft(text);
    const p=projectRef.current;if(!p)return;
    try{sessionStorage.setItem(`qingji-v3.editor.${p.id}`,JSON.stringify({text,base_version:p.version,saved_at:new Date().toISOString()}));}
    catch{setToast("浏览器暂时无法保留草稿，请完成正文保存后再刷新。");}
  }

  function clearEditorDraft(id=projectRef.current?.id){
    if(id)try{sessionStorage.removeItem(`qingji-v3.editor.${id}`);}catch{}
    setRecoverableDraft(null);
  }

  async function projectAction(action, values={}) {
    const id=projectRef.current?.id;
    const pending=projectQueue.current.then(async()=>{
      if (!id || projectRef.current?.id!==id) throw new Error("项目已切换，请在当前项目继续操作。");
      if(conflictRef.current)throw new Error("先处理另一个窗口的改动，本页内容仍保留。");
      const base=projectRef.current;
      let payload=values;
      if(action==="save"){
        const changes=changedProjectFields(projectRef.current,values.changes);
        if(!Object.keys(changes).length)return projectRef.current;
        payload={...values,changes};
      }
      if(action==="save")setSaving(true);
      try {
        let p;
        try {p=await request("/api/projects",{action,id,version:base.version,actor:actorName,...payload});}
        catch(e){
          if(e.status!==409)throw e;
          const remote=await request(`/api/project?id=${encodeURIComponent(id)}`);
          if(action==="save"){
            const merged=reconcileProjectChanges(base,payload.changes,remote);
            if(!merged.conflicts.length){
              p=Object.keys(merged.changes).length?await request("/api/projects",{action,id,version:remote.version,actor:actorName,changes:merged.changes}):remote;
              const submitted={...base,...values.changes};
              const later=reconcileProjectChanges(submitted,latestWorkingState.current,p);
              if(later.conflicts.length){
                const state={base:submitted,requested:latestWorkingState.current,remote:p,paths:later.conflicts};
                keepProject(p);conflictRef.current=state;setConflict(state);
                throw new Error("保存期间又有重叠编辑，本页更晚的改动仍保留。");
              }
              const view={...p,...later.changes};
              setMaterials(view.materials);setChoices(view.choices);setManualText(view.manual_text);setReadingSize(view.reading_size);setReport(p.report);setResult(p.result);
              setToast("已合并另一个窗口的独立改动");
            }else{
              const state={base,requested:payload.changes,remote,paths:merged.conflicts};
              conflictRef.current=state;setConflict(state);throw new Error("项目有重叠改动，请选择保留的版本。");
            }
          }else{
            const state={base,requested:{},remote,paths:["project"]};
            conflictRef.current=state;setConflict(state);throw new Error("项目已更新，先载入最新内容再继续操作。");
          }
        }
        keepProject(p);return p;
      }
      finally {if(action==="save")setSaving(false);}
    });
    projectQueue.current=pending.catch(()=>{});
    return pending;
  }

  async function persist(changes={}) {
    if (!projectRef.current) return null;
    const state={...workingState(),...changes};
    const p=await projectAction("save",{changes:state});
    savedState.current=JSON.stringify(editableProjectState(p));
    return p;
  }

  async function flushEdits() {
    if(!editing)return persist();
    const p=await persist({manual_text:draft,choices:{}});
    setManualText(draft);setChoices({});setEditing(false);clearEditorDraft(p.id);
    return p;
  }

  function acceptProject(p, destination="project", options={}) {
    keepProject(p);setReport(p.report);setMaterials(p.materials.map(m=>({...m,consent_status:"confirmed"})));setResult(p.result);
    setChoices(p.choices);setManualText(p.manual_text);setReadingSize(p.reading_size);
    setActiveId(p.result?.issues[0]?.id??null);setEditing(false);setDraft("");
    setTaskCandidates([]);
    if(!options.preserveTab){setTab("feedback");setChat([]);}
    setRevision(null);
    revisionRequest.current += 1; setRevisionLoading(false);
    setShowPaste(false);setPaste("");setError("");setScreen(destination==="review"&&!p.result?"review-start":destination);
    setPracticePlan(null);
    let cached=null;
    try{const saved=JSON.parse(sessionStorage.getItem(`qingji-v3.editor.${p.id}`)||"null");
      const shown=p.manual_text??changedText(p.result?.report.text||p.report.text,p.result?.issues||[],p.choices);
      if(saved&&typeof saved.text==="string"&&saved.text.length<=24000&&saved.text!==shown)cached=saved;
      else if(saved)sessionStorage.removeItem(`qingji-v3.editor.${p.id}`);
    }catch{}
    setRecoverableDraft(cached);
    try {setActorId(localStorage.getItem(`qingji-v3.actor.${p.id}`)||"");}catch {setActorId("");}
    savedState.current=JSON.stringify(editableProjectState(p));
  }

  async function recoverEditor(){
    if(!recoverableDraft)return;
    if(result){setDraft(recoverableDraft.text);setEditing(true);setScreen("review");setMobilePane("document");setRecoverableDraft(null);}
    else{
      setBusy(true);setError("");
      try{const p=await persist({report:{...project.report,text:recoverableDraft.text},choices:{},manual_text:null});
        acceptProject(p,"project");clearEditorDraft(p.id);setToast("草稿已恢复为待核对的报告文字");}
      catch(e){setError(e.message);}finally{setBusy(false);}
    }
  }

  async function saveEditor(){
    if(busy)return;
    setBusy(true);setError("");
    try{const p=await persist({manual_text:draft,choices:{}});setManualText(draft);setChoices({});setEditing(false);clearEditorDraft(p.id);setToast("正文已保存，请复查相关提醒");}
    catch(e){setError(e.message);}
    finally{setBusy(false);}
  }

  useEffect(()=>{
    if (!project?.id) return;
    if(conflictRef.current)return;
    const current=JSON.stringify(workingState());
    if (current===savedState.current) return;
    const timer=setTimeout(()=>persist().catch(e=>setError(e.message)),700);
    return ()=>clearTimeout(timer);
  },[project?.id,choices,manualText,readingSize,materials]);

  async function resolveConflict(preferLocal){
    const state=conflictRef.current;if(!state)return;
    setBusy(true);
    try{
      const remote=await request(`/api/project?id=${encodeURIComponent(state.base.id)}`);
      const merged=reconcileProjectChanges(state.base,state.requested,remote,preferLocal);
      const p=Object.keys(merged.changes).length?await request("/api/projects",{action:"save",id:remote.id,version:remote.version,actor:actorName,changes:merged.changes}):remote;
      conflictRef.current=null;setConflict(null);acceptProject(p,screen);setError("");
      setToast(preferLocal?"已保留本页的重叠改动，其他更新已合并":"已使用最新的重叠改动，其他更新已合并");
    }finally{setBusy(false);}
  }

  function backupConflict(){
    const state=conflictRef.current;if(!state)return;
    downloadText(`${project.name}_未保存草稿.json`,JSON.stringify({project_name:project.name,saved_at:new Date().toISOString(),base_version:state.base.version,changes:state.requested},null,2),"application/json;charset=utf-8");
  }

  async function goHome() {
    if(!mayLeavePractice())return;
    if(busy||operationRef.current)return;
    try {await flushEdits(); const data=await request("/api/projects");setProjects(data.projects);
      keepProject(null);setResult(null);setReport(null);setMaterials([]);setChoices({});setManualText(null);setShowPaste(false);setPaste("");setScreen("home");setError("");}
    catch(e){setError(e.message);}
  }

  async function navigate(destination) {
    if(destination!==screen&&!mayLeavePractice())return;
    if(busy||operationRef.current)return;
    if (!projectRef.current) return goHome();
    try {await flushEdits();if(destination==="review"&&!result){setScreen("review-start");}else setScreen(destination);}
    catch(e){setError(e.message);}
  }

  async function openProject(id) {
    if(!mayLeavePractice())return;
    if(busy||operationRef.current)return;
    setBusy(true);
    try {await flushEdits();acceptProject(await request(`/api/project?id=${encodeURIComponent(id)}`));}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }

  async function newProject() {
    if(!mayLeavePractice())return;
    if(busy||operationRef.current)return;
    setBusy(true);
    try {await flushEdits();acceptProject(await request("/api/projects",{action:"create",name:"新的社会实践项目"}));}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }

  async function saveDetails(changes) {
    setBusy(true);
    try {const edits="report" in changes?{...changes,choices:{},manual_text:null}:changes;const p=await persist(edits);if("report" in changes)acceptProject(p,screen);else setMaterials(p.materials.map(m=>({...m,consent_status:"confirmed"})));setToast("项目已保存到本机");return true;}
    catch(e){setError(e.message);return false;}finally{setBusy(false);}
  }

  async function taskAction(task,status) {
    if(mutationOperation.current||busy)return;
    mutationOperation.current=true;setBusy(true);
    try {await persist();await projectAction("task",{task_id:task.id,status});setToast(status==="done"?task.kind==="practice"?"已记录你的任务完成确认":"已记录你的补证确认":"任务已重新打开");}
    catch(e){setError(e.message);}
    finally{mutationOperation.current=false;setBusy(false);}
  }

  function setActor(id) {
    setActorId(id);
    try {localStorage.setItem(`qingji-v3.actor.${project.id}`,id);}catch {}
  }

  async function teamAction(action,values,message="已保存到项目") {
    if(busy||operationRef.current||mutationOperation.current)throw new Error("上一项操作正在保存，请稍后继续。");
    mutationOperation.current=true;
    setBusy(true);setError("");
    try {await flushEdits();const p=await projectAction(action,values);setToast(message);return p;}
    catch(e){setError(e.message);throw e;}
    finally {mutationOperation.current=false;setBusy(false);}
  }

  async function saveQuickRecord(material) {
    if(!recordToEdit&&materials.length>=8)throw new Error("项目目前最多保存八份材料，可先整理现有记录。");
    setBusy(true);setError("");
    try {const next=recordToEdit?materials.map(m=>m.id===material.id?material:m):[...materials,material];
      const p=await persist({materials:next});setMaterials(p.materials.map(m=>({...m,consent_status:"confirmed"})));setFocusMaterial(material.id);setScreen("materials");setRecordToEdit(null);setToast("记录已保存，已纳入的内容可参与 AI 核对");}
    catch(e){setError(e.message);throw e;}
    finally {setBusy(false);}
  }

  function openQuickRecord(material=null){if(!mayLeavePractice())return;setRecordToEdit(material);setQuickRecordOpen(true);}

  async function removeMaterial(material){
    if(mutationOperation.current||busy)throw new Error("上一项操作正在保存，请稍后继续。");
    mutationOperation.current=true;setBusy(true);setError("");
    try{await flushEdits();const p=await persist({materials:materials.filter(m=>m.id!==material.id)});setMaterials(p.materials.map(m=>({...m,consent_status:"confirmed"})));setToast("已从当前材料移除，核对历史仍保留");}
    catch(e){setError(e.message);throw e;}
    finally{mutationOperation.current=false;setBusy(false);}
  }

  async function archiveProject(id,archived) {
    if(busy||operationRef.current)return;
    setBusy(true);setError("");
    try {
      if(projectRef.current?.id===id){await flushEdits();await projectAction("archive",{archived});}
      else {const item=projects.find(p=>p.id===id);await request("/api/projects",{action:"archive",id,version:item.version,archived,actor:actorName});}
      const data=await request("/api/projects");setProjects(data.projects);
      setToast(archived?"项目已归档，可在归档列表恢复":"项目已恢复");
    }catch(e){setError(e.message);}finally{setBusy(false);}
  }

  async function exportPackage() {
    if(busy)return;
    setBusy(true);setError("");
    try {await flushEdits();const data=await request(`/api/package?id=${encodeURIComponent(project.id)}`);
      downloadText(`${project.name}_青迹项目.qingji.json`,JSON.stringify(data),"application/json;charset=utf-8");setToast("完整项目包已导出");}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }

  async function importPackage(file) {
    if(!file||busy)return;
    setBusy(true);setError("");
    try {
      if(file.size>12*1024*1024)throw new Error("项目包请控制在12MB以内。");
      let data;try {data=JSON.parse(await file.text());}catch {throw new Error("项目包无法读取，请选择青迹导出的JSON文件。");}
      await flushEdits();const p=await request("/api/projects",{action:"import",package:data,actor:actorName});acceptProject(p);
      setToast("已导入为独立项目，请检查本轮纳入的材料");
    }catch(e){setError(e.message);}finally{setBusy(false);if(packageInput.current)packageInput.current.value="";}
  }

  async function loadDeliveryCheck(options = {}) {
    const {flush = false, setAppBusy = false, caller = "project"} = options;
    if(!projectRef.current)throw new Error("请先打开实践项目。");
    if(setAppBusy)setBusy(true);
    const seq = ++deliveryReqSeqRef.current;
    const exportSessionId = exportSessionRef.current;
    const startProjectId = projectRef.current.id;

    const isStale = () => {
      if (projectRef.current?.id !== startProjectId) return true;
      if (seq !== deliveryReqSeqRef.current) return true;
      if (caller === "export") {
        if (!exportOpenRef.current || exportSessionRef.current !== exportSessionId) {
          return true;
        }
      }
      return false;
    };

    try {
      await projectQueue.current;
      if (isStale()) throw new Error("ABORTED_STALE");
      const p = flush ? await flushEdits() : projectRef.current;
      const check = current => request(`/api/delivery?id=${encodeURIComponent(current.id)}&version=${current.version}`);
      try {
        const res = await check(p);
        if (isStale()) throw new Error("ABORTED_STALE");
        return res;
      }
      catch(e) {
        if(e.status!==409)throw e;
        if (isStale()) throw new Error("ABORTED_STALE");
        const remote = await request(`/api/project?id=${encodeURIComponent(p.id)}`);
        if (isStale()) throw new Error("ABORTED_STALE");
        if(projectRef.current?.id !== p.id)throw new Error("项目已切换，请在当前项目继续检查。");

        // 关键保护：若用户正在编辑正文，被动检查绝不自动调用 acceptProject 打断当前编辑界面
        if (editingRef.current) {
          throw new Error("另一个窗口已更新项目，本页正文正在编辑中，暂未自动合并。");
        }
        // 版本守卫：防止较低版本 remote 覆盖已经载入的较新 projectRef
        if (remote.version <= projectRef.current.version) {
          throw new Error("ABORTED_STALE");
        }
        // 若发起检查的导出菜单在等待回包期间已关闭或会话已失效，被动迟到回包丢弃，不执行副作用
        if (caller === "export" && (!exportOpenRef.current || exportSessionRef.current !== exportSessionId)) {
          throw new Error("ABORTED_STALE");
        }
        if(JSON.stringify(latestWorkingState.current)!==JSON.stringify(editableProjectState(p)))
          throw new Error("另一个窗口已更新项目，本页新改动仍保留，请再次更新检查。");
        acceptProject(remote, screen, { preserveTab: true });
        setToast("已载入另一个窗口保存的最新内容");
        if (isStale()) throw new Error("ABORTED_STALE");
        return await check(remote);
      }
    } finally {if(setAppBusy)setBusy(false);}
  }

  async function generatePlan(issue) {
    if(busy||planOperation.current)return;
    if(hasEdits||projectRef.current?.needs_review){setToast("正文或资料已变化，先复查后再生成补证计划");return;}
    planOperation.current=true;setPlanningIssue(issue.id);setBusy(true);setError("");
    try {await persist();const p=projectRef.current;const mode="ai";
      const plan=await request("/api/plan",{project_id:p.id,version:p.version,issue_id:issue.id,mode,allow_external_processing:allowAI});
      setPracticePlan(plan);
    }catch(e){setError(e.message);}finally{planOperation.current=false;setPlanningIssue(null);setBusy(false);}
  }

  async function savePlanTask(task) {
    const p=await teamAction("create_task",{action_text:task.action,notes:task.notes},"补证安排已记为实践任务，可在项目里分工");
    if(p)setPracticePlan(null);
  }

  async function supplement(issue, file) {
    if(busy||operationRef.current)return;
    setBusy(true);setError("");
    try {await persist();const material=file?await readFile(file):null;const p=await projectAction("supplement",{issue_id:issue.id,material});
      setMaterials(p.materials.map(m=>({...m,consent_status:"confirmed"})));
      if(file){setFocusMaterial(p.materials.at(-1).id);setScreen("materials");}
      setToast(file?"已关联到这条结论，完善来源后可直接复查":"已记入本项目补证待办");}
    catch(e){setError(e.message);}finally{setBusy(false);if(supplementInput.current)supplementInput.current.value="";}
  }

  function locateTask(task) {
    if(!mayLeavePractice())return;
    const match = matchTaskIssue(task, {result});
    if (match.status === "unique") return locateIssue(match.issue.id, true);
    if (match.status === "ambiguous") {
      setIssueFilter("all"); setActiveId(null); setTab("feedback");
      setTaskCandidates(match.matches.map(i => i.id));
      setScreen("review"); setMobilePane("feedback");
    } else {
      setToast("当前记录无法可靠对应这条任务，请查看历史核对记录");
    }
  }

  function locateIssue(issueId, leaveConfirmed=false) {
    if(!leaveConfirmed&&!mayLeavePractice())return;
    const issue = result?.issues?.find((i) => i.id === issueId);
    if (issue) {
      setScreen("review");
      locate(issue);
      setMobilePane("feedback");
    } else {
      setToast("原句已在新版本中变化，请查看历史核对记录");
    }
  }

  async function showRevision(id) {
    const sequence = ++revisionRequest.current, projectId = project.id;
    setRevisionLoading(true);
    try {
      const data = await request(`/api/revision?id=${projectId}&revision=${id}`);
      if (sequence === revisionRequest.current && projectRef.current?.id === projectId) setRevision({...data, revision_id:id});
    } catch(e) {if (sequence === revisionRequest.current) setError(e.message);}
    finally {if (sequence === revisionRequest.current) setRevisionLoading(false);}
  }

  async function uploadReport(file) {
    if (!file || busy) return;
    setError(""); setBusy(true);
    try { const doc = await readFile(file); if(projectRef.current){const p=await persist({report:doc,choices:{},manual_text:null});acceptProject(p,"project");}else {setReport(doc); setShowPaste(false); setPaste("");} }
    catch (e) {setError(e.message);} finally {setBusy(false); if (reportInput.current) reportInput.current.value = "";}
  }

  async function uploadMaterials(files) {
    if (!files.length || busy) return;
    if (materials.length + files.length > 8) return setError("每次请提供不超过八份补充材料。");
    setBusy(true); setError("");
    try {const added = await Promise.all(Array.from(files).map(readFile));const all=[...materials,...added.map(m=>({...m,id:"m"+crypto.randomUUID(),consent_status:"confirmed",enabled:true}))];if(projectRef.current){const p=await persist({materials:all});setMaterials(p.materials.map(m=>({...m,consent_status:"confirmed"})));setToast("材料已保存，纳入的内容将用于 AI 分析");}else setMaterials(all);}
    catch (e) {setError(e.message);} finally {setBusy(false); if (materialsInput.current) materialsInput.current.value = "";}
  }

  async function startReview() {
    if(operationRef.current||busy)return;
    const document = showPaste ? {id: "report", name: "社会实践报告", text: paste, notes: []} : report;
    if (!document?.text.trim()) return setError("请先上传报告或粘贴正文。");
    operationRef.current=true;setBusy(true);setReviewing(true);setError("");
    try {const p=await request("/api/projects",{action:"create",name:document.name.replace(/\.(docx|pdf|txt|md)$/i,""),report:document,materials:materials.map(m=>({...m,consent_status:allowAI?"confirmed":m.consent_status}))});acceptProject(p);
      acceptProject(await projectAction("review",{report:document,mode:"ai",allow_external_processing:allowAI}),"review");}
    catch (e) {setError(e.message);} finally {operationRef.current=false;setReviewing(false);setBusy(false);}
  }

  async function openExample() {
    setBusy(true); setError("");
    try {await persist();acceptProject(await request("/api/projects",{action:"example"}),"review");} catch(e) {setError(e.message);} finally {setBusy(false);}
  }

  function locate(issue) {
    if (!issue) return;
    setTaskCandidates([]);
    if (issueFilter !== "all" && !isIssueVisible(issue, issueFilter, choices)) {
      setIssueFilter("all");
      setToast("已恢复显示全部结论以定位该项");
    }
    setActiveId(issue.id); setTab("feedback");
  }

  function handlePrevIssue() {
    if (!navInfo.canPrev || !navInfo.prevId) return;
    const target = visibleIssues.find((i) => i.id === navInfo.prevId);
    if (target) locate(target);
  }

  function handleNextIssue() {
    if (!navInfo.canNext || !navInfo.nextId) return;
    const target = visibleIssues.find((i) => i.id === navInfo.nextId);
    if (target) locate(target);
  }

  function handleFilterChange(newFilter) {
    setIssueFilter(newFilter);
    const newVisible = filterIssues(result?.issues || [], newFilter, choices);
    if (newVisible.length > 0 && !newVisible.some((i) => i.id === activeId)) {
      setActiveId(newVisible[0].id);
    } else if (newVisible.length === 0) {
      setActiveId(null);
    }
  }

  function apply(issue, choice) {
    if (manualText !== null) return setError("正文已手动编辑，请先复查，再处理提醒。");
    const nextChoices = {...choices, [issue.id]: choice};
    try {changedText(result.report.text, result.issues, nextChoices); setChoices(nextChoices); setError(""); setToast(choice === "accepted" ? "已更新正文，可撤销并复查" : "已保留原句，提醒仍保留在记录中");}
    catch(e) {setError(e.message);}
  }

  async function recheck(fromOverview=false) {
    if(!mayLeavePractice())return;
    if(operationRef.current||busy)return;
    const previousQuote=selectedIssue?.quote;
    let mode = "ai";
    operationRef.current=true;
    setBusy(true); setError("");
    setReviewing(true);
    try {
      if (mode === "example" && manualText !== null) mode = "preliminary";
      if (mode === "example" && projectRef.current.needs_review) mode=status?.ai_configured&&allowAI?"ai":"preliminary";
      await persist();
      const updated=await projectAction("review",{report:currentReport,mode,allow_external_processing:allowAI});
      acceptProject(updated,"review");
      const matching=updated.result.issues.find(i=>i.quote===previousQuote);
      if(matching)setActiveId(matching.id);
      setToast("复查已保存为新版本，旧记录仍可查看");
    } catch(e) {setError(e.message);} finally {operationRef.current=false;setReviewing(false);setBusy(false);}
  }

  async function ask(text = question) {
    if (!text.trim() || !selectedIssue || chatOperationRef.current || chatBusy || busy) return;
    if(projectRef.current?.needs_review||hasEdits||editing){setToast("正文或材料已变化，复查后再追问");return;}
    chatOperationRef.current=true;
    const outgoing = text.trim(); setQuestion(""); setChatBusy(true); setError(""); setTab("chat");
    setChat((items) => [...items, {role: "user", text: outgoing, issueId: selectedIssue.id}]);
    try {
      const p=await persist();
      const current=p.result?.issues.find(i=>i.id===selectedIssue.id&&i.quote===selectedIssue.quote&&i.category===selectedIssue.category);
      if(!current)throw new Error("这条结论已更新，请选择最新记录再提问。");
      const answer = await request("/api/chat", {project_id: p.id,version:p.version, issue: current, question: outgoing, allow_external_processing: allowAI});
      setChat((items) => [...items, {role: "assistant", text: answer.answer, issueId: selectedIssue.id, label: answer.label || "青迹"}]);
    } catch(e) {setQuestion(outgoing);setError(e.message);} finally {chatOperationRef.current=false;setChatBusy(false);}
  }

  function exportResult(kind) {
    setExportOpen(false);
    const exportText = editing ? draft : displayText;
    if (kind === "report") downloadText(`${reportName}_修改稿.txt`, exportText);
    else {
      const history = project?.history || [];
      const isImported = isImportedUnverified(result, history, project?.imported_from);
      const modeText = isImported ? "外部历史 · 未在本机复核" : modeLabel(result.mode);
      const rows = result.issues.map((issue, index) => `### ${index + 1}. ${issue.category}\n\n原句：${issue.quote}\n\n支持程度：${supportLabels[issue.support_status||"pending"]}\n\n原因：${issue.reason}\n\n依据：${issue.citations.map((c) => `${{support:"支持记录",different:"不同情况",context:"背景与限制"}[c.relation]||"原文依据"} · ${c.document_name}：${c.quote}`).join("；") || "本次未定位到具体支持片段"}\n\n建议：${issue.suggested_text || issue.next_step}\n\n作者选择：${choices[issue.id] === "accepted" ? "已采纳" : choices[issue.id] === "kept" ? "保留原句" : "未处理"}`);
      const tasks=project.tasks.map(t=>`- ${taskLabels[t.status]}：${t.quote}\n  下一步：${t.action}；关联${t.material_ids.length}份补充材料。`).join("\n\n");
      let pendingNotices = "";
      if (project.needs_review) pendingNotices += "项目材料已变化，当前结论依据尚未复查。\n\n";
      if (editing) pendingNotices += "正文正在编辑中，本次导出包含尚未提交保存的草稿，尚未复查。\n\n";
      else if (hasEdits) pendingNotices += "正文已修改，尚未复查。\n\n";
      downloadText(`${reportName}_审阅记录.md`, `# ${reportName} · 审阅记录\n\n实践项目：${project.name}\n\n检查方式：${modeText}\n\n${result.notices.join("\n\n")}\n\n${pendingNotices}${rows.join("\n\n")}\n\n## 补充行动\n\n${tasks||"暂无补证待办。"}\n\n## 当前正文\n\n${exportText}`, "text/markdown;charset=utf-8");
    }
    setToast("已导出所选文件");
  }

  async function exportWord(){
    if(exporting||busy)return;
    const exportText = editing ? draft : displayText;
    setExporting(true);setExportOpen(false);setError("");
    try{
      const response=await fetch("/api/export-docx",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:reportName,text:exportText})});
      if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"Word导出未完成，请重试。");}
      const blob=await response.blob();const url=URL.createObjectURL(blob),anchor=document.createElement("a");
      anchor.href=url;anchor.download=`${reportName}_修改稿.docx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      setToast("已导出当前正文的Word稿，使用基础排版");
    }catch(e){setError(e.message||"Word导出未完成，请重试。");}
    finally{setExporting(false);}
  }

  const visibleChat = chat.filter((item) => item.issueId === activeId);
  const sourceDocument = citation && (citation.document_id === "report" ? result?.report :
    (citation.live?materials:project?.review_materials||[]).find((m) => m.id === citation.document_id));
  useEffect(()=>{
    if(citation&&!sourceDocument){setCitation(null);setError("这次记录没有可用的材料原文，请在检查与变化记录中查看当时依据。");}
  },[citation,sourceDocument]);

  return <div className={`app project-app ${screen === "review" ? "review-app" : "home-app"}`}><ProjectSidebar project={project} screen={screen} onNavigate={navigate} onHome={goHome} saving={saving} blocked={!!citation||quickRecordOpen||!!conflict} busy={busy||chatBusy}/><div className="page-content" inert={!!citation||quickRecordOpen||!!conflict}>
    <input type="file" ref={reportInput} accept=".docx,.pdf,.txt,.md" className="file-input" aria-label="上传社会实践报告" onChange={e=>uploadReport(e.target.files[0])}/>
    <input type="file" multiple ref={materialsInput} accept=".docx,.pdf,.txt,.md" className="file-input" aria-label="补充依据材料" onChange={e=>uploadMaterials(e.target.files)}/>
    <input type="file" ref={supplementInput} accept=".docx,.pdf,.txt,.md" className="file-input" aria-label="为当前结论补充材料" onChange={e=>{if(supplementTarget.current&&e.target.files[0])supplement(supplementTarget.current,e.target.files[0]);}}/>
    <input type="file" ref={packageInput} accept=".json" className="file-input" aria-label="导入青迹项目包" onChange={e=>importPackage(e.target.files[0])}/>
    {screen === "review" && <header className="topbar">
      <button className="brand" aria-label="青迹首页" onClick={goHome} disabled={busy||chatBusy}><img src="/assets/qingji-wordmark.png" alt="青迹"/></button>
      {screen === "review" ? <>
        <span className="brand-divider"/>
        <span className="document-name" title={reportName}>{reportName}</span>
        <div className="export-wrap" ref={exportWrapRef}>
          <button
            ref={exportButtonRef}
            className="primary export-button"
            onClick={() => {
              setExportOpen(prev => {
                if (!prev) exportSessionRef.current += 1;
                return !prev;
              });
            }}
            disabled={busy || exporting}
            aria-expanded={exportOpen}
            aria-haspopup="dialog"
          >
            <Icon as={exporting ? IconLoader2 : IconUpload} className={exporting ? "spin" : ""}/>
            {exporting ? "导出中" : "导出"}
          </button>
          {exportOpen && (
            <ExportMenu
              project={project}
              result={result}
              choices={choices}
              displayText={displayText}
              draft={draft}
              reportName={reportName}
              hasEdits={hasEdits}
              editing={editing}
              choicesDirty={JSON.stringify(Object.fromEntries(Object.entries(choices).filter(([,v])=>v))) !== JSON.stringify(Object.fromEntries(Object.entries(project?.choices || {}).filter(([,v])=>v)))}
              materialsDirty={JSON.stringify(materials) !== JSON.stringify(project?.materials || [])}
              textChanged={hasEdits || (editing && draft !== (result?.report?.text ?? project?.report?.text))}
              isDirty={JSON.stringify(workingState()) !== savedState.current}
              busy={busy}
              exporting={exporting}
              onCheck={loadDeliveryCheck}
              onExportWord={exportWord}
              onExportReport={() => exportResult("report")}
              onExportRecord={() => exportResult("record")}
              onNavigate={navigate}
              onClose={() => {
                setExportOpen(false);
                exportButtonRef.current?.focus();
              }}
              triggerRef={exportButtonRef}
            />
          )}
        </div>
      </> : <span className="brand-subtitle">{project?.name||"社会实践 · 证据与结论"}</span>}
    </header>}
    {error && <div className="error-message" role="alert"><span>{error}</span><button className="icon-button" aria-label="关闭提示" onClick={() => setError("")}><Icon as={IconX}/></button></div>}
    {toast && <div className="toast" role="status"><Icon as={IconCheck}/>{toast}</div>}
    {recoverableDraft&&project&&<div className="draft-recovery" role="status"><span>有一份未保存的正文草稿{recoverableDraft.base_version!==project.version?"，项目已有更新":""}。</span><button className="text-button" onClick={recoverEditor} disabled={busy}>继续编辑草稿</button><button className="text-button" onClick={()=>clearEditorDraft()} disabled={busy}>舍弃草稿</button></div>}
    {reviewing&&<div className="review-progress" role="status" aria-live="polite"><Icon as={IconLoader2} className="spin"/><span><strong>正在核对报告与依据</strong><small>{project?"完成后会显示新结果，当前记录已保存在项目中。":"正在准备实践项目，随后开始核对。"}</small></span><span className="review-time" aria-hidden="true">已等待 {reviewSeconds} 秒</span></div>}

    {screen === "home" ? <main className="home-content">
      <section className="intro">
        <div className="intro-copy"><p className="eyebrow">青迹 · 可信社会实践</p><h1>带着问题出发，<br/>让每一步留下依据。</h1><p className="intro-description">从走访、记录，到有依据的社会实践报告。</p></div>
        <div className="home-entry-grid">
        <article className="start-practice-card"><FieldworkArt/><p className="entry-kicker">从实践出发</p><h2>一个问题，一段实践</h2><p>确定方向，安排下一步行动。</p><button className="primary home-start-practice" onClick={newProject} disabled={busy}>开始一项实践<Icon as={IconArrowUpRight}/></button></article>
        <details className="home-report-entry"><summary><FieldworkArt kind="notes"/><span className="entry-kicker">从报告继续</span><strong>让发现有据可循</strong><span className="entry-description">对照原始材料，核对报告中的结论。</span><span className="entry-link">已有报告，直接开始复核 <Icon as={IconArrowUpRight}/></span></summary><div className="upload-area">
          <div className={`dropzone ${report && !showPaste ? "has-document" : ""}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => {e.preventDefault(); uploadReport(e.dataTransfer.files[0]);}}>
            <button className="dropzone-button" disabled={busy} onClick={() => reportInput.current?.click()}><Icon as={busy ? IconLoader2 : report && !showPaste ? IconFileText : IconFileUpload} size={42} className={busy ? "spin" : ""}/><strong>{report && !showPaste ? report.name : "点击上传，或拖入报告"}</strong><span>{report && !showPaste ? "已读取正文 · 点击更换文件" : "DOCX / 文字PDF / TXT / Markdown · 最大5 MB"}</span></button>
          </div>
          <button className="paste-link" onClick={() => setShowPaste(!showPaste)} disabled={busy}>{showPaste ? "收起粘贴区域" : "也可以直接粘贴正文"}</button>
          {!!report?.notes?.length&&!showPaste&&<details className="file-read-notes"><summary>文件读取说明</summary>{report.notes.map((note,i)=><p key={i}>{note}</p>)}</details>}
          {showPaste && <label className="paste-area">报告正文<textarea value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="粘贴社会实践报告全文，包含前文依据与结论……" rows={8}/></label>}
          <div className="material-section"><button className="text-button" onClick={() => materialsInput.current?.click()} disabled={busy}><Icon as={IconPlus}/>补充访谈、记录或统计摘要<span className="optional">可选</span></button>{materials.map((m, index) => <div className="material-row" key={`${m.name}-${index}`}><Icon as={IconFileText}/><span>{m.name}</span><button className="icon-button" aria-label={`移除材料${m.name}`} disabled={busy} onClick={() => setMaterials(materials.filter((_, i) => i !== index))}><Icon as={IconX} size={16}/></button></div>)}</div>
          <p className="processing-note">默认使用 AI 分析报告与纳入的材料。</p>
          <button className="primary start-button" disabled={busy || !status || !(showPaste ? paste.trim() : report?.text)} onClick={startReview}>{busy ? <><Icon as={IconLoader2} className="spin"/>正在处理</> : <>开始检查<Icon as={IconArrowUpRight}/></>}</button>
        </div></details>
        </div><button className="example-link" onClick={openExample} disabled={busy}><Icon as={IconArrowUpRight}/>看看一份审阅示例</button>
      </section>
      <ProjectCards projects={projects} onOpen={openProject} onNew={newProject} onImport={()=>packageInput.current?.click()} onArchive={archiveProject} busy={busy}/>
      <footer className="home-footer">让实践有记录，让结论有依据。</footer>
    </main> : screen!=="review"&&project ? screen==="review-start" ? <ReviewStart onDraftChange={setPracticeDraft} project={project} materials={materials} busy={busy} onUpload={()=>reportInput.current?.click()} onSave={saveDetails} onStart={()=>recheck(true)}/> : screen==="materials" ?
      <MaterialsPanel materials={materials} reviewMaterials={project.review_materials} result={result} tasks={project.tasks} focusMaterial={focusMaterial} onChange={(index,change)=>setMaterials(items=>items.map((m,i)=>i===index?{...m,...change}:m))}
        onSave={()=>saveDetails({materials})} onUpload={()=>materialsInput.current?.click()} onQuickRecord={()=>openQuickRecord()} onEdit={openQuickRecord} onRemove={removeMaterial}
        onPreview={m=>setCitation({document_id:m.id,start:0,end:0,quote:"",live:true})} onPreviewCitation={c=>setCitation({...c,live:false})} onLocateIssue={locateIssue} onReview={()=>navigate("review")} onRecheck={()=>recheck(true)}
        hasReport={!!report?.text?.trim()} allowAI={allowAI} aiConfigured={status?.ai_configured} busy={busy} needsReview={project.needs_review}/>
      : <ProjectOverview currentReport={currentReport} key={project.id} reportRequest={reportRequest} onDraftChange={setPracticeDraft} hasPracticeDraft={practiceDraft} onPractice={async(action, values)=>{const p=await teamAction(action,values,"实践进展已保存");acceptProject(p,"project",{preserveTab:true});return p;}} project={project} result={result} onSave={saveDetails} onUpload={()=>reportInput.current?.click()} onReview={()=>navigate("review")}
        deliveryCheck={<DeliveryCheck version={project.version} hasEdits={editing||JSON.stringify(workingState())!==savedState.current} busy={busy} onCheck={loadDeliveryCheck} onNavigate={navigate}/>}
        onMaterials={()=>navigate("materials")} onQuickRecord={()=>openQuickRecord()} onRecheck={()=>recheck(true)} onTask={taskAction} onLocate={locateTask} onRevision={showRevision} revision={revision} revisionLoading={revisionLoading}
        allowAI={allowAI} aiConfigured={status?.ai_configured} busy={busy} actor={actorId} onActor={setActor} hasEdits={hasEdits||editing}
        onMembers={members=>teamAction("members",{members},"成员分工已保存")}
        onTaskDetail={(task,changes)=>teamAction("task_detail",{task_id:task.id,changes},"任务分工已保存")}
        onCreateTask={task=>teamAction("create_task",{question_id:task.question_id||"",action_text:task.action,assignee_id:task.assignee_id,due_date:task.due_date,notes:task.notes},"实践任务已建立")}
        onComment={values=>teamAction("comment",values,"讨论已记录")}
        onArchive={value=>archiveProject(project.id,value)} onPackage={exportPackage}/>
      : <>
      <div className="backbar"><button className="text-button" onClick={()=>navigate("project")} disabled={busy||chatBusy}><Icon as={IconArrowLeft}/>实践项目</button><div className="workspace-actions">{hasEdits && <><span className="pending-note">正文已修改，待复查</span><button className="text-button" onClick={() => {setChoices({}); setManualText(null); setToast("已恢复本次检查时的原文");}} disabled={busy}>撤销修改</button></>}<button className="text-button" disabled={busy || editing} onClick={()=>recheck()}><Icon as={busy ? IconLoader2 : IconRefresh} className={busy ? "spin" : ""}/>{busy ? "正在复查" : "复查"}</button></div></div>
      {project?.needs_review&&<div className="material-change-note review-change-note">项目材料已变化，当前结论依据尚未复查。<button className="text-button" onClick={()=>navigate("materials")}>查看材料</button></div>}
      <div className="mobile-switch" role="tablist" aria-label="切换审阅区域"><button role="tab" aria-selected={mobilePane === "document"} onClick={() => setMobilePane("document")}>报告原文</button><button role="tab" aria-selected={mobilePane === "feedback"} onClick={() => setMobilePane("feedback")}>审阅反馈</button></div>
      <main className={`workspace show-${mobilePane}`} aria-busy={busy}>
        <section className="document-pane" aria-label="报告原文" style={{"--reading-offset": `${readingSize - 18}px`}}>
          <div className="document-toolbar"><h2><Icon as={IconFileText} size={25}/>报告原文</h2><div className="document-tools"><label className="reading-size">字号<select aria-label="原文字号" value={readingSize} onChange={(e) => setReadingSize(Number(e.target.value))}>{[16,18,20,22].map(size => <option key={size} value={size}>{size}</option>)}</select></label><button className="edit-button" onClick={() => {if (editing) saveEditor(); else {setDraft(displayText); setEditing(true);}}} disabled={busy}><Icon as={editing ? IconCheck : IconPencil} size={16}/>{editing ? "保存正文" : "编辑"}</button><span className="mode-pill">{modeLabel(result.mode)}</span></div></div>
          <div className="document-scroll">{editing ? <label className="editor-label">编辑报告正文<textarea className="report-editor" aria-label="编辑报告正文" maxLength={24000} value={draft} onChange={(e) => cacheEditorDraft(e.target.value)} spellCheck={false}/><button className="text-button" onClick={() => {setEditing(false);setDraft("");clearEditorDraft();}}>取消编辑</button></label> : <article className="report-body"><h1>{reportName}</h1>{highlightedLines(displayText, manualText === null ? result.issues : [], choices, activeId).map(({line, parts, key}) => {
            if (!line.trim() || line.startsWith("示例报告") || line.trim() === reportName) return null;
            const content = parts.map((part, index) => part.issue ? <button key={index} id={`mark-${part.issue.id}`} className={`sentence-mark ${part.active ? "active" : ""}`} onClick={() => {locate(part.issue); setMobilePane("feedback");}} title="查看对应提醒">{part.text}<span className="inline-number">{result.issues.indexOf(part.issue) + 1}</span></button> : <span key={index}>{part.text}</span>);
            return /^[一二三四五六七八九十]+[、．.]/.test(line) ? <h2 key={key}>{content}</h2> : <p key={key}>{content}</p>;
          })}</article>}</div>
        </section>
        <section className="feedback-pane" aria-label="审阅反馈">
          <div className="feedback-tabs" role="tablist" aria-label="结论与追问"><button role="tab" aria-selected={tab === "feedback"} className={tab === "feedback" ? "selected" : ""} onClick={() => setTab("feedback")}>结论与依据</button><button role="tab" aria-selected={tab === "chat"} className={tab === "chat" ? "selected" : ""} onClick={() => setTab("chat")}>追问</button></div>
          <div className="feedback-scroll">{tab === "feedback" ? <>
            <div className="feedback-heading"><h2>{result.issues.length ? `结论核对（${result.issues.length}）` : "本次未发现需提示的内容"}</h2><span>根据已提交材料检查，建议由你确认。</span></div>
            <p className="mode-note">{result.mode === "example" ? "当前为示例演示，反馈与问答用于展示操作流程。" : result.mode === "preliminary" ? "当前为本地预检：定位需核对的表达，尚未判断结论是否成立。" : "AI 审阅已完成；依据与修改建议仍由你核对。"}</p>
            {result.issues.length > 0 && (
              <ReviewToolbar
                totalCount={filterCounts.all}
                pendingCount={filterCounts.pending}
                filter={issueFilter}
                onFilterChange={handleFilterChange}
                visibleCount={visibleIssues.length}
                currentIndex={navInfo.currentIndex}
                onPrev={handlePrevIssue}
                onNext={handleNextIssue}
                disabled={busy}
              />
            )}
            {result.issues.length === 0 && <div className="empty-feedback"><Icon as={IconCheck} size={30}/><h3>可以继续核对报告</h3><p>{result.mode === "example" ? "示例中的两条提醒已处理。真实报告仍需结合材料审阅。" : "没有提醒不代表报告已通过审核，也不证明记录本身真实。"}</p><button className="text-button" onClick={() => setMobilePane("document")}>查看当前正文</button></div>}
            {result.issues.length > 0 && visibleIssues.length === 0 && (
              <div className="empty-filter-state">
                <p>当前筛选下无对应结论（报告共有 {result.issues.length} 条结论）</p>
                <button type="button" className="secondary" onClick={() => handleFilterChange("all")}>
                  显示全部结论
                </button>
              </div>
            )}
            {taskCandidates.length > 0 && <div className="task-match-notice" role="status"><p>存在 {taskCandidates.length} 处相同原句，请选择要查看的位置。</p><div>{result.issues.filter(i=>taskCandidates.includes(i.id)).map(issue=><button className="secondary" key={issue.id} onClick={()=>locate(issue)}>第 {result.issues.indexOf(issue)+1} 处 · {supportLabels[issue.support_status||"pending"]}</button>)}</div></div>}
            <div className="issue-list">{visibleIssues.map((issue) => <section id={`issue-${issue.id}`} className={`issue-card ${activeId === issue.id ? "expanded" : ""}`} key={issue.id}>
              <button className="issue-header" aria-expanded={activeId === issue.id} onClick={() => activeId === issue.id ? setActiveId(null) : locate(issue)}>
                <span className="issue-number">{result.issues.indexOf(issue) + 1}</span>
                <strong>{issue.support_status==="supported" ? "这条结论有对应依据" : issue.category === "范围外推" && result.mode === "example" ? "结论范围超出访谈样本" : titles[issue.category]}</strong>
                <div className="issue-header-badges">
                  <span className={`category-pill support-pill status-${issue.support_status||"pending"}`}>
                    {supportLabels[issue.support_status||"pending"]}
                  </span>
                  {choices[issue.id] === "accepted" && <span className="choice-badge choice-accepted">已采纳改写</span>}
                  {choices[issue.id] === "kept" && <span className="choice-badge choice-kept">保留原句</span>}
                </div>
                <Icon as={activeId === issue.id ? IconChevronUp : IconChevronDown}/>
              </button>
              {activeId === issue.id && <div className="issue-detail">
                <section className="reason-section"><h3>依据能支持到哪里</h3><p>{issue.reason}</p></section>
                {issue.citations.length>0 ? ["support","different","context","unclassified"].map(relation=>{const sources=issue.citations.filter(c=>(c.relation||"unclassified")===relation);return sources.length>0&&<section key={relation}><h3>{{support:"支持记录",different:"不同情况与观点",context:"背景与限制",unclassified:"原文依据"}[relation]}</h3>{sources.map((source,sourceIndex)=><button className="citation-box" key={sourceIndex} onClick={()=>setCitation(source)}><span>{source.quote}</span><small>{source.document_name.replace(/\.(txt|docx|md)$/i,"")} · 查看原文<Icon as={IconArrowUpRight} size={14}/></small></button>)}</section>}) : <section className="evidence-section"><h3>依据说明</h3><p className="evidence-missing">本次未定位到已提交材料中的对应支持片段。</p></section>}

                {issue.suggested_text && <section className="suggestion-section"><h3>修改建议（可选）</h3><p className="suggestion-box">{issue.suggested_text}</p></section>}
                <div className="issue-actions">{issue.suggested_text && <button className="primary" onClick={() => apply(issue, "accepted")} disabled={busy || choices[issue.id] === "accepted"}>{choices[issue.id] === "accepted" ? <><Icon as={IconCheck}/>已采纳</> : "采用建议"}</button>}<button className="secondary" onClick={() => apply(issue, "kept")} disabled={busy}>保留原句</button><button className="why-button" onClick={() => ask("为什么这样判断？")} disabled={chatBusy||busy}><Icon as={IconHelpCircle}/>为什么这样判断？</button></div>
                {(issue.support_status!=="supported" || project?.tasks.some(t=>t.quote===issue.quote&&t.category===issue.category)) && <section className="supplement-section">
                  {issue.support_status!=="supported" && <><h3>补充依据与下一步</h3><p className="next-step-text">{issue.next_step || "补充一手访谈、现场观察或统计台账佐证。"}</p><div className="supplement-actions"><button className="text-button" onClick={()=>supplement(issue,null)} disabled={busy}><Icon as={IconPlus} size={16}/>记为补证待办</button><button className="secondary" onClick={()=>{supplementTarget.current=issue;supplementInput.current?.click();}} disabled={busy}>补充这条依据</button></div></>}
                  {project?.tasks.filter(t=>t.quote===issue.quote&&t.category===issue.category).map(t=><p className="task-inline-note" key={t.id}>{taskLabels[t.status]} · {t.material_ids.length} 份关联材料</p>)}
                </section>}
                {issue.support_status!=="supported" && <PracticePlan issue={issue} plan={practicePlan?.issue_id===issue.id?practicePlan:null} onGenerate={()=>generatePlan(issue)} onCreateTask={savePlanTask}
                  generating={planningIssue===issue.id} busy={busy} aiSelected={!!status?.ai_configured&&allowAI}/>}
                <details className="issue-discussion"><summary>团队讨论{project.comments?.filter(c=>c.target_type==="issue"&&c.target_id===issue.id&&c.target_state==="current").length>0&&<span className="heading-count">{project.comments.filter(c=>c.target_type==="issue"&&c.target_id===issue.id&&c.target_state==="current").length}</span>}</summary>
                  <label className="actor-choice">本次署名<select aria-label="结论讨论署名" value={actorId} onChange={e=>setActor(e.target.value)} disabled={busy}><option value="">未署名</option>{project.members?.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
                  <CommentThread comments={project.comments?.filter(c=>c.target_state==="current")} members={project.members} targetType="issue" targetId={issue.id}
                    onComment={values=>teamAction("comment",values,"结论讨论已记录")} busy={busy}/>
                </details>
                {choices[issue.id] === "accepted" && <button className="text-button undo-one" onClick={() => setChoices({...choices, [issue.id]: undefined})}>撤销这处修改</button>}
              </div>}
            </section>)}</div>
            <details className="review-notices"><summary>本次检查范围与说明</summary>{result.notices.map((notice, index) => <p key={index}>{notice}</p>)}</details>
          </> : <div className="chat-panel"><h2>围绕当前提醒继续问</h2>{selectedIssue ? <><div className="chat-context"><span className="category-pill">{selectedIssue.category}</span><p>{selectedIssue.quote}</p></div>{result.mode !== "ai" && <p className="mode-note">{result.mode === "example" ? "示例问答展示围绕反馈继续交流的方式。" : "当前为本地规则说明，尚未接入 AI 对话。"}</p>}<div className="chat-messages" aria-live="polite">{visibleChat.map((message, index) => <div key={index} className={`chat-message ${message.role}`}><strong>{message.role === "user" ? "你" : message.label}</strong><p>{message.text}</p></div>)}{chatBusy && <p className="chat-loading"><Icon as={IconLoader2} className="spin"/>正在回答…</p>}</div><div className="question-suggestions"><button onClick={() => ask("为什么这样判断？")} disabled={chatBusy}>为什么这样判断？</button><button onClick={() => ask("还需要补充什么依据？")} disabled={chatBusy}>还需要补充什么依据？</button></div><form className="chat-form" onSubmit={(e) => {e.preventDefault(); ask();}}><label className="sr-only" htmlFor="question">就当前提醒向青迹提问</label><textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="就这条提醒问青迹…" rows={3} maxLength={1500}/><button className="primary icon-button" type="submit" aria-label="发送问题" disabled={!question.trim() || chatBusy}><Icon as={IconSend}/></button></form></> : <div className="empty-feedback"><Icon as={IconMessageCircle} size={30}/><p>先在反馈中选择一条提醒，再继续提问。</p><button className="text-button" onClick={() => setTab("feedback")}>查看反馈</button></div>}</div>}</div>
        </section>
      </main>
    </>}
    </div>{citation&&sourceDocument&&<SourceViewer document={sourceDocument} citation={citation} snapshot={!citation.live} onClose={()=>setCitation(null)}/>}
    {quickRecordOpen&&<QuickRecord initial={recordToEdit} onSave={saveQuickRecord} onClose={()=>{setQuickRecordOpen(false);setRecordToEdit(null);}} busy={busy}/>}
    {conflict&&<ConflictDialog conflict={conflict} onResolve={resolveConflict} onBackup={backupConflict} busy={busy}/>}
  </div>;
}

function modeLabel(mode) {return mode === "example" ? "示例演示" : mode === "ai" ? "AI 审阅" : "本地预检";}
