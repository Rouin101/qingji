/**
 * 材料反向查看关联结论辅助函数
 * 仅由当前保存的 result.citations 的 document_id / relation 派生
 * 同一材料同一 issue 多片段去重为一条结论；report 内部引文不当作外部材料。
 */

export const relationLabels = {
  support: "支持记录",
  different: "不同情况",
  context: "背景与限制",
  unclassified: "原文依据"
};

/**
 * 判断当前材料是否相较于最近一次核对时的快照发生了变更
 * （名称、文字、来源类型、场景、采集时间、授权状态或启用设置）
 */
export function isMaterialSnapshotChanged(currentMaterial, snapshotMaterial) {
  if (!currentMaterial || !snapshotMaterial) return false;

  return (
    currentMaterial.name !== snapshotMaterial.name ||
    currentMaterial.text !== snapshotMaterial.text ||
    (currentMaterial.source_role || "待确认") !== (snapshotMaterial.source_role || "待确认") ||
    (currentMaterial.context || "") !== (snapshotMaterial.context || "") ||
    (currentMaterial.collected_at || "") !== (snapshotMaterial.collected_at || "") ||
    (currentMaterial.consent_status || "unconfirmed") !== (snapshotMaterial.consent_status || "unconfirmed") ||
    (currentMaterial.enabled !== false) !== (snapshotMaterial.enabled !== false)
  );
}

/**
 * 计算某份材料在上次核对中的引用与结论关系
 */
export function getMaterialCitationsInfo({ material, result, reviewMaterials = [] }) {
  if (!material || !material.id) {
    return {
      hasResult: false,
      citedCount: 0,
      isSnapshotChanged: false,
      snapshotAvailable: false,
      snapshot: null,
      citedIssues: []
    };
  }

  const hasResult = Boolean(result && Array.isArray(result.issues));
  const snapshot = (reviewMaterials || []).find((m) => m.id === material.id) || null;
  const isSnapshotChanged = isMaterialSnapshotChanged(material, snapshot);

  if (!hasResult) {
    return {
      hasResult: false,
      citedCount: 0,
      isSnapshotChanged,
      snapshotAvailable: Boolean(snapshot),
      snapshot,
      citedIssues: []
    };
  }

  const issues = result.issues || [];
  const citedIssues = [];

  for (const issue of issues) {
    const citations = issue.citations || [];
    // 严格按 document_id 匹配，排除 report 内部引文与空值
    const matchingCitations = citations.filter(
      (c) => c && c.document_id && c.document_id === material.id && c.document_id !== "report"
    );

    if (matchingCitations.length > 0) {
      // 同一材料同一 issue 多片段去重为一条结论，并保留关系集合
      const uniqueRelations = [
        ...new Set(matchingCitations.map((c) => Object.hasOwn(relationLabels, c.relation) ? c.relation : "unclassified"))
      ];

      citedIssues.push({
        issueId: issue.id,
        quote: issue.quote,
        category: issue.category,
        supportStatus: issue.support_status || "pending",
        relations: uniqueRelations,
        relationLabels: uniqueRelations.map((r) => relationLabels[r] || "原文依据"),
        citations: matchingCitations
      });
    }
  }

  return {
    hasResult: true,
    citedCount: citedIssues.length,
    isSnapshotChanged,
    snapshotAvailable: Boolean(snapshot),
    snapshot,
    citedIssues
  };
}
