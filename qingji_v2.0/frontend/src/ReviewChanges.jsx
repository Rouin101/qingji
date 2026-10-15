import { useState } from "react";
import "./review-changes.css";

const fields = {
  support_status: "支持程度",
  category: "类别",
  reason: "判断说明",
  suggested_text: "候选改写",
  next_step: "下一步建议",
  citations: "引用"
};

const materialFields = {
  name: "名称",
  text: "文字",
  source: "来源与场景",
  consent_status: "授权",
  enabled: "纳入设置",
  tags: "标签",
  notes: "读取说明"
};

const relationLabels = {
  support: "支持记录",
  different: "不同情况",
  context: "背景与限制",
  unclassified: "原文依据"
};

function Citations({ items = [] }) {
  return items.length ? (
    <ul className="changes-citations">
      {items.map((item, index) => (
        <li key={index}>
          <small>
            {relationLabels[item.relation || "unclassified"] || "原文依据"} · {item.document_name}
          </small>
          <p>{item.quote}</p>
        </li>
      ))}
    </ul>
  ) : (
    <p>未记录引文</p>
  );
}

function Scope({ known, ids = [], materials = [] }) {
  if (!known) return <>未记录，无法确定</>;
  const names = (ids || []).map(
    id => materials.find(material => material.id === id)?.name || "名称未记录的材料"
  );
  return (
    <>
      {names.length} 份{names.length > 0 && <span> · {names.join("、")}</span>}
    </>
  );
}

function CollapsibleRecordList({
  items = [],
  title,
  subtext = "",
  expanded,
  onToggle,
  threshold = 3
}) {
  if (!items || items.length === 0) return null;
  const visible = expanded ? items : items.slice(0, threshold);
  const hasMore = items.length > threshold;

  return (
    <div className="changes-record-list">
      <h4>{title} · {items.length} 条</h4>
      {subtext && <p className="compact-note">{subtext}</p>}
      {visible.map((item, index) => (
        <p key={index} className="record-list-item">{item.quote}</p>
      ))}
      {hasMore && (
        <button
          type="button"
          className="text-button changes-toggle-btn"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          {expanded ? "收起其余条目" : `展开其余 ${items.length - threshold} 条`}
        </button>
      )}
    </div>
  );
}

export function ReviewChanges({ changes, materials = [], previousMaterials = [], supportLabels = {} }) {
  const [expandChanged, setExpandChanged] = useState(false);
  const [expandNew, setExpandNew] = useState(false);
  const [expandRemoved, setExpandRemoved] = useState(false);
  if (!changes) return null;

  const { report = {}, scope = {}, records = {} } = changes;
  const material = changes.materials || {};
  const changedList = records.changed || [];
  const newList = records.listed_new || [];
  const removedList = records.no_longer_listed || [];
  const ambPrev = records.ambiguous_previous || [];
  const ambCurr = records.ambiguous_current || [];

  const value = (field, text) =>
    field === "support_status" ? supportLabels[text] || "待结合依据核对" : text || "未提供";

  const CHANGED_THRESHOLD = 8;
  const visibleChanged = expandChanged ? changedList : changedList.slice(0, CHANGED_THRESHOLD);
  const hasMoreChanged = changedList.length > CHANGED_THRESHOLD;

  return (
    <details className="review-changes">
      <summary>
        <strong>本次变化</strong>
        <span title={changes.summary}>{changes.summary}</span>
      </summary>
      <div className="review-changes-body">
        {changes.baseline_available && (
          <>
            <section>
              <h4>正文</h4>
              {report.available ? (
                <p>
                  {report.changed
                    ? `按行对比：调整 ${report.modified_lines} 行，增加 ${report.added_lines} 行，减少 ${report.removed_lines} 行。`
                    : "报告文字与复查前相同。"}
                </p>
              ) : (
                <p>缺少前后文字快照，无法比较。</p>
              )}
            </section>
            <section>
              <h4>材料</h4>
              {material.available ? (
                <>
                  {!material.added?.length && !material.removed?.length && !material.changed?.length && (
                    <p>已保存的材料快照没有变化。</p>
                  )}
                  {(material.added || []).map(item => (
                    <p key={"add" + item.id}>增加 · {item.name}</p>
                  ))}
                  {(material.removed || []).map(item => (
                    <p key={"remove" + item.id}>移除 · {item.name}</p>
                  ))}
                  {(material.changed || []).map(item => (
                    <p key={item.id}>
                      {item.name} · {(item.fields || []).map(field => materialFields[field] || field).join("、")}变化
                    </p>
                  ))}
                </>
              ) : (
                <p>历史材料快照不完整，无法比较。</p>
              )}
            </section>
            <section>
              <h4>两次记录的纳入范围</h4>
              <p>
                复查前：<Scope known={scope.previous_known} ids={scope.previous_ids} materials={previousMaterials} />
              </p>
              <p>
                本次：<Scope known={scope.current_known} ids={scope.current_ids} materials={materials} />
              </p>
            </section>
            <section>
              <h4>原句与判断</h4>
              {changedList.length === 0 &&
                newList.length === 0 &&
                removedList.length === 0 &&
                ambCurr.length === 0 &&
                ambPrev.length === 0 && <p>可对应的原句记录没有变化。</p>}

              {visibleChanged.map((record, index) => (
                <details className="changed-record" key={index}>
                  <summary>
                    <span>{record.quote}</span>
                    <small>{(record.fields || []).map(f => fields[f.field] || f.field).join("、")}变化</small>
                  </summary>
                  <div>
                    {(record.fields || []).map(field => (
                      <div className="changes-before-after" key={field.field}>
                        <h5>{fields[field.field] || field.field}</h5>
                        <div>
                          <small>复查前</small>
                          {field.field === "citations" ? (
                            <Citations items={field.before} />
                          ) : (
                            <p>{value(field.field, field.before)}</p>
                          )}
                        </div>
                        <div>
                          <small>本次</small>
                          {field.field === "citations" ? (
                            <Citations items={field.after} />
                          ) : (
                            <p>{value(field.field, field.after)}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              ))}

              {hasMoreChanged && (
                <button
                  type="button"
                  className="text-button changes-toggle-btn"
                  onClick={() => setExpandChanged(v => !v)}
                  aria-expanded={expandChanged}
                >
                  {expandChanged
                    ? "收起其余变化"
                    : `展开其余 ${changedList.length - CHANGED_THRESHOLD} 条变化`}
                </button>
              )}

              <CollapsibleRecordList
                items={newList}
                title="本次列出"
                subtext="（核对时新列出的原句，不代表新增客观事实）"
                expanded={expandNew}
                onToggle={() => setExpandNew(v => !v)}
                threshold={3}
              />

              <CollapsibleRecordList
                items={removedList}
                title="本次未列出"
                subtext="（本次核对未列出的原句，不代表该结论已解决或成立）"
                expanded={expandRemoved}
                onToggle={() => setExpandRemoved(v => !v)}
                threshold={3}
              />

              {(ambPrev.length > 0 || ambCurr.length > 0) && (
                <p className="compact-note">
                  复查前 {ambPrev.length} 条、本次 {ambCurr.length} 条原句无法可靠对应，未自动判断其前后关系。
                </p>
              )}
            </section>
          </>
        )}
        <div className="changes-notes">
          {(changes.notes || []).map((note, index) => (
            <p key={index}>{note}</p>
          ))}
        </div>
      </div>
    </details>
  );
}
