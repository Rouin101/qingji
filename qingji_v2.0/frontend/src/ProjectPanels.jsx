import {useEffect, useMemo, useRef, useState} from "react";
import {IconArchive, IconArrowUpRight, IconCheck, IconChevronDown, IconDots, IconDownload, IconFileText, IconFolder, IconNotes, IconPlus, IconRefresh, IconSearch, IconUpload} from "@tabler/icons-react";
import {TaskCard, TeamPanel} from "./TeamPanel.jsx";
import {ReviewChanges} from "./ReviewChanges.jsx";
import {computeTaskCounts, filterAndSortTasks} from "./task-filter-helpers.js";
import {getMaterialCitationsInfo} from "./material-citations-helpers.js";
import {isImportedUnverified} from "./export-status-helpers.js";
import "./task-toolbar.css";

export const supportLabels = {supported: "有对应依据", partial: "支持较窄表述", unsupported: "依据不足", disagreement: "存在不同情况", pending: "待结合依据核对"};
export const taskLabels = {open: "待补充", material_added: "已添材料，待复查", awaiting_confirmation: "已复查，待确认", done: "作者确认完成"};
const roles = ["待确认", "受访者陈述", "工作人员说明", "现场观察", "正式记录", "团队分析"];
const date = value => value ? new Date(value).toLocaleString("zh-CN", {hour12: false}) : "";
const archived = project => project.archived === true || Boolean(project.archived_at) || project.status === "archived";

export function ProjectSidebar({project, screen, onNavigate, onHome, saving, blocked, busy}) {
  return <aside className="project-sidebar" aria-label="青迹项目导航" inert={blocked}>
    <div className="sidebar-brand"><img src="/assets/qingji-wordmark.png" alt="青迹"/><p>可信社会实践</p></div>
    <nav>{[["project", "实践项目", IconFolder], ["materials", "实践材料", IconFileText], ["review", "结论核验", IconRefresh]].map(([key, label, Icon]) => {
      const active = screen === key || screen === "home" && key === "project";
      return <button key={key} className={active ? "active" : ""} aria-current={active ? "page" : undefined} onClick={() => key === "project" && !project ? onHome() : onNavigate(key)} disabled={busy || !project && key !== "project"}><Icon size={18} stroke={1.65}/>{label}</button>;
    })}</nav>
    {project && <div className="sidebar-context"><small>当前实践项目{archived(project) ? " · 已归档" : ""}</small><strong>{project.name}</strong><p>{project.materials.length} 份材料 · {(project.result?.issues || []).length} 条结论</p><p>{project.tasks.filter(task => task.status !== "done").length} 项待办</p><button className="text-button" onClick={onHome} disabled={busy}>切换项目 <IconArrowUpRight size={14}/></button></div>}
    <div className="sidebar-foot"><span className={`save-status ${saving || busy ? "working" : ""}`}/>{saving ? "正在保存…" : busy ? "正在处理…" : "记录保存在本机"}</div>
  </aside>;
}

