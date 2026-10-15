import { useEffect, useRef, useState } from "react";
import {
  IconFileText,
  IconFileDescription,
  IconFileCheck,
  IconDownload,
  IconRefresh,
  IconLoader2,
  IconAlertCircle,
  IconArrowUpRight,
} from "@tabler/icons-react";
import { downloadText } from "./review-state.js";
import {
  isImportedUnverified,
  computeAuthorChoices,
  computeStatusBadge,
  formatMaterialScope,
  computeSummaryBanner,
} from "./export-status-helpers.js";
import "./export-menu.css";

const SUPPORT_LABELS = {
  supported: "有对应依据",
  partial: "支持较窄表述",
  unsupported: "依据不足",
  disagreement: "存在不同情况",
  pending: "待结合依据核对",
};

export function ExportMenu({
  project,
  result,
  choices = {},
  displayText = "",
  draft = "",
  reportName = "社会实践报告",
  hasEdits = false,
  editing = false,
  choicesDirty = false,
  materialsDirty = false,
  textChanged = false,
  isDirty = false,
  busy = false,
  exporting = false,
  onCheck,
  onExportWord,
  onExportReport,
  onExportRecord,
  onNavigate,
  onClose,
  triggerRef,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const reqSeqRef = useRef(0);
  const menuRef = useRef(null);

  const isTextDirty = textChanged || editing || hasEdits;
  const isChoicesDirty = choicesDirty || (!isTextDirty && isDirty);
  const localUnsavedEdits = isTextDirty || isChoicesDirty || materialsDirty;
  const stale =
    localUnsavedEdits ||
    materialsDirty ||
    !!project?.needs_review ||
    (!!data && (!data.check.review.current || data.check.version !== project?.version));

  async function load() {
    const seq = ++reqSeqRef.current;
    setLoading(true);
    setError("");
    try {
      const res = await onCheck({ flush: false, setAppBusy: false, caller: "export" });
      if (seq === reqSeqRef.current) {
        setData(res);
      }
    } catch (e) {
      if (seq === reqSeqRef.current && e.message !== "ABORTED_STALE") {
        setError(e.message || "暂时无法读取交付状态，请重试。");
      }
    } finally {
      if (seq === reqSeqRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    load();
  }, [project?.id, project?.version]);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
        triggerRef?.current?.focus();
      }
    }
    const node = menuRef.current;
    if (node) {
      node.addEventListener("keydown", handleKeyDown);
      return () => node.removeEventListener("keydown", handleKeyDown);
    }
  }, [onClose, triggerRef]);

  const review = data?.check?.review;
  const materials = data?.check?.materials;
  const counts = data?.check?.counts;

  // 严格区分是否已在本机复查：已有最新历史时看历史标记；无历史且有 imported_from 时才回退交接来源
  const history = project?.history || [];
  const importedUnverified = isImportedUnverified(result, history, project?.imported_from);

  const { statusTitle, statusDetail, statusClass } = computeStatusBadge({
    editing,
    hasEdits: isTextDirty,
    importedUnverified,
    isDirty: isChoicesDirty,
    needsReview: materialsDirty || Boolean(project?.needs_review),
    review,
  });

  const materialScopeStr = formatMaterialScope(materials, review);

  // 同一快照计算作者取舍：只统计当前结果中需要作者取舍的条目（有依据的结论无需作者取舍）
  const activeIssues = result?.issues || [];
  const { acceptedCount, keptCount, undecidedCount, reviewableCount } = computeAuthorChoices(
    activeIssues,
    choices
  );

  const summaryBannerInfo = computeSummaryBanner({
    editing,
    hasEdits: isTextDirty,
    textChanged: isTextDirty,
    choicesChanged: isChoicesDirty,
    materialsChanged: materialsDirty,
    version: data?.check?.version ?? project?.version ?? 1,
  });

  function handleDownloadSummary() {
    if (!data) return;
    let md = data.markdown;
    let fileName = `${data.check.project_name}_交付前检查.md`;
    if (summaryBannerInfo?.banner) {
      fileName = `${data.check.project_name}_交付前检查_v${data.check.version}_已保存快照.md`;
      md = summaryBannerInfo.banner + md;
    }
    downloadText(fileName, md, "text/markdown;charset=utf-8");
  }

  return (
    <div
      ref={menuRef}
      className="export-menu"
      role="dialog"
      aria-label="导出与交付状态"
      tabIndex={-1}
    >
      <section className="export-status-card" aria-label="交付状态">
        {loading && !data && (
          <div className="export-status-loading">
            <IconLoader2 size={16} className="spin" />
            <span>正在整理交付状态…</span>
          </div>
        )}

        {error && (
          <div className="export-status-error" role="alert">
            <div className="export-error-msg">
              <IconAlertCircle size={15} />
              <span>{error}</span>
            </div>
            <button
              type="button"
              className="text-button export-retry-btn"
              onClick={load}
              disabled={loading}
            >
              <IconRefresh size={13} className={loading ? "spin" : ""} />
              重试读取状态
            </button>
          </div>
        )}

        {(data || (!loading && !error)) && (
          <>
            <div className="export-status-headline">
              <span className={`export-badge ${statusClass}`}>{statusTitle}</span>
              {review?.label && review.label !== statusTitle && !importedUnverified && (
                <span className="export-mode-tag">检查方式：{review.label}</span>
              )}
            </div>

            {statusDetail && (
              <p className="export-status-detail">{statusDetail}</p>
            )}

            {materialScopeStr && (
              <p className="export-materials-scope">{materialScopeStr}</p>
            )}

            {activeIssues.length > 0 && (
              <p className="export-choices-scope">
                作者取舍：
                {reviewableCount === 0 ? (
                  "结论均有对应依据，无需取舍"
                ) : (
                  <>
                    {acceptedCount > 0 && `已采纳改写 ${acceptedCount} · `}
                    {keptCount > 0 && `保留原句 ${keptCount} · `}
                    {undecidedCount > 0 ? `待处理 ${undecidedCount}` : "全部已处理"}
                  </>
                )}
                <small className="export-support-clarification">
                  （作者取舍不改变依据支持程度）
                </small>
              </p>
            )}

            <details className="export-status-details">
              <summary tabIndex={0}>
                <span>详细核对与材料范围</span>
              </summary>
              <div className="export-details-content">
                <div className="export-detail-row">
                  <strong>检查方式：</strong>
                  <span>{review?.label || "未开始核对"}</span>
                </div>
                {importedUnverified && (
                  <p className="export-detail-tip export-warning">
                    交接文件中的判断仍保留，需要在本机确认材料授权并复查。
                  </p>
                )}
                {review?.mode === "preliminary" && !importedUnverified && (
                  <p className="export-detail-tip">
                    当前记录是本地预检，尚未形成真实AI对当前材料的判断。
                  </p>
                )}
                {review?.mode === "example" && (
                  <p className="export-detail-tip">
                    当前记录是虚构示例，仅供操作演示。
                  </p>
                )}

                <div className="export-detail-row">
                  <strong>材料范围：</strong>
                  <span>
                    已保存 {materials?.total ?? 0} 份 · 准备纳入已授权 {materials?.eligible_current ?? 0} 份 · 上次核对实际纳入{" "}
                    {review?.last_used_material_count === null
                      ? "未知（旧记录未保存纳入范围）"
                      : `${review?.last_used_material_count ?? 0}份`}
                  </span>
                </div>
                {materials?.unconfirmed_included > 0 && (
                  <p className="export-detail-tip">
                    准备纳入但未授权：{materials.unconfirmed_included} 份
                  </p>
                )}
                {materials?.excluded > 0 && (
                  <p className="export-detail-tip">
                    明确排除：{materials.excluded} 份（明确排除的材料不要求补授权）
                  </p>
                )}

                <div className="export-detail-row">
                  <strong>已保存依据支持：</strong>
                  <span>
                    {Object.entries(review?.support_counts || {})
                      .map(([k, v]) => `${SUPPORT_LABELS[k] || k} ${v}`)
                      .join(" · ") || "无记录"}
                  </span>
                </div>
                <p className="export-detail-tip">
                  作者选择与支持程度分开记录；保留原句、采纳改写或完成任务不代表结论获得依据支持。
                </p>

                {counts && (counts.open_practice_tasks > 0 || counts.open_evidence_tasks > 0) && (
                  <div className="export-detail-row">
                    <strong>未完成行动：</strong>
                    <span>
                      实践行动 {counts.open_practice_tasks} 项 · 补证行动 {counts.open_evidence_tasks} 项待完成
                    </span>
                  </div>
                )}

                {counts && counts.undecided_claims !== undefined && (
                  <div className="export-detail-row">
                    <strong>已保存核对中待处理：</strong>
                    <span>{counts.undecided_claims} 项</span>
                  </div>
                )}

                <div className="export-detail-actions">
                  <button
                    type="button"
                    className="text-button"
                    onClick={handleDownloadSummary}
                    disabled={!data || loading}
                  >
                    <IconDownload size={14} />
                    {summaryBannerInfo?.banner ? "下载已保存快照摘要 (.md)" : "下载核对摘要 (.md)"}
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      onClose?.();
                      onNavigate?.("project");
                    }}
                  >
                    <IconArrowUpRight size={14} />
                    去项目页查看完整事项
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    onClick={load}
                    disabled={loading}
                  >
                    <IconRefresh size={14} className={loading ? "spin" : ""} />
                    刷新检查
                  </button>
                </div>
              </div>
            </details>
          </>
        )}
      </section>

      <div className="export-divider" role="separator" />

      <div className="export-actions">
        <button
          type="button"
          className="export-action-btn"
          onClick={onExportWord}
          disabled={busy || exporting}
        >
          <IconFileText size={16} />
          <span>导出 Word 修改稿</span>
        </button>
        <button
          type="button"
          className="export-action-btn"
          onClick={onExportReport}
          disabled={busy || exporting}
        >
          <IconFileDescription size={16} />
          <span>导出修改后报告</span>
        </button>
        <button
          type="button"
          className="export-action-btn"
          onClick={onExportRecord}
          disabled={busy || exporting}
        >
          <IconFileCheck size={16} />
          <span>导出审阅记录</span>
        </button>
      </div>

      <footer className="export-footer">
        <small>Word 使用基础排版 · 导出内容对应当前屏幕正文</small>
      </footer>
    </div>
  );
}
