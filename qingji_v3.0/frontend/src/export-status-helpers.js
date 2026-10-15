// 导出菜单状态与作者取舍计算辅助函数（供 ExportMenu 与单元测试直接共享）

export function isImportedUnverified(result, history = [], importedFrom = null) {
  if (!result) return false;
  return Boolean(history.length ? history[0]?.imported_unverified : importedFrom);
}

export function computeAuthorChoices(issues = [], choices = {}) {
  const reviewableIssues = issues.filter((i) => i.support_status !== "supported");
  const acceptedCount = reviewableIssues.filter((i) => choices[i.id] === "accepted").length;
  const keptCount = reviewableIssues.filter((i) => choices[i.id] === "kept").length;
  const undecidedCount = reviewableIssues.filter(
    (i) => choices[i.id] !== "accepted" && choices[i.id] !== "kept"
  ).length;
  return {
    acceptedCount,
    keptCount,
    undecidedCount,
    reviewableCount: reviewableIssues.length,
    totalCount: issues.length,
  };
}

export function computeStatusBadge({
  editing = false,
  hasEdits = false,
  importedUnverified = false,
  isDirty = false,
  needsReview = false,
  review = null,
}) {
  let statusTitle = "";
  let statusDetail = "";
  let statusClass = "export-badge-current";

  if (editing) {
    statusClass = "export-badge-warning";
    statusTitle = "正文正在编辑 · 待复查";
    statusDetail = "当前导出以编辑器中草稿为准；尚未保存或针对草稿复查。";
  } else if (hasEdits) {
    statusClass = "export-badge-warning";
    statusTitle = "正文已修改 · 待复查";
    statusDetail = "当前导出修改稿以当前修改文字为准；尚未针对修改后正文复查。";
  } else if (importedUnverified) {
    statusClass = "export-badge-warning";
    statusTitle = "外部历史 · 未在本机复核";
    statusDetail = "交接文件中的判断仍保留，需要在本机确认材料授权并复查。";
  } else if (isDirty) {
    statusClass = "export-badge-warning";
    statusTitle = "作者取舍已变更 · 待保存";
    statusDetail = "正文保持原句未改写；本地取舍记录尚未保存。";
  } else if (needsReview) {
    statusClass = "export-badge-warning";
    statusTitle = "材料已变化 · 待复查";
    statusDetail = "项目材料或授权已改变，当前结论依据尚未复查。";
  } else if (review) {
    statusTitle = `最后检查：${review.label}`;
    statusDetail = "对应当前保存内容";
  }

  return { statusTitle, statusDetail, statusClass };
}

export function formatMaterialScope(materials, review) {
  if (!materials || !review) return "";
  const lastUsedStr =
    review.last_used_material_count === null
      ? "未知（旧记录未保存纳入范围）"
      : `${review.last_used_material_count}份`;
  let str = `已保存${materials.total}份 · 授权准备纳入${materials.eligible_current}份 · 上次纳入${lastUsedStr}`;
  if (materials.excluded > 0) {
    str += ` · 排除${materials.excluded}份`;
  }
  return str;
}

export function computeSummaryBanner({
  editing = false,
  hasEdits = false,
  textChanged = false,
  choicesChanged = false,
  materialsChanged = false,
  version = 1,
}) {
  const isTextDirty = textChanged || editing || hasEdits;
  if (!isTextDirty && !choicesChanged && !materialsChanged) {
    return null;
  }
  let title = "注意：当前项目存在未保存改动";
  let note = "";
  let actionNote = "";

  if (isTextDirty) {
    title = "注意：当前导出正文存在未保存改动 · 待复查";
    note = editing
      ? "正文正在编辑中，包含尚未提交保存的草稿"
      : "正文已采纳改写，与核对基准不一致";
    actionNote = "当前导出的修改稿以屏幕最新文字为准，尚未基于当前修改后正文完成复查。";
  } else if (choicesChanged) {
    title = "注意：作者取舍已变更 · 待保存";
    note = "作者取舍已变更，当前正文保持原句未改写，本地取舍尚未保存";
    actionNote = "当前导出的修改稿正文保持原句未改写，本地取舍待保存；保留原句不改变结论依据支持程度。";
  } else if (materialsChanged) {
    title = "注意：项目材料已变更 · 待复查";
    note = "项目材料或授权已改变";
    actionNote = "当前结论依据尚未基于更新后的材料范围复查。";
  }

  const banner = [
    "> [!WARNING]",
    `> **${title}**`,
    `> 本核对摘要仅对应项目已保存的第 ${version} 版快照（${note}）。`,
    `> ${actionNote}`,
    "",
    ""
  ].join("\n");

  return {
    banner,
    isSnapshot: true,
  };
}