export function ProjectCards({projects, onOpen, onNew, onImport, onArchive, busy}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ongoing");
  const visible = useMemo(() => projects.filter(project => {
    const matchesStatus = filter === "all" || (filter === "archived" ? archived(project) : !archived(project));
    return matchesStatus && `${project.name} ${project.description || ""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  }).sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || ""))), [projects, query, filter]);

  return <section className="project-library">
    <div className="section-title"><h2>已有项目</h2><div className="section-actions">{onImport && <button className="text-button" onClick={onImport} disabled={busy}><IconUpload size={16}/>导入项目</button>}<button className="text-button" onClick={onNew} disabled={busy}><IconPlus size={16}/>新建实践项目</button></div></div>
    {projects.length > 0 && <div className="library-controls"><label className="search-control"><IconSearch size={17}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索项目" aria-label="搜索已有项目"/></label><div className="segment-control" aria-label="项目状态筛选">{[["all", "全部"], ["ongoing", "进行中"], ["archived", "归档"]].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div></div>}
    {visible.length ? <div className="project-grid">{visible.map(project => <article className="project-tile-shell" key={project.id}>
      <button className="recent-report project-tile" onClick={() => onOpen(project.id)} disabled={busy}><span className="project-folder-icon"><IconFolder size={23} stroke={1.5}/></span><span><strong>{project.name}</strong><span className="project-tile-badges">
        {!project.has_result && <span className="tile-status-badge badge-unreviewed">未开始核对</span>}
        {project.imported_unverified && <span className="tile-status-badge badge-imported">未在本机复核</span>}
        {project.has_result && !project.imported_unverified && project.needs_review && <span className="tile-status-badge badge-needs-review">待复查</span>}
        {project.overdue_count > 0 && <span className="tile-status-badge badge-overdue">逾期 {project.overdue_count} 项</span>}
        {project.is_example && <span className="tile-status-badge badge-example">虚构示例</span>}
      </span><small>{project.material_count} 份材料 · {project.claim_count} 条结论 · {project.task_count} 项待办</small><small>{date(project.updated_at)}{archived(project) ? " · 已归档" : ""}</small></span><IconArrowUpRight size={18}/></button>
      {onArchive && <button className="project-archive-link text-button" onClick={() => onArchive(project.id, !archived(project))} disabled={busy}>{archived(project) ? "恢复进行中" : "归档项目"}</button>}
    </article>)}</div> : <div className="inline-empty"><IconFolder size={21}/><p>{!projects.length ? "从一份报告，或一个新项目开始。" : query.trim() ? "没有找到匹配的项目。" : filter === "archived" ? "还没有归档的项目。" : "这里暂时没有进行中的项目。"}</p></div>}
  </section>;
}

export function ProcessingConsent({allowAI, onAllowAI, busy, compact = false}) {
  return <div className={`processing-options ${compact ? "compact" : ""}`}>
    <label className="processing-choice"><input type="checkbox" disabled={busy} checked={allowAI} onChange={event => onAllowAI(event.target.checked)}/>将报告及已授权、未排除材料发送至 AI 核对。</label>
    <details className="permission-details"><summary>处理范围</summary><p>使用本项目已配置的 AI 服务。常见手机号、邮箱和身份证号会先遮盖，其他识别信息请自行处理。未确认授权或已排除的材料不会发送。</p></details>
  </div>;
}

function CreatePracticeTask({project, onCreateTask, busy}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);
  async function create(event) {
    event.preventDefault();
    if (submission.current) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const action = fields.get("action")?.trim();
    if (!action) return;
    submission.current = true;
    setSaving(true);
    setError("");
    try {
      await onCreateTask({kind: "practice", action, assignee_id: fields.get("assignee_id") || "", due_date: fields.get("due_date") || "", notes: fields.get("notes") || ""});
      form.reset();
      form.closest("details").open = false;
    } catch (error) {
      setError(error.message || "任务未保存，请重试。");
    } finally {
      submission.current = false;
      setSaving(false);
    }
  }
  return <details className="create-task surface-disclosure"><summary><span><IconPlus size={17}/>新建实践任务</span><IconChevronDown size={16}/></summary><form className="create-task-form" onSubmit={create}><label className="task-action-label">要做什么<textarea name="action" rows={2} maxLength={1000} placeholder="如：整理本次访谈的原始记录" required disabled={busy || saving}/></label><label>负责人<select name="assignee_id" aria-label="新任务负责人" disabled={busy || saving}><option value="">未指派</option>{(project.members || []).map(member => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label><label>截止日期<input type="date" name="due_date" disabled={busy || saving}/></label><label className="task-notes-label">备注<textarea name="notes" rows={2} maxLength={3000} disabled={busy || saving}/></label><button className="secondary" disabled={busy || saving}>{saving ? "正在保存…" : "创建任务"}</button>{error && <p className="inline-error" role="alert">{error}</p>}</form></details>;
}

function RevisionDiscussion({comments = [], previous = false}) {
  if (!comments.length) return null;
  return <details className="revision-discussions">
    <summary>{previous ? "复查前的结论讨论" : "该次结论讨论"}<span className="heading-count">{comments.length}</span></summary>
    <ol className="comment-list">{comments.map(comment => <li key={comment.id}>
      <div className="comment-meta"><strong>{comment.actor || "未署名"}</strong><time>{date(comment.created_at)}</time></div>
      <p className="history-discussion-source"><span>{comment.category}</span>{comment.quote}</p>
      {comment.unverified && <small className="comment-state">外部历史，未在本机复核</small>}
      <p>{comment.body}</p>
    </li>)}</ol>
  </details>;
}

export function ProjectOverview({project, result, onSave, onUpload, onReview, onMaterials, onRecheck, onTask, onLocate, onRevision, revision, revisionLoading, allowAI, onAllowAI, aiConfigured, busy, onMembers, onTaskDetail, onCreateTask, onComment, onArchive, onPackage, actor, onActor, onQuickRecord, hasEdits, deliveryCheck}) {
  const [taskStatusFilter, setTaskStatusFilter] = useState("pending");
  const [taskAssigneeFilter, setTaskAssigneeFilter] = useState("all");
  const [taskKindFilter, setTaskKindFilter] = useState("all");

  const taskCounts = useMemo(() => computeTaskCounts(project.tasks || []), [project.tasks]);

  const visibleTasks = useMemo(() => {
    return filterAndSortTasks(project.tasks || [], {
      statusFilter: taskStatusFilter,
      assigneeFilter: taskAssigneeFilter,
      kindFilter: taskKindFilter,
    });
  }, [project.tasks, taskStatusFilter, taskAssigneeFilter, taskKindFilter]);

  const currentActorMember = useMemo(() => {
    return project.members?.find((m) => m.id === actor);
  }, [project.members, actor]);

  return <main className="project-content refined-project-content">
    <div className="project-heading"><div><p className="eyebrow">实践项目{archived(project) ? " · 已归档" : ""}</p><h1>{project.name}</h1>{project.description && <p className="project-description">{project.description}</p>}</div>{(onArchive || onPackage) && <details className="project-more"><summary>更多 <IconChevronDown size={15}/></summary><div>{onPackage && <button onClick={onPackage} disabled={busy}><IconDownload size={16}/>导出项目备份</button>}{onArchive && <button onClick={() => onArchive(!archived(project))} disabled={busy}><IconArchive size={16}/>{archived(project) ? "恢复进行中" : "归档项目"}</button>}</div></details>}</div>
    {project.imported_from && <p className="import-notice" role="note">{isImportedUnverified(result, project.history, project.imported_from) ? "外部交接副本：历史判断尚未在本机复核，请确认材料授权并复查。" : "由交接副本创建 · 当前核对状态与旧历史分别保存。"}</p>}
    <details className="project-settings"><summary>项目名称与简介</summary><form onSubmit={event => {event.preventDefault();const fields = new FormData(event.currentTarget);onSave({name: fields.get("name"), description: fields.get("description")});}}><label>项目名称<input name="name" defaultValue={project.name} maxLength={200} required disabled={busy}/></label><label>实践主题、地点与对象<textarea name="description" defaultValue={project.description} maxLength={2000} rows={3} disabled={busy}/></label><button className="secondary" disabled={busy}>保存项目信息</button></form></details>
    <div className="project-stats compact-stats"><div><small>实践材料</small><strong>{project.materials.length}</strong></div><div><small>结论记录</small><strong>{result?.issues.length || 0}</strong></div><div><small>待办</small><strong>{taskCounts.pending}</strong></div></div>
    <section className="project-report-card">
      <div className="report-card-heading"><span className="report-card-icon"><IconFileText size={24}/></span><div><h2>报告与结论</h2><p>{project.report.text ? project.report.name : "上传报告，或粘贴准备核对的文字。"}</p></div></div>
      {project.needs_review && <p className="material-change-note compact-change-note">{result ? "资料已变化，请复查当前依据。" : "报告已准备好，可以开始核对。"}</p>}
      <div className="project-primary-actions"><button className="primary" onClick={onRecheck} disabled={busy || !project.report.text.trim()}>{busy ? "正在核对…" : allowAI && aiConfigured ? "用 AI 核对当前资料" : "开始本地预检"}</button>{result && <button className="secondary" onClick={onReview} disabled={busy}>查看结论</button>}<button className="text-button" onClick={onUpload} disabled={busy}>{project.report.text ? "更换报告" : "上传报告"}</button></div>
      {aiConfigured ? <ProcessingConsent allowAI={allowAI} onAllowAI={onAllowAI} busy={busy}/> : <p className="mode-note">本地预检只定位需核对的表达，尚未判断结论是否成立。</p>}
      <details className="quick-claim"><summary>粘贴正文或核对一句话</summary><form onSubmit={event => {event.preventDefault();onSave({report: {id: "report", name: project.report.name || "结论草稿", text: new FormData(event.currentTarget).get("text"), notes: []}});}}><label>待核对文字<textarea key={project.report.text} name="text" defaultValue={project.report.text} rows={6} maxLength={24000} required disabled={busy}/></label><button className="secondary" disabled={busy}>保存待核对文字</button></form></details>
    </section>
    {(onMembers || onComment) && <TeamPanel project={project} onMembers={onMembers} onComment={onComment} actor={actor} onActor={onActor} busy={busy}/>}
    {deliveryCheck}
    <section className="project-tasks">
      <div className="section-title">
        <h2>下一步行动{taskCounts.pending > 0 && <span className="heading-count">{taskCounts.pending}</span>}</h2>
        <div className="section-actions">
          {onQuickRecord && <button className="text-button" onClick={onQuickRecord} disabled={busy}><IconNotes size={16}/>记一条实践记录</button>}
          <button className="text-button" onClick={onMaterials} disabled={busy}>实践材料 <IconArrowUpRight size={14}/></button>
        </div>
      </div>

      <div className="task-filter-toolbar">
        <div className="segment-control" role="tablist" aria-label="待办状态筛选">
          <button
            type="button"
            role="tab"
            aria-selected={taskStatusFilter === "pending"}
            onClick={() => setTaskStatusFilter("pending")}
          >
            待办 <span className="toolbar-count">{taskCounts.pending}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={taskStatusFilter === "done"}
            onClick={() => setTaskStatusFilter("done")}
          >
            已完成 <span className="toolbar-count">{taskCounts.done}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={taskStatusFilter === "all"}
            onClick={() => setTaskStatusFilter("all")}
          >
            全部 <span className="toolbar-count">{taskCounts.all}</span>
          </button>
        </div>

        <details className="task-more-filters">
          <summary>
            <span>更多筛选</span>
            {(taskAssigneeFilter !== "all" || taskKindFilter !== "all") && (
              <span className="filter-active-dot" title="有生效的次级筛选" />
            )}
          </summary>
          <div className="task-filter-fields">
            <label className="task-filter-field">
              <span>负责人</span>
              <select
                aria-label="按负责人筛选"
                value={taskAssigneeFilter}
                onChange={(e) => setTaskAssigneeFilter(e.target.value)}
              >
                <option value="all">全部负责人</option>
                <option value="unassigned">未指派</option>
                {currentActorMember && (
                  <option value={currentActorMember.id}>
                    当前署名：{currentActorMember.name}
                  </option>
                )}
                {project.members
                  ?.filter((m) => m.id !== currentActorMember?.id)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
              </select>
            </label>

            <label className="task-filter-field">
              <span>任务类型</span>
              <select
                aria-label="按任务类型筛选"
                value={taskKindFilter}
                onChange={(e) => setTaskKindFilter(e.target.value)}
              >
                <option value="all">全部类型</option>
                <option value="evidence">补证任务</option>
                <option value="practice">实践任务</option>
              </select>
            </label>

            {(taskAssigneeFilter !== "all" || taskKindFilter !== "all") && (
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setTaskAssigneeFilter("all");
                  setTaskKindFilter("all");
                }}
              >
                重置
              </button>
            )}
          </div>
        </details>
      </div>

      {onCreateTask && <CreatePracticeTask project={project} onCreateTask={onCreateTask} busy={busy}/>}

      {visibleTasks.length ? (
        <div className="task-list">
          {visibleTasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              project={project}
              labels={{...taskLabels, ...(task.kind === "practice" ? {open: "待完成", done: "作者确认完成"} : {})}}
              onTask={onTask}
              onLocate={onLocate}
              onTaskDetail={onTaskDetail}
              onComment={onComment}
              busy={busy}
              hasEdits={hasEdits}
            />
          ))}
        </div>
      ) : (
        <div className="inline-empty">
          <IconCheck size={21}/>
          <p>
            {project.tasks.length === 0
              ? onCreateTask ? "记录下一步安排，或从结论旁添加补证待办。" : "从结论旁添加补证待办，留住下一步行动。"
              : taskStatusFilter === "pending" && taskCounts.pending === 0
              ? "所有待办均已完成。"
              : "没有符合筛选条件的事项。"}
          </p>
        </div>
      )}
    </section>
    <section className="project-history"><div className="section-title"><h2>检查与变化记录</h2>{project.history.length > 0 && <span className="compact-note">{project.history.length} 次核对</span>}</div>{project.history.length ? <div className="history-list">{project.history.map((history, index) => <button key={history.id} onClick={() => onRevision(history.id)} className="history-row"><span><strong>{index === 0 ? "最近一次核对" : "历史核对"} · {history.mode === "ai" ? "AI" : history.mode === "example" ? "虚构示例" : "本地预检"}</strong><small>{date(history.created_at)} · {history.summary}</small></span><IconArrowUpRight size={16}/></button>)}</div> : <div className="inline-empty"><IconRefresh size={20}/><p>首次核对后，版本会保存在这里。</p></div>}<details className="history-note"><summary>记录保存什么</summary><p>每次核对保留整篇结果及当时材料。新结果不会覆盖旧版本，作者取舍和编辑也随项目保存。</p></details>
      {revisionLoading && <p className="compact-note" role="status">正在读取历史记录…</p>}
      {revision && <div className="revision-panel" data-revision-id={revision.revision_id} aria-busy={!!revisionLoading}>
        <ReviewChanges key={revision.revision_id} changes={revision.changes} materials={revision.materials} previousMaterials={revision.previous_materials} supportLabels={supportLabels}/>
        <h3>这次核对的结论与依据</h3>
        {revision.result.issues.length ? revision.result.issues.map(issue => <article key={issue.id}>
          <strong>{supportLabels[issue.support_status || "pending"]}</strong><p>{issue.quote}</p><p>{issue.reason}</p>
          {issue.citations.map((citation, index) => <blockquote key={index}>{citation.quote}<small>{citation.document_name}</small></blockquote>)}
        </article>) : <p>本轮未再提示结论，不能据此认为报告通过审核。</p>}
        <RevisionDiscussion comments={revision.discussions?.current_review}/>
        {revision.previous_result && <details className="revision-previous">
          <summary>查看复查前的判断与作者选择</summary>
          {revision.previous_result.issues.map(issue => <article key={issue.id}>
            <p>{issue.quote}</p><small>{supportLabels[issue.support_status || "pending"]} · {revision.choices[issue.id] === "accepted" ? "作者采纳改写" : revision.choices[issue.id] === "kept" ? "作者保留原句" : "未作取舍"}</small><p>{issue.reason}</p>
          </article>)}
          <RevisionDiscussion comments={revision.discussions?.previous_review} previous/>
        </details>}
      </div>}
    </section>
  </main>;
}

function MaterialTags({tags = [], onChange, busy}) {
  const input = useRef(null);
  const [value, setValue] = useState(tags.join("，"));
  const savedTags = tags.join("，");
  useEffect(() => {
    if (input.current !== document.activeElement) setValue(savedTags);
  }, [savedTags]);
  return <label className="material-tags-field">材料标签<input ref={input} aria-label="材料标签" value={value} maxLength={312} placeholder="如：访谈，社区服务" disabled={busy} onChange={event => {
    setValue(event.target.value);
    onChange([...new Set(event.target.value.split(/[,，;；\n]/).map(tag => tag.trim()).filter(Boolean))]);
  }}/><small>用逗号分隔；最多 12 个，每个 24 字。标签只用于整理。</small></label>;
}

export function MaterialCitationsSection({
  material,
  result,
  reviewMaterials = [],
  onPreviewCitation,
  onLocateIssue,
  supportLabels = {}
}) {
  const info = getMaterialCitationsInfo({ material, result, reviewMaterials });

  if (!info.hasResult) return null;

  if (info.citedCount === 0) {
    return (
      <div className="material-citations-wrap">
        <p className="material-citations-empty">
          上次核对：该次记录未引用
          {info.isSnapshotChanged && <span className="material-snapshot-badge">上次核对快照</span>}
        </p>
      </div>
    );
  }

  return (
    <div className="material-citations-wrap">
      <details className="material-citations-details">
        <summary>
          <span>
            上次核对引用于 {info.citedCount} 条结论
            {info.isSnapshotChanged && <span className="material-snapshot-badge">上次核对快照</span>}
          </span>
          <IconChevronDown size={15} />
        </summary>
        <div className="material-citations-body">
          {info.citedIssues.map((issue) => (
            <div key={issue.issueId} className="material-cited-issue">
              <div className="cited-issue-header">
                <div className="cited-issue-meta">
                  <span className={`cited-support-badge badge-${issue.supportStatus}`}>
                    {supportLabels[issue.supportStatus] || "待结合依据核对"}
                  </span>
                  {issue.relationLabels.map((label, rIdx) => (
                    <span key={rIdx} className="cited-relation-badge">
                      {label}
                    </span>
                  ))}
                </div>
                {onLocateIssue && (
                  <button
                    type="button"
                    className="text-button cited-locate-btn"
                    onClick={() => onLocateIssue(issue.issueId)}
                  >
                    在结论页查看 <IconArrowUpRight size={13} />
                  </button>
                )}
              </div>
              <p className="cited-issue-quote">{issue.quote}</p>
              {issue.citations.length > 0 && (
                <div className="cited-excerpts-list">
                  {issue.citations.map((c, cIdx) => (
                    <div key={cIdx} className="cited-excerpt-item">
                      <span>“{c.quote}”</span>
                      {onPreviewCitation && (
                        <button
                          type="button"
                          className="text-button cited-preview-btn"
                          onClick={() => onPreviewCitation(c)}
                        >
                          查看引文位置
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

export function MaterialsPanel({
  materials,
  reviewMaterials = [],
  result,
  onChange,
  onSave,
  onUpload,
  onPreview,
  onPreviewCitation,
  onLocateIssue,
  onReview,
  onRecheck,
  hasReport,
  allowAI,
  onAllowAI,
  aiConfigured,
  busy,
  needsReview,
  tasks = [],
  onQuickRecord,
  focusMaterial,
  onEdit,
  onRemove
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [confirmRemove, setConfirmRemove] = useState(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState("");
  const removal = useRef(false);

  async function removeMaterial(material) {
    if (!onRemove || removal.current) return;
    removal.current = true;
    setRemoving(true);
    setRemoveError("");
    try {
      await onRemove(material);
      setConfirmRemove(null);
    } catch (error) {
      setRemoveError(error.message || "材料未移除，请重试。");
    } finally {
      removal.current = false;
      setRemoving(false);
    }
  }
  useEffect(() => {
    if (!focusMaterial) return;
    setQuery("");
    setFilter("all");
    const details = document.getElementById(`material-${focusMaterial}`)?.querySelector(".material-source-details");
    if (details) details.open = true;
  }, [focusMaterial]);
  const visible = materials.map((material, index) => ({material, index})).filter(({material}) => {
    if (material.id === focusMaterial) return true;
    const confirmed = material.consent_status === "confirmed";
    const matchesStatus = filter === "all" || filter === "pending" && !confirmed || filter === "included" && confirmed && material.enabled !== false || filter === "excluded" && material.enabled === false;
    return matchesStatus && `${material.name} ${material.text} ${material.context || ""} ${material.source_role || ""} ${(material.tags || []).join(" ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  });
  const includedCount = materials.filter(material => material.enabled !== false && material.consent_status === "confirmed").length;

  return <main className="project-content material-content refined-material-content">
    <p className="eyebrow">实践材料</p><div className="section-title"><h1>材料与来源</h1><div className="section-actions">{onQuickRecord && <button className="secondary" onClick={onQuickRecord} disabled={busy}><IconNotes size={17}/>记一条记录</button>}<button className="primary" onClick={onUpload} disabled={busy}><IconPlus size={18}/>补充材料</button></div></div><p className="subtle material-intro">保留原始记录，也保留它的来源与边界。</p>
    {needsReview && <p className="material-change-note">确认来源与授权后，即可核对当前资料。</p>}
    {materials.length > 0 && <div className="library-controls material-library-controls"><label className="search-control"><IconSearch size={17}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索材料与正文" aria-label="搜索实践材料" disabled={busy}/></label><label className="filter-choice"><span className="sr-only">材料状态</span><select aria-label="材料状态筛选" value={filter} onChange={event => setFilter(event.target.value)} disabled={busy}><option value="all">全部材料（{materials.length}）</option><option value="included">本轮纳入</option><option value="pending">待确认授权</option><option value="excluded">已排除</option></select></label></div>}
    <fieldset className="material-controls" disabled={busy}><legend className="sr-only">材料来源与核对设置</legend>
      {visible.length ? <div className="material-library">{visible.map(({material, index}) => <article className={`material-card refined-material-card ${material.enabled === false ? "excluded" : ""}`} key={material.id || index} id={`material-${material.id}`}>
        <header>
          <span className="material-file-icon"><IconFileText size={22}/></span>
          <div className="material-title"><h2>{material.name}</h2><div className="material-meta"><span>{material.source_role || "待确认"}</span>{material.collected_at && <span>{material.collected_at}</span>}<span className="material-state">{material.consent_status !== "confirmed" ? "待确认授权" : material.enabled === false ? "已排除" : "本轮纳入"}</span></div></div>
          <div className="material-header-actions">
            <button className="text-button" onClick={() => onPreview(material)}>查看原文 <IconArrowUpRight size={14}/></button>
            {(onEdit || onRemove) && <details className="material-more">
              <summary aria-label={`材料操作${material.name}`}><IconDots size={19}/></summary>
              <div>
                {onEdit && <button onClick={event => {event.currentTarget.closest("details").open = false;onEdit(material);}} disabled={busy || removing}>编辑文字</button>}
                {onRemove && <button onClick={event => {event.currentTarget.closest("details").open = false;setConfirmRemove(material.id);setRemoveError("");}} disabled={busy || removing}>移除当前材料</button>}
              </div>
            </details>}
          </div>
        </header>
        {tasks.filter(task => (task.material_ids || []).includes(material.id)).map(task => <p className="material-linked-claim" key={task.id}>对应结论：{task.quote}</p>)}
        <MaterialCitationsSection
          material={material}
          result={result}
          reviewMaterials={reviewMaterials}
          onPreviewCitation={onPreviewCitation}
          onLocateIssue={onLocateIssue}
          supportLabels={supportLabels}
        />
        <p className="material-excerpt">{material.text.slice(0, 150)}{material.text.length > 150 ? "…" : ""}</p>
        {(material.tags || []).length > 0 && <div className="material-tags">{material.tags.map(tag => <span key={tag}>{tag}</span>)}</div>}
        <details className="material-source-details"><summary>来源信息 <IconChevronDown size={15}/></summary><div className="material-fields"><label>来源类型<select aria-label="来源类型" value={material.source_role || "待确认"} onChange={event => onChange(index, {source_role: event.target.value})}>{roles.map(role => <option key={role}>{role}</option>)}</select></label><label>采集时间<input value={material.collected_at || ""} placeholder="如：9月12日" maxLength={100} onChange={event => onChange(index, {collected_at: event.target.value})}/></label><label className="material-context">对象与采集场景<input value={material.context || ""} placeholder="影响结论范围时请补充" maxLength={1000} onChange={event => onChange(index, {context: event.target.value})}/></label><MaterialTags tags={material.tags} onChange={tags => onChange(index, {tags})} busy={busy}/></div></details>
        <div className="material-permissions"><label><input type="checkbox" checked={material.consent_status === "confirmed"} onChange={event => onChange(index, {consent_status: event.target.checked ? "confirmed" : "unconfirmed"})}/>已获得本项目引用及所选 AI 处理授权</label><label><input type="checkbox" checked={material.enabled !== false} onChange={event => onChange(index, {enabled: event.target.checked})}/>纳入本轮核对</label></div>
        {material.source_role === "团队分析" && <small className="material-analysis-note">团队分析提供背景，不能直接证明团队自己的事实结论。</small>}
        {confirmRemove === material.id && <div className="material-remove-confirm" role="group" aria-label="移除材料确认">
          <p>从当前材料移除，已保存核对历史仍保留。</p>
          <div><button className="secondary" onClick={() => removeMaterial(material)} disabled={busy || removing}>{removing ? "正在移除…" : "确认移除"}</button><button className="text-button" onClick={() => {setConfirmRemove(null);setRemoveError("");}} disabled={busy || removing}>取消</button></div>
          {removeError && <p className="inline-error" role="alert">{removeError}</p>}
        </div>}
      </article>)}</div> : <div className="inline-empty material-empty"><IconFileText size={24}/><p>{materials.length ? "没有找到匹配的材料。" : "先核对报告内部的依据，也可以随时补充原始记录。"}</p>{materials.length > 0 && <button className="text-button" onClick={() => {setQuery("");setFilter("all");}}>显示全部材料</button>}</div>}
      <div className="material-save-panel">{aiConfigured && hasReport && <div className="processing-options"><label className="processing-choice"><input aria-label="本轮使用AI复查" type="checkbox" checked={allowAI} onChange={event => onAllowAI(event.target.checked)}/>本轮使用 AI 核对报告与已授权、未排除材料。</label><details className="permission-details"><summary>处理范围</summary><p>将报告及已授权、未排除材料发送至已配置 AI 服务。常见手机号、邮箱及身份证号会先遮盖，其他识别信息请自行处理。</p></details></div>}<div className="material-save-actions">{hasReport && <button className="primary" onClick={onRecheck} disabled={busy}>{busy ? "正在核对…" : allowAI && aiConfigured ? "保存并AI复查" : "保存并本地预检"}</button>}<button className="secondary" onClick={onSave} disabled={busy}>保存材料信息</button><button className="text-button" onClick={onReview} disabled={busy}>回到结论核验</button><span className="material-review-scope">本轮纳入 {includedCount} / {materials.length} 份</span></div></div>
    </fieldset>
  </main>;
}
