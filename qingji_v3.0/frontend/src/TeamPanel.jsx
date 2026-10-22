import {useEffect, useMemo, useRef, useState} from "react";
import {IconCalendar, IconChevronDown, IconFileCheck, IconMessageCircle, IconPlus, IconUsers, IconX} from "@tabler/icons-react";
import {isTaskOverdue} from "./task-filter-helpers.js";
import {matchTaskIssue, analyzeEvidenceMaterials, getTaskResidentHint, SUPPORT_STATUS_LABELS} from "./evidence-feedback-helpers.js";

const formatDate = value => value ? new Date(value).toLocaleString("zh-CN", {hour12: false}) : "";
const memberName = (members, id) => members.find(member => member.id === id)?.name || "未指派";

export function CommentThread({comments = [], members = [], targetType, targetId, onComment, busy, compact = false}) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);
  const thread = comments.filter(comment => comment.target_type === targetType && comment.target_id === targetId);
  const discussionLabel = targetType === "task" ? "任务讨论" : targetType === "issue" ? "结论讨论" : "项目讨论";

  async function send(event) {
    event.preventDefault();
    if (!onComment || submission.current) return;
    const form = event.currentTarget;
    const body = new FormData(form).get("body")?.trim();
    if (!body) return;
    submission.current = true;
    setSending(true);
    setError("");
    try {
      await onComment({target_type: targetType, target_id: targetId, body});
      form.reset();
    } catch (error) {
      setError(error.message || "讨论未保存，请重试。");
    } finally {
      submission.current = false;
      setSending(false);
    }
  }

  return <div className={`comment-thread ${compact ? "compact" : ""}`}>
    {thread.length > 0 && <ol className="comment-list">{thread.map(comment => <li key={comment.id}>
      <div className="comment-meta"><strong>{members.find(member => member.id === comment.actor)?.name || comment.actor || "未署名"}</strong><time>{formatDate(comment.created_at)}</time></div>
      {["changed", "historical", "removed"].includes(comment.target_state) && <small className="comment-state">记录时内容已变更</small>}
      <p>{comment.body}</p>
    </li>)}</ol>}
    {onComment && <form className="comment-form" onSubmit={send}>
      <label className="sr-only">{discussionLabel}</label>
      <textarea name="body" rows={2} maxLength={3000} placeholder={targetType === "task" ? "补充进展或需要协助的地方…" : targetType === "issue" ? "记录这条结论的核对意见…" : "记录讨论、分工或交接说明…"} aria-label={discussionLabel} required disabled={busy || sending}/>
      <button className="secondary" type="submit" disabled={busy || sending}>{sending ? "正在保存…" : "记录讨论"}</button>
    </form>}
    {error && <p className="inline-error" role="alert">{error}</p>}
  </div>;
}

