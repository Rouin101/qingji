/**
 * 补证复查反馈与材料作用分析
 * 严格区分：任务关联材料、上次核对实际纳入、该结论实际引用
 */
import {isMaterialSnapshotChanged} from "./material-citations-helpers.js";

export const RELATION_LABELS = {
  support: "支持记录",
  different: "不同情况与观点",
  context: "背景与限制",
  unclassified: "原文依据"
};

export const SUPPORT_STATUS_LABELS = {
  supported: "有对应依据",
  partial: "支持较窄表述",
  unsupported: "依据不足",
  disagreement: "存在不同情况",
  pending: "待结合依据核对"
};

/**
 * 在项目当前核对结果中查找与补证任务唯一、可靠匹配的结论
 * 不按数组first猜关联，仅当quote与category唯一匹配时才返回
 */
export function matchTaskIssue(task, project) {
  if (!task || task.kind === "practice" || !task.quote) {
    return { status: "not_applicable", issue: null, matchCount: 0 };
  }
  const issues = project?.result?.issues;
  if (!Array.isArray(issues) || issues.length === 0) {
    return { status: "not_found", issue: null, matchCount: 0 };
  }

  const matches = issues.filter(i => {
    if (i.quote !== task.quote) return false;
    if (task.category && i.category !== task.category) return false;
    return true;
  });

  if (matches.length === 1) {
    return { status: "unique", issue: matches[0], matchCount: 1, matches };
  }
  if (matches.length === 0) {
    return { status: "not_found", issue: null, matchCount: 0 };
  }
  return { status: "ambiguous", issue: null, matchCount: matches.length, matches };
}

/**
 * 分析任务关联材料在上次核对中的实际纳入与引用情况
 */
export function analyzeEvidenceMaterials(task, matchedIssue, project) {
  const materialIds = Array.isArray(task?.material_ids) ? task.material_ids : [];
  const currentMaterials = Array.isArray(project?.materials) ? project.materials : [];
  const snapshotMaterials = Array.isArray(project?.review_materials) ? project.review_materials : [];
  const usedMaterialIds = project?.result?.used_material_ids;
  const isScopeUnknown = !Array.isArray(usedMaterialIds);
  const citations = Array.isArray(matchedIssue?.citations) ? matchedIssue.citations : [];

  const items = materialIds.map(mid => {
    const current = currentMaterials.find(m => m.id === mid) || null;
    const snapshot = snapshotMaterials.find(m => m.id === mid) || null;
    const name = current?.name || snapshot?.name || "未知材料";
    const isRemoved = !current && Boolean(snapshot);
    const isMissingEntirely = !current && !snapshot;

    let isModified = false;
    if (current && snapshot) {
      isModified = isMaterialSnapshotChanged(current, snapshot);
    }

    const isExcluded = current ? current.enabled === false : false;
    const isConsentRevoked = current ? current.consent_status !== "confirmed" : false;

    let usedStatus = "unknown";
    if (!isScopeUnknown) {
      usedStatus = usedMaterialIds.includes(mid) ? "included" : "not_included";
    }

    const matchedCitations = citations
      .filter(c => c.document_id === mid)
      .map(c => ({
        quote: c.quote,
        relation: c.relation || "unclassified",
        relationLabel: RELATION_LABELS[c.relation] || RELATION_LABELS.unclassified
      }));

    return {
      id: mid,
      name,
      current,
      snapshot,
      isRemoved,
      isMissingEntirely,
      isModified,
      isExcluded,
      isConsentRevoked,
      usedStatus,
      citations: matchedCitations,
      isCited: matchedCitations.length > 0
    };
  });

  const includedCount = isScopeUnknown
    ? null
    : items.filter(item => item.usedStatus === "included").length;
  const citedCount = items.filter(item => item.isCited).length;

  return {
    items,
    totalAssociated: materialIds.length,
    includedCount,
    citedCount,
    isScopeUnknown
  };
}

/**
 * 任务卡上的常驻单条最相关状态提示
 */
export function getTaskResidentHint(task, matchedIssue, matchStatus, project) {
  if (task.kind === "practice") {
    return "";
  }
  if (!task.last_review_at) {
    return "补充材料并复查后，可在此查看核对反馈";
  }
  if (matchStatus === "not_found") {
    return "原句在新版本中已变化，无法对应当前结论";
  }
  if (matchStatus === "ambiguous") {
    return "报告存在多处相同原句，无法唯一对应结论";
  }
  if (matchStatus === "unique" && matchedIssue) {
    const label = SUPPORT_STATUS_LABELS[matchedIssue.support_status] || matchedIssue.support_status;
    const count = (task.material_ids || []).length;
    return `上次核对判断：${label}${count > 0 ? ` · 关联 ${count} 份材料` : " · 待关联材料"}`;
  }
  return "";
}
