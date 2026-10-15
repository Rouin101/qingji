// 实践任务与补证待办筛选、排序及逾期计算纯函数

export function getTodayDateString() {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isTaskOverdue(task, todayString = null) {
  if (!task || task.status === "done" || !task.due_date) return false;
  const today = todayString || getTodayDateString();
  return task.due_date < today;
}

export function filterAndSortTasks(tasks = [], options = {}) {
  const {
    statusFilter = "pending", // "pending" | "done" | "all"
    assigneeFilter = "all",   // "all" | "unassigned" | memberId
    kindFilter = "all",       // "all" | "evidence" | "practice"
  } = options;

  if (!Array.isArray(tasks)) return [];

  // Filter
  const filtered = tasks.filter((task) => {
    // Status
    if (statusFilter === "pending" && task.status === "done") return false;
    if (statusFilter === "done" && task.status !== "done") return false;

    // Assignee
    if (assigneeFilter === "unassigned" && Boolean(task.assignee_id)) return false;
    if (assigneeFilter !== "all" && assigneeFilter !== "unassigned" && task.assignee_id !== assigneeFilter) {
      return false;
    }

    // Kind
    if (kindFilter !== "all" && (task.kind || "evidence") !== kindFilter) return false;

    return true;
  });

  // Sort by due date:
  // - tasks with due_date come first, in ascending chronological order (earlier first)
  // - tasks without due_date come after
  // - tasks with identical due dates preserve original list index
  const taskOrder = new Map(tasks.map((t, idx) => [t.id, idx]));
  const sorted = [...filtered].sort((a, b) => {
    const aDate = a.due_date || "";
    const bDate = b.due_date || "";
    if (aDate && bDate) {
      const cmp = aDate.localeCompare(bDate);
      if (cmp !== 0) return cmp;
    } else if (aDate && !bDate) {
      return -1;
    } else if (!aDate && bDate) {
      return 1;
    }
    return (taskOrder.get(a.id) ?? 0) - (taskOrder.get(b.id) ?? 0);
  });

  return sorted;
}

export function computeTaskCounts(tasks = [], todayString = null) {
  if (!Array.isArray(tasks)) return { pending: 0, done: 0, all: 0, overdue: 0 };
  const today = todayString || getTodayDateString();
  let pending = 0;
  let done = 0;
  let overdue = 0;

  for (const task of tasks) {
    if (task.status === "done") {
      done += 1;
    } else {
      pending += 1;
      if (task.due_date && task.due_date < today) {
        overdue += 1;
      }
    }
  }

  return { pending, done, all: tasks.length, overdue };
}