export function TeamPanel({project, onMembers, onComment, actor = "", onActor, busy}) {
  const members = project.members || [];
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);
  const [allActivity, setAllActivity] = useState(false);
  const activity = [...(project.activity || [])].reverse();

  async function updateMembers(nextMembers, form) {
    if (!onMembers || submission.current) return;
    submission.current = true;
    setSaving(true);
    setError("");
    try {
      await onMembers(nextMembers);
      form?.reset();
    } catch (error) {
      setError(error.message || "成员未保存，请重试。");
    } finally {
      submission.current = false;
      setSaving(false);
    }
  }

  return <details className="team-panel surface-disclosure">
    <summary>
      <span><IconUsers size={18}/>团队与讨论</span>
      <span className="summary-meta">{members.length ? `${members.length} 位成员` : "添加实践成员"}<IconChevronDown size={16}/></span>
    </summary>
    <div className="team-panel-body">
      <p className="compact-note">成员姓名用于本机分工与署名，不代表登录账号。跨设备可通过项目备份交接。</p>
      {onActor && <label className="actor-choice">本次署名
        <select aria-label="本次署名" value={actor} onChange={event => onActor(event.target.value)} disabled={busy || saving}>
          <option value="">未署名</option>
          {members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}
        </select>
      </label>}
      {members.length > 0 && <ul className="member-list">{members.map(member => {
        const assigned = project.tasks.some(task => task.assignee_id === member.id);
        return <li key={member.id}>
          <span className="member-avatar" aria-hidden="true">{Array.from(member.name)[0]}</span>
          <span className="member-information"><strong>{member.name}</strong><small>{member.role || "团队成员"}</small></span>
          {onMembers && <button className="icon-button" type="button" aria-label={`移除成员${member.name}`} title={assigned ? "请先调整其负责的任务" : "移除成员"} disabled={busy || saving || assigned} onClick={() => updateMembers(members.filter(item => item.id !== member.id))}><IconX size={16}/></button>}
        </li>;
      })}</ul>}
      {onMembers && <details className="member-add"><summary><IconPlus size={15}/>添加成员</summary><form className="member-form" onSubmit={event => {
        event.preventDefault();
        const form = event.currentTarget;
        const fields = new FormData(form);
        const name = fields.get("name")?.trim();
        if (!name) return;
        updateMembers([...members, {id: `member-${crypto.randomUUID()}`, name, role: fields.get("role")?.trim() || "团队成员"}], form);
      }}>
        <label>成员姓名<input name="name" maxLength={60} placeholder="如：小张" required disabled={busy || saving}/></label>
        <label>负责方向<input name="role" maxLength={40} placeholder="如：访谈与资料整理" disabled={busy || saving}/></label>
        <button className="secondary" disabled={busy || saving}>{saving ? "正在保存…" : "添加成员"}</button>
      </form></details>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="team-discussion">
        <h3><IconMessageCircle size={17}/>项目讨论</h3>
        <CommentThread comments={project.comments} members={members} targetType="project" targetId={project.id} onComment={onComment} busy={busy}/>
      </div>
      <details className="activity-log">
        <summary>操作记录{activity.length > 0 && <span>{activity.length}</span>}</summary>
        <p className="compact-note">本机记录，按时间倒序显示。{project.activity_earlier_count > 0 ? `更早 ${project.activity_earlier_count} 条未逐条保留。` : ""}</p>
        {activity.length > 0 ? <ol>{(allActivity ? activity : activity.slice(0, 10)).map(item => <li key={item.id}>
          <span className="activity-description">{item.detail || item.action}</span>
          <span className="activity-meta">{item.actor || "未署名"} · {formatDate(item.created_at)}</span>
        </li>)}</ol> : <p className="compact-note">暂无操作记录。</p>}
        {activity.length > 10 && <button className="text-button" type="button" onClick={() => setAllActivity(value => !value)}>{allActivity ? "收起到最近 10 条" : `展开全部 ${activity.length} 条`}</button>}
      </details>
    </div>
  </details>;
}

