// 结论筛选与逐条导航辅助函数

export function isIssueVisible(issue, filter, choices = {}) {
  if (!issue) return false;
  if (!filter || filter === "all") return true;
  if (filter === "pending") {
    // 待处理：需要作者取舍且尚未采纳或保留原句的有效结论；有依据结论无需强制取舍
    return (
      issue.support_status !== "supported" &&
      choices[issue.id] !== "accepted" &&
      choices[issue.id] !== "kept"
    );
  }
  if (filter === "supported") return issue.support_status === "supported";
  if (filter === "partial") return issue.support_status === "partial";
  if (filter === "unsupported") return issue.support_status === "unsupported";
  if (filter === "disagreement") return issue.support_status === "disagreement";
  if (filter === "pending_verify") return (issue.support_status || "pending") === "pending";
  return true;
}

export function filterIssues(issues = [], filter = "all", choices = {}) {
  if (!Array.isArray(issues)) return [];
  if (filter === "all") return issues;
  return issues.filter((issue) => isIssueVisible(issue, filter, choices));
}

// Continue in report order after an author decision removes the current item.
// A null selection is intentional (collapsed card or ambiguous task); preserve it.
export function reconcileIssueSelection(previous = [], visible = [], activeId = null) {
  if (activeId === null || visible.some(i => i.id === activeId)) return activeId;
  if (!visible.length) return null;
  const index = previous.findIndex(i => i.id === activeId);
  const ids = new Set(visible.map(i => i.id));
  const next = previous.slice(index + 1).find(i => ids.has(i.id));
  const before = previous.slice(0, Math.max(0, index)).findLast(i => ids.has(i.id));
  return (next || before || visible[0]).id;
}

export function getNavPosition(visibleIssues = [], activeId = null) {
  const total = visibleIssues.length;
  if (total === 0) {
    return {
      currentIndex: -1,
      total: 0,
      label: "0 / 0",
      canPrev: false,
      canNext: false,
      prevId: null,
      nextId: null,
    };
  }
  const currentIndex = visibleIssues.findIndex((i) => i.id === activeId);
  const canPrev = currentIndex > 0;
  const canNext = currentIndex >= 0 ? currentIndex < total - 1 : total > 0;
  const prevId = canPrev ? visibleIssues[currentIndex - 1].id : null;
  const nextId = canNext
    ? currentIndex >= 0
      ? visibleIssues[currentIndex + 1].id
      : visibleIssues[0].id
    : null;
  const label = currentIndex >= 0 ? `${currentIndex + 1} / ${total}` : `-- / ${total}`;

  return {
    currentIndex,
    total,
    label,
    canPrev,
    canNext,
    prevId,
    nextId,
  };
}

export function computeFilterCounts(issues = [], choices = {}) {
  const counts = {
    all: issues.length,
    pending: 0,
    supported: 0,
    partial: 0,
    unsupported: 0,
    disagreement: 0,
    pending_verify: 0,
  };

  for (const issue of issues) {
    const isSupported = issue.support_status === "supported";
    const isChosen = choices[issue.id] === "accepted" || choices[issue.id] === "kept";
    if (!isSupported && !isChosen) {
      counts.pending += 1;
    }
    if (issue.support_status === "supported") counts.supported += 1;
    else if (issue.support_status === "partial") counts.partial += 1;
    else if (issue.support_status === "unsupported") counts.unsupported += 1;
    else if (issue.support_status === "disagreement") counts.disagreement += 1;
    else if ((issue.support_status || "pending") === "pending") counts.pending_verify += 1;
  }

  return counts;
}