export function TaskCard({task, project, labels, onTask, onLocate, onTaskDetail, onComment, busy, hasEdits}) {
  const members = project.members || [];
  const practice = task.kind === "practice";
  const questions = project.lifecycle?.questions || [];
  const questionId = project.lifecycle?.task_links?.[task.id] || "";
  const linkedRecords = (project.lifecycle?.observations || []).filter(o=>o.task_id===task.id);
  const materialIds = task.material_ids || [];
  const materialSignature = materialIds.join("\u0000");
  const missingMaterials = materialIds.filter(id => !project.materials.some(material => material.id === id));
  const [selectedMaterials, setSelectedMaterials] = useState(materialIds);
  const [relationsChanged, setRelationsChanged] = useState(false);
  const [replaceMissing, setReplaceMissing] = useState(false);
  useEffect(() => {
    setSelectedMaterials(materialIds);
    setRelationsChanged(false);
    setReplaceMissing(false);
  }, [task.id, materialSignature]);
  const textChanged = hasEdits ?? (project.manual_text != null && project.manual_text !== project.result?.report.text
    || (project.result?.issues || []).some(issue => project.choices?.[issue.id] === "accepted" && issue.suggested_text && issue.suggested_text !== issue.quote));
  const needsRecheck = project.needs_review || textChanged;
  const canConfirm = practice || (!needsRecheck && task.last_review_at && materialIds.every(id => project.materials.some(material => material.id === id && material.enabled && material.consent_status === "confirmed")));
  const comments = (project.comments || []).filter(comment => comment.target_type === "task" && comment.target_id === task.id);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submission = useRef(false);

  const issueMatch = useMemo(() => matchTaskIssue(task, project), [task.quote, task.category, project?.result]);
  const matchedIssue = issueMatch.issue;
  const materialsAnalysis = useMemo(() => analyzeEvidenceMaterials(task, matchedIssue, project), [task.material_ids, matchedIssue, project?.materials, project?.review_materials, project?.result?.used_material_ids]);
  const residentHint = useMemo(() => getTaskResidentHint(task, matchedIssue, issueMatch.status, project), [task, matchedIssue, issueMatch.status, project]);

  async function save(event) {
    event.preventDefault();
    if (!onTaskDetail || submission.current) return;
    const form = new FormData(event.currentTarget);
    submission.current = true;
    setSaving(true);
    setError("");
    try {
      const changes = {assignee_id: form.get("assignee_id") || "", due_date: form.get("due_date") || "", notes: form.get("notes") || ""};
      if (practice && questions.length && !linkedRecords.length) changes.question_id = form.get("question_id") || "";
      if (!practice && (missingMaterials.length ? replaceMissing : relationsChanged)) changes.material_ids = form.getAll("material_ids");
      await onTaskDetail(task, changes);
    } catch (error) {
      setError(error.message || "分工未保存，请重试。");
    } finally {
      submission.current = false;
      setSaving(false);
    }
  }

  return <article className="task-card refined-task-card">
    <header><span className="category-pill">{labels[task.status] || task.status}</span><small>{practice ? "实践任务" : "补证任务"}</small></header>
    {!practice && task.quote && <p className="task-quote">{task.quote}</p>}
    <p className="task-action-copy">{task.action}</p>
    {practice && questions.length>0 && <p className="task-question-link">{questionId?`实践问题：${questions.find(q=>q.id===questionId)?.text || "待核对"}`:"尚未关联实践问题"}{linkedRecords.length>0 && <span> · {linkedRecords.length} 条阶段记录</span>}</p>}
    <div className="task-meta">
      <span>{memberName(members, task.assignee_id)}</span>
      {task.due_date && <span className={`task-due-date ${isTaskOverdue(task) ? "is-overdue" : ""}`}><IconCalendar size={14}/>{task.due_date} 截止{isTaskOverdue(task) && <span className="task-overdue-tag">已逾期</span>}</span>}
      {!practice && <span>{materialIds.length ? `已关联 ${materialIds.length} 份材料` : "待关联材料"}</span>}
    </div>
    {!practice && residentHint && <div className="task-resident-hint"><IconFileCheck size={14} stroke={1.5}/><span>{residentHint}</span></div>}
    {!practice && <details className="task-review-feedback">
      <summary>查看本次核对</summary>
      <div className="task-review-feedback-body">
        {issueMatch.status === "unique" && matchedIssue ? (
          <>
            <div className="feedback-claim-row">
              <span className={`support-tag ${matchedIssue.support_status}`}>
                {SUPPORT_STATUS_LABELS[matchedIssue.support_status] || matchedIssue.support_status}
              </span>
              <p className="feedback-claim-quote">{matchedIssue.quote}</p>
            </div>
            {matchedIssue.next_step && (
              <div className="feedback-next-step">
                <span className="feedback-subheading">下一步建议</span>
                <p>{matchedIssue.next_step}</p>
              </div>
            )}
            <div className="feedback-materials-breakdown">
              <span className="feedback-subheading">材料作用与实际引用</span>
              {materialsAnalysis.items.length > 0 ? (
                <ul className="feedback-materials-list">
                  {materialsAnalysis.items.map(item => (
                    <li key={item.id} className="feedback-material-item">
                      <div className="feedback-material-header">
                        <strong>{item.name}</strong>
                        {item.isRemoved && <span className="feedback-chip warning">材料已移除（快照）</span>}
                        {!item.isRemoved && item.isModified && <span className="feedback-chip notice">材料已变化（快照）</span>}
                        {item.isExcluded && <span className="feedback-chip">已排除</span>}
                        {item.isConsentRevoked && <span className="feedback-chip">待更新处理范围</span>}
                        <span className={`feedback-chip ${item.usedStatus === "included" ? "included" : "excluded"}`}>
                          {item.usedStatus === "included" ? "已纳入上次核对" : item.usedStatus === "not_included" ? "未纳入核对" : "纳入范围未知"}
                        </span>
                      </div>
                      {item.isCited ? (
                        <div className="feedback-material-citations">
                          {item.citations.map((c, idx) => (
                            <div key={idx} className="feedback-citation">
                              <span className="citation-relation-badge">{c.relationLabel}</span>
                              <span className="citation-quote">“{c.quote}”</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="feedback-not-cited">
                          {item.usedStatus === "included" ? "已纳入核对，但本次未作为直接依据引用" : "未在本次核对中引用"}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="compact-note">此任务尚未关联任何材料，复查时未纳入专属佐证。</p>
              )}
            </div>
            <div className="feedback-footer">
              <button className="text-button" type="button" onClick={() => onLocate(task)}>
                在结论核验中定位结论
              </button>
            </div>
          </>
        ) : issueMatch.status === "ambiguous" ? (
          <div className="feedback-unmatched">
            <p>报告中存在多处相同原句，无法唯一关联单条结论。</p>
            <button className="text-button" type="button" onClick={() => onLocate(task)}>
              前往结论核验查看各处反馈
            </button>
          </div>
        ) : (
          <div className="feedback-unmatched">
            <p>原句在当前报告版本中已修改或未在本次核对中列出，无法可靠对应当前结论。</p>
            <p className="compact-note">若需追溯历史核对时的判断，可查看项目历史快照。</p>
          </div>
        )}
      </div>
    </details>}
    <div className="task-actions">
      {!practice && <button className="text-button" onClick={() => onLocate(task)}>查看对应结论</button>}
      {task.status === "done" ? <button className="text-button" onClick={() => onTask(task, "open")} disabled={busy}>重新打开</button> : <button className="secondary" onClick={() => onTask(task, "done")} disabled={busy || !canConfirm}>{practice ? "确认任务完成" : "确认补证完成"}</button>}
    </div>
    {!practice && !canConfirm && <p className="task-completion-note">{needsRecheck ? "正文或材料有变化，复查后再确认。" : !task.last_review_at ? "补充材料并复查后再确认。" : "关联材料需纳入核对。"}</p>}
    {!practice && missingMaterials.length > 0 && <p className="task-link-note">有旧关联已移除，可选择当前材料后保存并复查。</p>}
    {(onTaskDetail || onComment) && <details className="task-details">
      <summary>分工与讨论{comments.length > 0 && <span>{comments.length}</span>}</summary>
      <div className="task-detail-body">
        {onTaskDetail && <form className="task-assignment-form" onSubmit={save}>
          {practice && questions.length>0 && <label className="task-notes-label">关联问题<select key={questionId} name="question_id" aria-label="任务关联问题" defaultValue={questionId} disabled={busy || saving || linkedRecords.length>0}><option value="">暂不关联问题</option>{questions.map(q=><option key={q.id} value={q.id}>{q.text}</option>)}</select>{linkedRecords.length>0 && <small>已有阶段记录关联此行动。如需更换问题，请先在阶段记录中调整对应行动。</small>}</label>}
          <label>负责人
            <select name="assignee_id" aria-label="任务负责人" defaultValue={task.assignee_id || ""} disabled={busy || saving}>
              <option value="">未指派</option>
              {members.map(member => <option key={member.id} value={member.id}>{member.name}</option>)}
            </select>
          </label>
          <label>截止日期<input name="due_date" type="date" defaultValue={task.due_date || ""} disabled={busy || saving}/></label>
          <label className="task-notes-label">任务备注<textarea name="notes" aria-label="任务备注" defaultValue={task.notes || ""} rows={2} maxLength={3000} placeholder="补充具体安排…" disabled={busy || saving}/></label>
          {!practice && <details className="task-material-relations">
            <summary>关联当前材料<span>{materialIds.length} 份已关联</span></summary>
            <div className="task-material-options">{project.materials.length ? project.materials.map(material => <label key={material.id}>
              <input type="checkbox" name="material_ids" value={material.id} checked={selectedMaterials.includes(material.id)} disabled={busy || saving} onChange={event => {
                setRelationsChanged(true);
                setSelectedMaterials(selected => event.target.checked ? [...selected, material.id] : selected.filter(id => id !== material.id));
              }}/>
              <span>{material.name}<small>{material.consent_status !== "confirmed" ? "待更新处理范围" : material.enabled === false ? "已排除" : "本轮纳入"}</small></span>
            </label>) : <p className="compact-note">当前还没有材料，可先到实践材料补充。</p>}</div>
            {missingMaterials.length > 0 && <label className="replace-material-links"><input type="checkbox" name="replace_material_links" checked={replaceMissing} onChange={event => setReplaceMissing(event.target.checked)} disabled={busy || saving}/>用当前选择更新材料关联</label>}
            <p className="compact-note">更新关联后，请复查再确认补证完成。</p>
          </details>}
          <button className="secondary" disabled={busy || saving}>{saving ? "正在保存…" : "保存分工"}</button>
        </form>}
        {error && <p className="inline-error" role="alert">{error}</p>}
        <CommentThread comments={project.comments} members={members} targetType="task" targetId={task.id} onComment={onComment} busy={busy} compact/>
      </div>
    </details>}
  </article>;
}
